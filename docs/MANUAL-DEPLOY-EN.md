# Manual Deployment Guide (Without CDK) - S3 Storage Version

This document describes how to manually create all resources in AWS Console without using CDK.

> ⚠️ **Important**: All resources must be created in the `us-east-1` region.
>
> - AWS Support API is only available in us-east-1
> - AWS Support EventBridge events are only sent to us-east-1
> - Creating resources in other regions will cause functionality to fail

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Step 1: Create Secrets Manager](#step-1-create-secrets-manager)
- [Step 2: Create S3 Bucket](#step-2-create-s3-bucket)
- [Step 3: Create IAM Roles](#step-3-create-iam-roles)
- [Step 4: Create Lambda Functions](#step-4-create-lambda-functions)
- [Step 5: Create API Gateway](#step-5-create-api-gateway)
- [Step 6: Create EventBridge Rules](#step-6-create-eventbridge-rules)
- [Step 7: Initialize Configuration](#step-7-initialize-configuration)
- [Step 8: Configure Lark App](#step-8-configure-lark-app)
- [Verify Deployment](#verify-deployment)

---

## Architecture Overview

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

### Resource List

| Resource Type | Name | Purpose |
|--------------|------|---------|
| Secrets Manager | LarkCaseBot-app-id | Store Lark App ID |
| Secrets Manager | LarkCaseBot-app-secret | Store Lark App Secret |
| S3 | LarkCaseBot-DataBucket | Bot config and case data storage |
| IAM Role | LarkCaseBot-MsgEventRole | MsgEventLambda execution role |
| IAM Role | LarkCaseBot-CaseUpdateRole | CaseUpdateLambda execution role |
| IAM Role | LarkCaseBot-CasePollerRole | CasePollerLambda execution role |
| IAM Role | LarkCaseBot-GroupCleanupRole | GroupCleanupLambda execution role |
| IAM Role | AWSSupportAccessRole | AWS Support API access |
| Lambda | LarkCaseBot-MsgEvent | Handle Lark messages |
| Lambda | LarkCaseBot-CaseUpdate | Handle case update events |
| Lambda | LarkCaseBot-CasePoller | Periodically poll case status |
| Lambda | LarkCaseBot-GroupCleanup | Auto-dissolve resolved case groups |
| API Gateway | LarkCaseBot-API | Webhook endpoint |
| EventBridge Rule | LarkCaseBot-CaseUpdate | Case update events |
| EventBridge Rule | LarkCaseBot-Poller | Scheduled polling |
| EventBridge Rule | LarkCaseBot-GroupCleanup | Hourly check for groups to dissolve |

---

## Prerequisites

- AWS account (with Business or Enterprise Support plan)
- Lark Open Platform account
- AWS CLI configured (optional, for CLI commands)

---

## Step 1: Create Secrets Manager

### 1.1 Create App ID Secret

**Console Method:**

1. Go to AWS Console → Secrets Manager
2. Click **Store a new secret**
3. Select **Other type of secret**
4. Add key-value pair:
   - Key: `app_id`
   - Value: `cli_xxxxxxxxxx` (your Lark App ID)
5. Secret name: `LarkCaseBot-app-id`
6. Complete creation

**CLI Method:**

```bash
aws secretsmanager create-secret \
  --name LarkCaseBot-app-id \
  --secret-string '{"app_id":"cli_xxxxxxxxxx"}'
```

### 1.2 Create App Secret Secret

**Console Method:**

1. Repeat the above steps
2. Add key-value pair:
   - Key: `app_secret`
   - Value: `xxxxxxxxxxxxxxxx` (your Lark App Secret)
3. Secret name: `LarkCaseBot-app-secret`

**CLI Method:**

```bash
aws secretsmanager create-secret \
  --name LarkCaseBot-app-secret \
  --secret-string '{"app_secret":"xxxxxxxxxxxxxxxx"}'
```

---

## Step 2: Create S3 Bucket

### 2.1 Create Data Bucket

**Console Method:**

1. Go to AWS Console → S3
2. Click **Create bucket**
3. Configure:
   - Bucket name: `larkcasebot-data-{account-id}` (must be globally unique)
   - Region: `us-east-1`
   - Block all public access: Enabled
   - Bucket Versioning: Enabled
   - Default encryption: SSE-S3
4. Click **Create bucket**

**CLI Method:**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET_NAME="larkcasebot-data-${ACCOUNT_ID}"

# Create bucket
aws s3api create-bucket \
  --bucket ${BUCKET_NAME} \
  --region us-east-1

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket ${BUCKET_NAME} \
  --versioning-configuration Status=Enabled

# Enable encryption
aws s3api put-bucket-encryption \
  --bucket ${BUCKET_NAME} \
  --server-side-encryption-configuration '{
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
  }'

# Block public access
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

### 2.2 S3 Storage Structure

The bucket uses the following directory structure:

```
larkcasebot-data-{account-id}/
├── config/
│   └── LarkBotProfile-0.json    # Bot configuration
├── cases/
│   └── {case_id}.json           # Individual case data
└── indexes/
    ├── chat_id/
    │   └── {chat_id}.json       # Chat ID index
    └── user_id/
        └── {user_id}.json       # User ID index
```

---

## Step 3: Create IAM Roles

### 3.1 Create AWSSupportAccessRole

This role is for accessing the AWS Support API.

**Trust Policy (trust-policy.json):**

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

> **Cross-Account Note**: 
> - `LAMBDA_ACCOUNT_ID` is the account ID where LarkCaseBot Lambda is deployed
> - `YOUR_ACCOUNT_ID` (current account) is the target account that needs Support API access
> - Use specific Lambda execution role ARN instead of `:root` to follow least privilege principle

**CLI Method:**

```bash
# Create role
aws iam create-role \
  --role-name AWSSupportAccessRole \
  --assume-role-policy-document file://trust-policy.json

# Attach AWSSupportAccess policy
aws iam attach-role-policy \
  --role-name AWSSupportAccessRole \
  --policy-arn arn:aws:iam::aws:policy/AWSSupportAccess
```

### 3.2 Create MsgEventRole

**Trust Policy:**

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

**Inline Policy (msg-event-policy.json):**

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
        "arn:aws:secretsmanager:*:*:secret:LarkCaseBot-app-secret*"
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

**CLI Method:**

```bash
# Create role
aws iam create-role \
  --role-name LarkCaseBot-MsgEventRole \
  --assume-role-policy-document file://lambda-trust-policy.json

# Attach basic execution policy
aws iam attach-role-policy \
  --role-name LarkCaseBot-MsgEventRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Create and attach inline policy
aws iam put-role-policy \
  --role-name LarkCaseBot-MsgEventRole \
  --policy-name MsgEventPolicy \
  --policy-document file://msg-event-policy.json
```

### 3.3 Create CaseUpdateRole

Similar to MsgEventRole, but without LambdaSelfInvoke permission.

```bash
aws iam create-role \
  --role-name LarkCaseBot-CaseUpdateRole \
  --assume-role-policy-document file://lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name LarkCaseBot-CaseUpdateRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### 3.4 Create CasePollerRole

Similar to CaseUpdateRole, needs permission to read Config table.

```bash
aws iam create-role \
  --role-name LarkCaseBot-CasePollerRole \
  --assume-role-policy-document file://lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name LarkCaseBot-CasePollerRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

---

## Step 4: Create Lambda Functions

### 4.1 Prepare Code Package

```bash
cd lambda
zip -r ../lambda-package.zip .
cd ..
```

### 4.2 Create MsgEventLambda

**Console Method:**

1. Go to AWS Console → Lambda
2. Click **Create function**
3. Configure:
   - Function name: `LarkCaseBot-MsgEvent`
   - Runtime: Python 3.12
   - Architecture: x86_64
   - Execution role: Use existing role → `LarkCaseBot-MsgEventRole`
4. Upload code package
5. Configure:
   - Handler: `msg_event_handler.lambda_handler`
   - Timeout: 60 seconds
   - Memory: 1024 MB
6. Add environment variables:

| Key | Value |
|-----|-------|
| APP_ID_ARN | `arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-id-XXXXX` |
| APP_SECRET_ARN | `arn:aws:secretsmanager:REGION:ACCOUNT:secret:LarkCaseBot-app-secret-XXXXX` |
| BOT_CONFIG_TABLE | `LarkCaseBot-Config` |
| CASE_TABLE | `LarkCaseBot-Cases` |
| CFG_KEY | `LarkBotProfile-0` |
| CASE_LANGUAGE | `zh` |
| USER_WHITELIST | `false` |

**CLI Method:**

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
    BOT_CONFIG_TABLE=LarkCaseBot-Config,
    CASE_TABLE=LarkCaseBot-Cases,
    CFG_KEY=LarkBotProfile-0,
    CASE_LANGUAGE=zh,
    USER_WHITELIST=false
  }"
```

### 4.3 Create CaseUpdateLambda

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

### 4.4 Create CasePollerLambda

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

### 4.5 Create GroupCleanupLambda (Auto-Dissolve Groups)

This Lambda runs hourly to automatically dissolve case groups that have been resolved for a specified time.

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

**Environment Variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTO_DISSOLVE_HOURS` | Hours after case resolution to auto-dissolve group | 72 |

> 💡 **Tip**: Set `AUTO_DISSOLVE_HOURS` to your desired value, e.g., 48 means auto-dissolve 48 hours after case resolution.

---

## Step 5: Create API Gateway

### 5.1 Create REST API

**Console Method:**

1. Go to AWS Console → API Gateway
2. Click **Create API** → **REST API** → **Build**
3. Configure:
   - API name: `LarkCaseBot-API`
   - Endpoint Type: Regional
4. Create resource:
   - Click **Create Resource**
   - Resource name: `messages`
   - Resource path: `/messages`
5. Create method:
   - Select `/messages` resource
   - Click **Create Method** → **POST**
   - Integration type: Lambda Function
   - Lambda Function: `LarkCaseBot-MsgEvent`
6. Deploy API:
   - Click **Deploy API**
   - Stage name: `prod`

**CLI Method:**

```bash
# Create API
API_ID=$(aws apigateway create-rest-api \
  --name LarkCaseBot-API \
  --endpoint-configuration types=REGIONAL \
  --query 'id' --output text)

# Get root resource ID
ROOT_ID=$(aws apigateway get-resources \
  --rest-api-id $API_ID \
  --query 'items[0].id' --output text)

# Create /messages resource
RESOURCE_ID=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $ROOT_ID \
  --path-part messages \
  --query 'id' --output text)

# Create POST method
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $RESOURCE_ID \
  --http-method POST \
  --authorization-type NONE

# Configure Lambda integration
aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $RESOURCE_ID \
  --http-method POST \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri arn:aws:apigateway:REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:REGION:ACCOUNT:function:LarkCaseBot-MsgEvent/invocations

# Add Lambda permission
aws lambda add-permission \
  --function-name LarkCaseBot-MsgEvent \
  --statement-id apigateway-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:REGION:ACCOUNT:$API_ID/*/POST/messages"

# Deploy API
aws apigateway create-deployment \
  --rest-api-id $API_ID \
  --stage-name prod

echo "Webhook URL: https://$API_ID.execute-api.REGION.amazonaws.com/prod/messages"
```

---

## Step 6: Create EventBridge Rules

### 6.1 Case Update Rule

**Console Method:**

1. Go to AWS Console → EventBridge → Rules
2. Click **Create rule**
3. Configure:
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

**CLI Method:**

```bash
# Create rule
aws events put-rule \
  --name LarkCaseBot-CaseUpdate \
  --event-pattern '{"source":["aws.support"],"detail-type":["Support Case Update"]}'

# Add target
aws events put-targets \
  --rule LarkCaseBot-CaseUpdate \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT:function:LarkCaseBot-CaseUpdate"

# Add Lambda permission
aws lambda add-permission \
  --function-name LarkCaseBot-CaseUpdate \
  --statement-id eventbridge-invoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:REGION:ACCOUNT:rule/LarkCaseBot-CaseUpdate
```

### 6.2 Scheduled Polling Rule

```bash
# Create rule (every 10 minutes)
aws events put-rule \
  --name LarkCaseBot-Poller \
  --schedule-expression "rate(10 minutes)"

# Add target
aws events put-targets \
  --rule LarkCaseBot-Poller \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT:function:LarkCaseBot-CasePoller"

# Add Lambda permission
aws lambda add-permission \
  --function-name LarkCaseBot-CasePoller \
  --statement-id eventbridge-schedule \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:REGION:ACCOUNT:rule/LarkCaseBot-Poller
```

### 6.3 Group Auto-Dissolve Rule

```bash
# Create rule (hourly)
aws events put-rule \
  --name LarkCaseBot-GroupCleanup \
  --schedule-expression "rate(1 hour)"

# Add target
aws events put-targets \
  --rule LarkCaseBot-GroupCleanup \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT:function:LarkCaseBot-GroupCleanup"

# Add Lambda permission
aws lambda add-permission \
  --function-name LarkCaseBot-GroupCleanup \
  --statement-id eventbridge-schedule \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:REGION:ACCOUNT:rule/LarkCaseBot-GroupCleanup
```

---

## Step 7: Initialize Configuration

### 7.1 Initialize S3 Configuration

Create configuration file `config/LarkBotProfile-0.json` in the S3 bucket:

```json
{
  "cfg_key": "LarkBotProfile-0",
  "accounts": {
    "0": {
      "role_arn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/AWSSupportAccessRole",
      "account_name": "Main Account"
    }
  },
  "user_whitelist": {},
  "help_text": "Send 'create case' to create a new case\nSend 'history' to view case history"
}
```

**CLI Method:**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET_NAME="larkcasebot-data-${ACCOUNT_ID}"

# Create configuration file
cat > /tmp/config.json <<EOF
{
  "cfg_key": "LarkBotProfile-0",
  "accounts": {
    "0": {
      "role_arn": "arn:aws:iam::${ACCOUNT_ID}:role/AWSSupportAccessRole",
      "account_name": "Main Account"
    }
  },
  "user_whitelist": {},
  "help_text": "Send 'create case' to create a new case\nSend 'history' to view case history"
}
EOF

# Upload to S3
aws s3 cp /tmp/config.json s3://${BUCKET_NAME}/config/LarkBotProfile-0.json

# Cleanup
rm /tmp/config.json
```

---

## Step 8: Configure Lark App

Refer to [LARK-SETUP.md](LARK-SETUP.md) to complete Lark app configuration:

1. Create Lark app
2. Configure permissions (18 permissions)
3. Configure event subscription
4. Set Webhook URL (URL obtained from Step 5)
5. Publish app

---

## Verify Deployment

### Test Webhook

```bash
curl -X POST https://YOUR_API_ID.execute-api.REGION.amazonaws.com/prod/messages \
  -H "Content-Type: application/json" \
  -d '{"type":"url_verification","challenge":"test123"}'
```

Should return:

```json
{"challenge": "test123"}
```

### Test Lark Message

Send `help` to the bot in Lark, you should receive help information.

### Check Logs

```bash
aws logs tail /aws/lambda/LarkCaseBot-MsgEvent --follow
```

---

## Add Cross-Account Support

For multi-account support, refer to [manual-account-setup.md](manual-account-setup.md).

---

## Cleanup Resources

To delete all resources:

```bash
# Delete Lambda functions
aws lambda delete-function --function-name LarkCaseBot-MsgEvent
aws lambda delete-function --function-name LarkCaseBot-CaseUpdate
aws lambda delete-function --function-name LarkCaseBot-CasePoller
aws lambda delete-function --function-name LarkCaseBot-GroupCleanup

# Delete EventBridge rules
aws events remove-targets --rule LarkCaseBot-CaseUpdate --ids 1
aws events delete-rule --name LarkCaseBot-CaseUpdate
aws events remove-targets --rule LarkCaseBot-Poller --ids 1
aws events delete-rule --name LarkCaseBot-Poller
aws events remove-targets --rule LarkCaseBot-GroupCleanup --ids 1
aws events delete-rule --name LarkCaseBot-GroupCleanup

# Delete API Gateway
aws apigateway delete-rest-api --rest-api-id YOUR_API_ID

# Delete IAM roles (must delete policies first)
aws iam delete-role-policy --role-name LarkCaseBot-MsgEventRole --policy-name MsgEventPolicy
aws iam detach-role-policy --role-name LarkCaseBot-MsgEventRole --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name LarkCaseBot-MsgEventRole
# ... repeat for other roles

# Delete S3 bucket (must empty first)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws s3 rm s3://larkcasebot-data-${ACCOUNT_ID} --recursive
aws s3api delete-bucket --bucket larkcasebot-data-${ACCOUNT_ID}

# Delete Secrets Manager
aws secretsmanager delete-secret --secret-id LarkCaseBot-app-id --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id LarkCaseBot-app-secret --force-delete-without-recovery
```

---

**Last Updated**: 2025-12-03
