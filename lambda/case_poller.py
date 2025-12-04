"""
Case Poller Lambda - Periodic Case Status Checker (S3 Storage Version)

This Lambda function runs on a schedule (configurable via CasePollInterval parameter)
to check the status of all open AWS Support cases across multiple accounts.

IMPORTANT: AWS Support API calls are hardcoded to us-east-1 region.
AWS Support API is only available in us-east-1, regardless of where
this Lambda is deployed.

Workflow:
1. Scan S3 for all cases not in 'resolved' status
2. For each case, assume the appropriate IAM role in the target account
3. Call AWS Support API to get current case status
4. If status changed, update S3 and send notification to Lark chat
5. Update last_checked timestamp for all processed cases

Triggered by: EventBridge scheduled rule (default: every 10 minutes)

Environment Variables:
- APP_ID_ARN: Secrets Manager ARN for Lark App ID
- APP_SECRET_ARN: Secrets Manager ARN for Lark App Secret
- DATA_BUCKET: S3 bucket name for case and config data
"""
import json
import os
import boto3
import urllib3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from s3_storage import get_open_cases, update_case
from i18n import get_message, DEFAULT_LANGUAGE

# Initialize AWS clients
secrets_client = boto3.client('secretsmanager')
sts_client = boto3.client('sts')

# Initialize urllib3 PoolManager
http = urllib3.PoolManager()

# Environment variables
APP_ID_ARN = os.environ['APP_ID_ARN']
APP_SECRET_ARN = os.environ['APP_SECRET_ARN']

# Cache
_app_id = None
_app_secret = None
_tenant_access_token = None


def get_app_credentials():
    """Get Lark app credentials"""
    global _app_id, _app_secret
    
    if _app_id is None:
        response = secrets_client.get_secret_value(SecretId=APP_ID_ARN)
        secret = json.loads(response['SecretString'])
        _app_id = secret.get('app_id', '')
    
    if _app_secret is None:
        response = secrets_client.get_secret_value(SecretId=APP_SECRET_ARN)
        secret = json.loads(response['SecretString'])
        _app_secret = secret.get('app_secret', '')
    
    return _app_id, _app_secret


def get_tenant_access_token():
    """Get Lark tenant access token"""
    global _tenant_access_token
    
    app_id, app_secret = get_app_credentials()
    
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }
    
    response = http.request(
        'POST',
        url,
        body=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    result = json.loads(response.data.decode('utf-8'))
    if result.get('code') == 0:
        _tenant_access_token = result.get('tenant_access_token')
        return _tenant_access_token
    else:
        raise Exception(f"Failed to get tenant access token: {result}")


def send_lark_message(chat_id: str, content: str):
    """Send message to Lark chat"""
    token = get_tenant_access_token()
    
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=chat_id"
    
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": content})
    }
    
    response = http.request(
        'POST',
        url,
        body=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    )
    
    result = json.loads(response.data.decode('utf-8'))
    return result.get('code') == 0


def get_case_details(role_arn: str, case_id: str, include_communications: bool = False) -> Optional[Dict]:
    """Get case details from AWS Support"""
    try:
        # Assume role
        assumed_role = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='LarkCaseBotPoller'
        )
        
        credentials = assumed_role['Credentials']
        support_client = boto3.client(
            'support',
            region_name='us-east-1',
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
        
        response = support_client.describe_cases(
            caseIdList=[case_id],
            includeResolvedCases=True,
            includeCommunications=include_communications
        )
        
        if response['cases']:
            return response['cases'][0]
        return None
    except Exception as e:
        print(f"Error getting case details: {e}")
        return None


def check_case_updates():
    """Check all open cases for updates (status changes and new communications)"""
    # Get all open cases from S3
    cases = get_open_cases()
    print(f"Found {len(cases)} open cases to check")
    
    for case in cases:
        case_id = case.get('case_id')
        try:
            role_arn = case.get('role_arn')
            case_chat_id = case.get('case_chat_id')
            last_status = case.get('status', 'opened')
            last_communication_time = case.get('last_communication_time')
            
            if not all([case_id, role_arn, case_chat_id]):
                print(f"Skipping case {case_id}: missing required fields")
                continue
            
            # Get current case details with communications
            case_details = get_case_details(role_arn, case_id, include_communications=True)
            if not case_details:
                print(f"Could not get details for case {case_id}")
                continue
            
            current_status = case_details.get('status', 'opened')
            display_id = case.get('display_id', case_id)
            
            # Check for new communications
            communications = case_details.get('recentCommunications', {}).get('communications', [])
            new_comms = []
            latest_comm_time = last_communication_time
            
            for comm in communications:
                comm_time_str = comm.get('timeCreated', '')
                if not comm_time_str:
                    continue
                
                # Check if this is a new communication (after last_communication_time)
                if last_communication_time:
                    try:
                        comm_time = datetime.fromisoformat(comm_time_str.replace('Z', '+00:00'))
                        last_time = datetime.fromisoformat(last_communication_time.replace('Z', '+00:00'))
                        if comm_time <= last_time:
                            continue  # Skip already synced communications
                    except Exception as e:
                        print(f"Error parsing time: {e}")
                        continue
                
                # Skip messages sent via Lark (already confirmed in chat, no need to echo back)
                body = comm.get('body', '')
                if '[From ' in body and 'via Lark]' in body:
                    print(f"Skipping Lark-originated message for case {case_id}")
                    # Still update latest_comm_time to avoid re-processing
                    if not latest_comm_time or comm_time_str > latest_comm_time:
                        latest_comm_time = comm_time_str
                    continue
                
                # Include AWS Support replies and customer replies from console
                new_comms.append(comm)
                
                # Track latest communication time
                if not latest_comm_time or comm_time_str > latest_comm_time:
                    latest_comm_time = comm_time_str
            
            # Sort by time (oldest first) to send in chronological order
            new_comms.sort(key=lambda x: x.get('timeCreated', ''))
            
            # Send notifications for all new communications
            for comm in new_comms:
                body = comm.get('body', '')
                submitted_by = comm.get('submittedBy', '')
                
                # Truncate long messages
                if len(body) > 1000:
                    body = body[:1000] + '...\n\n' + get_message(DEFAULT_LANGUAGE, 'poller_message_truncated')
                
                # Different emoji for AWS Support vs customer
                if 'Amazon Web Services' in submitted_by:
                    emoji = "📨"
                    sender = "AWS Support"
                else:
                    emoji = "💬"
                    sender = submitted_by if submitted_by else "Console"
                
                message = f"{emoji} {get_message(DEFAULT_LANGUAGE, 'poller_case_reply')} [{sender}]\n\n{get_message(DEFAULT_LANGUAGE, 'poller_case_label')}: {display_id}\n\n{body}"
                send_lark_message(case_chat_id, message)
                print(f"Sent communication notification for case {case_id} from {sender}")
            
            # Check if status changed
            status_changed = current_status != last_status
            if status_changed:
                print(f"Case {case_id} status changed: {last_status} -> {current_status}")
                
                # Send status notification to Lark
                status_map = {
                    'opened': get_message(DEFAULT_LANGUAGE, 'status_opened'),
                    'pending-customer-action': get_message(DEFAULT_LANGUAGE, 'status_pending_customer'),
                    'customer-action-completed': get_message(DEFAULT_LANGUAGE, 'status_customer_completed'),
                    'reopened': get_message(DEFAULT_LANGUAGE, 'status_reopened'),
                    'resolved': get_message(DEFAULT_LANGUAGE, 'status_resolved'),
                    'unassigned': get_message(DEFAULT_LANGUAGE, 'status_unassigned'),
                    'work-in-progress': get_message(DEFAULT_LANGUAGE, 'status_in_progress')
                }
                
                status_display = status_map.get(current_status, current_status)
                message = f"📢 {get_message(DEFAULT_LANGUAGE, 'poller_status_update')}\n\n{get_message(DEFAULT_LANGUAGE, 'poller_case_label')}: {display_id}\n{get_message(DEFAULT_LANGUAGE, 'poller_new_status')}: {status_display}"
                
                # Add auto-dissolve notice if case is resolved
                if current_status == 'resolved':
                    auto_dissolve_hours = int(os.environ.get('AUTO_DISSOLVE_HOURS', '72'))
                    message += f"\n\n{get_message(DEFAULT_LANGUAGE, 'case_resolved_dissolve_notice').format(auto_dissolve_hours)}"
                
                if send_lark_message(case_chat_id, message):
                    print(f"Sent status change notification for case {case_id}: {last_status} -> {current_status}")
                else:
                    print(f"Failed to send status change notification for case {case_id}")
            
            # Update S3 with latest info
            now_iso = datetime.now(timezone.utc).isoformat()
            update_data = {
                'last_checked': now_iso
            }
            if status_changed:
                update_data['status'] = current_status
                # Record resolved_at time for auto-dissolve feature
                if current_status == 'resolved':
                    update_data['resolved_at'] = now_iso
            if latest_comm_time and latest_comm_time != last_communication_time:
                update_data['last_communication_time'] = latest_comm_time
            
            update_case(case_id, update_data)
            
        except Exception as e:
            print(f"Error processing case {case_id}: {e}")
            continue


def lambda_handler(event, context):
    """Lambda handler for scheduled case polling"""
    print(f"Starting case polling at {datetime.now(timezone.utc).isoformat()}")
    
    try:
        check_case_updates()
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Case polling completed'})
        }
    except Exception as e:
        print(f"Error in case polling: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
