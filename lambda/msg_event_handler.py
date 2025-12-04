"""
Lark Message Event Handler Lambda - Main Bot Logic (S3 Storage Version)

This is the core Lambda function that handles all Lark message events and
implements the main bot functionality.

IMPORTANT: AWS Support API calls are hardcoded to us-east-1 region.
AWS Support API is only available in us-east-1, regardless of where
this Lambda is deployed.

Features:
1. Multi-step conversation flow for case creation
2. Case group chat creation and management
3. Message sync from Lark case chat to AWS Support
4. File attachment upload to AWS Support
5. Case history query
6. Multi-language support (zh/en/ja)
7. User whitelist access control
8. Cross-account AWS Support case creation

Commands:
- create case [title]: Create new AWS Support case
- reply case [content]: Reply to case (in case chat only)
- history: Query recent 10 cases
- follow [case ID]: Join existing case chat
- help: Show help message

Triggered by: API Gateway POST /messages (Lark webhook)

Environment Variables:
- APP_ID_ARN: Secrets Manager ARN for Lark App ID
- APP_SECRET_ARN: Secrets Manager ARN for Lark App Secret
- DATA_BUCKET: S3 bucket for bot configuration and case tracking
- CFG_KEY: Configuration key in S3 (default: LarkBotProfile-0)
- CASE_LANGUAGE: AWS Support case language (zh/ja/ko/en)
- USER_WHITELIST: Enable user whitelist (true/false)
"""
import json
import os
import boto3
import urllib3
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from aws_services_complete import (
    get_all_services_flat,
    get_services_for_issue_type,
    merge_with_cost_explorer_services,
    CE_TO_SUPPORT_MAPPING,
    ISSUE_TYPES
)
from i18n import get_user_language, get_message, detect_command_language, MESSAGES, DEFAULT_LANGUAGE
from s3_storage import (
    get_bot_config as s3_get_bot_config,
    get_case, put_case, update_case, delete_case,
    get_case_by_chat_id as s3_get_case_by_chat_id,
    get_cases_by_user as s3_get_cases_by_user,
    get_case_by_case_chat_id,
    scan_cases_by_filter
)

# Initialize urllib3 PoolManager
http = urllib3.PoolManager()

# Initialize AWS clients
secrets_client = boto3.client('secretsmanager')
sts_client = boto3.client('sts')

# Environment variables
APP_ID_ARN = os.environ['APP_ID_ARN']
APP_SECRET_ARN = os.environ['APP_SECRET_ARN']
DATA_BUCKET = os.environ.get('DATA_BUCKET', '')
CFG_KEY = os.environ.get('CFG_KEY', 'LarkBotProfile-0')
CASE_LANGUAGE = os.environ.get('CASE_LANGUAGE', 'zh')
USER_WHITELIST = os.environ.get('USER_WHITELIST', 'false').lower() == 'true'
ATTACHMENT_BUCKET = os.environ.get('ATTACHMENT_BUCKET', '')

# Cache
_app_id = None
_app_secret = None
_bot_config = None
_tenant_access_token = None

# Event deduplication cache (in-memory for Lambda warm starts)
_processed_events = {}
MAX_CACHE_SIZE = 100


def get_dual_timezone_time() -> str:
    """Get current time in both UTC and Beijing timezone
    
    Returns:
        Formatted string with both UTC and Beijing time
    """
    utc_now = datetime.now(timezone.utc)
    beijing_time = utc_now + timedelta(hours=8)
    
    utc_str = utc_now.strftime('%Y-%m-%d %H:%M:%S')
    beijing_str = beijing_time.strftime('%Y-%m-%d %H:%M:%S')
    
    return f"{utc_str} UTC / {beijing_str} GMT+8"


def format_aws_time_dual(aws_time_str: str) -> str:
    """Convert AWS time string to display both UTC and Beijing time
    
    Args:
        aws_time_str: AWS time string (usually in UTC)
        
    Returns:
        Formatted string with both UTC and Beijing time
    """
    try:
        # AWS times are usually in format like "2025-11-25T09:03:49Z"
        if 'T' in aws_time_str:
            dt = datetime.fromisoformat(aws_time_str.replace('Z', '+00:00'))
            
            # UTC time
            utc_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Beijing time (UTC+8)
            beijing_dt = dt + timedelta(hours=8)
            beijing_str = beijing_dt.strftime('%Y-%m-%d %H:%M:%S')
            
            return f"{utc_str} UTC / {beijing_str} GMT+8"
        else:
            # Already formatted, return as is
            return aws_time_str
    except Exception as e:
        print(f"Error formatting time {aws_time_str}: {e}")
        return aws_time_str


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


def get_tenant_access_token():
    """Get Lark tenant access token"""
    global _tenant_access_token
    
    # TODO: Implement token caching with expiration
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


def get_user_info(user_id: str = None, open_id: str = None) -> Dict[str, str]:
    """Get user information from Lark API
    
    Args:
        user_id: Lark user_id (internal ID)
        open_id: Lark open_id (app-level ID)
    
    Returns:
        Dict with 'name', 'en_name', 'email'
    """
    try:
        token = get_tenant_access_token()
        
        # Prefer open_id as it's more reliable in message events
        if open_id:
            url = f"https://open.larksuite.com/open-apis/contact/v3/users/{open_id}?user_id_type=open_id"
            fallback_name = open_id
        elif user_id:
            url = f"https://open.larksuite.com/open-apis/contact/v3/users/{user_id}?user_id_type=user_id"
            fallback_name = user_id
        else:
            return {'name': 'Unknown User'}
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        print(f"Requesting user info from: {url}")
        response = http.request('GET', url, headers=headers)
        result = json.loads(response.data.decode('utf-8'))
        print(f"User API response: {result}")
        
        if result.get('code') == 0:
            user_data = result.get('data', {}).get('user', {})
            return {
                'name': user_data.get('name', fallback_name),
                'en_name': user_data.get('en_name', ''),
                'email': user_data.get('email', '')
            }
        else:
            print(f"Failed to get user info: {result}")
            return {'name': fallback_name}
    except Exception as e:
        print(f"Error getting user info: {e}")
        return {'name': fallback_name if 'fallback_name' in locals() else 'Unknown User'}


def send_message(chat_id: str, msg_type: str, content: dict, reply_to_message_id: str = None):
    """Send message to Lark chat
    
    Args:
        chat_id: Target chat ID
        msg_type: Message type (text, post, etc.)
        content: Message content dict
        reply_to_message_id: Optional message ID to reply to (for threading)
    """
    token = get_tenant_access_token()
    
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "receive_id": chat_id,
        "msg_type": msg_type,
        "content": json.dumps(content)
    }
    
    # Add reply reference if provided
    if reply_to_message_id:
        payload["reply_in_thread"] = False  # Reply in main chat, not thread
        # Use uuid parameter to reference the original message
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{reply_to_message_id}/reply"
    
    encoded_data = json.dumps(payload).encode('utf-8')
    response = http.request(
        'POST',
        url,
        body=encoded_data,
        headers=headers
    )
    
    result = json.loads(response.data.decode('utf-8'))
    
    if result.get('code') != 0:
        # 200341 is card expired error, this is normal and should not throw exception
        if result.get('code') == 200341:
            print(f"Card expired (200341), this is expected and not an error")
            return result
        print(f"Failed to send message: {result}")
        raise Exception(f"Failed to send message: {result}")
    
    return result


def send_card(chat_id: str, card: dict):
    """Send interactive card to Lark chat"""
    token = get_tenant_access_token()
    
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card)
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
        print(f"Failed to send card: {result}")
        raise Exception(f"Failed to send card: {result}")
    
    return result


def recall_message(message_id: str):
    """Recall a message from Lark chat"""
    token = get_tenant_access_token()
    
    url = f"https://open.larksuite.com/open-apis/im/v1/messages/{message_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = http.request(
        'DELETE',
        url,
        headers=headers
    )
    
    result = json.loads(response.data.decode('utf-8'))
    
    if result.get('code') != 0:
        print(f"Failed to recall message: {result}")
        # Don't throw exception as message may have been deleted or expired
    
    return result


def send_post_message(chat_id: str, title: str, content: list):
    """Send rich text post message to Lark chat (supports bold, links, etc.)"""
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
    
    return result


def create_group_chat(name: str, user_ids: List[str]) -> str:
    """Create a group chat for case tracking"""
    token = get_tenant_access_token()
    
    url = "https://open.larksuite.com/open-apis/im/v1/chats"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "name": name,
        "description": f"AWS Support Case: {name}",
        "user_id_list": user_ids
    }
    
    encoded_data = json.dumps(payload).encode('utf-8')
    response = http.request(
        'POST',
        url,
        body=encoded_data,
        headers=headers
    )
    
    result = json.loads(response.data.decode('utf-8'))
    
    if result.get('code') == 0:
        return result['data']['chat_id']
    else:
        print(f"Failed to create group: {result}")
        raise Exception(f"Failed to create group: {result}")


def dissolve_group_chat(chat_id: str) -> dict:
    """Dissolve (delete) a group chat
    
    Returns:
        dict with 'success' (bool), 'code' (int), 'msg' (str)
    """
    try:
        token = get_tenant_access_token()
        
        url = f"https://open.larksuite.com/open-apis/im/v1/chats/{chat_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = http.request('DELETE', url, headers=headers)
        result = json.loads(response.data.decode('utf-8'))
        
        print(f"Dissolve group chat response: {result}")
        
        code = result.get('code', -1)
        msg = result.get('msg', 'Unknown error')
        
        if code == 0:
            return {'success': True, 'code': code, 'msg': 'Group dissolved'}
        else:
            return {'success': False, 'code': code, 'msg': msg}
    except Exception as e:
        print(f"Error dissolving group chat: {e}")
        return {'success': False, 'code': -1, 'msg': str(e)}


def download_file(file_key: str) -> bytes:
    """Download file from Lark"""
    token = get_tenant_access_token()
    
    url = f"https://open.larksuite.com/open-apis/im/v1/messages/{file_key}/resources/{file_key}"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    response = http.request('GET', url, headers=headers)
    
    if response.status == 200:
        return response.data
    else:
        raise Exception(f"Failed to download file: {response.status}")


def get_bot_config():
    """Get bot configuration from S3"""
    global _bot_config
    
    if _bot_config is None:
        _bot_config = s3_get_bot_config(CFG_KEY) or {}
    
    return _bot_config


def check_user_whitelist(user_id: str) -> bool:
    """Check if user is in whitelist"""
    if not USER_WHITELIST:
        return True
    
    config = get_bot_config()
    whitelist = config.get('user_whitelist', {})
    return user_id in whitelist


def match_command(text: str, command_key: str) -> tuple:
    """
    Match command in any supported language
    
    Args:
        text: User input text
        command_key: Command key (e.g., 'create_case', 'reply_case', 'history', 'follow', 'help')
        
    Returns:
        (matched: bool, lang: str, remaining_text: str)
    """
    text_lower = text.lower()
    
    # Special handling for help command - support multiple aliases
    if command_key == 'help':
        help_aliases = {
            'zh': [MESSAGES['zh']['help']],
            'en': [MESSAGES['en']['help']],
        }
        for lang, aliases in help_aliases.items():
            for alias in aliases:
                if text == alias or text_lower == alias.lower():
                    return (True, lang, '')
    
    # Check all supported languages
    for lang in ['zh', 'en']:
        if lang not in MESSAGES:
            continue
            
        cmd = MESSAGES[lang].get(command_key, '')
        if not cmd:
            continue
        
        # Exact match for single-word commands
        if command_key in ['history', 'help']:
            if text == cmd or text_lower == cmd.lower():
                return (True, lang, '')
        
        # Prefix match for commands with arguments
        elif text.startswith(cmd) or text_lower.startswith(cmd.lower()):
            # Extract remaining text after command
            remaining = text[len(cmd):].strip()
            return (True, lang, remaining)
    
    return (False, 'zh', '')


def get_case_by_chat_id(chat_id: str) -> Optional[Dict[str, Any]]:
    """Get case information by chat_id"""
    return s3_get_case_by_chat_id(chat_id)


def get_cases_by_user(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get user's recent cases"""
    return s3_get_cases_by_user(user_id, limit)


def save_case_info(case_id: str, display_id: str, chat_id: str, user_id: str, 
                   subject: str, account_id: str, case_chat_id: str = None, role_arn: str = None,
                   severity: str = None, created_by: str = None, created_by_open_id: str = None):
    """Save case information to S3"""
    item = {
        'case_id': case_id,
        'display_id': display_id,
        'chat_id': chat_id,
        'user_id': user_id,
        'subject': subject,
        'account_id': account_id,
        'created_at': datetime.utcnow().isoformat(),
        'status': 'open'
    }
    
    if case_chat_id:
        item['case_chat_id'] = case_chat_id
    
    if role_arn:
        item['role_arn'] = role_arn
    
    if severity:
        item['severity'] = severity
    
    if created_by:
        item['created_by'] = created_by
    
    if created_by_open_id:
        item['created_by_open_id'] = created_by_open_id
    
    put_case(case_id, item)


def add_communication_to_case(role_arn: str, case_id: str, body: str, 
                              attachment_set_id: str = None) -> bool:
    """Add communication to AWS Support case"""
    try:
        # Assume role
        assumed_role = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='LarkCaseBotAddCommunication'
        )
        
        credentials = assumed_role['Credentials']
        
        # Create Support client
        support_client = boto3.client(
            'support',
            region_name='us-east-1',
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
        
        # Add communication
        params = {
            'caseId': case_id,
            'communicationBody': body
        }
        
        if attachment_set_id:
            params['attachmentSetId'] = attachment_set_id
        
        response = support_client.add_communication_to_case(**params)
        print(f"Add communication response: {json.dumps(response, default=str)}")
        
        return True
    
    except Exception as e:
        print(f"Error adding communication: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def get_case_communications(role_arn: str, case_id: str) -> List[Dict[str, Any]]:
    """Get communications for a case from AWS Support"""
    try:
        # Assume role
        assumed_role = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='LarkCaseBotGetCommunications'
        )
        
        credentials = assumed_role['Credentials']
        
        # Create Support client
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
        
        cases = response.get('cases', [])
        if not cases:
            return []
        
        # Get recent communications from the case
        recent_communications = cases[0].get('recentCommunications', {}).get('communications', [])
        
        return recent_communications
    
    except Exception as e:
        print(f"Error getting communications: {str(e)}")
        import traceback
        traceback.print_exc()
        return []


def upload_attachment_to_support(role_arn: str, file_data: bytes, file_name: str) -> Optional[str]:
    """Upload attachment to AWS Support"""
    try:
        # Assume role
        assumed_role = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='LarkCaseBotUploadAttachment'
        )
        
        credentials = assumed_role['Credentials']
        
        # Create Support client
        support_client = boto3.client(
            'support',
            region_name='us-east-1',
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
        
        # Create attachment set
        response = support_client.add_attachments_to_set(
            attachments=[
                {
                    'fileName': file_name,
                    'data': file_data
                }
            ]
        )
        
        return response.get('attachmentSetId')
    
    except Exception as e:
        print(f"Error uploading attachment: {str(e)}")
        return None


def get_services_from_cost_explorer(role_arn: Optional[str] = None) -> List[str]:
    """Get services from Cost Explorer"""
    try:
        if role_arn:
            assumed_role = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName='LarkCaseBotCostExplorer'
            )
            credentials = assumed_role['Credentials']
            ce = boto3.client(
                'ce',
                region_name='us-east-1',
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken']
            )
        else:
            ce = boto3.client('ce', region_name='us-east-1')
        
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        
        response = ce.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
        )
        
        services = []
        for result in response['ResultsByTime']:
            for group in result['Groups']:
                service_name = group['Keys'][0]
                cost = float(group['Metrics']['UnblendedCost']['Amount'])
                if cost > 0:
                    services.append(service_name)
        
        return list(set(services))
    
    except Exception as e:
        print(f"Error getting services from Cost Explorer: {e}")
        return []


def map_ce_services_to_support(ce_services: List[str]) -> List[Dict[str, str]]:
    """Map Cost Explorer service names to AWS Support service codes"""
    mapping = CE_TO_SUPPORT_MAPPING
    
    seen_codes = set()
    mapped_services = []
    
    for ce_service in ce_services:
        if ce_service in mapping:
            code, display_name = mapping[ce_service]
            if code not in seen_codes:
                mapped_services.append({
                    'code': code,
                    'name': display_name,
                    'category': 'general-guidance'
                })
                seen_codes.add(code)
    
    return mapped_services


def create_support_case(role_arn: str, subject: str, description: str, 
                       severity: str, service_code: str, category_code: str,
                       issue_type: str = 'technical') -> Dict[str, Any]:
    """Create AWS Support case"""
    try:
        assumed_role = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='LarkCaseBot'
        )
        
        credentials = assumed_role['Credentials']
        
        support_client = boto3.client(
            'support',
            region_name='us-east-1',
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
        
        # If no valid categoryCode provided, try to get supported categories for this service
        print(f"Initial category_code: '{category_code}', service_code: '{service_code}', issue_type: '{issue_type}'")
        
        if not category_code or category_code == '':
            print(f"Need to auto-select category for service: {service_code}")
            try:
                # Try to get supported categories for this service
                categories_response = support_client.describe_services(
                    serviceCodeList=[service_code],
                    language=CASE_LANGUAGE
                )
                
                print(f"describe_services response: {json.dumps(categories_response, default=str)}")
                
                services = categories_response.get('services', [])
                if services and services[0].get('categories'):
                    categories = services[0]['categories']
                    category_codes = [cat.get('code', '') for cat in categories]
                    
                    print(f"Available categories for {service_code}: {category_codes}")
                    
                    # Priority selection: general-guidance > other > first one
                    if 'general-guidance' in category_codes:
                        category_code = 'general-guidance'
                        print(f"Selected 'general-guidance' (priority 1)")
                    elif 'other' in category_codes:
                        category_code = 'other'
                        print(f"Selected 'other' (priority 2)")
                    elif category_codes:
                        category_code = category_codes[0]
                        print(f"Selected first category: '{category_code}' (priority 3)")
                    else:
                        category_code = 'general-guidance'
                        print(f"No valid categories, using fallback: 'general-guidance'")
                else:
                    # If unable to get, use general-guidance as default
                    category_code = 'general-guidance'
                    print(f"No categories found, using default: {category_code}")
            except Exception as e:
                print(f"Failed to get categories, using default 'general-guidance': {e}")
                import traceback
                traceback.print_exc()
                category_code = 'general-guidance'
        
        # If category_code is still empty, use general-guidance
        if not category_code:
            category_code = 'general-guidance'
            print(f"Category code was empty, using default: {category_code}")       
        
        # Build create_case parameters
        create_params = {
            'subject': subject,
            'serviceCode': service_code,
            'severityCode': severity,
            'categoryCode': category_code,
            'communicationBody': description,
            'language': CASE_LANGUAGE,
            'issueType': issue_type
        }
        
        print(f"Attempting to create case with params: {json.dumps({k: v for k, v in create_params.items() if k != 'communicationBody'})}")
        
        try:
            response = support_client.create_case(**create_params)
            print(f"Support API response: {json.dumps(response)}")
        except Exception as first_error:
            # If the first attempt fails with InvalidParameterValueException,
            # try without issueType parameter (let AWS auto-determine it)
            if 'InvalidParameterValueException' in str(first_error):
                print(f"First attempt failed: {first_error}")
                print(f"Retrying without issueType parameter...")
                
                create_params_retry = create_params.copy()
                del create_params_retry['issueType']
                
                try:
                    response = support_client.create_case(**create_params_retry)
                    print(f"Retry succeeded! Response: {json.dumps(response)}")
                except Exception as second_error:
                    print(f"Second attempt also failed: {second_error}")
                    raise second_error
            else:
                raise first_error
        
        # AWS Support API returns caseId in format "case-xxx-xxx-xxx"
        # displayId is the short numeric ID, if API doesn't return it, we need to extract or query
        case_id = response['caseId']
        display_id = response.get('displayId', case_id)
        
        # If displayId equals caseId, try to get the real displayId via describe_cases
        if display_id == case_id:
            try:
                case_details = support_client.describe_cases(
                    caseIdList=[case_id],
                    includeResolvedCases=False
                )
                if case_details.get('cases'):
                    display_id = case_details['cases'][0].get('displayId', case_id)
                    print(f"Got displayId from describe_cases: {display_id}")
            except Exception as e:
                print(f"Failed to get displayId: {e}")
        
        return {
            'success': True,
            'case_id': case_id,
            'display_id': display_id,
            'issue_type': issue_type
        }
    
    except Exception as e:
        print(f"Error creating case: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


# Continue to next section...


def create_case_card(accounts: Dict[str, Dict[str, str]], subject: str = "", lang: str = "zh", creator_name: str = "", creator_id: str = "") -> Dict[str, Any]:
    """Create case card: contains all required information
    
    Args:
        accounts: Account configuration dict
        subject: Case title
        lang: Language code ('zh' or 'en')
        creator_name: Name of the user who created this card
        creator_id: User ID of the creator (for validation)
    """
    
    # Severity levels (sorted from low to high) - localized
    severities = [
        {'name': get_message(lang, 'card_severity_low'), 'code': 'low'},
        {'name': get_message(lang, 'card_severity_normal'), 'code': 'normal'},
        {'name': get_message(lang, 'card_severity_high'), 'code': 'high'},
        {'name': get_message(lang, 'card_severity_urgent'), 'code': 'urgent'}
    ]
    
    # Build account options
    account_options = []
    for account_key, account_info in accounts.items():
        account_name = account_info.get('account_name', f'Account {account_key}')
        role_arn = account_info.get('role_arn', '')
        # Extract account ID from role_arn
        account_id = role_arn.split(':')[4] if ':' in role_arn else 'Unknown'
        account_options.append({
            "text": {"tag": "plain_text", "content": f"{account_id} - {account_name}"},
            "value": account_key
        })
    
    # Get all services
    all_services = get_all_services_flat()
    
    # Use all services list directly, no longer fetching from Cost Explorer
    recent_services = []
    other_services = all_services
    
    # Build service options
    service_options = []
    
    if recent_services:
        for svc in recent_services[:20]:
            service_options.append({
                "text": {"tag": "plain_text", "content": f"⭐ {svc['name']}"},
                "value": svc["code"]
            })
        
        service_options.append({
            "text": {"tag": "plain_text", "content": get_message(lang, 'card_all_services')},
            "value": "separator"
        })
    
    for svc in (other_services if other_services else all_services)[:80]:
        service_options.append({
            "text": {"tag": "plain_text", "content": svc["name"]},
            "value": svc["code"]
        })
    
    # Build card elements
    elements = []
    
    # Always show account selection dropdown (even if only one account)
    if len(account_options) > 0:
        elements.extend([
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{get_message(lang, 'card_aws_account')}**"},
                "extra": {
                    "tag": "select_static",
                    "name": "account",
                    "placeholder": {"tag": "plain_text", "content": get_message(lang, 'card_select_account')},
                    "options": account_options
                }
            }
        ])
    
    # Display case title
    if subject:
        elements.extend([
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{get_message(lang, 'card_case_title')}**\n{subject}"}
            },
            {"tag": "hr"}
        ])
    
    # Add dropdowns
    elements.extend([
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**{get_message(lang, 'card_aws_service')}** ({len(service_options)})"},
            "extra": {
                "tag": "select_static",
                "name": "service",
                "placeholder": {"tag": "plain_text", "content": get_message(lang, 'card_select_service')},
                "options": service_options
            }
        },
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**{get_message(lang, 'card_severity')}**"},
            "extra": {
                "tag": "select_static",
                "name": "severity",
                "placeholder": {"tag": "plain_text", "content": get_message(lang, 'card_select_severity')},
                "options": [
                    {"text": {"tag": "plain_text", "content": sev["name"]}, "value": sev["code"]}
                    for sev in severities
                ]
            }
        },
        {"tag": "hr"},
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": get_message(lang, 'card_submit')
                    },
                    "type": "primary",
                    "value": {"action": "submit_case", "subject": subject}
                }
            ]
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{get_message(lang, 'card_assistant_title')}**\n\n"
                    f"{get_message(lang, 'card_create_flow')}\n"
                    f"{get_message(lang, 'card_create_step1')}\n"
                    f"{get_message(lang, 'card_create_step2')}\n"
                    f"{get_message(lang, 'card_create_step3')}\n\n"
                    f"{get_message(lang, 'card_communication')}\n"
                    f"{get_message(lang, 'card_comm_sync')}\n"
                    f"{get_message(lang, 'card_comm_upload')}\n"
                    f"{get_message(lang, 'card_comm_internal')}\n\n"
                    f"{get_message(lang, 'card_tips')}\n"
                    f"{get_message(lang, 'card_tip1')}\n"
                    f"{get_message(lang, 'card_tip2')}\n"
                    f"{get_message(lang, 'card_tip3')}\n"
                    f"{get_message(lang, 'card_tip4')}"
                )
            }
        }
    ])
    
    # Add creator info at the top of the card
    if creator_name:
        creator_label = "创建者" if lang == "zh" else "Created by"
        elements.insert(0, {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"👤 **{creator_label}:** {creator_name}"}
        })
        elements.insert(1, {"tag": "hr"})
    
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": get_message(lang, 'card_header'), "tag": "plain_text"},
            "template": "blue"
        },
        "elements": elements
    }
    
    # Store creator_id in card for validation (in button value)
    if creator_id:
        for element in elements:
            if element.get('tag') == 'action':
                for action in element.get('actions', []):
                    if action.get('value', {}).get('action') == 'submit_case':
                        action['value']['creator_id'] = creator_id
    
    return card


def is_user_in_chat(chat_id: str, user_open_id: str) -> bool:
    """Check if user is already in the chat group"""
    try:
        token = get_tenant_access_token()
        
        url = f"https://open.larksuite.com/open-apis/im/v1/chats/{chat_id}/members?member_id_type=open_id"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = http.request('GET', url, headers=headers)
        result = json.loads(response.data.decode('utf-8'))
        
        if result.get('code') == 0:
            members = result.get('data', {}).get('items', [])
            for member in members:
                if member.get('member_id') == user_open_id:
                    return True
        return False
    except Exception as e:
        print(f"Error checking chat members: {e}")
        return False


def add_user_to_chat(chat_id: str, user_id: str) -> dict:
    """Add user to a chat group
    
    Returns:
        dict with 'success' (bool), 'code' (int), 'msg' (str), 'already_in_chat' (bool)
    """
    try:
        # First check if user is already in the chat
        if is_user_in_chat(chat_id, user_id):
            print(f"User {user_id} is already in chat {chat_id}")
            return {'success': True, 'code': 0, 'msg': 'User already in chat', 'already_in_chat': True}
        
        token = get_tenant_access_token()
        
        url = f"https://open.larksuite.com/open-apis/im/v1/chats/{chat_id}/members"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "id_list": [user_id],
            "member_id_type": "open_id"  # Explicitly specify ID type
        }
        
        print(f"Adding user to chat: chat_id={chat_id}, user_id={user_id}")
        encoded_data = json.dumps(payload).encode('utf-8')
        response = http.request(
            'POST',
            url,
            body=encoded_data,
            headers=headers
        )
        
        result = json.loads(response.data.decode('utf-8'))
        print(f"Add user to chat response: {result}")
        
        code = result.get('code', -1)
        msg = result.get('msg', 'Unknown error')
        
        if code == 0:
            print(f"Successfully added user to chat")
            return {'success': True, 'code': code, 'msg': msg, 'already_in_chat': False}
        elif code == 1254044:  # User already in chat
            print(f"User already in chat")
            return {'success': True, 'code': code, 'msg': msg, 'already_in_chat': True}
        else:
            print(f"Failed to add user to chat: code={code}, msg={msg}")
            return {'success': False, 'code': code, 'msg': msg, 'already_in_chat': False}
    except Exception as e:
        print(f"Error adding user to chat: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'code': -1, 'msg': str(e), 'already_in_chat': False}


def handle_message_receive(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle message receive event"""
    message = event_data.get('message', {})
    sender = event_data.get('sender', {})
    chat_id = message.get('chat_id', '')
    user_id = sender.get('sender_id', {}).get('user_id', '')
    open_id = sender.get('sender_id', {}).get('open_id', '')
    message_type = message.get('message_type', 'text')
    chat_type = message.get('chat_type', 'p2p')
    message_id = message.get('message_id', '')
    
    # Note: user_lang will be detected later after parsing message text
    user_lang = 'zh'  # Default, will be updated after parsing message
    
    # Detailed logging: print message type and content keys
    print(f"=== Message Receive Event ===")
    print(f"  message_id: {message_id}")
    print(f"  message_type: {message_type}")
    print(f"  chat_type: {chat_type}")
    print(f"  chat_id: {chat_id}")
    print(f"  user_id: {user_id}")
    print(f"  message keys: {list(message.keys())}")
    
    if message_type != 'text':
        content_preview = str(message.get('content', ''))[:200]
        print(f"  Non-text message content preview: {content_preview}")
    
    # Check whitelist
    if not check_user_whitelist(user_id):
        no_permission_msg = get_message(DEFAULT_LANGUAGE, 'no_permission')
        send_message(chat_id, 'text', {'text': no_permission_msg}, reply_to_message_id=message_id)
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Check if this is a case chat message (query once, reuse later)
    print(f"Checking if chat_id {chat_id} is a case chat")
    case_info = get_case_by_case_chat_id(chat_id)
    is_case_chat = case_info is not None
    print(f"is_case_chat: {is_case_chat}")
    
    # File message: don't upload by default, only prompt user how to upload
    if message_type == 'file':
        print(f"Received file message, message_type: {message_type}")
        
        # Validate if this is really a file message (check required fields)
        content = json.loads(message.get('content', '{}'))
        file_key = content.get('file_key', '')
        file_name = content.get('file_name', 'attachment')
        
        print(f"File message validation: file_key={file_key}, message_id={message_id}")
        
        # If missing required fields, may be misidentified or special message, skip
        if not file_key or not message_id:
            print(f"Invalid file message (missing file_key or message_id), skipping file upload handler")
            # Continue processing as normal message
        elif is_case_chat:
            # Don't auto-upload, prompt user to reply with "upload" to upload
            # Note: Don't use reply_to_message_id here, so user knows to reply to the file message directly
            print(f"File received in case chat, not auto-uploading. case_id: {case_info.get('case_id')}")
            file_msg = f"{get_message(DEFAULT_LANGUAGE, 'file_received', file_name)}\n\n{get_message(DEFAULT_LANGUAGE, 'file_upload_hint')}"
            send_message(chat_id, 'text', {'text': file_msg})
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        else:
            # File upload in non-case chat, silently ignore
            print(f"File received in non-case chat, ignoring silently")
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Handle "upload" command (when replying to file message)
    if is_case_chat and message_type == 'text':
        # First clean @bot content for command detection
        content = json.loads(message.get('content', '{}'))
        cmd_text = content.get('text', '').strip()
        mentions = message.get('mentions', [])
        for mention in mentions:
            mention_key = mention.get('key', '')
            if mention_key:
                cmd_text = cmd_text.replace(mention_key, '').strip()
        
        # Handle "dissolve group" command
        if cmd_text in ['dissolve', 'dissolve group']:
            print(f"Dissolve group command detected, case_info: {case_info}")
            return handle_dissolve_group(case_info, chat_id, open_id)
        
        # Handle "upload" command (when replying to file message)
        parent_id = message.get('parent_id', '')
        if parent_id:
            print(f"Upload command check: parent_id={parent_id}, cmd_text='{cmd_text}'")
            if cmd_text in ['upload', '上传']:
                print(f"Upload command detected, parent_id: {parent_id}")
                return handle_upload_reply(case_info, parent_id, chat_id, user_id)
    
    # Handle text messages in case chat
    if is_case_chat:
        print(f"This is a case chat, case_id: {case_info.get('case_id')}")
        return handle_case_chat_message(case_info, message, user_id, open_id)
    
    # Parse message content
    content = json.loads(message.get('content', '{}'))
    text = content.get('text', '').strip()
    
    # In regular group chat, check if @bot
    if chat_type == 'group':
        mentions = message.get('mentions', [])
        bot_mentioned = False
        
        # Check if bot was mentioned
        for mention in mentions:
            mention_key = mention.get('key', '')
            if mention_key:
                # Remove @bot text
                text = text.replace(mention_key, '').strip()
                bot_mentioned = True
        
        # In regular group chat, ignore message if bot not mentioned
        if not bot_mentioned:
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Now detect user language based on message text (command language)
    user_lang = get_user_language(user_id=user_id, open_id=open_id, token_func=get_tenant_access_token, message_text=text)
    print(f"User language detected: {user_lang}, from text: {text[:50] if text else 'empty'}")
    
    # Handle commands with multi-language support
    # Check for create case command
    matched, cmd_lang, subject = match_command(text, 'create_case')
    if matched:
        if not subject:
            error_msg = get_message(DEFAULT_LANGUAGE, 'enter_title')
            send_message(chat_id, 'text', {'text': error_msg}, reply_to_message_id=message_id)
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Get configured account list
        config = get_bot_config()
        accounts = config.get('accounts', {})
        
        if not accounts:
            send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'no_accounts_configured')}, reply_to_message_id=message_id)
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Create initial draft
        draft_id = f"draft_{user_id}_{chat_id}_{int(datetime.now().timestamp())}"
        
        # First delete old drafts from this user in current chat (avoid multiple draft conflicts)
        old_drafts = s3_get_cases_by_user(user_id, limit=50)
        old_message_ids = []
        for item in old_drafts:
            if item.get('status') == 'draft' and item.get('chat_id') == chat_id:
                # Record old card message_id (if exists)
                if item.get('card_message_id'):
                    old_message_ids.append(item['card_message_id'])
                delete_case(item['case_id'])
        
        # Create new draft
        put_case(draft_id, {
            'case_id': draft_id,
            'user_id': user_id,
            'chat_id': chat_id,
            'subject': subject,
            'status': 'draft',
            'issue_type': 'technical',
            'created_at': datetime.now().isoformat()
        })
        
        # Recall old cards (if any)
        for msg_id in old_message_ids:
            try:
                recall_message(msg_id)
                print(f"Recalled old card message: {msg_id}")
            except Exception as e:
                print(f"Failed to recall old card {msg_id}: {e}")
        
        # Get creator name for display on card
        creator_name = ""
        try:
            user_info = get_user_info(user_id=user_id, open_id=open_id)
            creator_name = user_info.get('name', '')
        except Exception as e:
            print(f"Failed to get user info: {e}")
        
        # Send case card, display case title (use global default language)
        card = create_case_card(accounts, subject, lang=DEFAULT_LANGUAGE, creator_name=creator_name, creator_id=user_id)
        result = send_card(chat_id, card)
        
        # Save new card message_id to draft
        if result.get('data', {}).get('message_id'):
            new_message_id = result['data']['message_id']
            update_case(draft_id, {'card_message_id': new_message_id})
        
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    elif text.startswith('follow') or text.startswith(MESSAGES['zh']['follow']):
        # Extract case ID
        parts = text.split(' ', 1)
        if len(parts) < 2:
            send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'enter_case_id')}, reply_to_message_id=message_id)
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        display_id = parts[1].strip()
        
        # Find case - first try user's own cases
        user_cases = s3_get_cases_by_user(user_id, limit=50)
        case_info = None
        for item in user_cases:
            if item.get('display_id') == display_id or item.get('case_id') == display_id:
                case_info = item
                break
        
        # If not found in user's own cases, do global search
        if not case_info:
            print(f"Case not found in user's cases, searching globally for display_id: {display_id}")
            # Global scan to find case (by display_id)
            matches = scan_cases_by_filter(
                lambda c: c.get('display_id') == display_id or c.get('case_id') == display_id
            )
            
            if matches:
                case_info = matches[0]
                print(f"Found case globally: case_id={case_info.get('case_id')}")
            else:
                print(f"Case not found globally: {display_id}")
                send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'case_not_found', display_id)}, reply_to_message_id=message_id)
                return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Check if case has a chat group
        case_chat_id = case_info.get('case_chat_id')
        if not case_chat_id:
            send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'case_no_chat', display_id)}, reply_to_message_id=message_id)
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Add user to case chat
        # Need to use open_id instead of user_id
        try:
            # Get open_id from sender
            open_id = sender.get('sender_id', {}).get('open_id', '')
            
            print(f"Adding user to case chat: user_id={user_id}, open_id={open_id}, case_chat_id={case_chat_id}")
            
            if not open_id:
                send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'unable_get_user_info')}, reply_to_message_id=message_id)
                return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
            
            result = add_user_to_chat(case_chat_id, open_id)
            
            if result['success']:
                if result['already_in_chat']:
                    send_message(chat_id, 'text', {
                        'text': get_message(DEFAULT_LANGUAGE, 'already_in_chat', display_id)
                    }, reply_to_message_id=message_id)
                else:
                    send_message(chat_id, 'text', {
                        'text': get_message(DEFAULT_LANGUAGE, 'added_to_chat', display_id)
                    }, reply_to_message_id=message_id)
            else:
                # Add failed, show specific error
                error_code = result['code']
                error_msg = result['msg']
                print(f"Failed to add user to case chat: code={error_code}, msg={error_msg}")
                send_message(chat_id, 'text', {
                    'text': get_message(DEFAULT_LANGUAGE, 'add_to_chat_failed', error_code, error_msg)
                }, reply_to_message_id=message_id)
        except Exception as e:
            print(f"Error adding user to case chat: {e}")
            import traceback
            traceback.print_exc()
            send_message(chat_id, 'text', {
                'text': get_message(DEFAULT_LANGUAGE, 'add_to_chat_failed', -1, str(e))
            }, reply_to_message_id=message_id)
        
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    elif text in ['help', '帮助']:
        # Detect language from command (default to Chinese)
        is_chinese = text != 'help'
        
        # Show different help info based on context and language
        if chat_type == 'p2p':
            if is_chinese:
                content = [
                    [{"tag": "text", "text": "📝 "}, {"tag": "text", "text": "创建工单", "style": ["bold"]}],
                    [{"tag": "text", "text": "1. 输入命令: "},  {"tag": "text", "text": "开工单 [标题]", "style": ["bold"]}],
                    [{"tag": "text", "text": "2. 在弹出的卡片中选择:"}],
                    [{"tag": "text", "text": "   • AWS 账号（如有多个）"}],
                    [{"tag": "text", "text": "   • AWS 服务"}],
                    [{"tag": "text", "text": "   • 严重级别"}],
                    [{"tag": "text", "text": "3. 点击\"提交工单\"按钮"}],
                    [{"tag": "text", "text": "4. 机器人会自动创建专属工单群"}],
                    [{"tag": "text", "text": ""}],
                    [{"tag": "text", "text": "💬 "}, {"tag": "text", "text": "工单沟通", "style": ["bold"]}],
                    [{"tag": "text", "text": "• 在工单群中 "}, {"tag": "text", "text": "@bot [内容]", "style": ["bold"]}, {"tag": "text", "text": " 同步到 AWS Support"}],
                    [{"tag": "text", "text": "• 上传的文件会自动同步"}],
                    [{"tag": "text", "text": "• 普通消息仅保留在群内"}],
                    [{"tag": "text", "text": ""}],
                    [{"tag": "text", "text": "📋 "}, {"tag": "text", "text": "其他命令", "style": ["bold"]}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "历史", "style": ["bold"]}, {"tag": "text", "text": " - 查询最近10个工单"}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "关注 [工单ID]", "style": ["bold"]}, {"tag": "text", "text": " - 加入指定工单群"}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "帮助", "style": ["bold"]}, {"tag": "text", "text": " - 显示此帮助信息"}],
                ]
            else:
                content = [
                    [{"tag": "text", "text": "📝 "}, {"tag": "text", "text": "Create Case", "style": ["bold"]}],
                    [{"tag": "text", "text": "1. Enter command: "},  {"tag": "text", "text": "create case [title]", "style": ["bold"]}],
                    [{"tag": "text", "text": "2. Select in the popup card:"}],
                    [{"tag": "text", "text": "   • AWS Account (if multiple)"}],
                    [{"tag": "text", "text": "   • AWS Service"}],
                    [{"tag": "text", "text": "   • Severity Level"}],
                    [{"tag": "text", "text": "3. Click \"Submit Case\" button"}],
                    [{"tag": "text", "text": "4. Bot will auto-create a dedicated case chat"}],
                    [{"tag": "text", "text": ""}],
                    [{"tag": "text", "text": "💬 "}, {"tag": "text", "text": "Case Communication", "style": ["bold"]}],
                    [{"tag": "text", "text": "• In case chat "}, {"tag": "text", "text": "@bot [content]", "style": ["bold"]}, {"tag": "text", "text": " syncs to AWS Support"}],
                    [{"tag": "text", "text": "• Uploaded files are auto-synced"}],
                    [{"tag": "text", "text": "• Regular messages stay in chat only"}],
                    [{"tag": "text", "text": ""}],
                    [{"tag": "text", "text": "📋 "}, {"tag": "text", "text": "Other Commands", "style": ["bold"]}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "history", "style": ["bold"]}, {"tag": "text", "text": " - Query recent 10 cases"}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "follow [case ID]", "style": ["bold"]}, {"tag": "text", "text": " - Join specified case chat"}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "help", "style": ["bold"]}, {"tag": "text", "text": " - Show this help message"}],
                ]
            send_post_message(chat_id, "AWS Support Case Bot", content)
        else:
            if is_chinese:
                content = [
                    [{"tag": "text", "text": "📝 "}, {"tag": "text", "text": "创建工单", "style": ["bold"]}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot 开工单 [标题]", "style": ["bold"]}, {"tag": "text", "text": " - 创建新工单"}],
                    [{"tag": "text", "text": ""}],
                    [{"tag": "text", "text": "📋 "}, {"tag": "text", "text": "其他命令", "style": ["bold"]}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot 历史", "style": ["bold"]}, {"tag": "text", "text": " - 查询最近10个工单"}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot 关注 [工单ID]", "style": ["bold"]}, {"tag": "text", "text": " - 加入指定工单群"}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot 帮助", "style": ["bold"]}, {"tag": "text", "text": " - 显示此帮助信息"}],
                    [{"tag": "text", "text": ""}],
                    [{"tag": "text", "text": "💡 "}, {"tag": "text", "text": "提示", "style": ["bold"]}],
                    [{"tag": "text", "text": "• 在普通群中需要 @bot 才能使用命令"}],
                    [{"tag": "text", "text": "• 创建工单后会自动创建专属工单群"}],
                ]
            else:
                content = [
                    [{"tag": "text", "text": "📝 "}, {"tag": "text", "text": "Create Case", "style": ["bold"]}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot create case [title]", "style": ["bold"]}, {"tag": "text", "text": " - Create new case"}],
                    [{"tag": "text", "text": ""}],
                    [{"tag": "text", "text": "📋 "}, {"tag": "text", "text": "Other Commands", "style": ["bold"]}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot history", "style": ["bold"]}, {"tag": "text", "text": " - Query recent 10 cases"}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot follow [case ID]", "style": ["bold"]}, {"tag": "text", "text": " - Join specified case chat"}],
                    [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot help", "style": ["bold"]}, {"tag": "text", "text": " - Show this help message"}],
                    [{"tag": "text", "text": ""}],
                    [{"tag": "text", "text": "💡 "}, {"tag": "text", "text": "Tips", "style": ["bold"]}],
                    [{"tag": "text", "text": "• In regular groups, @bot is required to use commands"}],
                    [{"tag": "text", "text": "• A dedicated case chat is auto-created after case creation"}],
                ]
            send_post_message(chat_id, "AWS Support Case Bot", content)
        
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    elif text.startswith('history') or text.startswith('历史'):
        # Use global default language for bot responses
        no_history_msg = get_message(DEFAULT_LANGUAGE, 'no_history')
        
        # Query case history
        cases = get_cases_by_user(user_id, limit=10)
        
        if not cases:
            send_message(chat_id, 'text', {'text': no_history_msg}, reply_to_message_id=message_id)
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Filter out drafts
        cases = [c for c in cases if c.get('status') != 'draft']
        
        if not cases:
            send_message(chat_id, 'text', {'text': no_history_msg}, reply_to_message_id=message_id)
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Batch get case details (from AWS Support API)
        case_details_map = {}
        for case in cases[:10]:
            role_arn = case.get('role_arn')
            case_id = case.get('case_id')
            if role_arn and case_id:
                try:
                    # Get latest case info from AWS Support API
                    assumed_role = sts_client.assume_role(
                        RoleArn=role_arn,
                        RoleSessionName='LarkCaseBotHistoryQuery'
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
                        includeResolvedCases=True
                    )
                    if response.get('cases'):
                        case_details_map[case_id] = response['cases'][0]
                except Exception as e:
                    print(f"Error fetching case details for {case_id}: {e}")
        
        # Severity mapping
        severity_map = {
            'low': 'Low',
            'normal': 'Normal',
            'high': 'High',
            'urgent': 'Urgent',
            'critical': 'Critical'
        }
        
        # Status mapping (all possible AWS Support statuses) - bilingual
        status_map_en = {
            'opened': '🟢 In Progress',
            'pending-customer-action': '🟡 Pending Customer Action',
            'customer-action-completed': '🟢 Customer Action Completed',
            'reopened': '🟢 Reopened',
            'resolved': '⚪ Resolved',
            'unassigned': '🔵 Unassigned',
            'work-in-progress': '🟢 Work In Progress',
            'pending-amazon-action': '🟠 Pending AWS',
            'amazon-action-completed': '🟢 AWS Responded'
        }
        status_map_zh = {
            'opened': '🟢 处理中',
            'pending-customer-action': '🟡 等待客户操作',
            'customer-action-completed': '🟢 客户已操作',
            'reopened': '🟢 已重开',
            'resolved': '⚪ 已解决',
            'unassigned': '🔵 未分配',
            'work-in-progress': '🟢 处理中',
            'pending-amazon-action': '🟠 等待 AWS 处理',
            'amazon-action-completed': '🟢 AWS 已回复'
        }
        status_map = status_map_zh if is_chinese else status_map_en
        
        # Build rich text content
        content = []
        
        for i, case in enumerate(cases[:10], 1):
            display_id = case.get('display_id', case['case_id'])
            case_id = case.get('case_id')
            
            # Get detailed info from API
            detail = case_details_map.get(case_id, {})
            
            # AWS Support Console link
            support_url = f"https://support.console.aws.amazon.com/support/home#/case/?displayId={display_id}"
            
            # Use latest data from API
            subject = detail.get('subject', case.get('subject', 'N/A'))
            severity_code = detail.get('severityCode', case.get('severity', 'N/A'))
            severity_display = severity_map.get(severity_code, severity_code)
            status = detail.get('status', case.get('status', 'N/A'))
            status_display = status_map.get(status, status)
            time_created = detail.get('timeCreated', case.get('created_at', 'N/A'))
            # Convert to dual timezone display
            time_created = format_aws_time_dual(time_created)
            
            # Extract account ID from role_arn
            account_id = 'N/A'
            role_arn = case.get('role_arn', '')
            if role_arn and ':' in role_arn:
                # role_arn format: arn:aws:iam::123456789012:role/...
                parts = role_arn.split(':')
                if len(parts) >= 5:
                    account_id = parts[4]
            
            # Add case info (using rich text format)
            content.append([{"tag": "text", "text": "━━━━━━━━━━━━━━━━━━━"}])
            content.append([{"tag": "text", "text": ""}])
            content.append([{"tag": "text", "text": f"📋 {'工单' if is_chinese else 'Case'} #{i}", "style": ["bold"]}])
            content.append([{"tag": "a", "text": display_id, "href": support_url}])
            content.append([{"tag": "text", "text": ""}])
            content.append([{"tag": "text", "text": "📝 "}, {"tag": "text", "text": subject}])
            content.append([{"tag": "text", "text": f"👤 {'账号' if is_chinese else 'Account'}: "}, {"tag": "text", "text": account_id}])
            content.append([{"tag": "text", "text": f"📊 {'状态' if is_chinese else 'Status'}: "}, {"tag": "text", "text": status_display}])
            content.append([{"tag": "text", "text": f"⚠️ {'严重级别' if is_chinese else 'Severity'}: "}, {"tag": "text", "text": severity_display}])
            content.append([{"tag": "text", "text": f"🕐 {'创建时间' if is_chinese else 'Created'}: "}, {"tag": "text", "text": time_created}])
            content.append([{"tag": "text", "text": ""}])
            if is_chinese:
                content.append([{"tag": "text", "text": "💬 回复 "}, {"tag": "text", "text": f"关注 {display_id}", "style": ["bold"]}, {"tag": "text", "text": " 加入工单群"}])
            else:
                content.append([{"tag": "text", "text": "💬 Reply "}, {"tag": "text", "text": f"follow {display_id}", "style": ["bold"]}, {"tag": "text", "text": " to join case chat"}])
            content.append([{"tag": "text", "text": ""}])  # Empty line separator
        
        title = f"📚 工单历史 (最近 {len(cases[:10])} 个)" if is_chinese else f"📚 Your Case History (Recent {len(cases[:10])})"
        send_post_message(chat_id, title, content)
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}


def handle_case_chat_message(case_info: Dict[str, Any], message: Dict[str, Any], user_id: str, open_id: str = '') -> Dict[str, Any]:
    """Handle messages in case chat - only sync messages with @bot mention to AWS Support"""
    content = json.loads(message.get('content', '{}'))
    text = content.get('text', '').strip()
    
    if not text:
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Check if @bot mentioned
    mentions = message.get('mentions', [])
    has_bot_mention = False
    for mention in mentions:
        mention_key = mention.get('key', '')
        if mention_key:
            has_bot_mention = True
            text = text.replace(mention_key, '').strip()
    
    print(f"Case chat message - has_bot_mention: {has_bot_mention}, text after removing mentions: '{text}'")
    
    # Case chat specific help command (support both Chinese and English)
    if text in ['help', '帮助']:
        # Detect language from command
        is_chinese = text == '帮助'
        display_id = case_info.get('display_id', case_info.get('case_id'))
        support_url = f"https://support.console.aws.amazon.com/support/home#/case/?displayId={display_id}"
        
        if is_chinese:
            content = [
                [{"tag": "text", "text": "📋 "}, {"tag": "text", "text": "当前工单", "style": ["bold"]}, {"tag": "text", "text": ": "}, {"tag": "a", "text": display_id, "href": support_url}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "💬 "}, {"tag": "text", "text": "同步到 AWS Support", "style": ["bold"]}],
                [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot [内容]", "style": ["bold"]}, {"tag": "text", "text": " - 将消息同步到 AWS Support"}],
                [{"tag": "text", "text": "• "}, {"tag": "text", "text": "上传文件", "style": ["bold"]}, {"tag": "text", "text": " - 文件会自动同步"}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "💭 "}, {"tag": "text", "text": "群内讨论", "style": ["bold"]}],
                [{"tag": "text", "text": "• 普通消息（不 @bot）仅在群内显示，不会同步到 AWS Support"}],
                [{"tag": "text", "text": "• 适合团队内部讨论问题"}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "📢 "}, {"tag": "text", "text": "通知", "style": ["bold"]}],
                [{"tag": "text", "text": "• AWS Support 工程师的回复会自动推送到此群"}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "💡 "}, {"tag": "text", "text": "提示", "style": ["bold"]}],
                [{"tag": "text", "text": "• 向上滚动可查看完整工单详情"}],
                [{"tag": "text", "text": "• 点击工单ID可跳转到 AWS 控制台"}],
            ]
            title = "工单群使用说明"
        else:
            content = [
                [{"tag": "text", "text": "📋 "}, {"tag": "text", "text": "Current Case", "style": ["bold"]}, {"tag": "text", "text": ": "}, {"tag": "a", "text": display_id, "href": support_url}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "💬 "}, {"tag": "text", "text": "Sync to AWS Support", "style": ["bold"]}],
                [{"tag": "text", "text": "• "}, {"tag": "text", "text": "@bot [content]", "style": ["bold"]}, {"tag": "text", "text": " - Sync message to AWS Support"}],
                [{"tag": "text", "text": "• "}, {"tag": "text", "text": "Upload files", "style": ["bold"]}, {"tag": "text", "text": " - Files are auto-synced"}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "💭 "}, {"tag": "text", "text": "Internal Discussion", "style": ["bold"]}],
                [{"tag": "text", "text": "• Regular messages (without @bot) stay in chat only, not synced to AWS Support"}],
                [{"tag": "text", "text": "• Good for team internal discussions"}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "📢 "}, {"tag": "text", "text": "Notifications", "style": ["bold"]}],
                [{"tag": "text", "text": "• AWS Support engineer replies are auto-pushed to this chat"}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "💡 "}, {"tag": "text", "text": "Tips", "style": ["bold"]}],
                [{"tag": "text", "text": "• Scroll up to view full case details"}],
                [{"tag": "text", "text": "• Click case ID to jump to AWS Console"}],
            ]
            title = "Case Chat Instructions"
        
        send_post_message(case_info['case_chat_id'], title, content)
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # In case chat, only @bot messages are synced to AWS Support
    # Other messages are for internal discussion, not synced
    if not has_bot_mention:
        # Regular message, don't process, just for internal discussion
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # @bot message, sync to AWS Support
    if not text:
        send_message(case_info['case_chat_id'], 'text', {
            'text': get_message(DEFAULT_LANGUAGE, 'enter_reply_at_bot')
        })
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Get role_arn from case info (saved when case was created)
    role_arn = case_info.get('role_arn')
    
    if not role_arn:
        print(f"Error: No role_arn found for case {case_info.get('case_id')}")
        send_message(case_info['case_chat_id'], 'text', {
            'text': get_message(DEFAULT_LANGUAGE, 'config_no_account')
        })
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Add to AWS Support (using account from when case was created)
    display_id = case_info.get('display_id', case_info.get('case_id'))
    
    print(f"Adding communication to case {case_info['case_id']}, content length: {len(text)}")
    
    # Try to get user info for display
    user_name = 'Team Member'
    try:
        user_info = get_user_info(user_id=user_id, open_id=open_id)
        user_name = user_info.get('name', 'Team Member')
        
        # If name is ID format, use generic name
        if user_name.startswith('ou_') or user_name.startswith('on_'):
            user_name = 'Team Member'
    except Exception as e:
        print(f"Failed to get user name, using default: {e}")
        user_name = 'Team Member'
    
    success = add_communication_to_case(
        role_arn=role_arn,
        case_id=case_info['case_id'],
        body=f"[From {user_name} via Lark]\n\n{text}"
    )
    
    if success:
        print(f"Communication added successfully to case {case_info['case_id']}")
        
        # Send confirmation message with reply preview
        preview = text[:50] + '...' if len(text) > 50 else text
        send_message(case_info['case_chat_id'], 'text', {'text': get_message(DEFAULT_LANGUAGE, 'synced_to_case', display_id, preview)})
    else:
        print(f"Failed to add communication to case {case_info['case_id']}")
        send_message(case_info['case_chat_id'], 'text', {
            'text': get_message(DEFAULT_LANGUAGE, 'sync_failed', display_id)
        })
    
    return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}


def download_file_from_lark(message_id: str, file_key: str) -> bytes:
    """Download file from Lark using message_id and file_key"""
    try:
        token = get_tenant_access_token()
        
        # Lark file download API
        # Reference: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message-resource/get
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{message_id}/resources/{file_key}"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        # Add query parameter type, can be file, image, audio, video, media based on message type
        params = "?type=file"
        full_url = url + params
        
        print(f"Downloading file from Lark")
        print(f"  message_id: {message_id}")
        print(f"  file_key: {file_key}")
        print(f"  url: {full_url}")
        
        response = http.request('GET', full_url, headers=headers)
        
        print(f"Download response: status={response.status}")
        
        if response.status == 200:
            print(f"File downloaded successfully, size: {len(response.data)} bytes")
            return response.data
        else:
            # Print detailed error info
            error_body = response.data.decode('utf-8') if response.data else 'No response body'
            print(f"Failed to download file:")
            print(f"  Status: {response.status}")
            print(f"  Response: {error_body}")
            
            # Try without type parameter
            if params:
                print(f"Retrying without type parameter...")
                response2 = http.request('GET', url, headers=headers)
                if response2.status == 200:
                    print(f"Success without type parameter, size: {len(response2.data)} bytes")
                    return response2.data
                else:
                    error_body2 = response2.data.decode('utf-8') if response2.data else 'No response body'
                    print(f"Retry also failed: status={response2.status}, response={error_body2}")
            
            raise Exception(f"Failed to download file: HTTP {response.status} - {error_body}")
    
    except Exception as e:
        print(f"Error downloading file from Lark: {e}")
        raise


def get_message_content(message_id: str) -> Optional[Dict[str, Any]]:
    """Get message content by message_id from Lark API"""
    try:
        token = get_tenant_access_token()
        url = f"https://open.larksuite.com/open-apis/im/v1/messages/{message_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = http.request('GET', url, headers=headers)
        result = json.loads(response.data.decode('utf-8'))
        
        if result.get('code') == 0:
            return result.get('data', {}).get('items', [{}])[0]
        else:
            print(f"Failed to get message: {result}")
            return None
    except Exception as e:
        print(f"Error getting message content: {e}")
        return None


def handle_dissolve_group(case_info: Dict[str, Any], chat_id: str, open_id: str) -> Dict[str, Any]:
    """Handle dissolve group command - only creator can dissolve the case chat
    
    Args:
        case_info: Case information from S3
        chat_id: Current chat ID
        open_id: User's open_id who sent the command
    
    Returns:
        Lambda response dict
    """
    print(f"=== Handle Dissolve Group ===")
    print(f"  chat_id: {chat_id}")
    print(f"  open_id: {open_id}")
    print(f"  case_info: {case_info}")
    
    # Check if this is a case chat
    if not case_info:
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'dissolve_not_case_chat')})
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Check if user is the case creator
    created_by_open_id = case_info.get('created_by_open_id', '')
    created_by = case_info.get('created_by', '')
    
    print(f"  created_by_open_id: {created_by_open_id}")
    print(f"  created_by: {created_by}")
    
    # Verify permission: only creator can dissolve the chat
    if created_by_open_id and created_by_open_id != open_id:
        creator_name = created_by if created_by else get_message(DEFAULT_LANGUAGE, 'label_case_creator')
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'dissolve_only_creator', creator_name)})
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # If no created_by_open_id recorded, allow anyone to dissolve (backward compatibility for old cases)
    if not created_by_open_id:
        print("Warning: No created_by_open_id recorded, allowing dissolve for backward compatibility")
    
    # Get case info for prompt
    case_id = case_info.get('case_id', '')
    display_id = case_info.get('display_id', case_id)
    subject = case_info.get('subject', 'Unknown Subject')
    
    # Send pre-dissolve warning message
    send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'dissolve_warning', display_id, subject)})
    
    # Execute dissolve
    result = dissolve_group_chat(chat_id)
    
    if result['success']:
        print(f"Group dissolved successfully: {chat_id}")
        # Group dissolved, cannot send messages anymore
        # Update status in S3
        try:
            update_case(case_id, {
                'chat_dissolved': True,
                'dissolved_at': datetime.utcnow().isoformat()
            })
            print(f"Updated case {case_id} with dissolved status")
        except Exception as e:
            print(f"Failed to update case dissolved status: {e}")
        
        return {'statusCode': 200, 'body': json.dumps({'message': 'Group dissolved'})}
    else:
        error_msg = result.get('msg', 'Unknown error')
        error_code = result.get('code', -1)
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'dissolve_failed', error_code, error_msg)})
        return {'statusCode': 200, 'body': json.dumps({'message': 'Failed to dissolve group'})}


def handle_upload_reply(case_info: Dict[str, Any], parent_id: str, chat_id: str, user_id: str) -> Dict[str, Any]:
    """Handle upload command when replying to a file message"""
    print(f"=== Handle Upload Reply ===")
    print(f"  parent_id: {parent_id}")
    print(f"  case_id: {case_info.get('case_id')}")
    
    # Get the replied message content
    parent_message = get_message_content(parent_id)
    
    if not parent_message:
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'upload_get_msg_failed')})
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Check if it's a file message
    msg_type = parent_message.get('msg_type', '')
    if msg_type != 'file':
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'upload_reply_to_file')})
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    # Construct message object and call handle_file_upload
    message = {
        'message_id': parent_id,
        'message_type': 'file',
        'content': parent_message.get('body', {}).get('content', '{}')
    }
    
    return handle_file_upload(case_info, message, user_id)


def handle_file_upload(case_info: Dict[str, Any], message: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Handle file upload in case chat"""
    content_str = message.get('content', '{}')
    # content can be string or already parsed dict
    if isinstance(content_str, str):
        content = json.loads(content_str)
    else:
        content = content_str
    file_key = content.get('file_key', '')
    file_name = content.get('file_name', 'attachment')
    message_id = message.get('message_id', '')
    message_type = message.get('message_type', 'unknown')
    
    print(f"=== File Upload Handler ===")
    print(f"  message_id: {message_id}")
    print(f"  message_type: {message_type}")
    print(f"  file_key: {file_key}")
    print(f"  file_name: {file_name}")
    print(f"  case_id: {case_info.get('case_id')}")
    
    if not file_key or not message_id:
        print(f"Missing required fields, skipping")
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    try:
        # Download file
        print(f"Step 1: Downloading file from Lark...")
        file_data = download_file_from_lark(message_id, file_key)
        print(f"Step 1: Download completed, size: {len(file_data)} bytes")
        
        # Get role_arn from case info (saved when case was created)
        role_arn = case_info.get('role_arn')
        
        if not role_arn:
            print(f"Error: No role_arn found for case {case_info.get('case_id')}")
            send_message(case_info['case_chat_id'], 'text', {
                'text': get_message(DEFAULT_LANGUAGE, 'upload_no_account_info')
            })
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Upload to AWS Support (using account from case creation)
        display_id = case_info.get('display_id', case_info.get('case_id'))
        
        # Get user name
        user_info = get_user_info(user_id=user_id)
        user_name = user_info.get('name', 'Team Member')
        
        print(f"Step 2: Uploading to AWS Support...")
        attachment_set_id = upload_attachment_to_support(role_arn, file_data, file_name)
        
        if attachment_set_id:
            print(f"Step 2: Upload completed, attachment_set_id: {attachment_set_id}")
            
            # Add communication
            print(f"Step 3: Adding communication to case...")
            success = add_communication_to_case(
                role_arn=role_arn,
                case_id=case_info['case_id'],
                body=f"[From {user_name} via Lark] Uploaded attachment: {file_name}",
                attachment_set_id=attachment_set_id
            )
            
            if success:
                print(f"Step 3: Communication added successfully")
                # Send concise confirmation message
                confirmation_text = get_message(DEFAULT_LANGUAGE, 'upload_success', file_name, display_id)
                send_message(case_info['case_chat_id'], 'text', {'text': confirmation_text})
            else:
                print(f"Step 3: Failed to add communication")
                send_message(case_info['case_chat_id'], 'text', {
                    'text': get_message(DEFAULT_LANGUAGE, 'upload_add_failed')
                })
        else:
            print(f"Step 2: Failed to upload attachment")
            send_message(case_info['case_chat_id'], 'text', {
                'text': get_message(DEFAULT_LANGUAGE, 'upload_failed', file_name)
            })
    
    except Exception as e:
        error_msg = str(e)
        print(f"=== File Upload Error ===")
        print(f"  Error: {error_msg}")
        print(f"  message_id: {message_id}")
        print(f"  file_key: {file_key}")
        
        # Provide user-friendly error messages based on error type
        if "HTTP 400" in error_msg:
            user_msg = get_message(DEFAULT_LANGUAGE, 'upload_expired')
        elif "HTTP 403" in error_msg:
            user_msg = get_message(DEFAULT_LANGUAGE, 'upload_no_permission')
        elif "HTTP 404" in error_msg:
            user_msg = get_message(DEFAULT_LANGUAGE, 'upload_not_found')
        else:
            user_msg = get_message(DEFAULT_LANGUAGE, 'upload_error', error_msg)
        
        send_message(case_info['case_chat_id'], 'text', {'text': user_msg})
    
    return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}

def process_case_submission_async(action_value: Dict[str, Any], 
                                  operator: Dict[str, Any], user_id: str, context_chat_id: str):
    """Process case submission asynchronously after responding to Feishu
    
    This function contains all the time-consuming operations that were causing
    the 200341 timeout error. It's called after we've already responded to Feishu.
    """
    # Get case title from button value
    subject = action_value.get('subject', '').strip()
    
    # Get other info from draft (dropdown selected values)
    user_cases = s3_get_cases_by_user(user_id, limit=10)
    drafts = [c for c in user_cases if c.get('status') == 'draft']
    
    if not drafts:
        # Use context_chat_id as fallback
        send_message(context_chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'draft_not_found')})
        return
    
    draft = drafts[0]
    account_key = draft.get('account_key', '')
    service_code = draft.get('service_code', '')
    severity = draft.get('severity', '')
    
    # Get original chat_id from draft (where user initiated case creation)
    chat_id = draft.get('chat_id', context_chat_id)
    
    # Default issue type is technical
    issue_type = 'technical'
    
    # Validate required fields
    missing_fields = []
    if not subject:
        missing_fields.append('Case Title' if DEFAULT_LANGUAGE == 'en' else '工单标题')
    if not service_code:
        missing_fields.append('AWS Service' if DEFAULT_LANGUAGE == 'en' else 'AWS 服务')
    if not severity:
        missing_fields.append('Severity' if DEFAULT_LANGUAGE == 'en' else '严重程度')
    
    if missing_fields:
        fields_str = "\n".join([f"• {field}" for field in missing_fields])
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'fill_required_fields', fields_str)})
        return
    
    # Skip separator
    if service_code == 'separator':
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'select_valid_service')})
        return
    
    # Get configuration
    config = get_bot_config()
    accounts = config.get('accounts', {})
    
    # If no account selected, use the first account
    if not account_key and accounts:
        account_key = list(accounts.keys())[0]
    
    if not account_key or account_key not in accounts:
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'select_account')})
        return
    
    account_config = accounts.get(account_key, {})
    role_arn = account_config.get('role_arn')
    account_name = account_config.get('account_name', f'Account {account_key}')
    
    if not role_arn:
        send_message(chat_id, 'text', {'text': get_message(DEFAULT_LANGUAGE, 'config_error')})
        return
    
    # Create case directly with default description
    default_description = f"Case created, awaiting detailed description.\n\nIn case chat, @bot [content] to sync message to AWS Support.\n\nSuggested info:\n- Issue time and timezone\n- Resource IDs and region\n- Issue symptoms\n- Business impact\n- Contact info"
    
    result = create_support_case(
        role_arn=role_arn,
        subject=subject,
        description=default_description,
        severity=severity,
        service_code=service_code,
        category_code='',  # Don't specify category, let AWS auto-select
        issue_type=issue_type
    )
    
    # Use global default language for all bot responses
    # Note: Previously detected from subject, now using DEFAULT_LANGUAGE for consistency
    print(f"Using global default language: {DEFAULT_LANGUAGE}, subject: {subject[:30] if subject else 'empty'}")
    
    if result['success']:
        # Create case chat - use open_id
        try:
            # Get open_id from operator
            open_id = operator.get('open_id', '')
            if open_id:
                # Generate chat name: Case ID + Title (limit total length to 100 chars)
                # Format: Case 176404877500953 - Title
                base_name = f"Case {result['display_id']}"
                
                # If there's a title, add it to chat name (limit length)
                if subject:
                    # Calculate remaining available length: 100 - "Case " - display_id - " - " = about 80 chars
                    max_title_length = 100 - len(base_name) - 3  # 3 for " - "
                    if len(subject) > max_title_length:
                        # Truncate title and add ellipsis
                        truncated_subject = subject[:max_title_length-1] + "…"
                    else:
                        truncated_subject = subject
                    chat_name = f"{base_name} - {truncated_subject}"
                else:
                    chat_name = base_name
                
                case_chat_id = create_group_chat(
                    name=chat_name,
                    user_ids=[open_id]
                )
            else:
                print(f"No open_id found for user {user_id}")
                case_chat_id = None
        except Exception as e:
            print(f"Failed to create group: {e}")
            case_chat_id = None
        
        # Save case info
        # Extract target account ID from role_arn
        account_id = role_arn.split(':')[4] if ':' in role_arn else 'Unknown'
        
        # Get creator info (from operator)
        created_by = operator.get('user_id', user_id)
        created_by_open_id = operator.get('open_id', '')
        
        save_case_info(
            case_id=result['case_id'],
            display_id=result['display_id'],
            chat_id=chat_id,
            user_id=user_id,
            subject=subject,
            account_id=account_id,
            case_chat_id=case_chat_id,
            role_arn=role_arn,
            severity=severity,
            created_by=created_by,
            created_by_open_id=created_by_open_id
        )
        
        # Send success message (using rich text format for bold)
        issue_type_name = ISSUE_TYPES.get(issue_type, {}).get('name', issue_type)
        
        # Use global default language for all bot responses
        lang = DEFAULT_LANGUAGE
        
        # Build rich text content (localized)
        success_content = [
            [{"tag": "text", "text": get_message(lang, 'case_created_success')}],
            [{"tag": "text", "text": ""}],
            [{"tag": "text", "text": f"{get_message(lang, 'case_account_label')}: {account_id} ({account_name})"}],
            [{"tag": "text", "text": f"{get_message(lang, 'case_id_label')}: {result['display_id']}"}],
            [{"tag": "text", "text": f"{get_message(lang, 'case_issue_type_label')}: {issue_type_name}"}],
            [{"tag": "text", "text": f"{get_message(lang, 'case_title_label')}: {subject}"}],
            [{"tag": "text", "text": f"{get_message(lang, 'case_severity_label')}: {severity}"}],
            [{"tag": "text", "text": ""}],
        ]
        
        if case_chat_id:
            success_content.extend([
                [{"tag": "text", "text": get_message(lang, 'case_chat_created')}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": f"{get_message(lang, 'case_join_instruction')} "}, {"tag": "text", "text": f"@bot {get_message(lang, 'follow')} {result['display_id']}", "style": ["bold"]}, {"tag": "text", "text": f" {get_message(lang, 'case_join_suffix')}"}],
            ])
            
            # Send detailed case information in the case group chat
            severity_map = {
                'low': get_message(lang, 'severity_low'),
                'normal': get_message(lang, 'severity_normal'),
                'high': get_message(lang, 'severity_high'),
                'urgent': get_message(lang, 'severity_urgent'),
                'critical': get_message(lang, 'severity_critical')
            }
            severity_display = severity_map.get(severity, severity)
            
            # Get current time (UTC and Beijing time)
            created_time = get_dual_timezone_time()
            
            # Get creator's user info
            # Prefer name from operator, if not available then call API
            user_display_name = operator.get('user_name', '')
            
            if not user_display_name:
                creator_open_id = operator.get('open_id', '')
                print(f"Getting user info for user_id: {created_by}, open_id: {creator_open_id}")
                user_info = get_user_info(user_id=created_by, open_id=creator_open_id)
                print(f"User info result: {user_info}")
                user_display_name = user_info.get('name', '')
                
                # If still no name, use friendly fallback display
                if not user_display_name or user_display_name.startswith('ou_'):
                    user_display_name = get_message(lang, 'label_case_creator')
            
            print(f"Final user display name: {user_display_name}")
            
            # AWS Support Console link
            support_url = f"https://support.console.aws.amazon.com/support/home#/case/?displayId={result['display_id']}"
            
            # Build rich text content
            case_content = [
                [{"tag": "text", "text": get_message(lang, 'label_case_id'), "style": ["bold"]}, {"tag": "text", "text": ": "}, {"tag": "a", "text": result['display_id'], "href": support_url}],
                [{"tag": "text", "text": get_message(lang, 'label_title'), "style": ["bold"]}, {"tag": "text", "text": f": {subject}"}],
                [{"tag": "text", "text": get_message(lang, 'label_account'), "style": ["bold"]}, {"tag": "text", "text": f": {account_id} ({account_name})"}],
                [{"tag": "text", "text": get_message(lang, 'label_severity'), "style": ["bold"]}, {"tag": "text", "text": f": {severity_display}"}],
                [{"tag": "text", "text": get_message(lang, 'label_created_time'), "style": ["bold"]}, {"tag": "text", "text": f": {created_time}"}],
                [{"tag": "text", "text": get_message(lang, 'label_created_by'), "style": ["bold"]}, {"tag": "text", "text": f": {user_display_name}"}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "───────────────────"}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "💬 "}, {"tag": "text", "text": get_message(lang, 'sync_to_support'), "style": ["bold"]}],
                [{"tag": "text", "text": "• "}, {"tag": "text", "text": get_message(lang, 'sync_instruction'), "style": ["bold"]}, {"tag": "text", "text": get_message(lang, 'sync_description')}],
                [{"tag": "text", "text": "• "}, {"tag": "text", "text": get_message(lang, 'upload_attachment'), "style": ["bold"]}, {"tag": "text", "text": get_message(lang, 'upload_description')}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "💭 "}, {"tag": "text", "text": get_message(lang, 'internal_discussion'), "style": ["bold"]}],
                [{"tag": "text", "text": get_message(lang, 'internal_discussion_1')}],
                [{"tag": "text", "text": get_message(lang, 'internal_discussion_2')}],
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": "📢 "}, {"tag": "text", "text": get_message(lang, 'notification'), "style": ["bold"]}],
                [{"tag": "text", "text": get_message(lang, 'notification_1')}],
                [{"tag": "text", "text": get_message(lang, 'type_help')}, {"tag": "text", "text": get_message(lang, 'help'), "style": ["bold"]}, {"tag": "text", "text": get_message(lang, 'see_more_commands')}],
            ]
            
            send_post_message(case_chat_id, get_message(lang, 'case_details_title'), case_content)
        
        # Send success message (using rich text format)
        send_post_message(chat_id, "", success_content)
    else:
        error_text = get_message(DEFAULT_LANGUAGE, 'case_create_failed', result.get('error', 'Unknown error'))
        send_message(chat_id, 'text', {'text': error_text})


def handle_card_action(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle interactive card action - responds immediately to avoid 200341 timeout"""
    print(f"Card action event_data: {json.dumps(event_data)}")
    
    action = event_data.get('action', {})
    action_value = action.get('value', {})
    action_tag = action.get('tag', '')
    
    # Get user_id from operator
    operator = event_data.get('operator', {})
    user_id = operator.get('user_id', '')
    
    context = event_data.get('context', {})
    context_chat_id = context.get('open_chat_id', '')
    
    # Handle button click - submit case
    # CRITICAL: For submit_case, we return immediately and trigger async Lambda invocation
    if action_tag == 'button' and action_value.get('action') == 'submit_case':
        # Validate that the operator is the creator
        creator_id = action_value.get('creator_id', '')
        if creator_id and creator_id != user_id:
            # Not the creator, reject the action
            print(f"Card action rejected: operator {user_id} is not creator {creator_id}")
            # Return a toast message to inform the user
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({
                    "toast": {
                        "type": "error",
                        "content": get_message(DEFAULT_LANGUAGE, 'only_creator_can_submit')
                    }
                })
            }
        
        try:
            import boto3
            lambda_client = boto3.client('lambda')
            
            # Prepare payload for async processing
            async_payload = {
                'action_value': action_value,
                'operator': operator,
                'user_id': user_id,
                'context_chat_id': context_chat_id
            }
            
            # Invoke self asynchronously for case processing
            function_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
            print(f"Triggering async case processing via Lambda invoke: {function_name}")
            
            lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='Event',  # Async invocation - returns immediately
                Payload=json.dumps({
                    'async_case_processing': True,
                    'payload': async_payload
                })
            )
            print(f"Triggered async case processing for subject: {action_value.get('subject', 'N/A')}")
            
        except Exception as e:
            print(f"Error triggering async processing: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to sync processing if async fails
            process_case_submission_async(action_value, operator, user_id, context_chat_id)
        
        # Return immediately with empty response (avoids 200341 timeout)
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({})
        }
    
    # Handle dropdown selection - save to draft (fast operation, can be synchronous)
    elif action_tag == 'select_static':
        selected_value = action.get('option', '')
        
        # Find draft
        user_cases = s3_get_cases_by_user(user_id, limit=10)
        drafts = [c for c in user_cases if c.get('status') == 'draft']
        
        if drafts:
            draft = drafts[0]
            draft_id = draft['case_id']
            
            severity_codes = ['low', 'normal', 'high', 'urgent', 'critical']
            
            if selected_value in severity_codes:
                update_case(draft_id, {'severity': selected_value})
            elif selected_value.isdigit():
                update_case(draft_id, {'account_key': selected_value})
            else:
                update_case(draft_id, {'service_code': selected_value})
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({})
        }
    
    return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}


def is_event_processed(event_id: str) -> bool:
    """Check if event has been processed (S3 + in-memory cache for deduplication)"""
    global _processed_events
    
    # 1. Check in-memory cache first (fast path)
    if event_id in _processed_events:
        time_diff = datetime.utcnow() - _processed_events[event_id]
        if time_diff.total_seconds() < 300:  # 5 minutes
            print(f"Event {event_id} already processed (memory cache), skipping")
            return True
    
    # 2. Check S3 (for cold starts)
    try:
        dedup_case = get_case(f'event_dedup_{event_id}')
        
        if dedup_case:
            # Check if event was processed recently
            processed_at = datetime.fromisoformat(dedup_case.get('created_at', ''))
            time_diff = datetime.utcnow() - processed_at
            if time_diff.total_seconds() < 300:  # 5 minutes
                print(f"Event {event_id} already processed (S3), skipping")
                # Update memory cache
                _processed_events[event_id] = processed_at
                return True
    except Exception as e:
        print(f"Error checking S3 for event deduplication: {e}")
        # Continue anyway, don't block on S3 errors
    
    # 3. Mark event as processed (both memory and S3)
    now = datetime.utcnow()
    _processed_events[event_id] = now
    
    try:
        put_case(f'event_dedup_{event_id}', {
            'case_id': f'event_dedup_{event_id}',
            'created_at': now.isoformat(),
            'ttl': int((now + timedelta(minutes=10)).timestamp())  # For reference (S3 doesn't auto-delete)
        })
    except Exception as e:
        print(f"Error writing to S3 for event deduplication: {e}")
        # Continue anyway, memory cache is still active
    
    # Clean up old entries from memory cache if too large
    if len(_processed_events) > MAX_CACHE_SIZE:
        sorted_events = sorted(_processed_events.items(), key=lambda x: x[1])
        _processed_events = dict(sorted_events[-50:])
    
    return False


def lambda_handler(event, context):
    """Main Lambda handler"""
    try:
        print(f"Received event: {json.dumps(event)}")
        
        # Check if this is an async case processing invocation
        if event.get('async_case_processing'):
            payload = event.get('payload', {})
            print(f"Processing async case submission: {payload.get('action_value', {}).get('subject', 'N/A')}")
            process_case_submission_async(
                payload.get('action_value', {}),
                payload.get('operator', {}),
                payload.get('user_id', ''),
                payload.get('context_chat_id', '')
            )
            return {'statusCode': 200, 'body': json.dumps({'message': 'Async processing completed'})}
        
        body = event.get('body', '{}')
        if isinstance(body, str):
            body_dict = json.loads(body)
        else:
            body_dict = body
        
        # Handle URL verification
        if body_dict.get('type') == 'url_verification':
            challenge = body_dict.get('challenge', '')
            return {
                'statusCode': 200,
                'body': json.dumps({'challenge': challenge})
            }
        
        header = body_dict.get('header', {})
        event_type = header.get('event_type', '')
        event_id = header.get('event_id', '')
        
        # Event deduplication
        if event_id and is_event_processed(event_id):
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Route to appropriate handler
        if event_type == 'im.message.receive_v1':
            event_data = body_dict.get('event', {})
            return handle_message_receive(event_data)
        
        elif event_type == 'card.action.trigger':
            event_data = body_dict.get('event', {})
            return handle_card_action(event_data)
        
        # Ignore other event types (such as message recall, delete, edit, etc.)
        elif event_type in ['im.message.recalled_v1', 'im.message.deleted_v1', 'im.message.updated_v1']:
            print(f"Ignoring event type: {event_type}")
            return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
        
        # Unknown event type, log but don't process
        else:
            print(f"Unknown event type: {event_type}, ignoring")
        
        return {'statusCode': 200, 'body': json.dumps({'message': 'OK'})}
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
