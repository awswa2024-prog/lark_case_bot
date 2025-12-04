"""
S3 Storage Helper Module

This module provides S3-based storage functions for the Lark Case Bot.
Data is stored as JSON files in S3 with the following structure:

- config/{cfg_key}.json: Bot configuration
- cases/{case_id}.json: Individual case data
- indexes/chat_id/{chat_id}.json: Maps chat_id to case_id
- indexes/user_id/{user_id}.json: Maps user_id to list of case_ids with created_at

Note: S3 versioning is enabled for data protection and optimistic locking.
"""
import json
import os
import boto3
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from botocore.exceptions import ClientError

# Initialize S3 client
s3_client = boto3.client('s3')

# Environment variable
DATA_BUCKET = os.environ.get('DATA_BUCKET', '')

# Prefixes
CONFIG_PREFIX = 'config/'
CASES_PREFIX = 'cases/'
CHAT_INDEX_PREFIX = 'indexes/chat_id/'
USER_INDEX_PREFIX = 'indexes/user_id/'


def _get_object(key: str) -> Optional[Dict[str, Any]]:
    """Get JSON object from S3"""
    try:
        response = s3_client.get_object(Bucket=DATA_BUCKET, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return None
        raise


def _put_object(key: str, data: Dict[str, Any]):
    """Put JSON object to S3"""
    s3_client.put_object(
        Bucket=DATA_BUCKET,
        Key=key,
        Body=json.dumps(data, default=str).encode('utf-8'),
        ContentType='application/json'
    )


def _delete_object(key: str):
    """Delete object from S3"""
    try:
        s3_client.delete_object(Bucket=DATA_BUCKET, Key=key)
    except ClientError:
        pass  # Ignore if doesn't exist


def _list_objects(prefix: str) -> List[str]:
    """List object keys with given prefix"""
    keys = []
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=DATA_BUCKET, Prefix=prefix):
        for obj in page.get('Contents', []):
            keys.append(obj['Key'])
    return keys


# ============================================================================
# Bot Configuration Functions
# ============================================================================

def get_bot_config(cfg_key: str = 'LarkBotProfile-0') -> Optional[Dict[str, Any]]:
    """Get bot configuration from S3"""
    key = f"{CONFIG_PREFIX}{cfg_key}.json"
    return _get_object(key)


def put_bot_config(cfg_key: str, config: Dict[str, Any]):
    """Save bot configuration to S3"""
    key = f"{CONFIG_PREFIX}{cfg_key}.json"
    _put_object(key, config)


# ============================================================================
# Case Data Functions
# ============================================================================

def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    """Get case data by case_id"""
    key = f"{CASES_PREFIX}{case_id}.json"
    return _get_object(key)


def put_case(case_id: str, case_data: Dict[str, Any]):
    """Save case data and update indexes"""
    # Ensure case_id is in the data
    case_data['case_id'] = case_id
    
    # Save case data
    key = f"{CASES_PREFIX}{case_id}.json"
    _put_object(key, case_data)
    
    # Update chat_id index if present
    chat_id = case_data.get('chat_id')
    if chat_id:
        _update_chat_index(chat_id, case_id)
    
    # Update case_chat_id index if present (for case group chats)
    case_chat_id = case_data.get('case_chat_id')
    if case_chat_id:
        _update_chat_index(case_chat_id, case_id)
    
    # Update user_id index if present
    user_id = case_data.get('user_id')
    created_at = case_data.get('created_at', datetime.now(timezone.utc).isoformat())
    if user_id:
        _update_user_index(user_id, case_id, created_at)


def update_case(case_id: str, updates: Dict[str, Any]) -> bool:
    """Update specific fields in a case"""
    case_data = get_case(case_id)
    if not case_data:
        return False
    
    case_data.update(updates)
    put_case(case_id, case_data)
    return True


def delete_case(case_id: str):
    """Delete case and remove from indexes"""
    case_data = get_case(case_id)
    if case_data:
        # Remove from chat_id index
        chat_id = case_data.get('chat_id')
        if chat_id:
            _remove_from_chat_index(chat_id, case_id)
        
        case_chat_id = case_data.get('case_chat_id')
        if case_chat_id:
            _remove_from_chat_index(case_chat_id, case_id)
        
        # Remove from user_id index
        user_id = case_data.get('user_id')
        if user_id:
            _remove_from_user_index(user_id, case_id)
    
    # Delete case file
    key = f"{CASES_PREFIX}{case_id}.json"
    _delete_object(key)


# ============================================================================
# Index Functions
# ============================================================================

def _update_chat_index(chat_id: str, case_id: str):
    """Update chat_id -> case_id index"""
    key = f"{CHAT_INDEX_PREFIX}{chat_id}.json"
    index_data = _get_object(key) or {'chat_id': chat_id, 'case_ids': []}
    
    if case_id not in index_data['case_ids']:
        index_data['case_ids'].append(case_id)
        _put_object(key, index_data)


def _remove_from_chat_index(chat_id: str, case_id: str):
    """Remove case_id from chat_id index"""
    key = f"{CHAT_INDEX_PREFIX}{chat_id}.json"
    index_data = _get_object(key)
    if index_data and case_id in index_data.get('case_ids', []):
        index_data['case_ids'].remove(case_id)
        if index_data['case_ids']:
            _put_object(key, index_data)
        else:
            _delete_object(key)


def _update_user_index(user_id: str, case_id: str, created_at: str):
    """Update user_id -> case_ids index with created_at for sorting"""
    key = f"{USER_INDEX_PREFIX}{user_id}.json"
    index_data = _get_object(key) or {'user_id': user_id, 'cases': []}
    
    # Check if case already exists
    existing = next((c for c in index_data['cases'] if c['case_id'] == case_id), None)
    if not existing:
        index_data['cases'].append({
            'case_id': case_id,
            'created_at': created_at
        })
        # Sort by created_at descending
        index_data['cases'].sort(key=lambda x: x.get('created_at', ''), reverse=True)
        _put_object(key, index_data)


def _remove_from_user_index(user_id: str, case_id: str):
    """Remove case_id from user_id index"""
    key = f"{USER_INDEX_PREFIX}{user_id}.json"
    index_data = _get_object(key)
    if index_data:
        index_data['cases'] = [c for c in index_data.get('cases', []) if c['case_id'] != case_id]
        if index_data['cases']:
            _put_object(key, index_data)
        else:
            _delete_object(key)


# ============================================================================
# Query Functions
# ============================================================================

def get_all_cases() -> List[Dict[str, Any]]:
    """Get all cases from S3
    
    Returns:
        List of case dictionaries
    """
    keys = _list_objects(CASES_PREFIX)
    cases = []
    
    for key in keys:
        if key.endswith('.json'):
            case_data = _get_object(key)
            if case_data:
                cases.append(case_data)
    
    return cases


def get_case_by_chat_id(chat_id: str) -> Optional[Dict[str, Any]]:
    """Get case by chat_id (returns first match)"""
    key = f"{CHAT_INDEX_PREFIX}{chat_id}.json"
    index_data = _get_object(key)
    
    if index_data and index_data.get('case_ids'):
        # Return the first (most recent) case
        case_id = index_data['case_ids'][-1]  # Last added
        return get_case(case_id)
    return None


def get_cases_by_chat_id(chat_id: str) -> List[Dict[str, Any]]:
    """Get all cases for a chat_id"""
    key = f"{CHAT_INDEX_PREFIX}{chat_id}.json"
    index_data = _get_object(key)
    
    if not index_data:
        return []
    
    cases = []
    for case_id in index_data.get('case_ids', []):
        case_data = get_case(case_id)
        if case_data:
            cases.append(case_data)
    return cases


def get_cases_by_user(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get user's recent cases (sorted by created_at descending)"""
    key = f"{USER_INDEX_PREFIX}{user_id}.json"
    index_data = _get_object(key)
    
    if not index_data:
        return []
    
    cases = []
    for case_ref in index_data.get('cases', [])[:limit]:
        case_data = get_case(case_ref['case_id'])
        if case_data:
            cases.append(case_data)
    return cases


def scan_cases_by_filter(filter_func) -> List[Dict[str, Any]]:
    """Scan all cases and filter (expensive, use sparingly)"""
    keys = _list_objects(CASES_PREFIX)
    results = []
    
    for key in keys:
        if key.endswith('.json'):
            case_data = _get_object(key)
            if case_data and filter_func(case_data):
                results.append(case_data)
    
    return results


def get_open_cases() -> List[Dict[str, Any]]:
    """Get all cases that are not resolved"""
    return scan_cases_by_filter(
        lambda c: c.get('status', 'open') != 'resolved'
    )


def get_case_by_case_chat_id(case_chat_id: str) -> Optional[Dict[str, Any]]:
    """Get case by case_chat_id (case group chat only)
    
    This function only matches the case_chat_id field (the dedicated case group),
    NOT the chat_id field (where the case was created from).
    """
    # Only scan for case_chat_id match - do NOT use chat_id index
    # because chat_id index contains both source chats and case chats
    cases = scan_cases_by_filter(lambda c: c.get('case_chat_id') == case_chat_id)
    return cases[0] if cases else None
