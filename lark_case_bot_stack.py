"""
AWS CDK Infrastructure Stack for Lark Case Bot (S3 Storage Version)

IMPORTANT: This stack MUST be deployed to us-east-1 region.
- AWS Support API is only available in us-east-1
- AWS Support EventBridge events are only sent to us-east-1
- Deploying to other regions will result in missing EventBridge notifications

This module defines the complete AWS infrastructure for the Lark bot:

Resources Created:
- Secrets Manager: Stores Lark App ID and App Secret
- S3 Buckets:
  - DataBucket: Stores bot configuration and case tracking data as JSON files
    - config/{cfg_key}.json: Bot configuration
    - cases/{case_id}.json: Case data
    - indexes/chat_id/{chat_id}.json: Chat ID to case ID mapping
    - indexes/user_id/{user_id}.json: User ID to case IDs mapping
- Lambda Functions:
  - MsgEventLambda: Handles Lark message events (create case, reply, etc.)
  - CaseUpdateLambda: Handles AWS Support case update events from EventBridge
  - CasePollerLambda: Periodically polls case status for updates
- API Gateway: REST API endpoint for Lark webhook
- EventBridge: Rules for AWS Support case events and scheduled polling
- IAM Roles: Lambda execution roles with cross-account assume role permissions

Parameters:
- CaseLanguage: AWS Support case language (zh/ja/ko/en)
- CasePollInterval: Polling interval in minutes (1-60)
- UserWhitelist: Enable/disable user whitelist feature
"""
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnParameter,
    aws_lambda as lambda_,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    aws_s3 as s3,
    aws_events as events,
    aws_events_targets as targets,
    aws_logs as logs,
    CfnOutput,
)
from constructs import Construct

class LarkCaseBotStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Parameters
        case_language = CfnParameter(self, "CaseLanguage",
            type="String",
            default="zh",
            allowed_values=["zh", "ja", "ko", "en"],
            description="AWS Support case language"
        )
        
        case_poll_interval = CfnParameter(self, "CasePollInterval",
            type="Number",
            default=10,
            min_value=1,
            max_value=60,
            description="Case status polling interval in minutes (1-60)"
        )

        user_whitelist = CfnParameter(self, "UserWhitelist",
            type="String",
            default="false",
            allowed_values=["true", "false"],
            description="Enable user whitelist"
        )

        auto_dissolve_hours = CfnParameter(self, "AutoDissolveHours",
            type="Number",
            default=72,
            min_value=1,
            max_value=720,
            description="Hours to wait before auto-dissolving resolved case groups (1-720, default: 72)"
        )

        # Allowed AWS account IDs for cross-account Support API access
        # Comma-separated list of account IDs that Lambda can assume role into
        allowed_account_ids = CfnParameter(self, "AllowedAccountIds",
            type="String",
            default="",
            description="Comma-separated list of AWS account IDs allowed for cross-account Support API access (e.g., '123456789012,987654321098'). Leave empty to allow all accounts (not recommended for production)."
        )

        # Secrets Manager for Lark App ID
        app_id_secret = secretsmanager.Secret(self, "AppIDSecret",
            secret_name=f"{construct_id}-lark-app-id",
            description="Lark Bot App ID",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"app_id":"REPLACE_WITH_YOUR_APP_ID"}',
                generate_string_key="placeholder"
            )
        )

        # Secrets Manager for Lark App Secret
        app_secret_secret = secretsmanager.Secret(self, "AppSecretSecret",
            secret_name=f"{construct_id}-lark-app-secret",
            description="Lark Bot App Secret",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"app_secret":"REPLACE_WITH_YOUR_APP_SECRET"}',
                generate_string_key="placeholder"
            )
        )

        # Secrets Manager for Lark Encrypt Key (optional, for event decryption)
        encrypt_key_secret = secretsmanager.Secret(self, "EncryptKeySecret",
            secret_name=f"{construct_id}-lark-encrypt-key",
            description="Lark Bot Encrypt Key (optional, for event decryption)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"encrypt_key":""}',
                generate_string_key="placeholder"
            )
        )

        # Secrets Manager for Lark Verification Token (for request verification)
        verification_token_secret = secretsmanager.Secret(self, "VerificationTokenSecret",
            secret_name=f"{construct_id}-lark-verification-token",
            description="Lark Bot Verification Token (for request verification)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"verification_token":""}',
                generate_string_key="placeholder"
            )
        )

        # S3 bucket for bot data (config and cases)
        # Structure:
        #   config/{cfg_key}.json - Bot configuration
        #   cases/{case_id}.json - Case data
        #   indexes/chat_id/{chat_id}.json - Chat ID index
        #   indexes/user_id/{user_id}.json - User ID index
        data_bucket = s3.Bucket(self, "DataBucket",
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                # Auto-delete old versions after 30 days
                s3.LifecycleRule(
                    noncurrent_version_expiration=Duration.days(30)
                )
            ]
        )

        # EventBridge bus for case updates
        case_event_bus = events.EventBus(self, "CaseEventBus",
            event_bus_name=f"{construct_id}-case-event-bus"
        )

        # IAM role for message event Lambda
        msg_event_role = iam.Role(self, "MsgEventRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        # Note: AWSSupportAccessRole is optional and created manually for single-account setup
        # For cross-account setup, use LarkSupportCaseApiAll role in target accounts
        # See docs/manual-account-setup.md for details

        # Grant permissions
        app_id_secret.grant_read(msg_event_role)
        app_secret_secret.grant_read(msg_event_role)
        encrypt_key_secret.grant_read(msg_event_role)
        verification_token_secret.grant_read(msg_event_role)
        data_bucket.grant_read_write(msg_event_role)

        # Allow Lambda to assume roles for Support API
        # Note: For tighter security, specify AllowedAccountIds parameter during deployment
        # e.g., cdk deploy --parameters AllowedAccountIds="123456789012,210987654321"
        msg_event_role.add_to_policy(iam.PolicyStatement(
            sid="AllowToAssumeToRoleWithSupportAPIAccess",
            effect=iam.Effect.ALLOW,
            actions=["sts:AssumeRole"],
            resources=[
                "arn:aws:iam::*:role/LarkSupportCaseApiAll*",
                "arn:aws:iam::*:role/AWSSupportAccessRole"
            ]
        ))

        # Cost Explorer access removed - using static service list instead
        
        # Allow Lambda to invoke itself for async processing (avoid Lark webhook timeout)
        # Add policy BEFORE creating Lambda to avoid circular dependency
        msg_event_role.add_to_policy(iam.PolicyStatement(
            sid="AllowSelfInvoke",
            effect=iam.Effect.ALLOW,
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:*MsgEventLambda*"]
        ))

        # Message event Lambda function (urllib3 is included in boto3, no layer needed)
        # Note: log_retention removed to avoid circular dependency with API Gateway
        msg_event_lambda = lambda_.Function(self, "MsgEventLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="msg_event_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            role=msg_event_role,
            timeout=Duration.seconds(60),  # Increased to 60 seconds
            memory_size=1024,  # Increased to 1024 MB (more memory = faster CPU)
            environment={
                "APP_ID_ARN": app_id_secret.secret_arn,
                "APP_SECRET_ARN": app_secret_secret.secret_arn,
                "ENCRYPT_KEY_ARN": encrypt_key_secret.secret_arn,
                "VERIFICATION_TOKEN_ARN": verification_token_secret.secret_arn,
                "DATA_BUCKET": data_bucket.bucket_name,
                "CFG_KEY": "LarkBotProfile-0",
                "CASE_LANGUAGE": case_language.value_as_string,
                "USER_WHITELIST": user_whitelist.value_as_string,
            }
        )

        # Case update Lambda function (triggered by EventBridge)
        case_update_role = iam.Role(self, "CaseUpdateRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        app_id_secret.grant_read(case_update_role)
        app_secret_secret.grant_read(case_update_role)
        data_bucket.grant_read_write(case_update_role)
        
        # Allow assuming roles to fetch communication content
        case_update_role.add_to_policy(iam.PolicyStatement(
            sid="AllowAssumeRoleForCommunication",
            effect=iam.Effect.ALLOW,
            actions=["sts:AssumeRole"],
            resources=[
                "arn:aws:iam::*:role/AWSSupportAccessRole",
                "arn:aws:iam::*:role/LarkSupportCaseApiAll*"
            ]
        ))

        case_update_lambda = lambda_.Function(self, "CaseUpdateLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="case_update_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            role=case_update_role,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "APP_ID_ARN": app_id_secret.secret_arn,
                "APP_SECRET_ARN": app_secret_secret.secret_arn,
                "DATA_BUCKET": data_bucket.bucket_name,
                "AUTO_DISSOLVE_HOURS": str(auto_dissolve_hours.value_as_number),
            },
            log_retention=logs.RetentionDays.ONE_WEEK
        )

        # EventBridge rule for case updates (on default event bus)
        # AWS Support events are sent to the default event bus
        case_update_rule = events.Rule(self, "CaseUpdateRule",
            event_pattern=events.EventPattern(
                source=["aws.support"],
                detail_type=["Support Case Update"]
            ),
            description="Capture AWS Support case updates and push to Lark"
        )
        case_update_rule.add_target(targets.LambdaFunction(case_update_lambda))

        # Case Poller Lambda - Periodically checks case status across all accounts
        case_poller_role = iam.Role(self, "CasePollerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        app_id_secret.grant_read(case_poller_role)
        app_secret_secret.grant_read(case_poller_role)
        data_bucket.grant_read_write(case_poller_role)

        # Allow assuming roles in other accounts
        case_poller_role.add_to_policy(iam.PolicyStatement(
            sid="AllowAssumeRoleForCasePolling",
            effect=iam.Effect.ALLOW,
            actions=["sts:AssumeRole"],
            resources=[
                "arn:aws:iam::*:role/AWSSupportAccessRole",
                "arn:aws:iam::*:role/LarkSupportCaseApiAll*"
            ]
        ))

        case_poller_lambda = lambda_.Function(self, "CasePollerLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="case_poller.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            role=case_poller_role,
            timeout=Duration.seconds(300),
            memory_size=512,
            environment={
                "APP_ID_ARN": app_id_secret.secret_arn,
                "APP_SECRET_ARN": app_secret_secret.secret_arn,
                "DATA_BUCKET": data_bucket.bucket_name,
                "AUTO_DISSOLVE_HOURS": str(auto_dissolve_hours.value_as_number),
            },
            log_retention=logs.RetentionDays.ONE_WEEK
        )

        # Schedule: Use configurable polling interval
        case_poller_rule = events.Rule(self, "CasePollerRule",
            schedule=events.Schedule.rate(Duration.minutes(case_poll_interval.value_as_number)),
            description=f"Poll all accounts for case status updates (interval: {case_poll_interval.value_as_number} minutes)"
        )
        case_poller_rule.add_target(targets.LambdaFunction(case_poller_lambda))

        # Group Cleanup Lambda - Auto-dissolve resolved case groups
        group_cleanup_role = iam.Role(self, "GroupCleanupRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        app_id_secret.grant_read(group_cleanup_role)
        app_secret_secret.grant_read(group_cleanup_role)
        data_bucket.grant_read_write(group_cleanup_role)

        group_cleanup_lambda = lambda_.Function(self, "GroupCleanupLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="group_cleanup.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            role=group_cleanup_role,
            timeout=Duration.minutes(5),
            memory_size=256,
            environment={
                "APP_ID_ARN": app_id_secret.secret_arn,
                "APP_SECRET_ARN": app_secret_secret.secret_arn,
                "DATA_BUCKET": data_bucket.bucket_name,
                "AUTO_DISSOLVE_HOURS": str(auto_dissolve_hours.value_as_number),
            },
            log_retention=logs.RetentionDays.ONE_WEEK
        )

        # Schedule: Run every hour to check for groups to dissolve
        group_cleanup_rule = events.Rule(self, "GroupCleanupRule",
            schedule=events.Schedule.rate(Duration.hours(1)),
            description="Check and auto-dissolve resolved case groups"
        )
        group_cleanup_rule.add_target(targets.LambdaFunction(group_cleanup_lambda))

        # API Gateway
        api = apigw.RestApi(self, "LarkCaseBotApi",
            rest_api_name="Lark Case Bot API",
            description="API Gateway for Lark bot webhook",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_rate_limit=100,
                throttling_burst_limit=200,
                # Disable logging to avoid CloudWatch Logs role requirement
                logging_level=apigw.MethodLoggingLevel.OFF,
                data_trace_enabled=False
            )
        )

        # Add /messages endpoint
        messages = api.root.add_resource("messages")
        messages.add_method("POST", apigw.LambdaIntegration(msg_event_lambda))

        # Outputs
        CfnOutput(self, "WebhookUrl",
            value=f"{api.url}messages",
            description="Lark webhook URL (use this in Lark Open Platform)"
        )

        CfnOutput(self, "msgEventapiEndpoint",
            value=api.url,
            description="API Gateway endpoint (add /messages for webhook URL)"
        )

        CfnOutput(self, "msgEventRoleArn",
            value=msg_event_role.role_arn,
            description="Lambda role ARN for Support API assume role trust policy"
        )

        CfnOutput(self, "CaseEventBusArn",
            value=case_event_bus.event_bus_arn,
            description="EventBridge bus ARN for case update events"
        )

        CfnOutput(self, "DataBucketName",
            value=data_bucket.bucket_name,
            description="S3 bucket for bot configuration and case tracking"
        )

        CfnOutput(self, "DataBucketArn",
            value=data_bucket.bucket_arn,
            description="S3 bucket ARN for bot data"
        )

        CfnOutput(self, "AppIDSecretArn",
            value=app_id_secret.secret_arn,
            description="Secrets Manager ARN for Lark App ID"
        )

        CfnOutput(self, "AppSecretSecretArn",
            value=app_secret_secret.secret_arn,
            description="Secrets Manager ARN for Lark App Secret"
        )

        CfnOutput(self, "EncryptKeySecretArn",
            value=encrypt_key_secret.secret_arn,
            description="Secrets Manager ARN for Lark Encrypt Key"
        )

        CfnOutput(self, "VerificationTokenSecretArn",
            value=verification_token_secret.secret_arn,
            description="Secrets Manager ARN for Lark Verification Token"
        )

        # Note: AWSSupportAccessRole output removed - role is optional and created manually
        # For cross-account setup, create LarkSupportCaseApiAll role in target accounts
        
        CfnOutput(self, "CasePollIntervalOutput",
            value=case_poll_interval.value_as_string,
            description="Case status polling interval in minutes"
        )
        
        CfnOutput(self, "CasePollerRoleArn",
            value=case_poller_role.role_arn,
            description="Case Poller Lambda role ARN (add to trust policy in target accounts)"
        )
        
        CfnOutput(self, "AutoDissolveHoursOutput",
            value=str(auto_dissolve_hours.value_as_number),
            description="Hours to wait before auto-dissolving resolved case groups"
        )
