#!/bin/bash

set -e

REGION="us-east-1"
STACK_NAME="LarkCaseBotStack"

echo "=== Cleaning up Lark Case Bot resources ==="
echo ""

# Read accounts from accounts.json
ACCOUNTS=$(cat accounts.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
for acc in data['accounts']:
    print(f\"{acc['profile']}|{acc['account_name']}|{acc['account_id']}\")
")

for line in $ACCOUNTS; do
    IFS='|' read -r PROFILE ACCOUNT_NAME ACCOUNT_ID <<< "$line"
    
    echo "----------------------------------------"
    echo "Account: $ACCOUNT_NAME ($ACCOUNT_ID)"
    echo "Profile: $PROFILE"
    echo "----------------------------------------"
    
    # Check if stack exists
    if aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --region $REGION \
        --profile $PROFILE \
        --no-cli-pager 2>/dev/null; then
        
        echo "✓ Stack found. Deleting..."
        
        # Delete the stack
        aws cloudformation delete-stack \
            --stack-name $STACK_NAME \
            --region $REGION \
            --profile $PROFILE \
            --no-cli-pager
        
        echo "⏳ Waiting for stack deletion to complete..."
        aws cloudformation wait stack-delete-complete \
            --stack-name $STACK_NAME \
            --region $REGION \
            --profile $PROFILE \
            --no-cli-pager
        
        echo "✅ Stack deleted successfully"
    else
        echo "ℹ️  No stack found (already deleted or never deployed)"
    fi
    
    echo ""
done

echo "=== Cleanup complete ==="
