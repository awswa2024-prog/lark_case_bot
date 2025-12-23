"""
Case Update Handler Lambda - Real-time AWS Support Event Processor (S3 Storage Version)

This Lambda function handles real-time AWS Support case events from EventBridge
and pushes notifications to the corresponding Lark chat.

IMPORTANT: This Lambda MUST be deployed in us-east-1 region.
AWS Support EventBridge events are ONLY sent to us-east-1.
Deploying to other regions will result in no events being received.

Supported Events:
- AddCommunicationToCase: New reply from AWS Support engineer
- ResolveCase: Case marked as resolved
- ReopenCase: Case reopened

Features:
- Fetches complete communication content from AWS Support API
- Filters out Lark-originated messages to avoid echo
- Tracks last_communication_time to prevent duplicate notifications
- Supports dual timezone display (UTC and Beijing time)
- Sends rich text messages with case links to AWS Console

Triggered by: EventBridge rule matching 'aws.support' events

Environment Variables:
- APP_ID_ARN: Secrets Manager ARN for Lark App ID
- APP_SECRET_ARN: Secrets Manager ARN for Lark App Secret
- DATA_BUCKET: S3 bucket name for case data
"""
import json
import os
import boto3
import urllib3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Union
from s3_storage import get_case, update_case

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
    
    # TODO: Implement token caching with expiration
    # For now, get fresh token each time
    
    app_id, app_secret = get_app_credentials()
    
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }
    
    encoded_data = json.dumps(payload).encode('utf-8')
    response = http.request(
        'POST',
        url,
        body=encoded_data,
        headers={'Content-Type': 'application/json'}
    )
    
    result = json.loads(response.data.decode('utf-8'))
    
    if result.get('code') == 0:
        _tenant_access_token = result.get('tenant_access_token')
        return _tenant_access_token
    else:
        raise Exception(f"Failed to get tenant access token: {result}")


def get_case_info(case_id: str) -> Optional[Dict[str, Any]]:
    """Get case information from S3"""
    return get_case(case_id)


def update_last_communication_time(case_id: str, last_time: str):
    """Update the last communication time in S3"""
    update_case(case_id, {'last_communication_time': last_time})


def get_recent_communications(role_arn: str, case_id: str, last_communication_time: Optional[str] = None, minutes_back: int = 15) -> tuple:
    """
    Get recent communications from AWS Support case since last check
    
    Args:
        role_arn: IAM role ARN to assume
        case_id: AWS Support case ID
        last_communication_time: ISO timestamp of last processed communication (optional)
        minutes_back: Fallback: how many minutes back to look if no last_communication_time (default: 15)
    
    Returns:
        Tuple of (communications_list, case_status)
        - communications_list: List of communication dicts, sorted by time (oldest first)
        - case_status: Current case status string
    """
    try:
        # Assume role
        assumed_role = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='LarkCaseBotGetCommunication'
        )
        
        credentials = assumed_role['Credentials']
        support_client = boto3.client(
            'support',
            region_name='us-east-1',
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
        
        # Get case details with communications
        response = support_client.describe_cases(
            caseIdList=[case_id],
            includeCommunications=True,
            includeResolvedCases=True
        )
        
        if not response['cases']:
            return ([], None)
        
        case_data = response['cases'][0]
        case_status = case_data.get('status', 'unknown')
        communications = case_data.get('recentCommunications', {}).get('communications', [])
        
        if not communications:
            return ([], case_status)
        
        # Calculate time threshold
        if last_communication_time:
            # Use the last communication time from S3
            try:
                threshold = datetime.fromisoformat(last_communication_time.replace('Z', '+00:00'))
                print(f"Using last communication time as threshold: {last_communication_time}")
            except Exception as e:
                print(f"Error parsing last_communication_time {last_communication_time}: {e}")
                # Fallback to time window
                now = datetime.now(timezone.utc)
                threshold = now - timedelta(minutes=minutes_back)
                print(f"Fallback to {minutes_back} minutes window")
        else:
            # No last communication time, use time window
            now = datetime.now(timezone.utc)
            threshold = now - timedelta(minutes=minutes_back)
            print(f"No last communication time, using {minutes_back} minutes window")
        
        # Filter communications within time window
        recent_comms = []
        for comm in communications:
            time_created_str = comm.get('timeCreated', '')
            if not time_created_str:
                continue
            
            try:
                # Parse AWS time format
                comm_time = datetime.fromisoformat(time_created_str.replace('Z', '+00:00'))
                
                # Check if after threshold (only get new communications)
                if comm_time > threshold:
                    body = comm.get('body', '')
                    
                    # Skip Lark-originated messages
                    if is_lark_originated_message(body):
                        print(f"Skipping Lark-originated message from {comm.get('submittedBy')}")
                        continue
                    
                    recent_comms.append({
                        'body': body,
                        'submitted_by': comm.get('submittedBy', 'AWS Support'),
                        'time_created': time_created_str,
                        'case_id': comm.get('caseId', case_id)
                    })
            except Exception as e:
                print(f"Error parsing communication time {time_created_str}: {e}")
                continue
        
        if last_communication_time:
            print(f"Found {len(recent_comms)} new communications since {last_communication_time}")
        else:
            print(f"Found {len(recent_comms)} recent communications (within {minutes_back} minutes)")
        
        # Reverse the list so oldest messages are sent first (matching Lark timeline)
        # AWS API returns newest first, but we want to send oldest first
        recent_comms.reverse()
        
        return (recent_comms, case_status)
        
    except Exception as e:
        print(f"Error getting communications: {e}")
        import traceback
        traceback.print_exc()
        return ([], None)


def send_post_message(chat_id: str, title: str, content: list):
    """Send rich text post message to Lark chat"""
    token = get_tenant_access_token()
    
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    post_content = {
        "zh_cn": {
            "title": title,
            "content": content
        }
    }
    
    payload = {
        "receive_id": chat_id,
        "msg_type": "post",
        "content": json.dumps(post_content)
    }
    
    encoded_data = json.dumps(payload).encode('utf-8')
    response = http.request(
        'POST',
        url,
        body=encoded_data,
        headers=headers
    )
    
    result = json.loads(response.data.decode('utf-8'))
    
    if result.get('code') != 0:
        print(f"Failed to send post message: {result}")
        raise Exception(f"Failed to send post message: {result}")


def format_aws_time_dual(aws_time_str: str) -> str:
    """Convert AWS time string to display both UTC and Beijing time"""
    try:
        if 'T' in aws_time_str:
            dt = datetime.fromisoformat(aws_time_str.replace('Z', '+00:00'))
            
            # UTC time
            utc_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Beijing time (UTC+8)
            beijing_dt = dt + timedelta(hours=8)
            beijing_str = beijing_dt.strftime('%Y-%m-%d %H:%M:%S')
            
            return f"{utc_str} UTC / {beijing_str} GMT+8"
        else:
            return aws_time_str
    except Exception as e:
        print(f"Error formatting time {aws_time_str}: {e}")
        return aws_time_str


def is_lark_originated_message(body: str) -> bool:
    """Check if the message was originated from Lark"""
    # Messages sent from Lark have this prefix pattern (Chinese: "[来自" means "[From")
    return body.startswith('[来自') and 'via Lark]' in body


def get_dual_timezone_time() -> str:
    """Get current time in both UTC and Beijing timezone"""
    utc_now = datetime.now(timezone.utc)
    beijing_time = utc_now + timedelta(hours=8)
    
    utc_str = utc_now.strftime('%Y-%m-%d %H:%M:%S')
    beijing_str = beijing_time.strftime('%Y-%m-%d %H:%M:%S')
    
    return f"{utc_str} UTC / {beijing_str} GMT+8"


def format_case_update(event_detail: Dict[str, Any], case_info: Dict[str, Any]) -> Optional[Union[tuple, List[tuple]]]:
    """
    Format case update message
    Returns: 
        - (title, content) tuple for single message
        - List of (title, content) tuples for multiple messages
        - None to skip
    """
    event_type = event_detail.get('event-name', event_detail.get('event-type-code', ''))
    case_id = event_detail.get('case-id', '')
    display_id = case_info.get('display_id', case_id)
    
    print(f"Processing event: event_type={event_type}, case_id={case_id}, display_id={display_id}")
    
    # Build AWS Console link (use display_id as clickable link)
    support_url = f"https://support.console.aws.amazon.com/support/home#/case/?displayId={display_id}"
    
    if event_type == 'AddCommunicationToCase':
        # New reply - get all communications within time window
        communication_id = event_detail.get('communication-id', '')
        origin = event_detail.get('origin', '')
        
        print(f"Communication event: id={communication_id}, origin={origin}")
        
        # Get role_arn to call AWS Support API
        role_arn = case_info.get('role_arn')
        
        if not role_arn:
            print(f"No role_arn found for case {case_id}, cannot fetch communication")
            return None
        
        # Get last processed communication time
        last_communication_time = case_info.get('last_communication_time')
        
        # Get new communications (only those after last time) and case status
        recent_comms, case_status = get_recent_communications(role_arn, case_id, last_communication_time, minutes_back=15)
        
        if not recent_comms:
            print(f"No new communications found for case {case_id}")
            return None
        
        # Build message for each reply
        messages_to_send = []
        latest_time = None  # Track the latest communication time
        
        for comm in recent_comms:
            body = comm['body']
            submitted_by = comm['submitted_by']
            time_created = comm['time_created']
            
            # Format time
            time_str = format_aws_time_dual(time_created) if time_created else get_dual_timezone_time()
            
            # Determine reply source
            is_aws_support = 'amazon' in submitted_by.lower() or 'aws' in submitted_by.lower()
            
            # Set icon
            if is_aws_support:
                icon = "👨‍💻"
            else:
                icon = "👤"
            
            # Limit message length to avoid being too long
            max_body_length = 8000
            if len(body) > max_body_length:
                body_preview = body[:max_body_length] + "\n\n... (Content truncated, click Case ID to view full content)"
            else:
                body_preview = body
            
            # Build message content (no title, Case ID as link)
            content = [
                [{"tag": "a", "text": f"Case ID: {display_id}", "href": support_url, "style": ["bold"]}],
                [{"tag": "text", "text": "📊 Status", "style": ["bold"]}, {"tag": "text", "text": f": {case_status}"}],
                [{"tag": "text", "text": f"{icon} Replied By", "style": ["bold"]}, {"tag": "text", "text": f": {submitted_by}"}],
                [{"tag": "text", "text": "🕐 Time", "style": ["bold"]}, {"tag": "text", "text": f": {time_str}"}],
                [{"tag": "text", "text": ""}],
            ]
            
            # Split reply content by lines
            for line in body_preview.split('\n'):
                if line.strip():
                    content.append([{"tag": "text", "text": line}])
                else:
                    content.append([{"tag": "text", "text": ""}])
            
            # Use empty title (Lark will display as normal message)
            messages_to_send.append(("", content))
            
            # Track the latest communication time
            latest_time = time_created
        
        # Return message list and latest time (for updating S3)
        # Format: (messages, latest_communication_time)
        if len(messages_to_send) > 1:
            return (messages_to_send, latest_time)
        elif messages_to_send:
            return (messages_to_send[0], latest_time)
        else:
            return None
    
    elif event_type == 'ResolveCase':
        # Skip if already resolved (dedup multiple EventBridge events)
        if case_info.get('status') == 'resolved':
            print(f"Case {case_id} already resolved, skipping duplicate ResolveCase event")
            return None
        
        # Case resolved - record resolved time for auto-dissolve
        resolved_at = datetime.now(timezone.utc).isoformat()
        update_case(case_id, {
            'status': 'resolved',
            'resolved_at': resolved_at
        })
        
        time_str = get_dual_timezone_time()
        auto_dissolve_hours = int(os.environ.get('AUTO_DISSOLVE_HOURS', '72'))
        
        content = [
            [{"tag": "a", "text": f"Case ID: {display_id}", "href": support_url, "style": ["bold"]}],
            [{"tag": "text", "text": "Time", "style": ["bold"]}, {"tag": "text", "text": f": {time_str}"}],
            [{"tag": "text", "text": ""}],
            [{"tag": "text", "text": "✅ Case has been marked as resolved"}],
            [{"tag": "text", "text": ""}],
            [{"tag": "text", "text": f"⏰ This group will be automatically dissolved in {auto_dissolve_hours} hours", "style": ["italic"]}],
            [{"tag": "text", "text": "To follow up, please reopen the case in AWS Console", "style": ["italic"]}],
        ]
        return ("✅ Case Resolved", content)
    
    elif event_type == 'ReopenCase':
        # Case reopened - update status in S3
        update_case(case_id, {
            'status': 'reopened',
            'resolved_at': None  # Clear resolved time
        })
        
        time_str = get_dual_timezone_time()
        content = [
            [{"tag": "a", "text": f"Case ID: {display_id}", "href": support_url, "style": ["bold"]}],
            [{"tag": "text", "text": "Time", "style": ["bold"]}, {"tag": "text", "text": f": {time_str}"}],
            [{"tag": "text", "text": ""}],
            [{"tag": "text", "text": "🔓 Case has been reopened"}],
        ]
        return ("🔓 Case Reopened", content)
    
    elif event_type == 'CreateCase':
        # Case creation - usually no notification needed (user initiated)
        print(f"Ignoring CreateCase event (user initiated)")
        return None
    
    else:
        # Ignore other event types
        print(f"Ignoring event type: {event_type}")
        return None


def lambda_handler(event, context):
    """Main Lambda handler for EventBridge events"""
    try:
        print(f"Received event: {json.dumps(event)}")
        
        # Parse EventBridge event
        detail = event.get('detail', {})
        case_id = detail.get('case-id', '')
        
        if not case_id:
            print("No case ID in event")
            return {'statusCode': 200, 'body': 'No case ID'}
        
        # Get case info from S3
        case_info = get_case_info(case_id)
        
        if not case_info:
            print(f"Case {case_id} not found in S3")
            return {'statusCode': 200, 'body': 'Case not found'}
        
        # Use case_chat_id (case group) if available, otherwise fall back to chat_id
        case_chat_id = case_info.get('case_chat_id')
        chat_id = case_info.get('chat_id')
        
        target_chat_id = case_chat_id if case_chat_id else chat_id
        
        if not target_chat_id:
            print(f"No chat_id or case_chat_id for case {case_id}")
            return {'statusCode': 200, 'body': 'No chat ID'}
        
        # Format and send message(s)
        result = format_case_update(detail, case_info)
        
        if result is None:
            print(f"Event type ignored, no message sent")
            return {'statusCode': 200, 'body': 'Event ignored'}
        
        # Extract messages and latest_time from result
        # Result format: 
        # - For communication events: (messages, latest_communication_time) where messages is tuple or list of tuples
        # - For other events: (title, content) tuple directly
        latest_communication_time = None
        
        if isinstance(result, tuple) and len(result) == 2:
            first, second = result
            # Check if second element is a timestamp string (communication event)
            # vs a list (content for single message)
            if isinstance(second, str) and not isinstance(first, str):
                # Communication event: (messages, timestamp)
                messages, latest_communication_time = result
            elif isinstance(second, list):
                # Single message: (title, content)
                messages = result
            else:
                messages = result
        else:
            # Other event types
            messages = result
        
        # Handle single message or multiple messages
        if isinstance(messages, list) and len(messages) > 0 and isinstance(messages[0], tuple):
            # Multiple messages
            print(f"Sending {len(messages)} messages")
            for title, content in messages:
                send_post_message(target_chat_id, title, content)
                print(f"Sent message")
        else:
            # Single message
            title, content = messages
            send_post_message(target_chat_id, title, content)
            print(f"Sent message")
        
        # Update last communication time in S3 if we have it
        if latest_communication_time:
            update_last_communication_time(case_id, latest_communication_time)
            print(f"Updated last_communication_time to {latest_communication_time}")
        
        print(f"Successfully sent update for case {case_id} to chat {target_chat_id}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Update sent successfully'})
        }
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
