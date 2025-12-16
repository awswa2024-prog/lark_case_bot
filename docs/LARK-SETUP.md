# Lark 应用配置完整指南 (S3 存储版本)

本文档整合了 Lark 应用的所有配置步骤，包括创建应用、权限配置、事件订阅和 Webhook 设置。

> **注意**: 此版本使用 S3 存储数据。

---

## 目录

- [1. 创建 Lark 应用](#1-创建-lark-应用)
- [2. 权限配置](#2-权限配置)
- [3. 事件订阅](#3-事件订阅)
- [4. Webhook 配置](#4-webhook-配置)
- [5. 机器人配置](#5-机器人配置)
- [6. 发布应用](#6-发布应用)
- [7. 验证配置](#7-验证配置)

---

## 1. 创建 Lark 应用

### 1.1 访问开放平台

1. 登录 [Lark 开放平台](https://open.larksuite.com/)
2. 点击右上角 **创建应用**
3. 选择 **企业自建应用**

### 1.2 填写应用信息

| 字段 | 建议值 |
|-----|-------|
| 应用名称 | Case Support Bot |
| 应用描述 | AWS Support 工单管理机器人 |
| 应用图标 | 上传一个图标 |

### 1.3 获取凭证

创建完成后，在 **凭证与基础信息** 页面获取：

- **App ID**: `cli_xxxxxxxxxx`
- **App Secret**: `xxxxxxxxxxxxxxxx`

⚠️ 妥善保管这些凭证，后续部署需要使用。

---

## 2. 权限配置

### 2.1 进入权限管理

1. 在应用管理页面，点击左侧 **权限管理**
2. 搜索并添加以下权限

### 2.2 快速导入权限（推荐）

点击 **批量开通** 或 **导入**，粘贴以下 JSON：

```json
{
  "scopes": {
    "tenant": [
      "contact:contact.base:readonly",
      "contact:user.base:readonly",
      "contact:user.email:readonly",
      "contact:user.employee_id:readonly",
      "docs:document.media:upload",
      "im:chat",
      "im:chat.members:read",
      "im:chat.members:write_only",
      "im:chat:create",
      "im:chat:delete",
      "im:chat:readonly",
      "im:message",
      "im:message.group_at_msg:readonly",
      "im:message.group_msg:readonly",
      "im:message.p2p_msg:readonly",
      "im:message:readonly",
      "im:message:send_as_bot",
      "im:resource"
    ],
    "user": []
  }
}
```

> 💡 **提示**: 使用 JSON 导入可以一次性添加所有权限，无需逐个搜索。

### 2.3 手动添加权限（备选）

如果无法使用 JSON 导入，可手动搜索并添加以下权限：

| 权限 Scope | 权限名称 | 用途 |
|-----------|---------|------|
| `contact:contact.base:readonly` | 获取通讯录基本信息 | 获取用户信息 |
| `contact:user.base:readonly` | 获取用户基本信息 | 显示用户真实姓名 |
| `contact:user.email:readonly` | 获取用户邮箱信息 | 用户邮箱 |
| `contact:user.employee_id:readonly` | 获取用户 user ID | 用户标识 |
| `docs:document.media:upload` | 上传图片和附件到云文档中 | 附件处理 |
| `im:chat` | 管理群组 | 群组管理 |
| `im:chat.members:read` | 查看群成员 | 获取群成员列表 |
| `im:chat.members:write_only` | 添加、移除群成员 | 管理群成员 |
| `im:chat:create` | 创建群 | 创建工单群 |
| `im:chat:delete` | 解散群 | 解散工单群 |
| `im:chat:readonly` | 获取群组信息 | 读取群信息 |
| `im:message` | 获取与发送单聊、群组消息 | 核心消息功能 |
| `im:message.group_at_msg:readonly` | 接收群聊中@机器人消息事件 | 响应 @机器人 |
| `im:message.group_msg:readonly` | 获取群聊中所有的用户聊天消息 | 同步消息到 AWS |
| `im:message.p2p_msg:readonly` | 读取用户发给机器人的单聊消息 | 处理私聊命令 |
| `im:message:readonly` | 获取单聊、群组消息 | 读取历史消息 |
| `im:message:send_as_bot` | 以应用的身份发消息 | 机器人发消息 |
| `im:resource` | 获取与上传图片或文件资源 | 处理图片文件 |

> ⚠️ **注意**: JSON 中包含 18 个权限。如需文件下载功能，还需手动添加：
> - `im:message.file:readonly` - 获取消息中的文件内容
> - `im:resource:readonly` - 读取图片或文件资源

### 2.4 权限分类说明

#### 通讯录权限（用户信息）

```
contact:contact.base:readonly
contact:user.base:readonly
contact:user.email:readonly
contact:user.employee_id:readonly
```

✅ 有了这些权限，AWS Support 消息前缀将显示为 `[来自 张三 via Lark]` 而非 `[来自 团队成员 via Lark]`

#### 群组管理权限

```
im:chat
im:chat:create
im:chat:delete
im:chat:readonly
im:chat.members:read
im:chat.members:write_only
```

#### 消息权限

```
im:message
im:message:send_as_bot
im:message:readonly
im:message.group_at_msg:readonly
im:message.group_msg:readonly
im:message.p2p_msg:readonly
```

#### 文件处理权限

```
im:resource
im:resource:readonly
im:message.file:readonly
docs:document.media:upload
```

### 2.4 申请权限审批

部分权限可能需要管理员审批，联系企业管理员进行审批。

---

## 3. 事件订阅

### 3.1 进入事件订阅

1. 在应用管理页面，点击左侧 **事件订阅**
2. 配置请求地址和订阅事件

### 3.2 配置请求地址

填入部署后获取的 Webhook URL：

```
https://xxxxxxxxxx.execute-api.us-east-1.amazonaws.com/prod/webhook
```

### 3.3 订阅事件列表

添加以下事件：

| 事件名称 | 事件标识 | 说明 |
|---------|---------|------|
| 接收消息 | `im.message.receive_v1` | 接收用户发送的消息 |
| 卡片回调 | `card.action.trigger` | 处理卡片按钮点击 |

### 3.4 验证 URL

配置完成后，Lark 会发送验证请求。确保 Lambda 已部署并能正确响应 `url_verification` 事件。

---

## 4. Webhook 配置

### 4.1 获取 Webhook URL

部署 CDK Stack 后，从 CloudFormation Outputs 获取：

```bash
aws cloudformation describe-stacks \
  --stack-name LarkCaseBotStack \
  --query 'Stacks[0].Outputs[?OutputKey==`WebhookUrl`].OutputValue' \
  --output text
```

### 4.2 配置加密策略

在 **事件订阅** 页面：

1. 找到 **加密策略** 设置
2. 选择 **不加密**（推荐）或配置 Encrypt Key

### 4.3 配置 Verification Token

1. 在 **事件订阅** 页面找到 **Verification Token**
2. 记录此 Token（可选，用于验证请求来源）

---

## 5. 机器人配置

### 5.1 启用机器人能力

1. 在应用管理页面，点击左侧 **应用能力** > **机器人**
2. 开启机器人能力

### 5.2 配置机器人信息

| 字段 | 建议值 |
|-----|-------|
| 机器人名称 | Case Support Bot |
| 机器人描述 | AWS Support 工单管理 |
| 机器人头像 | 上传一个头像 |

### 5.3 配置消息卡片

1. 点击 **消息卡片** 设置
2. 添加卡片请求地址（与 Webhook URL 相同）

---

## 6. 发布应用

### 6.1 版本管理

1. 点击左侧 **版本管理与发布**
2. 点击 **创建版本**
3. 填写版本号和更新说明

### 6.2 申请发布

1. 选择发布范围（全员可用 / 指定部门）
2. 提交审核
3. 等待管理员审批

### 6.3 发布上线

审批通过后，应用即可使用。

---

## 7. 验证配置

### 7.1 测试消息接收

在 Lark 中向机器人发送：

```
帮助
```

应收到帮助信息卡片。

### 7.2 测试创建工单

发送：

```
开工单 测试工单
```

应弹出工单创建卡片。

### 7.3 检查日志

```bash
aws logs tail /aws/lambda/LarkCaseBotStack-MsgEventLambda* --follow
```

### 7.4 常见问题

#### 问题：收不到消息

- 检查事件订阅是否配置正确
- 检查 Webhook URL 是否正确
- 检查 Lambda 日志是否有错误

#### 问题：无法创建群

- 检查 `im:chat:create` 权限是否已开通
- 检查权限是否已审批通过

#### 问题：用户名显示为"团队成员"

- 检查 `contact:user.base:readonly` 权限是否已开通
- 检查权限可用范围是否包含目标用户

#### 问题：无法解散群

- 检查 `im:chat` 和 `im:chat:delete` 权限是否已开通
- 只有群创建者可以解散群

---

## 功能与权限对照表

| 功能 | 所需权限 |
|-----|---------|
| 显示用户真实姓名 | `contact:user.base:readonly` |
| 创建工单群 | `im:chat:create` |
| 解散工单群 | `im:chat`, `im:chat:delete` |
| 添加/移除群成员 | `im:chat.members:write_only` |
| 发送消息 | `im:message`, `im:message:send_as_bot` |
| 接收 @机器人 消息 | `im:message.group_at_msg:readonly` |
| 同步群消息到 AWS | `im:message.group_msg:readonly` |
| 处理附件 | `im:resource`, `im:resource:readonly`, `im:message.file:readonly` |

---

## 参考链接

- [Lark 开放平台](https://open.larksuite.com/)
- [权限管理文档](https://open.larksuite.com/document/home/introduction-to-scope-and-authorization/scope-introduction)
- [事件订阅文档](https://open.larksuite.com/document/ukTMukTMukTM/uUTNz4SN1MjL1UzM)
- [机器人开发指南](https://open.larksuite.com/document/home/develop-a-bot-in-5-minutes/create-an-app)

---

**最后更新**: 2025-12-03
