#!/usr/bin/env python3
"""
Lark Case Bot CLI - Setup and Configuration Tool (S3 Storage Version)

Commands:
  setup   - Initialize bot: update secrets, create IAM roles, configure S3
  cleanup - Remove all LarkCase resources from all accounts
  verify  - Verify deployment status

Usage:
  python setup_lark_bot.py setup              # Full setup using accounts.json
  python setup_lark_bot.py setup --skip-iam   # Skip IAM role creation
  python setup_lark_bot.py cleanup            # Remove all resources
  python setup_lark_bot.py verify             # Verify configuration
"""
import argparse
import boto3
import json
import sys
import os
from typing import Dict, Any, List, Optional

from i18n import t, set_lang

CONFIG_FILE = 'accounts.json'
ROLE_NAME = 'LarkSupportCaseApiAll'
REGION = 'us-east-1'


def load_config() -> Dict[str, Any]:
    """Load accounts.json configuration"""
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ Config file '{CONFIG_FILE}' not found")
        print(f"   Please copy accounts-example.json to {CONFIG_FILE} and fill in values")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_stack_outputs() -> Dict[str, str]:
    """Get CloudFormation Stack outputs"""
    cfn = boto3.client('cloudformation', region_name=REGION)
    try:
        response = cfn.describe_stacks(StackName='LarkCaseBotStack')
        return {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0]['Outputs']}
    except Exception:
        print(f"❌ LarkCaseBotStack not found. Please run: cdk deploy")
        sys.exit(1)


def print_header(title: str):
    """Print section header"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


# ============================================================================
# Setup Command
# ============================================================================

def cmd_setup(args):
    """Full setup: update secrets, create IAM roles, configure S3"""
    config = load_config()
    outputs = get_stack_outputs()
    
    print_header("🚀 Lark Case Bot Setup (S3 Storage)")
    
    # Show configuration
    print("📋 Configuration:")
    print(f"   Lark App ID: {config['lark']['app_id']}")
    print(f"   S3 Bucket: {outputs.get('DataBucketName', 'N/A')}")
    print(f"   Accounts: {len(config['accounts'])}")
    for acc in config['accounts']:
        print(f"     - {acc['account_name']} ({acc['account_id']}) [profile: {acc.get('profile', 'default')}]")
    
    # 1. Update Secrets Manager
    print("\n📝 Step 1: Updating Secrets Manager...")
    update_secrets(config, outputs)
    
    # 2. Create IAM roles in all accounts
    if not args.skip_iam:
        print("\n📝 Step 2: Creating IAM roles in all accounts...")
        lambda_role_arns = [
            outputs.get('msgEventRoleArn', ''),
            outputs.get('CasePollerRoleArn', ''),
        ]
        lambda_role_arns = [r for r in lambda_role_arns if r]
        print(f"   Lambda Role ARNs: {len(lambda_role_arns)}")
        
        for acc in config['accounts']:
            create_iam_role(acc, lambda_role_arns)
    else:
        print("\n⏭️  Step 2: Skipping IAM role creation (--skip-iam)")
    
    # 3. Setup cross-account EventBridge
    setup_cross_account_eventbridge(config, outputs)
    
    # 4. Initialize S3 config
    print("\n📝 Step 4: Initializing S3 configuration...")
    initialize_s3_config(config, outputs)
    
    # Summary
    print_header("✅ Setup Complete!")
    print("📋 Next steps:")
    print(f"   1. Configure Lark Webhook URL:")
    print(f"      {outputs.get('WebhookUrl', 'N/A')}")
    print(f"\n   2. Subscribe to Lark events:")
    print(f"      - im.message.receive_v1")
    print(f"      - card.action.trigger")
    print(f"\n   3. Test: Send 'help' in Lark")
    print()


def update_secrets(config: Dict, outputs: Dict):
    """Update Lark credentials in Secrets Manager"""
    sm = boto3.client('secretsmanager', region_name=REGION)
    
    app_id = config['lark']['app_id']
    app_secret = config['lark']['app_secret']
    
    sm.update_secret(SecretId=outputs['AppIDSecretArn'], 
                     SecretString=json.dumps({"app_id": app_id}))
    print(f"   ✅ App ID updated")
    
    sm.update_secret(SecretId=outputs['AppSecretSecretArn'], 
                     SecretString=json.dumps({"app_secret": app_secret}))
    print(f"   ✅ App Secret updated")


def create_iam_role(account: Dict, lambda_role_arns: List[str]):
    """Create IAM role in target account using its profile"""
    account_id = account['account_id']
    account_name = account['account_name']
    profile = account.get('profile', 'default')
    
    print(f"\n   🔧 Account: {account_name} ({account_id})")
    print(f"      Profile: {profile}")
    
    try:
        session = boto3.Session(profile_name=profile, region_name=REGION)
        iam = session.client('iam')
        
        # Verify we're in the right account
        sts = session.client('sts')
        actual_account = sts.get_caller_identity()['Account']
        if actual_account != account_id:
            print(f"      ⚠️  Warning: Profile '{profile}' is for account {actual_account}, not {account_id}")
        
        # Build trust policy with all Lambda roles
        principal = lambda_role_arns if len(lambda_role_arns) > 1 else lambda_role_arns[0]
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "sts:AssumeRole"
            }]
        }
        
        try:
            iam.get_role(RoleName=ROLE_NAME)
            # Role exists, update trust policy
            iam.update_assume_role_policy(RoleName=ROLE_NAME, 
                                          PolicyDocument=json.dumps(trust_policy))
            print(f"      ✅ Role exists, trust policy updated")
        except iam.exceptions.NoSuchEntityException:
            # Create new role
            iam.create_role(
                RoleName=ROLE_NAME,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"Lark bot Support API access - {account_name}"
            )
            print(f"      ✅ Role created: {ROLE_NAME}")
        
        # Ensure policy is attached
        try:
            iam.attach_role_policy(RoleName=ROLE_NAME, 
                                   PolicyArn='arn:aws:iam::aws:policy/AWSSupportAccess')
        except Exception:
            pass  # Already attached
        print(f"      ✅ AWSSupportAccess policy attached")
        
    except Exception as e:
        print(f"      ❌ Failed: {e}")
        print(f"      ℹ️  Please manually create role {ROLE_NAME} in account {account_id}")


def setup_cross_account_eventbridge(config: Dict, outputs: Dict):
    """Setup EventBridge rules to forward Support case events from all accounts"""
    print("\n📝 Step 3: Setting up cross-account EventBridge...")
    
    main_account = boto3.client('sts').get_caller_identity()['Account']
    event_bus_arn = outputs['CaseEventBusArn']
    
    for acc in config['accounts']:
        if acc['account_id'] == main_account:
            continue
            
        account_id = acc['account_id']
        account_name = acc['account_name']
        profile = acc.get('profile', 'default')
        
        print(f"\n   🔧 Account: {account_name} ({account_id})")
        
        try:
            session = boto3.Session(profile_name=profile, region_name=REGION)
            events = session.client('events')
            iam = session.client('iam')
            
            # Create EventBridge rule
            events.put_rule(
                Name='LarkCaseBot-ForwardSupportEvents',
                Description='Forward AWS Support case events to main account',
                EventPattern=json.dumps({
                    "source": ["aws.support"],
                    "detail-type": ["Support Case Update"]
                }),
                State='ENABLED'
            )
            
            # Create IAM role for EventBridge
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "events.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            }
            
            role_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Action": "events:PutEvents",
                    "Resource": event_bus_arn
                }]
            }
            
            try:
                iam.create_role(
                    RoleName='LarkCaseBot-EventBridgeRole',
                    AssumeRolePolicyDocument=json.dumps(trust_policy)
                )
            except iam.exceptions.EntityAlreadyExistsException:
                pass
            
            iam.put_role_policy(
                RoleName='LarkCaseBot-EventBridgeRole',
                PolicyName='ForwardToMainAccount',
                PolicyDocument=json.dumps(role_policy)
            )
            
            # Add target
            events.put_targets(
                Rule='LarkCaseBot-ForwardSupportEvents',
                Targets=[{
                    'Id': '1',
                    'Arn': event_bus_arn,
                    'RoleArn': f'arn:aws:iam::{account_id}:role/LarkCaseBot-EventBridgeRole'
                }]
            )
            
            print(f"      ✅ EventBridge forwarding configured")
            
        except Exception as e:
            print(f"      ❌ Failed: {e}")
    
    # Update main account event bus policy
    try:
        events_main = boto3.client('events', region_name=REGION)
        other_accounts = [acc['account_id'] for acc in config['accounts'] if acc['account_id'] != main_account]
        
        if other_accounts:
            events_main.put_permission(
                EventBusName='LarkCaseBotStack-case-event-bus',
                Action='events:PutEvents',
                Principal='*',
                StatementId='AllowCrossAccountPutEvents'
            )
            print(f"\n   ✅ Main account event bus policy updated")
    except Exception as e:
        if 'already exists' not in str(e):
            print(f"   ⚠️  Event bus policy: {e}")


def initialize_s3_config(config: Dict, outputs: Dict):
    """Initialize S3 with account configuration"""
    s3 = boto3.client('s3', region_name=REGION)
    bucket_name = outputs['DataBucketName']
    
    # Build accounts map
    accounts = {}
    for i, acc in enumerate(config['accounts']):
        accounts[str(i)] = {
            "role_arn": f"arn:aws:iam::{acc['account_id']}:role/{ROLE_NAME}",
            "account_name": acc['account_name']
        }
    
    # Bot config from file or defaults
    bot_config = config.get('bot', {})
    cfg_key = bot_config.get('cfg_key', 'LarkBotProfile-0')
    
    # Get user whitelist settings
    user_whitelist = bot_config.get('user_whitelist', {})
    
    config_data = {
        "cfg_key": cfg_key,
        "accounts": accounts,
        "user_whitelist": user_whitelist
    }
    
    s3.put_object(
        Bucket=bucket_name,
        Key=f'config/{cfg_key}.json',
        Body=json.dumps(config_data, indent=2, ensure_ascii=False).encode('utf-8'),
        ContentType='application/json'
    )
    print(f"   ✅ S3 config initialized with {len(config['accounts'])} account(s)")


# ============================================================================
# Cleanup Command
# ============================================================================

def cmd_cleanup(args):
    """Remove all LarkCase resources from all accounts"""
    config = load_config()
    
    print_header("🧹 Cleanup LarkCase Resources")
    
    print("📋 Will remove resources from:")
    for acc in config['accounts']:
        print(f"   - {acc['account_name']} ({acc['account_id']}) [profile: {acc.get('profile', 'default')}]")
    
    if not args.yes:
        confirm = input("\n⚠️  Continue? (y/N): ")
        if confirm.lower() != 'y':
            print("Cancelled.")
            return
    
    print("\n🗑️  Deleting resources...")
    for acc in config['accounts']:
        delete_account_resources(acc)
    
    print_header("✅ Cleanup Complete!")
    print("ℹ️  Note: CDK stack not destroyed. Run 'cdk destroy' separately if needed.\n")


def delete_account_resources(account: Dict):
    """Delete all resources from target account"""
    account_id = account['account_id']
    account_name = account['account_name']
    profile = account.get('profile', 'default')
    main_account = boto3.client('sts').get_caller_identity()['Account']
    
    print(f"\n   🔧 Account: {account_name} ({account_id})")
    
    try:
        session = boto3.Session(profile_name=profile, region_name=REGION)
        iam = session.client('iam')
        events = session.client('events')
        
        # Delete EventBridge resources (only for non-main accounts)
        if account_id != main_account:
            try:
                events.remove_targets(Rule='LarkCaseBot-ForwardSupportEvents', Ids=['1'])
                events.delete_rule(Name='LarkCaseBot-ForwardSupportEvents')
                print(f"      ✅ EventBridge rule deleted")
            except Exception:
                pass
            
            try:
                iam.delete_role_policy(RoleName='LarkCaseBot-EventBridgeRole', PolicyName='ForwardToMainAccount')
                iam.delete_role(RoleName='LarkCaseBot-EventBridgeRole')
                print(f"      ✅ EventBridge role deleted")
            except Exception:
                pass
        
        # Delete Support API role
        try:
            policies = iam.list_attached_role_policies(RoleName=ROLE_NAME)
            for policy in policies['AttachedPolicies']:
                iam.detach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy['PolicyArn'])
            iam.delete_role(RoleName=ROLE_NAME)
            print(f"      ✅ Support API role deleted")
        except iam.exceptions.NoSuchEntityException:
            print(f"      ⚠️  Support API role not found")
        except Exception as e:
            print(f"      ❌ Failed: {e}")
        
    except Exception as e:
        print(f"      ❌ Failed: {e}")


# ============================================================================
# Verify Command
# ============================================================================

def cmd_verify(args):
    """Verify deployment and configuration"""
    config = load_config()
    
    print_header("🔍 Verifying Configuration")
    
    all_ok = True
    
    # 1. Check Stack
    print("📦 CloudFormation Stack...")
    try:
        outputs = get_stack_outputs()
        required = ['WebhookUrl', 'DataBucketName', 'msgEventRoleArn']
        missing = [k for k in required if k not in outputs]
        if missing:
            print(f"   ❌ Missing outputs: {missing}")
            all_ok = False
        else:
            print(f"   ✅ Stack OK")
    except SystemExit:
        all_ok = False
        return
    
    # 2. Check Secrets
    print("\n🔐 Secrets Manager...")
    try:
        sm = boto3.client('secretsmanager', region_name=REGION)
        sm.get_secret_value(SecretId=outputs['AppIDSecretArn'])
        sm.get_secret_value(SecretId=outputs['AppSecretSecretArn'])
        print(f"   ✅ Secrets OK")
    except Exception as e:
        print(f"   ❌ Secrets error: {e}")
        all_ok = False
    
    # 3. Check S3 config
    print("\n📊 S3 Configuration...")
    try:
        s3 = boto3.client('s3', region_name=REGION)
        response = s3.get_object(
            Bucket=outputs['DataBucketName'],
            Key='config/LarkBotProfile-0.json'
        )
        s3_config = json.loads(response['Body'].read().decode('utf-8'))
        accounts = s3_config.get('accounts', {})
        print(f"   ✅ S3 config OK ({len(accounts)} accounts configured)")
    except Exception as e:
        print(f"   ❌ S3 config error: {e}")
        all_ok = False
    
    # 4. Check IAM roles exist
    print("\n🔑 IAM Roles (existence check)...")
    for acc in config['accounts']:
        profile = acc.get('profile', 'default')
        try:
            session = boto3.Session(profile_name=profile, region_name=REGION)
            iam = session.client('iam')
            role = iam.get_role(RoleName=ROLE_NAME)
            # Check if AWSSupportAccess is attached
            policies = iam.list_attached_role_policies(RoleName=ROLE_NAME)
            has_support = any(p['PolicyName'] == 'AWSSupportAccess' for p in policies['AttachedPolicies'])
            if has_support:
                print(f"   ✅ {acc['account_name']}: Role exists with AWSSupportAccess")
            else:
                print(f"   ⚠️  {acc['account_name']}: Role exists but missing AWSSupportAccess policy")
        except iam.exceptions.NoSuchEntityException:
            print(f"   ❌ {acc['account_name']}: Role not found")
            all_ok = False
        except Exception as e:
            print(f"   ❌ {acc['account_name']}: {e}")
            all_ok = False
    
    # Summary
    if all_ok:
        print_header("✅ All Verifications Passed!")
    else:
        print_header("⚠️  Some Verifications Failed")
    print()


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Lark Case Bot CLI - Setup and Configuration Tool (S3 Storage)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python setup_lark_bot.py setup              # Full setup
  python setup_lark_bot.py setup --skip-iam   # Skip IAM role creation
  python setup_lark_bot.py cleanup            # Remove all resources
  python setup_lark_bot.py cleanup -y         # Remove without confirmation
  python setup_lark_bot.py verify             # Verify configuration
'''
    )
    
    parser.add_argument('--lang', choices=['en', 'zh'], help='Language (en/zh)')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # setup
    setup_p = subparsers.add_parser('setup', help='Initialize bot configuration')
    setup_p.add_argument('--skip-iam', action='store_true', help='Skip IAM role creation')
    
    # cleanup
    cleanup_p = subparsers.add_parser('cleanup', help='Remove all LarkCase resources')
    cleanup_p.add_argument('-y', '--yes', action='store_true', help='Skip confirmation')
    
    # verify
    subparsers.add_parser('verify', help='Verify configuration')
    
    args = parser.parse_args()
    
    if args.lang:
        set_lang(args.lang)
    
    if args.command == 'setup':
        cmd_setup(args)
    elif args.command == 'cleanup':
        cmd_cleanup(args)
    elif args.command == 'verify':
        cmd_verify(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
