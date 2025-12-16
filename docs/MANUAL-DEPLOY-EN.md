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
                    ┌────────────────────────────┼─────────────────────────────┐
                    │                            │                             │
              ┌─────┴─────┐              ┌───────┴────────┐            ┌───────┴────────┐
              │EventBridge│──────────────│CaseUpdateLambda│            │CasePollerLambda│
              │  (Rule)   │              └────────────────┘            └────────────────┘
              └───────────┘
```

### Resource List

| Resource Type | Name | Purpose |
|--------------|------|---------|
| Secrets Manager | LarkCaseBot-app-id | Store Lark App ID |
| Secrets Manager | LarkCaseBot-app-secret | Store Lark App Secret |
| Secrets Manager | LarkCaseBot-encrypt-key | Store Lark Encrypt Key (optional, for event decryption) |
| Secrets Manager | LarkCaseBot-verification-token | Store Lark Verification Token (for request verification) |
| S3 | LarkCaseBot-DataBucket | Bot config and case data storage |
| IAM Role | LarkCaseBot-MsgEventRole | MsgEventLambda execution role |
| IAM Role | LarkCaseBot-CaseUpdateRole | CaseUpdateLambda execution role |
| IAM Role | LarkCaseBot-CasePollerRole | CasePollerLambda execution role |
| IAM Role | LarkCaseBot-GroupCleanupRole | GroupCleanupLambda execution role |
| IAM Role | LarkCaseBot-SupportApiRole | AWS Support API access |
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

1. Go to AWS Console → Secrets Manager (ensure you're in **us-east-1** region)
2. Click **Store a new secret**
3. Step 1 - Choose secret type:
   - Secret type: **Other type of secret**
   - Key/value pairs: Click **Plaintext** tab, enter:
   ```json
   {"app_id":"cli_xxxxxxxxxx"}
   ```
   - Encryption key: Keep default `aws/secretsmanager`
   - Click **Next**
4. Step 2 - Configure secret:
   - Secret name: `LarkCaseBot-app-id`
   - Description: `Lark App ID for Case Bot`
   - Click **Next**
5. Step 3 - Configure rotation: Keep default, click **Next**
6. Step 4 - Review: Click **Store**
7. ⚠️ **Record Secret ARN**: After creation, click to enter and copy the full **Secret ARN** (needed for Lambda environment variables)

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

### 1.3 Create Encrypt Key Secret (Optional)

Used to decrypt Lark events (if encryption is enabled).

**Console Method:**

1. Repeat the above steps
2. Click **Plaintext** tab, enter:
   ```json
   {"encrypt_key":""}
   ```
   > 💡 If not using encryption, keep it as empty string
3. Secret name: `LarkCaseBot-encrypt-key`

**CLI Method:**

```bash
aws secretsmanager create-secret \
  --name LarkCaseBot-encrypt-key \
  --secret-string '{"encrypt_key":""}'
```

### 1.4 Create Verification Token Secret

Used to verify request origin.

**Console Method:**

1. Repeat the above steps
2. Click **Plaintext** tab, enter:
   ```json
   {"verification_token":"xxxxxxxxxxxxxxxx"}
   ```
   > Get Verification Token from Lark Open Platform → Event Subscription page
3. Secret name: `LarkCaseBot-verification-token`

**CLI Method:**

```bash
aws secretsmanager create-secret \
  --name LarkCaseBot-verification-token \
  --secret-string '{"verification_token":"xxxxxxxxxxxxxxxx"}'
```

---

## Step 2: Create S3 Bucket

### 2.1 Create Data Bucket

**Console Method:**

1. Go to AWS Console → S3 (ensure you're in **us-east-1** region)
2. Click **Create bucket**
3. General configuration:
   - Bucket name: `larkcasebot-data-{account-id}` (replace `{account-id}` with your 12-digit AWS account ID)
   - AWS Region: **US East (N. Virginia) us-east-1**
4. Object Ownership: Keep default **ACLs disabled**
5. Block Public Access settings:
   - ✅ **Block all public access** (must be checked)
6. Bucket Versioning:
   - Select **Enable**
7. Default encryption:
   - Encryption type: **Server-side encryption with Amazon S3 managed keys (SSE-S3)**
   - Bucket Key: **Enable**
8. Click **Create bucket**

> 💡 **Tip**: Remember the bucket name, Lambda environment variable `DATA_BUCKET` needs it

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

# Configure lifecycle rule (delete old versions after 30 days)
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

### 3.1 Create LarkCaseBot-SupportApiRole

This role is for accessing the AWS Support API.

**Trust Policy (trust-policy.json):**

> ⚠️ **Important**: Replace `LAMBDA_ACCOUNT_ID` with the main account ID where Lambda is deployed, and replace `MSGEVENT_ROLE_NAME` and `CASEPOLLER_ROLE_NAME` with actual role names.
>
> If using CDK deployment, role names are similar to: `LarkCaseBotStack-MsgEventHandlerServiceRole12345-ABCDEFG`
>
> You can get them with:
> ```bash
> aws cloudformation describe-stacks --stack-name LarkCaseBotStack \
>   --query 'Stacks[0].Outputs[?contains(OutputKey,`Role`)].{Key:OutputKey,Value:OutputValue}' --output table
> ```

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws:iam::LAMBDA_ACCOUNT_ID:role/MSGEVENT_ROLE_NAME",
          "arn:aws:iam::LAMBDA_ACCOUNT_ID:role/CASEPOLLER_ROLE_NAME"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

> **Cross-Account Note**: 
> - `LAMBDA_ACCOUNT_ID` is the main account ID where LarkCaseBot Lambda is deployed
> - Must use **full role ARN**, do not use wildcard `*`
> - If unsure about role names, check Lambda function execution roles in main account IAM Console

**CLI Method:**

```bash
# Create role
aws iam create-role \
  --role-name LarkCaseBot-SupportApiRole \
  --assume-role-policy-document file://trust-policy.json

# Attach AWSSupportAccess policy
aws iam attach-role-policy \
  --role-name LarkCaseBot-SupportApiRole \
  --policy-arn arn:aws:iam::aws:policy/AWSSupportAccess
```

### 3.2 Create MsgEventRole

**Console Method:**

1. Go to AWS Console → IAM → Roles
2. Click **Create role**
3. Step 1 - Select trusted entity:
   - Trusted entity type: **AWS service**
   - Use case: **Lambda**
   - Click **Next**
4. Step 2 - Add permissions:
   - Search and check `AWSLambdaBasicExecutionRole`
   - Click **Next**
5. Step 3 - Name, review, and create:
   - Role name: `LarkCaseBot-MsgEventRole`
   - Click **Create role**
6. Add inline policy:
   - Find the role just created, click to enter
   - Click **Add permissions** → **Create inline policy**
   - Select **JSON** tab
   - Paste the inline policy JSON below
   - Policy name: `MsgEventPolicy`
   - Click **Create policy**

**Trust Policy (auto-created):**

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

> ⚠️ **Important**: Replace `ACCOUNT_ID` with your 12-digit AWS account ID in the policy below.
>
> 💡 **About `*` in Secret ARN**: Secrets Manager auto-appends a 6-character random suffix (like `-AbCdEf`) to secret names, so the policy uses `LarkCaseBot-app-id*` to match. For stricter permission control, you can replace `*` with the full ARN (copy from Secrets Manager Console) after creating the secret.

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

> 💡 **About `*` in AssumeRole**: `arn:aws:iam::*:role/LarkCaseBot-SupportApiRole` allows access to Support API roles in any account. If only specific accounts need support, replace with specific account ID list, like: `arn:aws:iam::111122223333:role/LarkCaseBot-SupportApiRole`

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

**Console Method:**

1. Go to AWS Console → IAM → Roles → **Create role**
2. Trusted entity type: **AWS service** → Use case: **Lambda**
3. Add permissions: Check `AWSLambdaBasicExecutionRole`
4. Role name: `LarkCaseBot-CaseUpdateRole`
5. After creation, add inline policy (replace `ACCOUNT_ID` with your account ID):

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

**CLI Method:**

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

### 3.4 Create CasePollerRole

**Console Method:**

1. Go to AWS Console → IAM → Roles → **Create role**
2. Trusted entity type: **AWS service** → Use case: **Lambda**
3. Add permissions: Check `AWSLambdaBasicExecutionRole`
4. Role name: `LarkCaseBot-CasePollerRole`
5. After creation, add inline policy (replace `ACCOUNT_ID` with your account ID):

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

**CLI Method:**

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

### 3.5 Create GroupCleanupRole

**Console Method:**

1. Go to AWS Console → IAM → Roles → **Create role**
2. Trusted entity type: **AWS service** → Use case: **Lambda**
3. Add permissions: Check `AWSLambdaBasicExecutionRole`
4. Role name: `LarkCaseBot-GroupCleanupRole`
5. After creation, add inline policy (replace `ACCOUNT_ID` with your account ID):

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

> 💡 **Note**: GroupCleanupRole doesn't need `AssumeRoleForSupport` permission because it only reads S3 data and calls Lark API.

**CLI Method:**

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

---

## Step 4: Create Lambda Functions

### Lambda Functions Overview

| Lambda | Handler | Execution Role | Timeout | Memory | Trigger |
|--------|---------|----------------|---------|--------|---------|
| MsgEvent | `msg_event_handler.lambda_handler` | MsgEventRole | 60s | 1024MB | API Gateway |
| CaseUpdate | `case_update_handler.lambda_handler` | CaseUpdateRole | 30s | 256MB | EventBridge (aws.support) |
| CasePoller | `case_poller.lambda_handler` | CasePollerRole | 300s | 512MB | EventBridge (every 10 min) |
| GroupCleanup | `group_cleanup.lambda_handler` | GroupCleanupRole | 300s | 256MB | EventBridge (hourly) |

### 4.1 Prepare Code Package

```bash
cd lambda
zip -r ../lambda-package.zip .
cd ..
```

---

### 4.2 Create MsgEventLambda

**Configuration Overview:**

| Setting | Value |
|---------|-------|
| Function Name | `LarkCaseBot-MsgEvent` |
| Handler | `msg_event_handler.lambda_handler` |
| Execution Role | `LarkCaseBot-MsgEventRole` |
| Timeout | 60 seconds |
| Memory | 1024 MB |
| Trigger | API Gateway (Lark Webhook) |

**Environment Variables:**

| Key | Value | Description |
|-----|-------|-------------|
| APP_ID_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id-XXXXX` | Lark App ID |
| APP_SECRET_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret-XXXXX` | Lark App Secret |
| ENCRYPT_KEY_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-encrypt-key-XXXXX` | Lark Encrypt Key (optional) |
| VERIFICATION_TOKEN_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-verification-token-XXXXX` | Lark Verification Token |
| DATA_BUCKET | `larkcasebot-data-ACCOUNT_ID` | S3 data bucket |
| CFG_KEY | `LarkBotProfile-0` | Config key name |
| CASE_LANGUAGE | `zh` | Case language (zh/en/ja/ko) |
| USER_WHITELIST | `false` | Enable user whitelist |

> ⚠️ **Note**: 
> - Replace `ACCOUNT_ID` with your actual AWS account ID
> - The `-XXXXX` suffix in Secret ARN is auto-generated; copy the full ARN from Secrets Manager

**Console Method:**

1. Go to AWS Console → Lambda (ensure you're in **us-east-1** region)
2. Click **Create function**
3. Select **Author from scratch**
4. Basic configuration:
   - Function name: `LarkCaseBot-MsgEvent`
   - Runtime: **Python 3.12**
   - Architecture: **x86_64**
5. Permissions configuration:
   - Expand **Change default execution role**
   - Select **Use an existing role**
   - Existing role: `LarkCaseBot-MsgEventRole`
6. Click **Create function**
7. Upload code:
   - In **Code** tab, click **Upload from** → **.zip file**
   - Upload `lambda-package.zip`
8. Configure Runtime settings:
   - Click **Edit**
   - Handler: `msg_event_handler.lambda_handler`
   - Click **Save**
9. Configure General configuration:
   - Click **Configuration** → **General configuration** → **Edit**
   - Timeout: **1 minute 0 seconds**
   - Memory: **1024 MB**
   - Click **Save**
10. Add environment variables:
    - Click **Configuration** → **Environment variables** → **Edit**
    - Add all variables per the table above

**CLI Method:**

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

### 4.3 Create CaseUpdateLambda

**Configuration Overview:**

| Setting | Value |
|---------|-------|
| Function Name | `LarkCaseBot-CaseUpdate` |
| Handler | `case_update_handler.lambda_handler` |
| Execution Role | `LarkCaseBot-CaseUpdateRole` |
| Timeout | 30 seconds |
| Memory | 256 MB |
| Trigger | EventBridge rule `LarkCaseBot-CaseUpdate` (case update events) |

**Environment Variables:**

| Key | Value | Description |
|-----|-------|-------------|
| APP_ID_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id-XXXXX` | Lark App ID |
| APP_SECRET_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret-XXXXX` | Lark App Secret |
| DATA_BUCKET | `larkcasebot-data-ACCOUNT_ID` | S3 data bucket |
| AUTO_DISSOLVE_HOURS | `72` | Hours after resolution to auto-dissolve group |

**CLI Method:**

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

### 4.4 Create CasePollerLambda

**Configuration Overview:**

| Setting | Value |
|---------|-------|
| Function Name | `LarkCaseBot-CasePoller` |
| Handler | `case_poller.lambda_handler` |
| Execution Role | `LarkCaseBot-CasePollerRole` |
| Timeout | 300 seconds (5 minutes) |
| Memory | 512 MB |
| Trigger | EventBridge rule `LarkCaseBot-Poller` (every 10 minutes) |

**Environment Variables:**

| Key | Value | Description |
|-----|-------|-------------|
| APP_ID_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id-XXXXX` | Lark App ID |
| APP_SECRET_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret-XXXXX` | Lark App Secret |
| DATA_BUCKET | `larkcasebot-data-ACCOUNT_ID` | S3 data bucket |
| AUTO_DISSOLVE_HOURS | `72` | Hours after resolution to auto-dissolve group |

**CLI Method:**

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

### 4.5 Create GroupCleanupLambda

**Configuration Overview:**

| Setting | Value |
|---------|-------|
| Function Name | `LarkCaseBot-GroupCleanup` |
| Handler | `group_cleanup.lambda_handler` |
| Execution Role | `LarkCaseBot-GroupCleanupRole` |
| Timeout | 300 seconds (5 minutes) |
| Memory | 256 MB |
| Trigger | EventBridge rule `LarkCaseBot-GroupCleanup` (hourly) |

**Environment Variables:**

| Key | Value | Description |
|-----|-------|-------------|
| APP_ID_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-id-XXXXX` | Lark App ID |
| APP_SECRET_ARN | `arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:LarkCaseBot-app-secret-XXXXX` | Lark App Secret |
| DATA_BUCKET | `larkcasebot-data-ACCOUNT_ID` | S3 data bucket |
| AUTO_DISSOLVE_HOURS | `72` | Hours after resolution to auto-dissolve group |

**CLI Method:**

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

### 4.6 Environment Variables Reference

| Variable | Description | Used By |
|----------|-------------|---------|
| `APP_ID_ARN` | Secrets Manager ARN for Lark App ID | All |
| `APP_SECRET_ARN` | Secrets Manager ARN for Lark App Secret | All |
| `ENCRYPT_KEY_ARN` | Secrets Manager ARN for Lark Encrypt Key | MsgEvent |
| `VERIFICATION_TOKEN_ARN` | Secrets Manager ARN for Lark Verification Token | MsgEvent |
| `DATA_BUCKET` | S3 data bucket name | All |
| `CFG_KEY` | S3 config key name | MsgEvent |
| `CASE_LANGUAGE` | Case language (zh/en/ja/ko) | MsgEvent |
| `USER_WHITELIST` | Enable user whitelist | MsgEvent |
| `AUTO_DISSOLVE_HOURS` | Hours after resolution to auto-dissolve group | CaseUpdate, CasePoller, GroupCleanup |

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
   - Integration type: **Lambda Function**
   - ⚠️ **Lambda Proxy Integration**: ✅ **Must be checked** (checked by default)
   - Lambda Function: `LarkCaseBot-MsgEvent`
   - Click **Create Method**
6. Configure throttling (optional but recommended):
   - Click **Stages** on the left → **prod** (after deployment)
   - In **Stage Editor** find **Default Method Throttling**
   - Rate: `100` requests per second
   - Burst: `200` requests
7. Deploy API:
   - Click **Deploy API**
   - Stage name: `prod`

> ⚠️ **Important**: Lambda Proxy Integration must be enabled, otherwise Lambda cannot correctly receive Lark webhook requests. If not checked, it will cause request format errors.

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
  --source-arn "arn:aws:execute-api:us-east-1:${ACCOUNT_ID}:$API_ID/*/POST/messages"

# Deploy API
aws apigateway create-deployment \
  --rest-api-id $API_ID \
  --stage-name prod

# Configure throttling (consistent with CDK deployment)
aws apigateway update-stage \
  --rest-api-id $API_ID \
  --stage-name prod \
  --patch-operations \
    op=replace,path=/throttling/rateLimit,value=100 \
    op=replace,path=/throttling/burstLimit,value=200

echo "Webhook URL: https://$API_ID.execute-api.us-east-1.amazonaws.com/prod/messages"
```

---

## Step 6: Create EventBridge Rules

### 6.1 Case Update Rule

**Console Method:**

1. Go to AWS Console → EventBridge → Rules (ensure you're in **us-east-1** region)
2. Ensure Event bus is **default**
3. Click **Create rule**
4. Step 1 - Define rule detail:
   - Name: `LarkCaseBot-CaseUpdate`
   - Description: `Capture AWS Support case updates and push to Lark`
   - Event bus: **default**
   - Rule type: **Rule with an event pattern**
   - Click **Next**
5. Step 2 - Build event pattern:
   - Event source: **AWS events or EventBridge partner events**
   - Creation method: **Custom pattern (JSON editor)**
   - Event pattern:

```json
{
  "source": ["aws.support"],
  "detail-type": ["Support Case Update"]
}
```

   - Click **Next**
6. Step 3 - Select target(s):
   - Target types: **AWS service**
   - Select a target: **Lambda function**
   - Function: `LarkCaseBot-CaseUpdate`
   - ⚠️ If prompted **"Add permission to Lambda function"**, click **Allow** or **Add**
   - Click **Next**
7. Step 4 - Configure tags: (optional, skip)
   - Click **Next**
8. Step 5 - Review and create:
   - Confirm configuration is correct, click **Create rule**

> 💡 **About Lambda trigger permissions**: Console automatically prompts to add Lambda resource-based policy when creating EventBridge rules. If using CLI, you must manually run `aws lambda add-permission` command.

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

> 💡 **Note**: When creating a rule, AWS Console may show a hint to use the "Scheduler" builder. You can ignore this - EventBridge Rules with schedule expressions still work and are what CDK deploys.

**Console Method:**

1. Go to AWS Console → EventBridge → Rules
2. Click **Create rule**
3. Step 1 - Define rule detail:
   - Name: `LarkCaseBot-Poller`
   - Description: `Poll AWS Support case status every 10 minutes`
   - Event bus: **default**
   - Rule type: **Schedule**
   - Click **Continue in EventBridge Scheduler** if prompted, or **Continue to create rule** to stay with Rules
   - Click **Next**
4. Step 2 - Define schedule:
   - Schedule pattern: **A schedule that runs at a regular rate**
   - Rate expression: `10` **minutes**
   - Click **Next**
5. Step 3 - Select target(s):
   - Target types: **AWS service**
   - Select a target: **Lambda function**
   - Function: `LarkCaseBot-CasePoller`
   - ⚠️ If prompted to add permissions, click **Allow**
   - Click **Next**
6. Complete creation

**CLI Method:**

```bash
# Create rule (every 10 minutes, consistent with CDK default)
aws events put-rule \
  --name LarkCaseBot-Poller \
  --schedule-expression "rate(10 minutes)" \
  --region us-east-1

# Add target
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws events put-targets \
  --rule LarkCaseBot-Poller \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:LarkCaseBot-CasePoller" \
  --region us-east-1

# Add Lambda permission
aws lambda add-permission \
  --function-name LarkCaseBot-CasePoller \
  --statement-id eventbridge-schedule \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:${ACCOUNT_ID}:rule/LarkCaseBot-Poller
```

### 6.3 Group Auto-Dissolve Rule

**Console Method:**

1. Go to AWS Console → EventBridge → Rules
2. Click **Create rule**
3. Step 1 - Define rule detail:
   - Name: `LarkCaseBot-GroupCleanup`
   - Description: `Auto-dissolve resolved case groups every hour`
   - Event bus: **default**
   - Rule type: **Schedule**
   - Click **Continue to create rule** if prompted about Scheduler
   - Click **Next**
4. Step 2 - Define schedule:
   - Schedule pattern: **A schedule that runs at a regular rate**
   - Rate expression: `1` **hour**
   - Click **Next**
5. Step 3 - Select target(s):
   - Target types: **AWS service**
   - Select a target: **Lambda function**
   - Function: `LarkCaseBot-GroupCleanup`
   - ⚠️ If prompted to add permissions, click **Allow**
   - Click **Next**
6. Complete creation

**CLI Method:**

```bash
# Create rule (hourly)
aws events put-rule \
  --name LarkCaseBot-GroupCleanup \
  --schedule-expression "rate(1 hour)" \
  --region us-east-1

# Add target
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws events put-targets \
  --rule LarkCaseBot-GroupCleanup \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:LarkCaseBot-GroupCleanup" \
  --region us-east-1

# Add Lambda permission
aws lambda add-permission \
  --function-name LarkCaseBot-GroupCleanup \
  --statement-id eventbridge-schedule \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:${ACCOUNT_ID}:rule/LarkCaseBot-GroupCleanup
```

### 6.4 Cross-Account EventBridge Configuration (Required for Multi-Account)

> ⚠️ **Important**: If you need to support multiple AWS accounts, you must configure cross-account EventBridge forwarding, otherwise case updates from other accounts won't be pushed to Lark.

#### 6.4.1 Create Custom Event Bus in Main Account

```bash
# Set variables
MAIN_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create custom Event Bus
aws events create-event-bus \
  --name LarkCaseBot-case-event-bus \
  --region us-east-1

# Allow other accounts to send events to this Bus
# 💡 --principal "*" allows any account to send events. For stricter control, use specific account IDs like --principal "111122223333"
# Or use put-permission multiple times to add multiple accounts
aws events put-permission \
  --event-bus-name LarkCaseBot-case-event-bus \
  --action events:PutEvents \
  --principal "*" \
  --statement-id AllowCrossAccountPutEvents \
  --region us-east-1
```

#### 6.4.2 Create Main Account Event Bus Rule

```bash
# Create rule on custom Event Bus to forward to CaseUpdate Lambda
aws events put-rule \
  --name LarkCaseBot-CrossAccountCaseUpdate \
  --event-bus-name LarkCaseBot-case-event-bus \
  --event-pattern '{"source":["aws.support"],"detail-type":["Support Case Update"]}' \
  --region us-east-1

# Add Lambda target
aws events put-targets \
  --rule LarkCaseBot-CrossAccountCaseUpdate \
  --event-bus-name LarkCaseBot-case-event-bus \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:${MAIN_ACCOUNT_ID}:function:LarkCaseBot-CaseUpdate" \
  --region us-east-1

# Add Lambda permission
aws lambda add-permission \
  --function-name LarkCaseBot-CaseUpdate \
  --statement-id eventbridge-crossaccount \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:us-east-1:${MAIN_ACCOUNT_ID}:rule/LarkCaseBot-case-event-bus/LarkCaseBot-CrossAccountCaseUpdate"
```

#### 6.4.3 Configure Event Forwarding in Other Accounts

> Execute the following commands in **each other account that needs support**:

```bash
# Set variables (replace with actual values)
MAIN_ACCOUNT_ID="111122223333"  # Main account ID
THIS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 1. Create EventBridge forwarding rule
aws events put-rule \
  --name LarkCaseBot-ForwardSupportEvents \
  --event-pattern '{"source":["aws.support"],"detail-type":["Support Case Update"]}' \
  --state ENABLED \
  --region us-east-1

# 2. Create EventBridge IAM role
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

# 3. Add forwarding permission policy
cat > /tmp/eventbridge-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "events:PutEvents",
      "Resource": "arn:aws:events:us-east-1:${MAIN_ACCOUNT_ID}:event-bus/LarkCaseBot-case-event-bus"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name LarkCaseBot-EventBridgeRole \
  --policy-name ForwardToMainAccount \
  --policy-document file:///tmp/eventbridge-policy.json

# 4. Wait for role to take effect
sleep 10

# 5. Add forwarding target
aws events put-targets \
  --rule LarkCaseBot-ForwardSupportEvents \
  --targets "[{
    \"Id\": \"1\",
    \"Arn\": \"arn:aws:events:us-east-1:${MAIN_ACCOUNT_ID}:event-bus/LarkCaseBot-case-event-bus\",
    \"RoleArn\": \"arn:aws:iam::${THIS_ACCOUNT_ID}:role/LarkCaseBot-EventBridgeRole\"
  }]" \
  --region us-east-1

# Cleanup temp files
rm /tmp/eventbridge-trust.json /tmp/eventbridge-policy.json

echo "✅ EventBridge forwarding configuration complete"
```

#### 6.4.4 Verify Cross-Account Configuration

```bash
# Check rule in other account
aws events describe-rule \
  --name LarkCaseBot-ForwardSupportEvents \
  --region us-east-1

# Check targets
aws events list-targets-by-rule \
  --rule LarkCaseBot-ForwardSupportEvents \
  --region us-east-1

# Check IAM role
aws iam get-role --role-name LarkCaseBot-EventBridgeRole
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
      "role_arn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/LarkCaseBot-SupportApiRole",
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
      "role_arn": "arn:aws:iam::${ACCOUNT_ID}:role/LarkCaseBot-SupportApiRole",
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
curl -X POST https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/prod/messages \
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

**Last Updated**: 2025-12-16
