#!/usr/bin/env python3
"""
Group Cleanup Lambda - Auto-dissolve resolved case groups

This Lambda automatically dissolves Lark groups for resolved cases 
after a configurable time period (default: 72 hours).

Triggered by: EventBridge scheduled rule (every hour)

Environment Variables:
- DATA_BUCKET: S3 bucket name for case data
- APP_ID_ARN: Secrets Manager ARN for Lark App ID
- APP_SECRET_ARN: Secrets Manager ARN for Lark App Secret
- AUTO_DISSOLVE_HOURS: Hours to wait before auto-dissolving (default: 72)
"""
import json
import os
import boto3
import urllib3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from s3_storage import get_all_cases, update_case

# Initialize clients
secrets_client = boto3.client('secretsmanager')
http = urllib3.PoolManager()

# Environment variables
AUTO_DISSOLVE_HOURS = int(os.environ.get('AUTO_DISSOLVE_HOURS', '72'))
APP_ID_ARN = os.environ.get('APP_ID_ARN', '')
APP_SECRET_ARN = os.environ.get('APP_SECRET_ARN', '')

# Cache
_app_id = None
_app_secret = None
_tenant_access_token = None


def get_app_credentials():
    """Get Lark app credentials from Secrets Manager"""
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


def get_tenant_access_token() -> str:
    """Get Lark tenant access token"""
    global _tenant_access_token
    
    app_id, app_secret = get_app_credentials()
    
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": app_id, "app_secret": app_secret}
    
    response = http.request(
        'POST', url,
        body=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    result = json.loads(response.data.decode('utf-8'))
    if result.get('code') == 0:
        _tenant_access_token = result.get('tenant_access_token')
        return _tenant_access_token
    else:
        raise Exception(f"Failed to get access token: {result}")


def send_message(chat_id: str, text: str):
    """Send text message to chat"""
    token = get_tenant_access_token()
    
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }
    
    response = http.request('POST', url, body=json.dumps(payload).encode('utf-8'), headers=headers)
    result = json.loads(response.data.decode('utf-8'))
    
    if result.get('code') != 0:
        print(f"Failed to send message: {result}")


def dissolve_group_chat(chat_id: str) -> dict:
    """Dissolve (delete) a group chat"""
    try:
        token = get_tenant_access_token()
        
        url = f"https://open.larksuite.com/open-apis/im/v1/chats/{chat_id}"
        headers = {"Authorization": f"Bearer {token}"}
        
        response = http.request('DELETE', url, headers=headers)
        result = json.loads(response.data.decode('utf-8'))
        
        if result.get('code') == 0:
            return {'success': True, 'code': 0, 'msg': 'Group dissolved'}
        else:
            return {'success': False, 'code': result.get('code'), 'msg': result.get('msg', 'Unknown error')}
            
    except Exception as e:
        print(f"Error dissolving group: {e}")
        return {'success': False, 'code': -1, 'msg': str(e)}


def check_and_dissolve_resolved_cases() -> int:
    """Check for resolved cases that should be auto-dissolved"""
    print(f"=== Group Cleanup (Auto-dissolve after {AUTO_DISSOLVE_HOURS} hours) ===")
    
    try:
        all_cases = get_all_cases()
        print(f"Found {len(all_cases)} total cases")
        
        now = datetime.now(timezone.utc)
        dissolved_count = 0
        
        for case in all_cases:
            case_id = case.get('case_id')
            status = case.get('status')
            resolved_at = case.get('resolved_at')
            case_chat_id = case.get('case_chat_id')
            chat_dissolved = case.get('chat_dissolved', False)
            
            # Skip if not resolved, already dissolved, or no chat
            if status != 'resolved' or chat_dissolved or not resolved_at or not case_chat_id:
                continue
            
            try:
                # Parse resolved time
                resolved_time = datetime.fromisoformat(resolved_at.replace('Z', '+00:00'))
                hours_passed = (now - resolved_time).total_seconds() / 3600
                
                print(f"Case {case_id}: resolved {hours_passed:.1f}h ago")
                
                if hours_passed >= AUTO_DISSOLVE_HOURS:
                    print(f"Auto-dissolving group for case {case_id}")
                    
                    # Send notification before dissolving
                    display_id = case.get('display_id', case_id)
                    send_message(case_chat_id, 
                        f"🤖 Case {display_id} has been resolved for over {AUTO_DISSOLVE_HOURS} hours.\n"
                        f"This group will now be automatically dissolved.\n\n"
                        f"The case still exists in AWS Support Console if you need to reopen it."
                    )
                    
                    # Dissolve the group
                    result = dissolve_group_chat(case_chat_id)
                    
                    if result['success']:
                        update_case(case_id, {
                            'chat_dissolved': True,
                            'dissolved_at': now.isoformat(),
                            'auto_dissolved': True
                        })
                        dissolved_count += 1
                        print(f"✅ Auto-dissolved group for case {case_id}")
                    else:
                        print(f"❌ Failed to dissolve: {result['msg']}")
                        
            except Exception as e:
                print(f"Error processing case {case_id}: {e}")
                continue
        
        print(f"Auto-dissolved {dissolved_count} groups")
        return dissolved_count
        
    except Exception as e:
        print(f"Error in group cleanup: {e}")
        return 0


def lambda_handler(event, context):
    """Lambda handler for scheduled group cleanup"""
    print(f"Group cleanup triggered: {json.dumps(event, default=str)}")
    
    try:
        dissolved_count = check_and_dissolve_resolved_cases()
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Group cleanup completed',
                'dissolved_count': dissolved_count
            })
        }
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
