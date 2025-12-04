#!/usr/bin/env python3
"""
CDK Application Entry Point

This is the main entry point for the AWS CDK application.
It creates and synthesizes the LarkCaseBotStack which deploys all required
AWS resources for the Lark bot integration with AWS Support.

IMPORTANT: This stack MUST be deployed to us-east-1 region.
AWS Support API and EventBridge events are only available in us-east-1.

Usage:
    cdk deploy    - Deploy the stack to AWS (us-east-1 only)
    cdk synth     - Synthesize CloudFormation template
    cdk diff      - Show changes between deployed and local stack
"""
import aws_cdk as cdk
from lark_case_bot_stack import LarkCaseBotStack

app = cdk.App()

# IMPORTANT: Must deploy to us-east-1
# - AWS Support API is only available in us-east-1
# - AWS Support EventBridge events are only sent to us-east-1
LarkCaseBotStack(app, "LarkCaseBotStack",
    description="Lark Bot for AWS Support Case Creation with Cost Explorer Integration",
    env=cdk.Environment(region="us-east-1")
)

app.synth()
