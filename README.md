# Lark AWS Support Case Bot (S3 Storage Version)

[中文版](README_CN.md) | English

A Lark bot for creating and managing AWS Support cases. Supports multi-account, bidirectional sync, and file attachments.

> ⚠️ **Important**: This project must be deployed to the `us-east-1` region. AWS Support API and EventBridge events are only available in this region.

## Storage Architecture

This version uses **S3** for data storage:
- `config/{cfg_key}.json` - Bot configuration
- `cases/{case_id}.json` - Individual case data
- `indexes/chat_id/{chat_id}.json` - Chat ID to case mapping
- `indexes/user_id/{user_id}.json` - User ID to cases mapping

## Quick Start

```bash
# 1. Deploy (automatically deploys to us-east-1)
./deploy.sh

# Or with custom auto-dissolve time (default: 72 hours)
./deploy.sh --auto-dissolve-hours 48

# 2. Configure
cp accounts-example.json accounts.json
vim accounts.json
python3 setup_lark_bot.py setup

# 3. Configure Lark Webhook (use the URL from setup output)

# 4. Test - Send "help" in Lark
```

**What `setup_lark_bot.py setup` does:**
- Updates Lark credentials in Secrets Manager
- Creates IAM roles in all accounts for Support API access
- **Sets up cross-account EventBridge** to forward Support case updates to Lark
- Initializes S3 configuration with account mappings

This ensures **bidirectional sync** works automatically:
- Lark → AWS Support (via Lambda)
- AWS Support → Lark (via EventBridge)

## Main Features

- **Create Case**: `create case [title]` or `开工单 [标题]`
- **View History**: `history` or `历史`
- **Follow Case**: `follow [case ID]` or `关注 [工单ID]`
- **Dissolve Group**: `dissolve` or `解散群` (creator only)
- **Auto-Dissolve**: Automatically dissolve case groups N hours after resolution (default: 72h)
- **Bidirectional Sync**: Lark ↔ AWS Support real-time message sync
- **File Upload**: Reply to a file in case group and type "upload" or "上传工单"

## Case Group Operations

| Action | Description |
|--------|-------------|
| `@bot [message]` | Sync message to AWS Support |
| Direct message | Internal team discussion (not synced) |
| Reply to file + "upload" | Upload attachment to AWS |
| `dissolve` | Dissolve case group (creator only) |

## Documentation

- [Lark App Setup](docs/LARK-SETUP.md) - Complete guide for app creation, permissions, event subscription
- [Manual Deployment](docs/MANUAL-DEPLOY.md) - Full manual deployment without CDK
- [Technical Docs](docs/TECHNICAL.md) - Deployment, development, troubleshooting
- [Manual Account Setup](docs/manual-account-setup.md) - Cross-account IAM configuration

## Operations Scripts

```bash
cd scripts

# Quick Lambda deployment (after code changes)
./deploy-all-lambdas.sh

# Update cross-account permissions
./update-trust-policies.sh

# Comprehensive testing
./test-all.sh
```

## Project Structure

```
lark_case_bot_s3/
├── README.md                 # This file (English)
├── README_CN.md              # Chinese version
├── setup_lark_bot.py        # Configuration tool
├── app.py                   # CDK entry point
├── lark_case_bot_stack.py   # CDK Stack
├── accounts-example.json    # Configuration example
├── lambda/                  # Lambda functions
│   ├── msg_event_handler.py      # Main bot logic (Lark webhook)
│   ├── case_update_handler.py    # EventBridge case update notifications
│   ├── case_poller.py            # Scheduled case status polling
│   ├── group_cleanup.py          # Auto-dissolve resolved case groups
│   ├── s3_storage.py             # S3 storage helper module
│   ├── i18n.py                   # Multi-language support (zh/en)
│   └── aws_services_complete.py  # AWS service catalog
├── scripts/                 # Operations scripts
└── docs/                    # Documentation
```

## Related Links

- [AWS Support API](https://docs.aws.amazon.com/awssupport/latest/APIReference/)
- [Lark Open Platform](https://open.larksuite.com/)
