#!/bin/bash

# Full CDK deployment script (S3 Storage Version)
# For initial deployment or updating the entire stack (Lambda, API Gateway, S3, etc.)
#
# IMPORTANT: This stack MUST be deployed to us-east-1 region.
# - AWS Support API is only available in us-east-1
# - AWS Support EventBridge events are only sent to us-east-1
# - The region is hardcoded in app.py to ensure correct deployment
#
# Usage:
#   ./deploy.sh                          # Deploy with default settings
#   ./deploy.sh --auto-dissolve-hours 48 # Custom auto-dissolve time

set -e

# Parse arguments
AUTO_DISSOLVE_HOURS=72

while [[ $# -gt 0 ]]; do
    case $1 in
        --auto-dissolve-hours)
            AUTO_DISSOLVE_HOURS="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --auto-dissolve-hours N  Hours to wait before auto-dissolving resolved case groups (default: 72)"
            echo "  --help                   Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "🚀 Starting Lark Case Bot Stack deployment..."
echo ""
echo "⚠️  IMPORTANT: This stack will be deployed to us-east-1 (hardcoded)"
echo "   AWS Support API and EventBridge events are only available in us-east-1"
echo "⏰ Auto-dissolve: ${AUTO_DISSOLVE_HOURS} hours after case resolution"
echo ""

# Check if in correct directory
if [ ! -f "app.py" ]; then
    echo "❌ Error: Please run this script from the lark_case_bot_py directory"
    exit 1
fi

# Check AWS credentials
echo "🔐 Checking AWS credentials..."
if ! aws sts get-caller-identity &> /dev/null; then
    echo "❌ Error: AWS credentials not configured or expired"
    echo "Please run: aws configure"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
# Force us-east-1 region for AWS Support API compatibility
REGION="us-east-1"

echo "✅ AWS Account: $ACCOUNT_ID"
echo "✅ AWS Region: $REGION (hardcoded for AWS Support API)"

# Check Python dependencies
echo "📦 Checking Python dependencies..."
if [ ! -d ".venv" ]; then
    echo "⚠️  Virtual environment not found, creating..."
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

# Bootstrap CDK (if needed)
echo "🔧 Checking CDK Bootstrap..."
if ! aws cloudformation describe-stacks --stack-name CDKToolkit &> /dev/null; then
    echo "⚠️  CDK not bootstrapped, running bootstrap..."
    cdk bootstrap aws://$ACCOUNT_ID/$REGION
else
    echo "✅ CDK already bootstrapped"
fi

# Synthesize CloudFormation template
echo "🔨 Synthesizing CloudFormation template..."
cdk synth

# Show changes to be deployed
echo ""
echo "📋 Reviewing changes to be deployed..."
cdk diff || true

# Confirm deployment
echo ""
read -p "Continue with deployment? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Deployment cancelled"
    exit 0
fi

# Deploy
echo ""
echo "🚀 Starting deployment..."
cdk deploy --require-approval never --parameters AutoDissolveHours=$AUTO_DISSOLVE_HOURS

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Update Lark App ID and App Secret in Secrets Manager"
echo "   2. Configure Bot settings in S3 bucket (account info)"
echo "   3. Configure Webhook URL in Lark Open Platform"
echo "   4. Test the bot functionality"
echo ""
echo "💡 View output info:"
echo "   aws cloudformation describe-stacks --stack-name LarkCaseBotStack --query 'Stacks[0].Outputs'"
echo ""
