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
                    ┌────────────────────────────┼────────────────────────────┐
                    │                            │                            │
              ┌─────┴─────┐              ┌───────┴───────┐            ┌───────┴───────┐
              │EventBridge│──────────────│CaseUpdateLambda│            │CasePollerLambda│
              │  (Rule)   │              └───────────────┘            └───────────────┘
              └───────────┘
```

### 资源清单

| 资源类型 | 名称 | 用途 |
|---------|------|------|
| Secrets Manager | LarkCaseBot-app-id | 存储 Lark App ID |
| Secrets Manager | LarkCaseBot-app-secret | 存储 Lark App Secret |
| Secrets Manager | LarkCaseBot-encrypt-key | 存储 Lark Encrypt Key（可选） |
| Secrets Manager | LarkCaseBot-verification-token | 存储 Lark Verification Token |
| S3 | LarkCaseBot-DataBucket | Bot 配置和工单数据存储 |
| IAM Role | LarkCaseBot-MsgEventRole | MsgEventLambda 执行角色 |
| IAM Role | LarkCaseBot-CaseUpdateRole | CaseUpdateLambda 执行角色 |
| IAM Role | LarkCaseBot-CasePollerRole | CasePollerLambda 执行角色 |
| IAM Role | LarkCaseBot-GroupCleanupRole | GroupCleanupLambda 执行角色 |
| IAM Role | AWSSupportAccessRole | AWS Support API 访问 |
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

1. 进入 AWS Console → Secrets Manager
2. 点击 **Store a new secret**
3. 选择 **Other type of secret**
4. 添加键值对：
   - Key: `app_id`
   - Value: `cli_xxxxxxxxxx`（你的 Lark App ID）
5. Secret name: `LarkCaseBot-app-id`
6. 完成创建

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
2. 添加键值对：
   - Key: `encrypt_key`
   - Value: `xxxxxxxxxxxxxxxx`（从 Lark 事件订阅页面获取，留空表示不使用加密）
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
2. 添加键值对：
   - Key: `verification_token`
   - Value: `xxxxxxxxxxxxxxxx`（从 Lark 事件订阅页面获取）
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

1. 进入 AWS Console → S3
2. 点击 **Create bucket**
3. 配置：
   - Bucket name: `larkcasebot-data-{account-id}` (需要全局唯一)
   - Region: `us-east-1`
   - Block all public access: 启用
   - Bucket Versioning: 启用
   - Default encryption: SSE-S3
4. 点击 **Create bucket**

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

### 3.1 创建 AWSSupportAccessRole

这是访问 AWS Support API 的角色。

**信任策略 (trust-policy.json)：**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::LAMBDA_ACCOUNT_ID:role/LarkCaseBotStack-MsgEventRole*"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

> **跨账号说明**: 
> - `LAMBDA_ACCOUNT_ID` 是部署 LarkCaseBot Lambda 的账号 ID
> - `YOUR_ACCOUNT_ID` (当前账号) 是需要访问 Support API 的目标账号
> - 使用具体的 Lambda 执行角色 ARN 而非 `:root`，遵循最小权限原则

**CLI 方式：**

```bash
# 创建角色
aws iam create-role \
  --role-name AWSSupportAccessRole \
  --assume-role-policy-document file://trust-policy.json

# 附加 AWSSupportAccess 策略
aws iam attach-role-policy \
  --role-name AWSSupportAccessRole \
  --policy-arn arn:aws:iam::aws:policy/AWSSupportAccess
```

### 3.2 创建 MsgEventRole

**信任策略：**

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

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SecretsManagerAccess",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": [
        "arn:aws:secretsmanager:*:*:secret:LarkCaseBot-app-id*",
        "arn:aws:secretsmanager:*:*:secret:LarkCaseBot-app-secret*",
        "arn:aws:secretsmanager:*:*:secret:LarkCaseBot-encrypt-key*",
        "arn:aws:secretsmanager:*:*:secret:LarkCaseBot-verification-token*"
      ]
    },
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::larkcasebot-data-*",
        "arn:aws:s3:::larkcasebot-data-*/*"
      ]
    },
    {
      "Sid": "AssumeRoleForSupport",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": [
        "arn:aws:iam::*:role/AWSSupportAccessRole",
        "arn:aws:iam::*:role/LarkSupportCaseApiAll*"
      ]
    },
    {
      "Sid": "LambdaSelfInvoke",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:*:*:function:LarkCaseBot-MsgEvent"
    }
  ]
}
```

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

### 3.3 创建 CaseUpdateRole

与 MsgEventRole 类似，但不需要 LambdaSelfInvoke 权限。

```bash
aws iam create-role \
  --role-name LarkCaseBot-CaseUpdateRole \
  --assume-role-policy-document file://lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name LarkCaseBot-CaseUpdateRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### 3.4 创建 CasePollerRole

与 CaseUpdateRole 类似，需要读取 Config 表的权限。

```bash
aws iam create-role \
  --role-name LarkCaseBot-CasePollerRole \
  --assume-role-policy-document file://lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name LarkCaseBot-CasePollerRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

---

## Step 4: 创建 Lambda 函数

### 4.1 准备代码包

```bash
cd lambda
zip -r ../lambda-package.zip .
cd ..
```

### 4.2 创建 MsgEventLambda

**Console 方式：**

1. 进入 AWS Console → Lambda
2. 点击 **Create function**
3. 配置：
   - Function name: `LarkCaseBot-MsgEvent`
   - Runtime: Python 3.12
   - Architecture: x86_64
   - Execution role: Use existing role → `LarkCaseBot-MsgEventRole`
4. 上传代码包
5. 配置：
   - Handler: `msg_event_handler.lambda_handler`
   - Timeout: 60 seconds
   - Memory: 1024 MB
6. 添加环境变量：

| Key | Value |
|-----|-------|
| APP_ID_ARN | `arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-id-XXXXX` |
| APP_SECRET_ARN | `arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-secret-XXXXX` |
| ENCRYPT_KEY_ARN | `arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-encrypt-key-XXXXX` |
| VERIFICATION_TOKEN_ARN | `arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-verification-token-XXXXX` |
| BOT_CONFIG_TABLE | `LarkCaseBot-Config` |
| CASE_TABLE | `LarkCaseBot-Cases` |
| CFG_KEY | `LarkBotProfile-0` |
| CASE_LANGUAGE | `zh` |
| USER_WHITELIST | `false` |

**CLI 方式：**

```bash
aws lambda create-function \
  --function-name LarkCaseBot-MsgEvent \
  --runtime python3.12 \
  --handler msg_event_handler.lambda_handler \
  --role arn:aws:iam::ACCOUNT_ID:role/LarkCaseBot-MsgEventRole \
  --zip-file fileb://lambda-package.zip \
  --timeout 60 \
  --memory-size 1024 \
  --environment "Variables={
    APP_ID_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-id-XXXXX,
    APP_SECRET_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-secret-XXXXX,
    ENCRYPT_KEY_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-encrypt-key-XXXXX,
    VERIFICATION_TOKEN_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-verification-token-XXXXX,
    BOT_CONFIG_TABLE=LarkCaseBot-Config,
    CASE_TABLE=LarkCaseBot-Cases,
    CFG_KEY=LarkBotProfile-0,
    CASE_LANGUAGE=zh,
    USER_WHITELIST=false
  }"
```

### 4.3 创建 CaseUpdateLambda

```bash
aws lambda create-function \
  --function-name LarkCaseBot-CaseUpdate \
  --runtime python3.12 \
  --handler case_update_handler.lambda_handler \
  --role arn:aws:iam::ACCOUNT_ID:role/LarkCaseBot-CaseUpdateRole \
  --zip-file fileb://lambda-package.zip \
  --timeout 30 \
  --memory-size 256 \
  --environment "Variables={
    APP_ID_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-id-XXXXX,
    APP_SECRET_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-secret-XXXXX,
    CASE_TABLE=LarkCaseBot-Cases
  }"
```

### 4.4 创建 CasePollerLambda

```bash
aws lambda create-function \
  --function-name LarkCaseBot-CasePoller \
  --runtime python3.12 \
  --handler case_poller.lambda_handler \
  --role arn:aws:iam::ACCOUNT_ID:role/LarkCaseBot-CasePollerRole \
  --zip-file fileb://lambda-package.zip \
  --timeout 300 \
  --memory-size 512 \
  --environment "Variables={
    APP_ID_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-id-XXXXX,
    APP_SECRET_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-secret-XXXXX,
    CASE_TABLE=LarkCaseBot-Cases,
    CONFIG_TABLE=LarkCaseBot-Config
  }"
```

### 4.5 创建 GroupCleanupLambda（自动解散群）

此 Lambda 每小时运行一次，自动解散已解决超过指定时间的工单群。

```bash
aws lambda create-function \
  --function-name LarkCaseBot-GroupCleanup \
  --runtime python3.12 \
  --handler group_cleanup.lambda_handler \
  --role arn:aws:iam::ACCOUNT_ID:role/LarkCaseBot-CasePollerRole \
  --zip-file fileb://lambda-package.zip \
  --timeout 300 \
  --memory-size 256 \
  --environment "Variables={
    APP_ID_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-id-XXXXX,
    APP_SECRET_ARN=arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-secret-XXXXX,
    DATA_BUCKET=larkcasebot-data-ACCOUNT_ID,
    AUTO_DISSOLVE_HOURS=72
  }"
```

**环境变量说明：**

| 变量 | 说明 | 默认值 |
|-----|------|-------|
| `AUTO_DISSOLVE_HOURS` | 工单解决后多少小时自动解散群 | 72 |

> 💡 **提示**: 将 `AUTO_DISSOLVE_HOURS` 设为你需要的小时数，例如 48 表示工单解决后 48 小时自动解散群。

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
   - Integration type: Lambda Function
   - Lambda Function: `LarkCaseBot-MsgEvent`
6. 部署 API：
   - 点击 **Deploy API**
   - Stage name: `prod`

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
  --source-arn "arn:aws:execute-api:REGION:ACCOUNT:$API_ID/*/POST/messages"

# 部署 API
aws apigateway create-deployment \
  --rest-api-id $API_ID \
  --stage-name prod

echo "Webhook URL: https://$API_ID.execute-api.REGION.amazonaws.com/prod/messages"
```

---

## Step 6: 创建 EventBridge 规则

### 6.1 工单更新规则

**Console 方式：**

1. 进入 AWS Console → EventBridge → Rules
2. 点击 **Create rule**
3. 配置：
   - Name: `LarkCaseBot-CaseUpdate`
   - Event bus: default
   - Rule type: Rule with an event pattern
4. Event pattern:

```json
{
  "source": ["aws.support"],
  "detail-type": ["Support Case Update"]
}
```

5. Target: Lambda function → `LarkCaseBot-CaseUpdate`

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

```bash
# 创建规则（每 10 分钟）
aws events put-rule \
  --name LarkCaseBot-Poller \
  --schedule-expression "rate(10 minutes)"

# 添加目标
aws events put-targets \
  --rule LarkCaseBot-Poller \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT:function:LarkCaseBot-CasePoller"

# 添加 Lambda 权限
aws lambda add-permission \
  --function-name LarkCaseBot-CasePoller \
  --statement-id eventbridge-schedule \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:REGION:ACCOUNT:rule/LarkCaseBot-Poller
```

### 6.3 群自动解散规则

```bash
# 创建规则（每小时）
aws events put-rule \
  --name LarkCaseBot-GroupCleanup \
  --schedule-expression "rate(1 hour)"

# 添加目标
aws events put-targets \
  --rule LarkCaseBot-GroupCleanup \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT:function:LarkCaseBot-GroupCleanup"

# 添加 Lambda 权限
aws lambda add-permission \
  --function-name LarkCaseBot-GroupCleanup \
  --statement-id eventbridge-schedule \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:REGION:ACCOUNT:rule/LarkCaseBot-GroupCleanup
```

---

## Step 7: 初始化配置

### 7.1 初始化 S3 配置

在 S3 存储桶中创建配置文件 `config/LarkBotProfile-0.json`：

```json
{
  "cfg_key": "LarkBotProfile-0",
  "accounts": {
    "0": {
      "role_arn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/AWSSupportAccessRole",
      "account_name": "主账号"
    }
  },
  "user_whitelist": {},
  "help_text": "发送 '开工单' 创建新工单\n发送 '历史' 查看工单历史"
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
      "role_arn": "arn:aws:iam::${ACCOUNT_ID}:role/AWSSupportAccessRole",
      "account_name": "主账号"
    }
  },
  "user_whitelist": {},
  "help_text": "发送 '开工单' 创建新工单\n发送 '历史' 查看工单历史"
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
aws secretsmanager delete-secret --secret-id LarkCaseBot-encrypt-key --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id LarkCaseBot-verification-token --force-delete-without-recovery
```

---

**最后更新**: 2025-12-03
