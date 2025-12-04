#!/usr/bin/env python3
"""
Internationalization (i18n) module for Lark Case Bot CLI

Supports English (en) and Chinese (zh) languages.
Default language is determined by LANG environment variable or can be set explicitly.
"""
import os
from typing import Dict

# Language messages
MESSAGES: Dict[str, Dict[str, str]] = {
    # ============================================================================
    # Common messages
    # ============================================================================
    "config_not_found": {
        "en": "Config file {path} not found",
        "zh": "配置文件 {path} 不存在"
    },
    "config_copy_hint": {
        "en": "Please copy {example} to {config} and fill in real values",
        "zh": "请复制 {example} 为 {config} 并填入真实值"
    },
    "config_format_error": {
        "en": "Config file format error: {error}",
        "zh": "配置文件格式错误: {error}"
    },
    "stack_not_found": {
        "en": "Error: LarkCaseBotStack not found. Please run: cdk deploy",
        "zh": "错误: 找不到 LarkCaseBotStack，请先运行: cdk deploy"
    },
    
    # ============================================================================
    # Setup command messages
    # ============================================================================
    "setup_start": {
        "en": "Starting Lark Case Bot initialization...",
        "zh": "开始初始化 Lark Case Bot..."
    },
    "using_config_file": {
        "en": "Using config file: {path}",
        "zh": "使用配置文件: {path}"
    },
    "missing_lark_credentials": {
        "en": "Missing Lark credentials. Please use --app-id and --app-secret, or set in config file",
        "zh": "缺少 Lark 凭证，请使用 --app-id 和 --app-secret 参数，或在配置文件中设置"
    },
    "updating_secrets": {
        "en": "Updating Secrets Manager...",
        "zh": "更新 Secrets Manager..."
    },
    "app_id_updated": {
        "en": "App ID updated",
        "zh": "App ID 已更新"
    },
    "app_secret_updated": {
        "en": "App Secret updated",
        "zh": "App Secret 已更新"
    },
    "update_failed": {
        "en": "Update failed: {error}",
        "zh": "更新失败: {error}"
    },
    "init_s3": {
        "en": "Initializing S3 configuration...",
        "zh": "初始化 S3 配置..."
    },
    "s3_initialized": {
        "en": "S3 configuration initialized",
        "zh": "S3 配置已初始化"
    },
    "configured_accounts": {
        "en": "Configured {count} account(s)",
        "zh": "配置了 {count} 个账号"
    },
    "init_failed": {
        "en": "Initialization failed: {error}",
        "zh": "初始化失败: {error}"
    },
    "creating_iam_role": {
        "en": "Creating IAM role...",
        "zh": "创建 IAM 角色..."
    },
    "iam_role_created": {
        "en": "IAM role created: {role}",
        "zh": "IAM 角色已创建: {role}"
    },
    "policy_attached": {
        "en": "Policy attached",
        "zh": "策略已附加"
    },
    "role_exists": {
        "en": "Role {role} already exists",
        "zh": "角色 {role} 已存在"
    },
    "create_failed": {
        "en": "Creation failed: {error}",
        "zh": "创建失败: {error}"
    },
    
    # ============================================================================
    # Setup summary messages
    # ============================================================================
    "setup_complete": {
        "en": "Initialization complete!",
        "zh": "初始化完成!"
    },
    "next_steps": {
        "en": "Next steps:",
        "zh": "下一步:"
    },
    "configure_webhook": {
        "en": "1. Configure Lark Webhook:",
        "zh": "1. 配置 Lark Webhook:"
    },
    "subscribe_events": {
        "en": "2. Subscribe to Lark events:",
        "zh": "2. 订阅 Lark 事件:"
    },
    "test_bot": {
        "en": "3. Test the bot:",
        "zh": "3. 测试机器人:"
    },
    "send_help": {
        "en": "   Send in Lark: help",
        "zh": "   在 Lark 发送: 帮助"
    },
    
    # ============================================================================
    # Accounts command messages
    # ============================================================================
    "configuring_multi_account": {
        "en": "Configuring multi-account support...",
        "zh": "配置多账号支持..."
    },
    "lambda_role": {
        "en": "Lambda role: {arn}",
        "zh": "Lambda 角色: {arn}"
    },
    "no_accounts": {
        "en": "No accounts to configure",
        "zh": "没有账号需要配置"
    },
    "processing_account": {
        "en": "Processing account: {name} ({id})",
        "zh": "处理账号: {name} ({id})"
    },
    "updating_s3": {
        "en": "Updating S3 configuration...",
        "zh": "更新 S3 配置..."
    },
    "detected_format": {
        "en": "Detected {format} format",
        "zh": "检测到 {format} 格式"
    },
    "unrecognized_format": {
        "en": "Unrecognized config format",
        "zh": "无法识别的配置格式"
    },
    "load_file_failed": {
        "en": "Failed to load file: {error}",
        "zh": "加载文件失败: {error}"
    },
    "interactive_mode": {
        "en": "Interactive mode (Ctrl+C to end)",
        "zh": "交互模式 (Ctrl+C 结束)"
    },
    "account_id_prompt": {
        "en": "Account ID (Enter to finish): ",
        "zh": "账号 ID (回车结束): "
    },
    "account_name_prompt": {
        "en": "Account name: ",
        "zh": "账号名称: "
    },
    "aws_profile_prompt": {
        "en": "AWS Profile (optional): ",
        "zh": "AWS Profile (可选): "
    },
    "trust_policy_updated": {
        "en": "Trust policy updated",
        "zh": "信任策略已更新"
    },
    "warning_wrong_account": {
        "en": "Warning: Current credentials access account {actual}, not target account {target}",
        "zh": "警告: 当前凭证访问的是账号 {actual}，而非目标账号 {target}"
    },
    "using_target_arn": {
        "en": "Using target account ARN: {arn}",
        "zh": "将使用目标账号 ARN: {arn}"
    },
    "failed": {
        "en": "Failed: {error}",
        "zh": "失败: {error}"
    },
    "using_expected_arn": {
        "en": "Using expected role ARN: {arn}",
        "zh": "将使用预期的角色 ARN: {arn}"
    },
    "manual_create_hint": {
        "en": "Please ensure role {role} is manually created in account {account}",
        "zh": "请确保在账号 {account} 中手动创建角色 {role}"
    },
    "backed_up_to": {
        "en": "Backed up to: {file}",
        "zh": "已备份到: {file}"
    },
    "s3_updated": {
        "en": "S3 updated",
        "zh": "S3 已更新"
    },
    "query_failed": {
        "en": "Query failed: {error}",
        "zh": "查询失败: {error}"
    },
    
    # ============================================================================
    # Accounts summary messages
    # ============================================================================
    "accounts_configured": {
        "en": "Configured {count} account(s)",
        "zh": "已配置 {count} 个账号"
    },
    "config_complete": {
        "en": "Configuration complete!",
        "zh": "配置完成!"
    },
    "test_hint": {
        "en": "Test: Send 'create case' in Lark",
        "zh": "测试: 在 Lark 发送 '开工单'"
    },
    "configured_accounts_title": {
        "en": "Configured Accounts ({count})",
        "zh": "已配置账号 ({count} 个)"
    },
    "account_id_label": {
        "en": "Account ID: {id}",
        "zh": "账号 ID: {id}"
    },
    "role_arn_label": {
        "en": "Role ARN: {arn}",
        "zh": "角色 ARN: {arn}"
    },
    "config_not_found_s3": {
        "en": "Configuration not found in S3",
        "zh": "S3 中未找到配置"
    },
    
    # ============================================================================
    # Verify command messages
    # ============================================================================
    "verifying_config": {
        "en": "Verifying configuration...",
        "zh": "验证配置..."
    },
    "verifying_stack": {
        "en": "Verifying CloudFormation Stack...",
        "zh": "验证 CloudFormation Stack..."
    },
    "stack_ok": {
        "en": "Stack OK",
        "zh": "Stack 正常"
    },
    "stack_error": {
        "en": "Stack error",
        "zh": "Stack 异常"
    },
    "verifying_s3": {
        "en": "Verifying S3...",
        "zh": "验证 S3..."
    },
    "s3_ok": {
        "en": "S3 OK",
        "zh": "S3 正常"
    },
    "s3_error": {
        "en": "S3 error",
        "zh": "S3 异常"
    },
    "verifying_secrets": {
        "en": "Verifying Secrets...",
        "zh": "验证 Secrets..."
    },
    "secrets_ok": {
        "en": "Secrets OK",
        "zh": "Secrets 正常"
    },
    "secrets_error": {
        "en": "Secrets error",
        "zh": "Secrets 异常"
    },
    "testing_roles": {
        "en": "Testing role assumption...",
        "zh": "测试角色假设..."
    },
    "roles_ok": {
        "en": "Role tests passed",
        "zh": "角色测试通过"
    },
    "roles_partial_fail": {
        "en": "Some role tests failed",
        "zh": "部分角色测试失败"
    },
    "missing_output": {
        "en": "Missing output: {key}",
        "zh": "缺少输出: {key}"
    },
    "missing_accounts_config": {
        "en": "Missing accounts configuration",
        "zh": "缺少 accounts 配置"
    },
    "accounts_count": {
        "en": "Configured {count} account(s)",
        "zh": "已配置 {count} 个账号"
    },
    "error": {
        "en": "Error: {error}",
        "zh": "错误: {error}"
    },
    "app_id_secret_exists": {
        "en": "App ID Secret exists",
        "zh": "App ID Secret 存在"
    },
    "app_secret_exists": {
        "en": "App Secret exists",
        "zh": "App Secret 存在"
    },
    "success": {
        "en": "Success",
        "zh": "成功"
    },
    "all_verified": {
        "en": "All verifications passed!",
        "zh": "所有验证通过!"
    },
    "some_failed": {
        "en": "Some verifications failed, please check",
        "zh": "部分验证失败，请检查"
    },
    
    # ============================================================================
    # CLI help messages
    # ============================================================================
    "cli_description": {
        "en": "Lark Case Bot CLI - Configuration Management Tool",
        "zh": "Lark Case Bot CLI - 配置管理工具"
    },
    "available_commands": {
        "en": "Available commands",
        "zh": "可用命令"
    },
    "setup_help": {
        "en": "Initialize bot",
        "zh": "初始化机器人"
    },
    "accounts_help": {
        "en": "Manage AWS accounts",
        "zh": "管理 AWS 账号"
    },
    "verify_help": {
        "en": "Verify configuration",
        "zh": "验证配置"
    },
    "add_help": {
        "en": "Add accounts",
        "zh": "添加账号"
    },
    "list_help": {
        "en": "List accounts",
        "zh": "列出账号"
    },
    
    # ============================================================================
    # Default bot messages (for S3 initialization)
    # ============================================================================
    "default_help_text": {
        "en": "📋 AWS Support Case Bot\n\nUsage:\n1. Type 'create case' to create a case\n2. Select account and fill in details\n3. Click submit",
        "zh": "📋 AWS支持案例机器人\n\n使用方法：\n1. 输入'开工单'创建案例\n2. 选择账户并填写信息\n3. 点击提交"
    },
    "default_no_permission": {
        "en": "You don't have permission to create cases. Please contact administrator.",
        "zh": "你没有权限开工单，请联系管理员"
    },
    "default_ack": {
        "en": "Received",
        "zh": "收到"
    },
    "default_account_name": {
        "en": "Main Account {account}",
        "zh": "主账号 {account}"
    },
}


def get_lang() -> str:
    """
    Detect language from environment.
    Returns 'zh' for Chinese, 'en' for English (default).
    """
    lang = os.environ.get('LANG', '').lower()
    if 'zh' in lang or 'cn' in lang:
        return 'zh'
    return 'en'


# Current language setting
_current_lang = get_lang()


def set_lang(lang: str):
    """Set current language ('en' or 'zh')"""
    global _current_lang
    if lang in ('en', 'zh'):
        _current_lang = lang


def get_current_lang() -> str:
    """Get current language setting"""
    return _current_lang


def t(key: str, **kwargs) -> str:
    """
    Get translated message by key.
    
    Args:
        key: Message key
        **kwargs: Format arguments
        
    Returns:
        Translated and formatted message
    """
    if key not in MESSAGES:
        return key
    
    msg = MESSAGES[key].get(_current_lang, MESSAGES[key].get('en', key))
    
    if kwargs:
        try:
            return msg.format(**kwargs)
        except KeyError:
            return msg
    return msg
