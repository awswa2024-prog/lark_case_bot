# Lark AWS Support 工单机器人 (S3 存储版本)

[English](README.md) | 中文版

Lark机器人，用于创建和管理 AWS Support 工单。支持多账号、双向同步、附件上传。

> ⚠️ **重要**: 此项目必须部署到 `us-east-1` 区域。AWS Support API 和 EventBridge 事件只在该区域可用。

## 存储架构

此版本使用 **S3** 存储数据：
- `config/{cfg_key}.json` - 机器人配置
- `cases/{case_id}.json` - 单个工单数据
- `indexes/chat_id/{chat_id}.json` - 聊天 ID 到工单映射
- `indexes/user_id/{user_id}.json` - 用户 ID 到工单映射

## 快速开始

```bash
# 1. 部署 (自动部署到 us-east-1)
./deploy.sh

# 或自定义自动解散时间 (默认: 72小时)
./deploy.sh --auto-dissolve-hours 48

# 2. 配置
cp accounts-example.json accounts.json
vim accounts.json
python3 setup_lark_bot.py setup

# 3. 配置Lark Webhook（使用 setup 输出的 URL）

# 4. 测试 - 在Lark发送 "帮助"
```

**`setup_lark_bot.py setup` 做什么:**
- 更新 Secrets Manager 中的 Lark 凭证
- 在所有账号创建 Support API 访问的 IAM 角色
- **设置跨账号 EventBridge** 转发 Support 工单更新到 Lark
- 初始化 S3 配置和账号映射

确保**双向同步**自动工作:
- Lark → AWS Support (通过 Lambda)
- AWS Support → Lark (通过 EventBridge)

## 主要功能

- **创建工单**: `开工单 [标题]` 或 `create case [title]`
- **查看历史**: `历史` 或 `history`
- **关注工单**: `关注 [工单ID]` 或 `follow [case ID]`
- **解散工单群**: `解散群` 或 `dissolve`（仅创建者）
- **双向同步**: Lark ↔ AWS Support 消息实时同步
- **附件上传**: 在工单群回复文件并输入"上传工单"

## 工单群操作

| 操作 | 说明 |
|------|------|
| `@bot [内容]` | 同步消息到 AWS Support |
| 直接发消息 | 团队内部讨论（不同步） |
| 回复文件 + "上传工单" | 上传附件到 AWS |
| `解散群` | 解散工单群（仅创建者） |

## 文档

- [Lark 应用配置](docs/LARK-SETUP.md) - 创建应用、权限、事件订阅完整指南
- [手动部署指南](docs/MANUAL-DEPLOY.md) - 不使用 CDK 的完整手动部署
- [技术文档](docs/TECHNICAL.md) - 部署、开发、故障排查
- [手动账号配置](docs/manual-account-setup.md) - 跨账号 IAM 配置

## 运维脚本

```bash
cd scripts

# 快速部署 Lambda（代码修改后）
./deploy-all-lambdas.sh

# 更新跨账户权限
./update-trust-policies.sh

# 综合测试
./test-all.sh
```

## 项目结构

```
lark_case_bot_s3/
├── README.md                 # 英文版
├── README_CN.md              # 本文件（中文版）
├── setup_lark_bot.py        # 配置工具
├── app.py                   # CDK 入口
├── lark_case_bot_stack.py   # CDK Stack
├── accounts-example.json    # 配置示例
├── lambda/                  # Lambda 函数
│   ├── msg_event_handler.py      # 主机器人逻辑（Lark webhook）
│   ├── case_update_handler.py    # EventBridge 工单更新通知
│   ├── case_poller.py            # 定时工单状态轮询
│   ├── group_cleanup.py          # 自动解散已解决工单群
│   ├── s3_storage.py             # S3 存储辅助模块
│   ├── i18n.py                   # 多语言支持（中/英）
│   └── aws_services_complete.py  # AWS 服务目录
├── scripts/                 # 运维脚本
└── docs/                    # 文档
```

## 相关链接

- [AWS Support API](https://docs.aws.amazon.com/awssupport/latest/APIReference/)
- [Lark开放平台](https://open.larksuite.com/)
