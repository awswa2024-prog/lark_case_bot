# 手动部署指南（不使用 CDK）- S3 存储版本

本文档介绍如何在 AWS Console 中手动创建所有资源，无需使用 CDK。

> ⚠️ **重要**: 所有资源必须创建在 `us-east-1` 区域。
>
> - AWS Support API 只在 us-east-1 可用
> - AWS Support EventBridge 事件只发送到 us-east-1
> - 在其他区域创建资源将导致功能无法正常工作

---

## 目录

- [架构概览](#架构概览)
- [前置条件](#前置条件)
- [Step 1: 创建 Secrets Manager](#step-1-创建-secrets-manager)
- [Step 2: 创建 S3 存储桶](#step-2-创建-s3-存储桶)
- [Step 3: 创建 IAM 角色](#step-3-创建-iam-角色)
- [Step 4: 创建 Lambda 函数](#step-4-创建-lambda-函数)
- [Step 5: 创建 API Gateway](#step-5-创建-api-gateway)
- [Step 6: 创建 EventBridge 规则](#step-6-创建-eventbridge-规则)
- [Step 7: 初始化配置](#step-7-初始化配置)
- [Step 8: 配置 Lark 应用](#step-8-配置-lark-应用)
- [验证部署](#验证部署)

---

## 架构概览

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Lark App  │────▶│ API Gateway │────▶│ MsgEventLambda   │
└─────────────┘     └─────────────┘     └────────┬─────────┘
                                                 │
                    ┌────────────────────────────┼────────────────────────────┐
                    │                            ▼                            │
              ┌─────┴─────┐              ┌───────────────┐            ┌───────┴───────┐
              │ Secrets   │              │      S3       │            │ AWS Support   │
              │ Manager   │              │ (Config/Case) │            │     API       │
              └───────────┘              └───────────────┘            └───────────────┘
                                                 ▲
                    ┌────────────────────────────┼─────────────────────────────┐
                    │                            │                             │
              ┌─────┴─────┐              ┌───────┴────────┐            ┌───────┴────────┐
              │EventBridge│──────────────│CaseUpdateLambda│            │CasePollerLambda│
              │  (Rule)   │              └────────────────┘            └────────────────┘
              └───────────┘
```

### 资源清单

| 资源类型 | 名称 | 用途 |
|---------|------|------|
| Secrets Manager | LarkCaseBot-app-id | 存储 Lark App ID |
| Secrets Manager | LarkCaseBot-app-secret | 存储 Lark App Secret |
| Secrets Manager | LarkCaseBot-encrypt-key | 存储 Lark Encrypt Key（可选，用于事件解密） |
| Secrets Manager | LarkCaseBot-verification-token | 存储 Lark Verification Token（用于请求验证） |
| S3 | LarkCaseBot-DataBucket | Bot 配置和工单数据存储 |
| IAM Role | LarkCaseBot-MsgEventRole | MsgEventLambda 执行角色 |
| IAM Role | LarkCaseBot-CaseUpdateRole | CaseUpdateLambda 执行角色 |
| IAM Role | LarkCaseBot-CasePollerRole | CasePollerLambda 执行角色 |
| IAM Role | LarkCaseBot-GroupCleanupRole | GroupCleanupLambda 执行角色 |
| IAM Role | LarkCaseBot-SupportApiRole | AWS Support API 访问 |
| Lambda | LarkCaseBot-MsgEvent | 处理 Lark 消息 |
| Lambda | LarkCaseBot-CaseUpdate | 处理工单更新事件 |
| Lambda | LarkCaseBot-CasePoller | 定期轮询工单状态 |
| Lambda | LarkCaseBot-GroupCleanup | 自动解散已解决工单群 |
| API Gateway | LarkCaseBot-API | Webhook 端点 |
| EventBridge Rule | LarkCaseBot-CaseUpdate | 工单更新事件 |
| EventBridge Rule | LarkCaseBot-Poller | 定时轮询 |
| EventBridge Rule | LarkCaseBot-GroupCleanup | 每小时检查需解散的群 |

---

## 前置条件

- AWS 账号（有 Business 或 Enterprise Support 计划）
- Lark 开放平台账号
- AWS CLI 已配置（可选，用于 CLI 命令）

---

## Step 1: 创建 Secrets Manager

### 1.1 创建 App ID Secret

**Console 方式：**

1. 进入 AWS Console → Secrets Manager（确保在 **us-east-1** 区域）
2. 点击 **Store a new secret**
3. Step 1 - Choose secret type：
   - Secret type: **Other type of secret**
   - Key/value pairs：点击 **Plaintext** 标签，输入：
   ```json
   {"app_id":"cli_xxxxxxxxxx"}
   ```
   - Encryption key: 保持默认 `aws/secretsmanager`
   - 点击 **Next**
4. Step 2 - Configure secret：
   - Secret name: `LarkCaseBot-app-id`
   - Description: `Lark App ID for Case Bot`
   - 点击 **Next**
5. Step 3 - Configure rotation：保持默认，点击 **Next**
6. Step 4 - Review：点击 **Store**
7. ⚠️ **记录 Secret ARN**：创建后点击进入，复制完整的 **Secret ARN**（Lambda 环境变量需要）

**CLI 方式：**

```bash
aws secretsmanager create-secret \
  --name LarkCaseBot-app-id \
  --secret-string '{"app_id":"cli_xxxxxxxxxx"}'
```

### 1.2 创建 App Secret Secret

**Console 方式：**

1. 重复上述步骤
2. 添加键值对：
   - Key: `app_secret`
   - Value: `xxxxxxxxxxxxxxxx`（你的 Lark App Secret）
3. Secret name: `LarkCaseBot-app-secret`

**CLI 方式：**

```bash
aws secretsmanager create-secret \
  --name LarkCaseBot-app-secret \
  --secret-string '{"app_secret":"xxxxxxxxxxxxxxxx"}'
```

### 1.3 创建 Encrypt Key Secret（可选）

用于解密 Lark 事件（如果启用了加密）。

**Console 方式：**

1. 重复上述步骤
2. 点击 **Plaintext** 标签，输入：
   ```json
   {"encrypt_key":""}
   ```
   > 💡 如果不使用加密，保持空字符串即可
3. Secret name: `LarkCaseBot-encrypt-key`

**CLI 方式：**

```bash
aws secretsmanager create-secret \
  --name LarkCaseBot-encrypt-key \
  --secret-string '{"encrypt_key":""}'
```

### 1.4 创建 Verification Token Secret

用于验证请求来源。

**Console 方式：**

1. 重复上述步骤
2. 点击 **Plaintext** 标签，输入：
   ```json
   {"verification_token":"xxxxxxxxxxxxxxxx"}
   ```
   > 从 Lark 开放平台 → 事件订阅页面获取 Verification Token
3. Secret name: `LarkCaseBot-verification-token`

**CLI 方式：**

```bash
aws secretsmanager create-secret \
  --name LarkCaseBot-verification-token \
  --secret-string '{"verification_token":"xxxxxxxxxxxxxxxx"}'
```

---

## Step 2: 创建 S3 存储桶

### 2.1 创建数据存储桶

**Console 方式：**

1. 进入 AWS Console → S3（确保在 **us-east-1** 区域）
2. 点击 **Create bucket**
3. General configuration：
   - Bucket name: `larkcasebot-data-{account-id}`（将 `{account-id}` 替换为你的 12 位 AWS 账号 ID）
   - AWS Region: **US East (N. Virginia) us-east-1**
4. Object Ownership：保持默认 **ACLs disabled**
5. Block Public Access settings：
   - ✅ **Block all public access**（必须勾选）
6. Bucket Versioning：
   - 选择 **Enable**
7. Default encryption：
   - Encryption type: **Server-side encryption with Amazon S3 managed keys (SSE-S3)**
   - Bucket Key: **Enable**
8. 点击 **Create bucket**

> 💡 **提示**: 记住存储桶名称，Lambda 环境变量 `DATA_BUCKET` 需要使用

**CLI 方式：**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET_NAME="larkcasebot-data-${ACCOUNT_ID}"

# 创建存储桶
aws s3api create-bucket \
  --bucket ${BUCKET_NAME} \
  --region us-east-1

# 启用版本控制
aws s3api put-bucket-versioning \
  --bucket ${BUCKET_NAME} \
  --versioning-configuration Status=Enabled

# 启用加密
aws s3api put-bucket-encryption \
  --bucket ${BUCKET_NAME} \
  --server-side-encryption-configuration '{
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
  }'

# 阻止公共访问
aws s3api put-public-access-block \
  --bucket ${BUCKET_NAME} \
  --public-access-block-configuration '{
    "BlockPublicAcls": true,
    "IgnorePublicAcls": true,
    "BlockPublicPolicy": true,
    "RestrictPublicBuckets": true
  }'

# 配置生命周期规则（30天后删除旧版本）
aws s3api put-bucket-lifecycle-configuration \
  --bucket ${BUCKET_NAME} \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "DeleteOldVersions",
      "Status": "Enabled",
      "NoncurrentVersionExpiration": {"NoncurrentDays": 30},
      "Filter": {"Prefix": ""}
    }]
  }'

echo "Bucket created: ${BUCKET_NAME}"
```

### 2.2 S3 存储结构

存储桶将使用以下目录结构：

```
larkcasebot-data-{account-id}/
├── config/
│   └── LarkBotProfile-0.json    # Bot 配置
├── cases/
│   └── {case_id}.json           # 单个工单数据
└── indexes/
    ├── chat_id/
    │   └── {chat_id}.json       # 聊天 ID 索引
    └── user_id/
        └── {user_id}.json       # 用户 ID 索引
```

---

## Step 3: 创建 IAM 角色

> 💡 **创建顺序说明**: 先创建 Lambda 执行角色（3.1-3.4），最后创建 SupportApiRole（3.5）。因为 SupportApiRole 的信任策略需要引用 Lambda 角色的 ARN。

### 3.1 创建 MsgEventRole

**Console 方式：**

1. 进入 AWS Console → IAM → Roles
2. 点击 **Create role**
3. Step 1 - Select trusted entity：
   - Trusted entity type: **AWS service**
   - Use case: **Lambda**
   - 点击 **Next**
4. Step 2 - Add permissions：
   - 搜索并勾选 `AWSLambdaBasicExecutionRole`
   - 点击 **Next**
5. Step 3 - Name, review, and create：
   - Role name: `LarkCaseBot-MsgEventRole`
   - 点击 **Create role**
6. 添加内联策略：
   - 找到刚创建的角色，点击进入
   - 点击 **Add permissions** → **Create inline policy**
   - 选择 **JSON** 标签
   - 粘贴下方的内联策略 JSON
   - Policy name: `MsgEventPolicy`
   - 点击 **Create policy**

**信任策略（自动创建）：**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**内联策略 (msg-event-policy.json)：**

> ⚠️ **重要**: 将下方策略中的 `ACCOUNT_ID` 替换为你的 12 位 AWS 账号 ID。
>
> 💡 **关于 Secret ARN 中的 `*`**: Secrets Manager 会自动在 secret 名称后添加 6 位随机后缀（如 `-AbCdEf`），因此策略使用 `LarkCaseBot-app-id*` 来匹配。如果你需要更严格的权限控制，可以在创建 secret 后，将 `*` 替换为完整的 ARN（从 Secrets Manager Console 复制）。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SecretsManagerAccess",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-encrypt-key*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-verification-token*"
      ]
    },
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::larkcasebot-data-ACCOUNT_ID",
        "arn:aws:s3:::larkcasebot-data-ACCOUNT_ID/*"
      ]
    },
    {
      "Sid": "AssumeRoleForSupport",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::*:role/LarkCaseBot-SupportApiRole"
    },
    {
      "Sid": "LambdaSelfInvoke",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT_ID:function:LarkCaseBot-MsgEvent"
    }
  ]
}
```

> 💡 **关于 AssumeRole 中的 `*`**: `arn:aws:iam::*:role/LarkCaseBot-SupportApiRole` 允许访问任意账户的 Support API 角色。如果只需支持特定账户，可替换为具体账户 ID 列表，如：`arn:aws:iam::111122223333:role/LarkCaseBot-SupportApiRole`

**CLI 方式：**

```bash
# 创建角色
aws iam create-role \
  --role-name LarkCaseBot-MsgEventRole \
  --assume-role-policy-document file://lambda-trust-policy.json

# 附加基础执行策略
aws iam attach-role-policy \
  --role-name LarkCaseBot-MsgEventRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# 创建并附加内联策略
aws iam put-role-policy \
  --role-name LarkCaseBot-MsgEventRole \
  --policy-name MsgEventPolicy \
  --policy-document file://msg-event-policy.json
```

### 3.2 创建 CaseUpdateRole

**Console 方式：**

1. 进入 AWS Console → IAM → Roles → **Create role**
2. Trusted entity type: **AWS service** → Use case: **Lambda**
3. 添加权限：勾选 `AWSLambdaBasicExecutionRole`
4. Role name: `LarkCaseBot-CaseUpdateRole`
5. 创建后添加内联策略：
   - 点击 **Add permissions** → **Create inline policy** → **JSON**
   - 粘贴下方 JSON（将 `ACCOUNT_ID` 替换为你的账号 ID）
   - Policy name: `CaseUpdatePolicy`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SecretsManagerAccess",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret*"
      ]
    },
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::larkcasebot-data-ACCOUNT_ID", "arn:aws:s3:::larkcasebot-data-ACCOUNT_ID/*"]
    },
    {
      "Sid": "AssumeRoleForSupport",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::*:role/LarkCaseBot-SupportApiRole"
    }
  ]
}
```

**CLI 方式：**

```bash
aws iam create-role \
  --role-name LarkCaseBot-CaseUpdateRole \
  --assume-role-policy-document file://lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name LarkCaseBot-CaseUpdateRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy \
  --role-name LarkCaseBot-CaseUpdateRole \
  --policy-name CaseUpdatePolicy \
  --policy-document file://case-update-policy.json
```

### 3.3 创建 CasePollerRole

**Console 方式：**

1. 进入 AWS Console → IAM → Roles → **Create role**
2. Trusted entity type: **AWS service** → Use case: **Lambda**
3. 添加权限：勾选 `AWSLambdaBasicExecutionRole`
4. Role name: `LarkCaseBot-CasePollerRole`
5. 创建后添加内联策略：
   - 点击 **Add permissions** → **Create inline policy** → **JSON**
   - 粘贴下方 JSON（将 `ACCOUNT_ID` 替换为你的账号 ID）
   - Policy name: `CasePollerPolicy`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SecretsManagerAccess",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret*"
      ]
    },
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::larkcasebot-data-ACCOUNT_ID", "arn:aws:s3:::larkcasebot-data-ACCOUNT_ID/*"]
    },
    {
      "Sid": "AssumeRoleForSupport",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::*:role/LarkCaseBot-SupportApiRole"
    }
  ]
}
```

**CLI 方式：**

```bash
aws iam create-role \
  --role-name LarkCaseBot-CasePollerRole \
  --assume-role-policy-document file://lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name LarkCaseBot-CasePollerRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy \
  --role-name LarkCaseBot-CasePollerRole \
  --policy-name CasePollerPolicy \
  --policy-document file://case-poller-policy.json
```

### 3.4 创建 GroupCleanupRole

**Console 方式：**

1. 进入 AWS Console → IAM → Roles → **Create role**
2. Trusted entity type: **AWS service** → Use case: **Lambda**
3. 添加权限：勾选 `AWSLambdaBasicExecutionRole`
4. Role name: `LarkCaseBot-GroupCleanupRole`
5. 创建后添加内联策略：
   - 点击 **Add permissions** → **Create inline policy** → **JSON**
   - 粘贴下方 JSON（将 `ACCOUNT_ID` 替换为你的账号 ID）
   - Policy name: `GroupCleanupPolicy`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SecretsManagerAccess",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret*"
      ]
    },
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::larkcasebot-data-ACCOUNT_ID", "arn:aws:s3:::larkcasebot-data-ACCOUNT_ID/*"]
    }
  ]
}
```

> 💡 **注意**: GroupCleanupRole 不需要 `AssumeRoleForSupport` 权限，因为它只读取 S3 数据和调用 Lark API。

**CLI 方式：**

```bash
aws iam create-role \
  --role-name LarkCaseBot-GroupCleanupRole \
  --assume-role-policy-document file://lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name LarkCaseBot-GroupCleanupRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy \
  --role-name LarkCaseBot-GroupCleanupRole \
  --policy-name GroupCleanupPolicy \
  --policy-document file://group-cleanup-policy.json
```

### 3.5 创建 LarkCaseBot-SupportApiRole

这是访问 AWS Support API 的角色。必须在 Lambda 执行角色创建完成后再创建此角色。

> ⚠️ **注意**: 此角色**不是** Lambda 执行角色，而是被 Lambda 执行角色 AssumeRole 调用的角色。信任策略需要信任 IAM 角色（不是 Lambda 服务）。

**Console 方式：**

1. 进入 AWS Console → IAM → Roles → **Create role**
2. Step 1 - Select trusted entity：
   - Trusted entity type: **Custom trust policy**
   - 粘贴下方信任策略 JSON（将 `ACCOUNT_ID` 替换为你的账号 ID）
   - 点击 **Next**
3. Step 2 - Add permissions：
   - 搜索并勾选 `AWSSupportAccess`
   - 点击 **Next**
4. Step 3 - Name, review, and create：
   - Role name: `LarkCaseBot-SupportApiRole`
   - 点击 **Create role**

**信任策略 (Custom trust policy)：**

> 将 `ACCOUNT_ID` 替换为部署 Lambda 的主账号 ID。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws:iam::ACCOUNT_ID:role/LarkCaseBot-MsgEventRole",
          "arn:aws:iam::ACCOUNT_ID:role/LarkCaseBot-CasePollerRole"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

> **跨账号说明**: 
> - `ACCOUNT_ID` 是部署 LarkCaseBot Lambda 的主账号 ID
> - 必须使用**完整的角色 ARN**，不要使用通配符 `*`

**CLI 方式：**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 创建信任策略文件
cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws:iam::${ACCOUNT_ID}:role/LarkCaseBot-MsgEventRole",
          "arn:aws:iam::${ACCOUNT_ID}:role/LarkCaseBot-CasePollerRole"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# 创建角色
aws iam create-role \
  --role-name LarkCaseBot-SupportApiRole \
  --assume-role-policy-document file:///tmp/trust-policy.json

# 附加 AWSSupportAccess 策略
aws iam attach-role-policy \
  --role-name LarkCaseBot-SupportApiRole \
  --policy-arn arn:aws:iam::aws:policy/AWSSupportAccess

# 清理
rm /tmp/trust-policy.json
```

---

## Step 4: 创建 Lambda 函数

### Lambda 函数总览

| Lambda | Handler | 执行角色 | 超时 | 内存 | 触发器 |
|--------|---------|---------|------|------|--------|
| MsgEvent | `msg_event_handler.lambda_handler` | MsgEventRole | 60s | 1024MB | API Gateway |
| CaseUpdate | `case_update_handler.lambda_handler` | CaseUpdateRole | 30s | 256MB | EventBridge (aws.support) |
| CasePoller | `case_poller.lambda_handler` | CasePollerRole | 300s | 512MB | EventBridge (每 5 分钟) |
| GroupCleanup | `group_cleanup.lambda_handler` | GroupCleanupRole | 300s | 256MB | EventBridge (每小时) |

### 4.1 准备代码包

```bash
cd lambda
zip -r ../lambda-package.zip .
cd ..
```

---

### 4.2 创建 MsgEventLambda

**配置概览：**

| 配置项 | 值 |
|-------|-----|
| 函数名 | `LarkCaseBot-MsgEvent` |
| Handler | `msg_event_handler.lambda_handler` |
| 执行角色 | `LarkCaseBot-MsgEventRole` |
| 超时 | 60 秒 |
| 内存 | 1024 MB |
| 触发器 | API Gateway（Lark Webhook） |

**环境变量：**

| Key | Value | 说明 |
|-----|-------|------|
| APP_ID_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id-XXXXX` | Lark App ID |
| APP_SECRET_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret-XXXXX` | Lark App Secret |
| ENCRYPT_KEY_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-encrypt-key-XXXXX` | Lark Encrypt Key（可选） |
| VERIFICATION_TOKEN_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-verification-token-XXXXX` | Lark Verification Token |
| DATA_BUCKET | `larkcasebot-data-ACCOUNT_ID` | S3 数据桶（仅桶名，非 ARN） |
| CFG_KEY | `LarkBotProfile-0` | 配置键名 |
| CASE_LANGUAGE | `zh` | 工单语言 (zh/en/ja/ko) |
| USER_WHITELIST | `false` | 是否启用用户白名单 |

> ⚠️ **注意**: 
> - 将 `ACCOUNT_ID` 替换为你的实际 AWS 账号 ID
> - Secret ARN 末尾的 `-XXXXX` 是自动生成的，需要从 Secrets Manager 复制完整 ARN
> - `DATA_BUCKET` 只需要桶名（如 `larkcasebot-data-123456789012`），不是完整 ARN

**Console 方式：**

1. 进入 AWS Console → Lambda（确保在 **us-east-1** 区域）
2. 点击 **Create function**
3. 选择 **Author from scratch**
4. 基本配置：
   - Function name: `LarkCaseBot-MsgEvent`
   - Runtime: **Python 3.12**
   - Architecture: **x86_64**
5. 权限配置：
   - 展开 **Change default execution role**
   - 选择 **Use an existing role**
   - Existing role: `LarkCaseBot-MsgEventRole`
6. 点击 **Create function**
7. 上传代码：
   - 在 **Code** 标签页，点击 **Upload from** → **.zip file**
   - 上传 `lambda-package.zip`
8. 配置 Runtime settings：
   - 点击 **Edit**
   - Handler: `msg_event_handler.lambda_handler`
   - 点击 **Save**
9. 配置 General configuration：
   - 点击 **Configuration** → **General configuration** → **Edit**
   - Timeout: **1 minute 0 seconds**
   - Memory: **1024 MB**
   - 点击 **Save**
10. 添加环境变量：
    - 点击 **Configuration** → **Environment variables** → **Edit**
    - 按上方环境变量表格添加所有变量

**CLI 方式：**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda create-function \
  --function-name LarkCaseBot-MsgEvent \
  --runtime python3.12 \
  --handler msg_event_handler.lambda_handler \
  --role arn:aws:iam::${ACCOUNT_ID}:role/LarkCaseBot-MsgEventRole \
  --zip-file fileb://lambda-package.zip \
  --timeout 60 \
  --memory-size 1024 \
  --region us-east-1 \
  --environment "Variables={
    APP_ID_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-app-id-XXXXX,
    APP_SECRET_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-app-secret-XXXXX,
    ENCRYPT_KEY_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-encrypt-key-XXXXX,
    VERIFICATION_TOKEN_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-verification-token-XXXXX,
    DATA_BUCKET=larkcasebot-data-${ACCOUNT_ID},
    CFG_KEY=LarkBotProfile-0,
    CASE_LANGUAGE=zh,
    USER_WHITELIST=false
  }"
```

---

### 4.3 创建 CaseUpdateLambda

**配置概览：**

| 配置项 | 值 |
|-------|-----|
| 函数名 | `LarkCaseBot-CaseUpdate` |
| Handler | `case_update_handler.lambda_handler` |
| 执行角色 | `LarkCaseBot-CaseUpdateRole` |
| 超时 | 30 秒 |
| 内存 | 256 MB |
| 触发器 | EventBridge 规则 `LarkCaseBot-CaseUpdate`（工单更新事件） |

**环境变量：**

| Key | Value | 说明 |
|-----|-------|------|
| APP_ID_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id-XXXXX` | Lark App ID |
| APP_SECRET_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret-XXXXX` | Lark App Secret |
| DATA_BUCKET | `larkcasebot-data-ACCOUNT_ID` | S3 数据桶（仅桶名，非 ARN） |
| AUTO_DISSOLVE_HOURS | `72` | 工单解决后自动解散群的小时数 |

**CLI 方式：**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda create-function \
  --function-name LarkCaseBot-CaseUpdate \
  --runtime python3.12 \
  --handler case_update_handler.lambda_handler \
  --role arn:aws:iam::${ACCOUNT_ID}:role/LarkCaseBot-CaseUpdateRole \
  --zip-file fileb://lambda-package.zip \
  --timeout 30 \
  --memory-size 256 \
  --region us-east-1 \
  --environment "Variables={
    APP_ID_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-app-id-XXXXX,
    APP_SECRET_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-app-secret-XXXXX,
    DATA_BUCKET=larkcasebot-data-${ACCOUNT_ID},
    AUTO_DISSOLVE_HOURS=72
  }"
```

---

### 4.4 创建 CasePollerLambda

**配置概览：**

| 配置项 | 值 |
|-------|-----|
| 函数名 | `LarkCaseBot-CasePoller` |
| Handler | `case_poller.lambda_handler` |
| 执行角色 | `LarkCaseBot-CasePollerRole` |
| 超时 | 300 秒（5 分钟） |
| 内存 | 512 MB |
| 触发器 | EventBridge 规则 `LarkCaseBot-Poller`（每 5 分钟） |

**环境变量：**

| Key | Value | 说明 |
|-----|-------|------|
| APP_ID_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id-XXXXX` | Lark App ID |
| APP_SECRET_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret-XXXXX` | Lark App Secret |
| DATA_BUCKET | `larkcasebot-data-ACCOUNT_ID` | S3 数据桶（仅桶名，非 ARN） |
| AUTO_DISSOLVE_HOURS | `72` | 工单解决后自动解散群的小时数 |

**CLI 方式：**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda create-function \
  --function-name LarkCaseBot-CasePoller \
  --runtime python3.12 \
  --handler case_poller.lambda_handler \
  --role arn:aws:iam::${ACCOUNT_ID}:role/LarkCaseBot-CasePollerRole \
  --zip-file fileb://lambda-package.zip \
  --timeout 300 \
  --memory-size 512 \
  --region us-east-1 \
  --environment "Variables={
    APP_ID_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-app-id-XXXXX,
    APP_SECRET_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-app-secret-XXXXX,
    DATA_BUCKET=larkcasebot-data-${ACCOUNT_ID},
    AUTO_DISSOLVE_HOURS=72
  }"
```

---

### 4.5 创建 GroupCleanupLambda

**配置概览：**

| 配置项 | 值 |
|-------|-----|
| 函数名 | `LarkCaseBot-GroupCleanup` |
| Handler | `group_cleanup.lambda_handler` |
| 执行角色 | `LarkCaseBot-GroupCleanupRole` |
| 超时 | 300 秒（5 分钟） |
| 内存 | 256 MB |
| 触发器 | EventBridge 规则 `LarkCaseBot-GroupCleanup`（每小时） |

**环境变量：**

| Key | Value | 说明 |
|-----|-------|------|
| APP_ID_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id-XXXXX` | Lark App ID |
| APP_SECRET_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret-XXXXX` | Lark App Secret |
| DATA_BUCKET | `larkcasebot-data-ACCOUNT_ID` | S3 数据桶（仅桶名，非 ARN） |
| AUTO_DISSOLVE_HOURS | `72` | 工单解决后自动解散群的小时数 |

**CLI 方式：**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda create-function \
  --function-name LarkCaseBot-GroupCleanup \
  --runtime python3.12 \
  --handler group_cleanup.lambda_handler \
  --role arn:aws:iam::${ACCOUNT_ID}:role/LarkCaseBot-GroupCleanupRole \
  --zip-file fileb://lambda-package.zip \
  --timeout 300 \
  --memory-size 256 \
  --region us-east-1 \
  --environment "Variables={
    APP_ID_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-app-id-XXXXX,
    APP_SECRET_ARN=arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:LarkCaseBot-app-secret-XXXXX,
    DATA_BUCKET=larkcasebot-data-${ACCOUNT_ID},
    AUTO_DISSOLVE_HOURS=72
  }"
```

---

### 4.6 环境变量说明

| 变量 | 说明 | 使用的 Lambda |
|-----|------|--------------|
| `APP_ID_ARN` | Lark App ID 的 Secrets Manager ARN | 全部 |
| `APP_SECRET_ARN` | Lark App Secret 的 Secrets Manager ARN | 全部 |
| `ENCRYPT_KEY_ARN` | Lark Encrypt Key 的 Secrets Manager ARN（可选） | MsgEvent |
| `VERIFICATION_TOKEN_ARN` | Lark Verification Token 的 Secrets Manager ARN | MsgEvent |
| `DATA_BUCKET` | S3 数据桶名称（仅桶名，非 ARN） | 全部 |
| `CFG_KEY` | S3 配置键名 | MsgEvent |
| `CASE_LANGUAGE` | 工单语言 (zh/en/ja/ko) | MsgEvent |
| `USER_WHITELIST` | 是否启用用户白名单 | MsgEvent |
| `AUTO_DISSOLVE_HOURS` | 工单解决后自动解散群的小时数 | CaseUpdate, CasePoller, GroupCleanup |

> 💡 **提示**: 
> - 将 `AUTO_DISSOLVE_HOURS` 设为你需要的小时数，例如 48 表示工单解决后 48 小时自动解散群。
> - `DATA_BUCKET` 只需要桶名（如 `larkcasebot-data-123456789012`），不是完整 ARN。

---

## Step 5: 创建 API Gateway

### 5.1 创建 REST API

**Console 方式：**

1. 进入 AWS Console → API Gateway
2. 点击 **Create API** → **REST API** → **Build**
3. 配置：
   - API name: `LarkCaseBot-API`
   - Endpoint Type: Regional
4. 创建资源：
   - 点击 **Create Resource**
   - Resource name: `messages`
   - Resource path: `/messages`
5. 创建方法：
   - 选择 `/messages` 资源
   - 点击 **Create Method** → **POST**
   - Integration type: **Lambda Function**
   - ⚠️ **Lambda Proxy Integration**: ✅ **必须勾选**（默认已勾选）
   - Lambda Function: `LarkCaseBot-MsgEvent`
   - 点击 **Create Method**
6. 配置限流（可选但推荐）：
   - 点击左侧 **Stages** → **prod**（部署后）
   - 在 **Stage Editor** 中找到 **Default Method Throttling**
   - Rate: `100` requests per second
   - Burst: `200` requests
7. 部署 API：
   - 点击 **Deploy API**
   - Stage name: `prod`

> ⚠️ **重要**: Lambda Proxy Integration 必须启用，否则 Lambda 无法正确接收 Lark webhook 请求。如果未勾选，会导致请求格式错误。

**CLI 方式：**

```bash
# 创建 API
API_ID=$(aws apigateway create-rest-api \
  --name LarkCaseBot-API \
  --endpoint-configuration types=REGIONAL \
  --query 'id' --output text)

# 获取根资源 ID
ROOT_ID=$(aws apigateway get-resources \
  --rest-api-id $API_ID \
  --query 'items[0].id' --output text)

# 创建 /messages 资源
RESOURCE_ID=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $ROOT_ID \
  --path-part messages \
  --query 'id' --output text)

# 创建 POST 方法
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $RESOURCE_ID \
  --http-method POST \
  --authorization-type NONE

# 配置 Lambda 集成
aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $RESOURCE_ID \
  --http-method POST \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:REGION:ACCOUNT:function:LarkCaseBot-MsgEvent/invocations

# 添加 Lambda 权限
aws lambda add-permission \
  --function-name LarkCaseBot-MsgEvent \
  --statement-id apigateway-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:us-east-1:${ACCOUNT_ID}:$API_ID/*/POST/messages"

# 部署 API
aws apigateway create-deployment \
  --rest-api-id $API_ID \
  --stage-name prod

# 配置限流（与 CDK 部署一致）
aws apigateway update-stage \
  --rest-api-id $API_ID \
  --stage-name prod \
  --patch-operations \
    op=replace,path=/throttling/rateLimit,value=100 \
    op=replace,path=/throttling/burstLimit,value=200

echo "Webhook URL: https://$API_ID.execute-api.us-east-1.amazonaws.com/prod/messages"
```

---

## Step 6: 创建 EventBridge 规则

### 6.1 工单更新规则

**Console 方式：**

1. 进入 AWS Console → Amazon EventBridge → Rules（确保在 **us-east-1** 区域）
2. 确保 Event bus 选择 **default**
3. 在页面上配置以下内容：

   **Event pattern 部分：**
   - 选择 **Custom pattern (JSON editor)**
   - 输入以下 pattern：
   ```json
   {
     "source": ["aws.support"],
     "detail-type": ["Support Case Update"]
   }
   ```

   **Target 部分：**
   - Target types: **AWS service**
   - Select a target: **Lambda function**
   - Function: `LarkCaseBot-CaseUpdate`

   **Permissions 部分：**
   - 选择 **Use execution role (recommended)**

4. 点击 **Create** 按钮，弹出 Configuration 对话框
5. 在对话框中填写：
   - **Rule name**: `LarkCaseBot-CaseUpdate`
   - **Description**: `Capture AWS Support case updates and push to Lark`（可选）
   - **Event bus name**: 保持 `default`
   - **Activation**: 保持 **Active** 勾选
6. 点击 **Create** 确认创建

> 💡 **注意**: 旧版 Console 使用多步骤向导（先填 Rule name），新版使用单页表单（最后填 Rule name）。

```json
> 💡 **注意**: 旧版 Console 使用多步骤向导（先填 Rule name），新版使用单页表单（最后填 Rule name）。

**CLI 方式：**

```bash
# 创建规则
aws events put-rule \
  --name LarkCaseBot-CaseUpdate \
  --event-pattern '{"source":["aws.support"],"detail-type":["Support Case Update"]}'

# 添加目标
aws events put-targets \
  --rule LarkCaseBot-CaseUpdate \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT:function:LarkCaseBot-CaseUpdate"

# 添加 Lambda 权限
aws lambda add-permission \
  --function-name LarkCaseBot-CaseUpdate \
  --statement-id eventbridge-invoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:REGION:ACCOUNT:rule/LarkCaseBot-CaseUpdate
```

### 6.2 定时轮询规则

**Console 方式：**

1. 进入 AWS Console → Amazon EventBridge → Rules（确保在 **us-east-1** 区域）
2. 在页面顶部提示区域，点击 **scheduled rule builder** 链接
3. **Step 1 - Define rule detail**：
   - **Name**: `LarkCaseBot-Poller`
   - **Description**: `Poll AWS Support case status every 5 minutes`（可选）
   - **Event bus**: 保持 `default`
   - 勾选 **Enable the rule on the selected event bus**
   - 点击 **Next**
4. **Step 2 - Define schedule**：
   - 选择 **A schedule that runs at a regular rate, such as every 10 minutes**
   - Rate expression: `5` **minutes**
   - 点击 **Next**
5. **Step 3 - Select target(s)**：
   - Target types: **AWS service**
   - Select a target: **Lambda function**
   - Function: `LarkCaseBot-CasePoller`
   - 点击 **Next**
6. **Step 4 - Configure tags**：跳过，点击 **Next**
7. **Step 5 - Review and create**：检查配置，点击 **Create rule**

**CLI 方式：**

```bash
# 创建规则（每 5 分钟）
aws events put-rule \
  --name LarkCaseBot-Poller \
  --schedule-expression "rate(5 minutes)" \
  --region us-east-1

# 添加目标
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws events put-targets \
  --rule LarkCaseBot-Poller \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:LarkCaseBot-CasePoller" \
  --region us-east-1

# 添加 Lambda 权限
aws lambda add-permission \
  --function-name LarkCaseBot-CasePoller \
  --statement-id eventbridge-schedule \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:${ACCOUNT_ID}:rule/LarkCaseBot-Poller
```

### 6.3 群自动解散规则

**Console 方式：**

1. 进入 AWS Console → Amazon EventBridge → Rules（确保在 **us-east-1** 区域）
2. 在页面顶部提示区域，点击 **scheduled rule builder** 链接
3. **Step 1 - Define rule detail**：
   - **Name**: `LarkCaseBot-GroupCleanup`
   - **Description**: `Auto-dissolve resolved case groups every hour`（可选）
   - **Event bus**: 保持 `default`
   - 勾选 **Enable the rule on the selected event bus**
   - 点击 **Next**
4. **Step 2 - Define schedule**：
   - 选择 **A schedule that runs at a regular rate, such as every 10 minutes**
   - Rate expression: `1` **hours**
   - 点击 **Next**
5. **Step 3 - Select target(s)**：
   - Target types: **AWS service**
   - Select a target: **Lambda function**
   - Function: `LarkCaseBot-GroupCleanup`
   - 点击 **Next**
6. **Step 4 - Configure tags**：跳过，点击 **Next**
7. **Step 5 - Review and create**：检查配置，点击 **Create rule**

**CLI 方式：**

```bash
# 创建规则（每小时）
aws events put-rule \
  --name LarkCaseBot-GroupCleanup \
  --schedule-expression "rate(1 hour)" \
  --region us-east-1

# 添加目标
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws events put-targets \
  --rule LarkCaseBot-GroupCleanup \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:LarkCaseBot-GroupCleanup" \
  --region us-east-1

# 添加 Lambda 权限
aws lambda add-permission \
  --function-name LarkCaseBot-GroupCleanup \
  --statement-id eventbridge-schedule \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:${ACCOUNT_ID}:rule/LarkCaseBot-GroupCleanup
```

---

### 多账户配置说明

> 📋 **适用场景**：
> | 部署场景 | 6.4 Support API 角色 | 6.5 跨账户 EventBridge |
> |---------|---------------------|----------------------|
> | 单账户部署 | ❌ 跳过 | ❌ 跳过 |
> | 多账户部署 | ✅ **必需** - 否则无法管理其他账户工单 | ⚡ **可选** - 启用实时推送（不配置则每 5 分钟轮询） |
>
> 💡 **单账户用户**：直接跳到 [Step 7: 初始化配置](#step-7-初始化配置)

---

### 6.4 在其他账户创建 Support API 角色（多账户必需）

> ⚠️ **多账户必需**: 此角色允许主账户的 Lambda 调用其他账户的 Support API，用于创建和管理工单。
>
> 💡 **提示**: 此角色的 ARN 将在 [Step 7.1 S3 配置](#71-初始化-s3-配置) 中使用。

在**每个需要支持的其他账户**中执行以下步骤：

**Console 方式：**

1. 登录到**其他账号**的 AWS Console
2. 进入 IAM → Roles → **Create role**
3. Step 1 - Select trusted entity:
   - Trusted entity type: **Custom trust policy**
   - 粘贴以下信任策略（将 `MAIN_ACCOUNT_ID` 替换为主账号 ID）：
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Principal": {
             "AWS": [
               "arn:aws:iam::MAIN_ACCOUNT_ID:role/LarkCaseBot-MsgEventRole",
               "arn:aws:iam::MAIN_ACCOUNT_ID:role/LarkCaseBot-CasePollerRole"
             ]
           },
           "Action": "sts:AssumeRole"
         }
       ]
     }
     ```
   - 点击 **Next**
4. Step 2 - Add permissions:
   - 搜索并选择 `AWSSupportAccess`
   - 点击 **Next**
5. Step 3 - Name, review, and create:
   - Role name: `LarkCaseBot-SupportApiRole`
   - Description: `Lark bot cross-account support access`
   - 点击 **Create role**

**CLI 方式：**

```bash
# 设置变量
MAIN_ACCOUNT_ID="111122223333"  # 替换为主账号 ID

# 创建信任策略
cat > /tmp/support-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws:iam::${MAIN_ACCOUNT_ID}:role/LarkCaseBot-MsgEventRole",
          "arn:aws:iam::${MAIN_ACCOUNT_ID}:role/LarkCaseBot-CasePollerRole"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# 创建角色
aws iam create-role \
  --role-name LarkCaseBot-SupportApiRole \
  --assume-role-policy-document file:///tmp/support-trust.json \
  --description "Lark bot cross-account support access"

# 附加 AWSSupportAccess 策略
aws iam attach-role-policy \
  --role-name LarkCaseBot-SupportApiRole \
  --policy-arn arn:aws:iam::aws:policy/AWSSupportAccess

# 清理
rm /tmp/support-trust.json

echo "✅ Support API 角色创建完成"
```

---

### 6.5 跨账户 EventBridge 配置（多账户可选）

> ⚡ **多账户可选**: 配置跨账户 EventBridge 转发，使其他账户的工单更新能**实时**推送到 Lark。
>
> 💡 **不配置的影响**: CasePoller 仍会每 5 分钟轮询所有账户的工单更新，功能正常但有延迟。

#### 6.5.1 在其他账户配置事件转发

> 在**每个需要支持的其他账户**中执行以下步骤：
>
> ⚠️ **重要**: 必须在 **us-east-1** 区域操作！AWS Support 事件仅在 us-east-1 生成。

**Console 方式：**

**Step A: 创建 IAM 角色**

1. 进入 AWS Console → IAM → Roles → **Create role**
2. Step 1 - Select trusted entity:
   - Trusted entity type: **Custom trust policy**
   - 粘贴以下信任策略：
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Principal": {"Service": "events.amazonaws.com"},
           "Action": "sts:AssumeRole"
         }
       ]
     }
     ```
   - 点击 **Next**
3. Step 2 - Add permissions: 点击 **Next**（稍后添加内联策略）
4. Step 3 - Name, review, and create:
   - Role name: `LarkCaseBot-EventBridgeRole`
   - 点击 **Create role**
5. 找到刚创建的角色，点击进入
6. 在 Permissions 标签页，点击 **Add permissions** → **Create inline policy**
7. 选择 **JSON** 标签，粘贴（将 `MAIN_ACCOUNT_ID` 替换为主账户 ID）：
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": "events:PutEvents",
         "Resource": "arn:aws:events:us-east-1:MAIN_ACCOUNT_ID:event-bus/default"
       }
     ]
   }
   ```
8. 点击 **Next**
9. Policy name: `ForwardToMainAccount`
10. 点击 **Create policy**

**Step B: 创建 EventBridge 规则**

1. 进入 Amazon EventBridge → Rules
2. 确保 Event bus 选择 `default`
3. 点击 **Create rule**
4. 在主页面配置：

   **Event pattern 部分：**
   - Event source: **AWS events or EventBridge partner events**
   - Creation method: **Use pattern form**
   - Event source: **AWS services**
   - AWS service: **Support**
   - Event type: **Support Case Update**

   **Target 部分：**
   - Target type: **EventBridge event bus**
   - Target: **Event bus in a different account or Region**
   - Event bus as target: `arn:aws:events:us-east-1:MAIN_ACCOUNT_ID:event-bus/default`（替换 MAIN_ACCOUNT_ID）
   - Execution role: **Use existing role** → `LarkCaseBot-EventBridgeRole`

5. 点击 **Create** 按钮，弹出 Configuration 对话框
6. 在对话框中填写：
   - **Rule name**: `LarkCaseBot-ForwardSupportEvents`
   - **Description**: `Forward Support case updates to main account`（可选）
   - **Event bus name**: 保持 `default`
   - **Activation**: 保持 **Active** 勾选
7. 点击 **Create** 确认创建

**CLI 方式：**

```bash
# 设置变量（替换为实际值）
MAIN_ACCOUNT_ID="111122223333"  # 主账户 ID
THIS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 1. 创建 EventBridge IAM 角色
cat > /tmp/eventbridge-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "events.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name LarkCaseBot-EventBridgeRole \
  --assume-role-policy-document file:///tmp/eventbridge-trust.json

# 2. 添加转发权限策略
cat > /tmp/eventbridge-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "events:PutEvents",
      "Resource": "arn:aws:events:us-east-1:${MAIN_ACCOUNT_ID}:event-bus/default"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name LarkCaseBot-EventBridgeRole \
  --policy-name ForwardToMainAccount \
  --policy-document file:///tmp/eventbridge-policy.json

# 3. 等待角色生效
sleep 10

# 4. 创建 EventBridge 转发规则
aws events put-rule \
  --name LarkCaseBot-ForwardSupportEvents \
  --event-pattern '{"source":["aws.support"],"detail-type":["Support Case Update"]}' \
  --state ENABLED \
  --region us-east-1

# 5. 添加转发目标
aws events put-targets \
  --rule LarkCaseBot-ForwardSupportEvents \
  --targets "[{
    \"Id\": \"1\",
    \"Arn\": \"arn:aws:events:us-east-1:${MAIN_ACCOUNT_ID}:event-bus/default\",
    \"RoleArn\": \"arn:aws:iam::${THIS_ACCOUNT_ID}:role/LarkCaseBot-EventBridgeRole\"
  }]" \
  --region us-east-1

# 清理临时文件
rm /tmp/eventbridge-trust.json /tmp/eventbridge-policy.json

echo "✅ EventBridge 转发配置完成"
```

#### 6.5.2 在主账户配置 default Event Bus 权限

> ⚠️ **注意**: 此步骤需要在其他账户创建 `LarkCaseBot-EventBridgeRole` 角色（6.5.1 Step A）**之后**执行，因为策略中引用的角色必须已存在。

**Console 方式：**

1. 进入 AWS Console → Amazon EventBridge → Event buses
2. 点击 **default** event bus
3. 点击 **Permissions** 标签页
4. 在 Resource-based policy 部分，点击 **Manage permissions**
5. 在 Edit event bus 页面的 **Resource-based policy** 文本框中，粘贴以下策略（将 `OTHER_ACCOUNT_ID` 和 `MAIN_ACCOUNT_ID` 替换为实际账户 ID）：
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "AllowCrossAccountPutEvents",
         "Effect": "Allow",
         "Principal": {
           "AWS": [
             "arn:aws:iam::OTHER_ACCOUNT_ID:role/LarkCaseBot-EventBridgeRole"
           ]
         },
         "Action": "events:PutEvents",
         "Resource": "arn:aws:events:us-east-1:MAIN_ACCOUNT_ID:event-bus/default"
       }
     ]
   }
   ```
   > 💡 多个账户时，在 Principal.AWS 数组中添加多个角色 ARN。
6. 点击 **Update**

**CLI 方式：**

```bash
# 设置变量
MAIN_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
OTHER_ACCOUNT_ID="111122223333"  # 替换为其他账户 ID

# 允许其他账户的 EventBridge 角色发送事件到 default bus
aws events put-permission \
  --event-bus-name default \
  --action events:PutEvents \
  --principal "arn:aws:iam::${OTHER_ACCOUNT_ID}:role/LarkCaseBot-EventBridgeRole" \
  --statement-id "AllowAccount${OTHER_ACCOUNT_ID}" \
  --region us-east-1
```

> 💡 如需添加多个账户，重复执行 `put-permission` 命令，每次使用不同的 `statement-id`。

#### 6.5.3 验证跨账户配置

**Console 方式：**

1. 在其他账户：
   - EventBridge → Rules → 确认 `LarkCaseBot-ForwardSupportEvents` 状态为 Enabled
   - 点击规则查看 Targets，确认目标是主账户的 default Event Bus
2. 在主账户：
   - EventBridge → Rules（default bus）→ 确认 `LarkCaseBot-CaseUpdate` 存在且目标是 Lambda

**CLI 方式：**

```bash
# 在其他账户检查规则
aws events describe-rule \
  --name LarkCaseBot-ForwardSupportEvents \
  --region us-east-1

# 检查目标
aws events list-targets-by-rule \
  --rule LarkCaseBot-ForwardSupportEvents \
  --region us-east-1

# 检查 IAM 角色
aws iam get-role --role-name LarkCaseBot-EventBridgeRole
```

---

## Step 7: 初始化配置

### 7.1 初始化 S3 配置

> 💡 **多账户用户**: 如需支持多个账户，请先完成 [6.4 创建 Support API 角色](#64-在其他账户创建-support-api-角色多账户必需)，然后在下方配置中添加其他账户的 `role_arn`。

在 S3 存储桶中创建配置文件 `config/LarkBotProfile-0.json`：

```json
{
  "cfg_key": "LarkBotProfile-0",
  "accounts": {
    "0": {
      "role_arn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/LarkCaseBot-SupportApiRole",
      "account_name": "主账号"
    }
  },
  "user_whitelist": {}
}
```

**CLI 方式：**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET_NAME="larkcasebot-data-${ACCOUNT_ID}"

# 创建配置文件
cat > /tmp/config.json <<EOF
{
  "cfg_key": "LarkBotProfile-0",
  "accounts": {
    "0": {
      "role_arn": "arn:aws:iam::${ACCOUNT_ID}:role/LarkCaseBot-SupportApiRole",
      "account_name": "主账号"
    }
  },
  "user_whitelist": {}
}
EOF

# 上传到 S3
aws s3 cp /tmp/config.json s3://${BUCKET_NAME}/config/LarkBotProfile-0.json

# 清理
rm /tmp/config.json
```

---

## Step 8: 配置 Lark 应用

参考 [LARK-SETUP.md](LARK-SETUP.md) 完成 Lark 应用配置：

1. 创建 Lark 应用
2. 配置权限（18 个权限）
3. 配置事件订阅
4. 设置 Webhook URL（Step 5 获取的 URL）
5. 发布应用

---

## 验证部署

### 测试 Webhook

```bash
curl -X POST https://YOUR_API_ID.execute-api.REGION.amazonaws.com/prod/messages \
  -H "Content-Type: application/json" \
  -d '{"type":"url_verification","challenge":"test123"}'
```

应返回：

```json
{"challenge": "test123"}
```

### 测试 Lark 消息

在 Lark 中向机器人发送 `帮助`，应收到帮助信息。

### 检查日志

```bash
aws logs tail /aws/lambda/LarkCaseBot-MsgEvent --follow
```

---

## 添加跨账号支持

如需支持多个 AWS 账号，参考 [manual-account-setup.md](manual-account-setup.md)。

---

## 清理资源

如需删除所有资源：

```bash
# 删除 Lambda 函数
aws lambda delete-function --function-name LarkCaseBot-MsgEvent
aws lambda delete-function --function-name LarkCaseBot-CaseUpdate
aws lambda delete-function --function-name LarkCaseBot-CasePoller
aws lambda delete-function --function-name LarkCaseBot-GroupCleanup

# 删除 EventBridge 规则
aws events remove-targets --rule LarkCaseBot-CaseUpdate --ids 1
aws events delete-rule --name LarkCaseBot-CaseUpdate
aws events remove-targets --rule LarkCaseBot-Poller --ids 1
aws events delete-rule --name LarkCaseBot-Poller
aws events remove-targets --rule LarkCaseBot-GroupCleanup --ids 1
aws events delete-rule --name LarkCaseBot-GroupCleanup

# 删除 API Gateway
aws apigateway delete-rest-api --rest-api-id YOUR_API_ID

# 删除 IAM 角色（需先删除策略）
aws iam delete-role-policy --role-name LarkCaseBot-MsgEventRole --policy-name MsgEventPolicy
aws iam detach-role-policy --role-name LarkCaseBot-MsgEventRole --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name LarkCaseBot-MsgEventRole
# ... 重复删除其他角色

# 删除 S3 存储桶（需先清空）
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws s3 rm s3://larkcasebot-data-${ACCOUNT_ID} --recursive
aws s3api delete-bucket --bucket larkcasebot-data-${ACCOUNT_ID}

# 删除 Secrets Manager
aws secretsmanager delete-secret --secret-id LarkCaseBot-app-id --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id LarkCaseBot-app-secret --force-delete-without-recovery
```

---

**最后更新**: 2025-12-16
