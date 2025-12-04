# 手动添加 AWS 账号指南 (S3 存储版本)

如果你无法使用 `setup_lark_bot.py` 脚本自动创建 IAM 角色（例如权限不足或没有配置 AWS Profile），可以按照以下步骤手动添加账号。

> **注意**: 此版本使用 S3 存储配置数据。

## 前置条件

1. 已部署 LarkCaseBotStack
2. 知道主账号的 Lambda Role ARN（从 CloudFormation Outputs 获取）
3. 对目标账号有 IAM 管理权限

## 步骤 1: 获取 Lambda Role ARN

在主账号（部署 LarkCaseBotStack 的账号）执行：

```bash
aws cloudformation describe-stacks \
  --stack-name LarkCaseBotStack \
  --query 'Stacks[0].Outputs[?OutputKey==`msgEventRoleArn`].OutputValue' \
  --output text
```

输出示例：
```
arn:aws:iam::111122223333:role/LarkCaseBotStack-MsgEventRoleXXXXXXXX-XXXXXXXXXXXX
```

记下这个 ARN，后续步骤需要用到。

## 步骤 2: 在目标账号创建 IAM 角色

### 方式 1: 使用 AWS Console（推荐）

1. 登录到**目标账号**的 AWS Console
2. 进入 IAM 服务
3. 点击左侧菜单 "Roles" → "Create role"
4. 选择 "Custom trust policy"，粘贴以下内容（替换 `<LAMBDA_ROLE_ARN>`）：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "<LAMBDA_ROLE_ARN>"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

例如：
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::111122223333:role/LarkCaseBotStack-MsgEventRoleXXXXXXXX-XXXXXXXXXXXX"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

5. 点击 "Next"
6. 搜索并选择策略：`AWSSupportAccess`
7. 点击 "Next"
8. 角色名称输入：`LarkSupportCaseApiAll`
9. 描述（可选）：`Lark bot cross-account support access`
10. 点击 "Create role"

### 方式 2: 使用 AWS CLI

在目标账号执行（需要先配置对应的 AWS Profile）：

```bash
# 设置变量
LAMBDA_ROLE_ARN="arn:aws:iam::111122223333:role/LarkCaseBotStack-MsgEventRoleXXXXXXXX-XXXXXXXXXXXX"
TARGET_ACCOUNT_ID="123456789012"  # 目标账号 ID
ROLE_NAME="LarkSupportCaseApiAll"

# 创建信任策略文件
cat > trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "${LAMBDA_ROLE_ARN}"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# 创建角色
aws iam create-role \
  --role-name ${ROLE_NAME} \
  --assume-role-policy-document file://trust-policy.json \
  --description "Lark bot cross-account support access"

# 附加策略
aws iam attach-role-policy \
  --role-name ${ROLE_NAME} \
  --policy-arn arn:aws:iam::aws:policy/AWSSupportAccess

# 清理临时文件
rm trust-policy.json

# 输出角色 ARN
echo "Role ARN: arn:aws:iam::${TARGET_ACCOUNT_ID}:role/${ROLE_NAME}"
```

### 方式 3: 使用 CloudFormation

创建 `cross-account-role.yaml`：

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: 'Cross-account IAM role for Lark Case Bot'

Parameters:
  LambdaRoleArn:
    Type: String
    Description: ARN of the Lambda role in the main account
    Default: arn:aws:iam::111122223333:role/LarkCaseBotStack-MsgEventRoleXXXXXXXX-XXXXXXXXXXXX

Resources:
  LarkSupportRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: LarkSupportCaseApiAll
      Description: Lark bot cross-account support access
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              AWS: !Ref LambdaRoleArn
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/AWSSupportAccess

Outputs:
  RoleArn:
    Description: ARN of the created role
    Value: !GetAtt LarkSupportRole.Arn
```

部署：
```bash
aws cloudformation create-stack \
  --stack-name LarkCaseBotCrossAccountRole \
  --template-body file://cross-account-role.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters ParameterKey=LambdaRoleArn,ParameterValue=<LAMBDA_ROLE_ARN>
```

## 步骤 3: 将账号信息添加到 S3

### 方式 1: 使用 AWS Console

1. 登录到**主账号**的 AWS Console
2. 进入 S3 服务
3. 找到存储桶：`larkcasebotstack-databucketXXXXX-XXXXX`
4. 进入 `config/` 目录
5. 下载 `LarkBotProfile-0.json` 文件
6. 编辑 JSON 文件，在 `accounts` 中添加新账号：

```json
{
  "cfg_key": "LarkBotProfile-0",
  "accounts": {
    "0": {
      "role_arn": "arn:aws:iam::111122223333:role/AWSSupportAccessRole",
      "account_name": "primary"
    },
    "1": {
      "role_arn": "arn:aws:iam::123456789012:role/LarkSupportCaseApiAll",
      "account_name": "production"
    },
    "2": {
      "role_arn": "arn:aws:iam::210987654321:role/LarkSupportCaseApiAll",
      "account_name": "staging"
    }
  }
}
```

7. 上传修改后的文件到 S3

### 方式 2: 使用 AWS CLI

```bash
# 获取存储桶名
BUCKET_NAME=$(aws cloudformation describe-stacks \
  --stack-name LarkCaseBotStack \
  --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

# 下载当前配置
aws s3 cp s3://${BUCKET_NAME}/config/LarkBotProfile-0.json current-config.json

# 编辑 current-config.json，在 accounts 中添加新账号
# 示例：使用 jq 添加新账号
jq '.accounts += {
  "2": {
    "role_arn": "arn:aws:iam::123456789012:role/LarkSupportCaseApiAll",
    "account_name": "production"
  }
}' current-config.json > updated-config.json

# 上传回 S3
aws s3 cp updated-config.json s3://${BUCKET_NAME}/config/LarkBotProfile-0.json

# 清理临时文件
rm current-config.json updated-config.json
```

### 方式 3: 使用 Python 脚本

创建 `add_account_manual.py`：

```python
#!/usr/bin/env python3
import boto3
import json
import sys

def add_account(account_id, account_name, region='us-east-1'):
    """手动添加账号到 S3"""
    
    # 获取存储桶名
    cfn = boto3.client('cloudformation', region_name=region)
    response = cfn.describe_stacks(StackName='LarkCaseBotStack')
    outputs = {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0]['Outputs']}
    bucket_name = outputs['DataBucketName']
    
    # 连接 S3
    s3 = boto3.client('s3', region_name=region)
    
    # 获取当前配置
    try:
        response = s3.get_object(Bucket=bucket_name, Key='config/LarkBotProfile-0.json')
        config = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        config = {'cfg_key': 'LarkBotProfile-0', 'accounts': {}}
    
    # 获取现有账号
    accounts = config.get('accounts', {})
    
    # 找到下一个可用的索引
    next_index = str(len(accounts))
    
    # 构造角色 ARN
    role_arn = f"arn:aws:iam::{account_id}:role/LarkSupportCaseApiAll"
    
    # 添加新账号
    accounts[next_index] = {
        'role_arn': role_arn,
        'account_name': account_name
    }
    
    # 更新 S3
    config['accounts'] = accounts
    s3.put_object(
        Bucket=bucket_name,
        Key='config/LarkBotProfile-0.json',
        Body=json.dumps(config, indent=2).encode('utf-8'),
        ContentType='application/json'
    )
    
    print(f"✅ 账号已添加:")
    print(f"   账号 ID: {account_id}")
    print(f"   账号名称: {account_name}")
    print(f"   角色 ARN: {role_arn}")
    print(f"   索引: {next_index}")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("用法: python add_account_manual.py <账号ID> <账号名称>")
        print("示例: python add_account_manual.py 123456789012 production")
        sys.exit(1)
    
    account_id = sys.argv[1]
    account_name = sys.argv[2]
    
    add_account(account_id, account_name)
```

使用方法：
```bash
python add_account_manual.py 123456789012 production
```

## 步骤 4: 验证配置

### 验证角色可以被假设

在主账号执行：

```bash
# 获取 Lambda Role ARN
LAMBDA_ROLE_ARN=$(aws cloudformation describe-stacks \
  --stack-name LarkCaseBotStack \
  --query 'Stacks[0].Outputs[?OutputKey==`msgEventRoleArn`].OutputValue' \
  --output text)

# 假设 Lambda 角色
TEMP_CREDS=$(aws sts assume-role \
  --role-arn ${LAMBDA_ROLE_ARN} \
  --role-session-name test-session \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)

# 设置临时凭证
export AWS_ACCESS_KEY_ID=$(echo $TEMP_CREDS | awk '{print $1}')
export AWS_SECRET_ACCESS_KEY=$(echo $TEMP_CREDS | awk '{print $2}')
export AWS_SESSION_TOKEN=$(echo $TEMP_CREDS | awk '{print $3}')

# 尝试假设目标账号角色
TARGET_ROLE_ARN="arn:aws:iam::123456789012:role/LarkSupportCaseApiAll"
aws sts assume-role \
  --role-arn ${TARGET_ROLE_ARN} \
  --role-session-name test-cross-account

# 如果成功，会返回临时凭证
# 清理环境变量
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
```

### 在 Lark 中测试

1. 在 Lark 中发送 `开工单`
2. 检查账号下拉列表中是否出现新添加的账号
3. 尝试创建一个测试工单

## 常见问题

### Q1: 角色创建成功，但无法假设？

**原因**：信任策略中的 Lambda Role ARN 不正确

**解决**：
1. 确认 Lambda Role ARN 是否正确
2. 在目标账号更新信任策略：
```bash
aws iam update-assume-role-policy \
  --role-name LarkSupportCaseApiAll \
  --policy-document file://trust-policy.json
```

### Q2: 在 Lark 中看不到新账号？

**原因**：S3 配置未更新或格式错误

**解决**：
1. 检查 S3 中的配置文件格式
2. 确保索引是连续的（0, 1, 2, ...）
3. 重启 Lambda（等待几分钟让缓存失效）

### Q3: 创建工单时提示权限错误？

**原因**：角色没有附加 AWSSupportAccess 策略

**解决**：
```bash
aws iam attach-role-policy \
  --role-name LarkSupportCaseApiAll \
  --policy-arn arn:aws:iam::aws:policy/AWSSupportAccess
```

### Q4: 如何删除账号？

在 S3 配置文件中删除对应的账号条目，或使用脚本：

```python
# 删除索引为 2 的账号
accounts.pop('2', None)
s3.put_object(
    Bucket=bucket_name,
    Key='config/LarkBotProfile-0.json',
    Body=json.dumps(config, indent=2).encode('utf-8'),
    ContentType='application/json'
)
```

## 批量添加多个账号

如果需要添加多个账号，可以使用以下脚本：

```bash
#!/bin/bash
# batch-add-accounts.sh

ACCOUNTS=(
  "123456789012:production"
  "210987654321:staging"
  "345678901234:development"
)

for account in "${ACCOUNTS[@]}"; do
  IFS=':' read -r account_id account_name <<< "$account"
  echo "添加账号: $account_name ($account_id)"
  python add_account_manual.py "$account_id" "$account_name"
done
```

## 总结

手动添加账号的核心步骤：
1. ✅ 获取主账号的 Lambda Role ARN
2. ✅ 在目标账号创建 IAM 角色（带信任策略和 AWSSupportAccess 策略）
3. ✅ 将账号信息添加到主账号的 S3 配置文件
4. ✅ 验证配置是否正确

如果遇到问题，可以使用 `setup_lark_bot.py verify --roles` 命令验证所有角色的可访问性。
