#!/bin/bash
set -e

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${GREEN}🚀 Lark Case Bot - Deploy All Lambda Functions${NC}"
echo "=================================="

# Check lambda directory
if [ ! -d "$PROJECT_DIR/lambda" ]; then
    echo -e "${RED}❌ Error: lambda directory not found${NC}"
    exit 1
fi

# Package code
echo -e "${YELLOW}📦 Packaging Lambda code...${NC}"
cd "$PROJECT_DIR/lambda"
zip -q -r "$PROJECT_DIR/function.zip" *.py
cd "$PROJECT_DIR"
echo -e "${GREEN}✓ Code packaging complete${NC}"
echo ""

# Deploy function
deploy_function() {
    local search_pattern=$1
    local display_name=$2
    
    echo -e "${YELLOW}📋 Finding $display_name...${NC}"
    FUNCTION_NAME=$(aws lambda list-functions \
        --query "Functions[?contains(FunctionName, '$search_pattern')].FunctionName" \
        --output text 2>/dev/null | head -1)
    
    if [ -z "$FUNCTION_NAME" ]; then
        echo -e "${RED}❌ $display_name not found${NC}"
        return 1
    fi
    
    echo -e "${GREEN}✓ Found: $FUNCTION_NAME${NC}"
    
    echo -e "${YELLOW}⬆️  Uploading code...${NC}"
    UPDATE_RESULT=$(aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb://function.zip \
        --query 'LastUpdateStatus' \
        --output text \
        --no-cli-pager 2>&1)
    
    if [ "$UPDATE_RESULT" == "InProgress" ] || [ "$UPDATE_RESULT" == "Successful" ]; then
        echo -e "${GREEN}✓ $display_name upload successful${NC}"
        
        # Wait for update to complete
        sleep 2
        STATUS=$(aws lambda get-function-configuration \
            --function-name "$FUNCTION_NAME" \
            --query 'LastUpdateStatus' \
            --output text \
            --no-cli-pager 2>/dev/null)
        
        if [ "$STATUS" == "Successful" ]; then
            echo -e "${GREEN}✓ $display_name update complete${NC}"
        else
            echo -e "${YELLOW}⚠️  $display_name update status: $STATUS${NC}"
        fi
    else
        echo -e "${RED}❌ $display_name upload failed: $UPDATE_RESULT${NC}"
        return 1
    fi
    
    echo ""
    return 0
}

# Deploy all Lambda functions
FAILED=0

deploy_function "MsgEventLambda" "Message Event Handler" || ((FAILED++))
deploy_function "CasePoller" "Case Poller" || ((FAILED++))
deploy_function "CaseUpdate" "Case Update Handler" || ((FAILED++))

# Clean up temporary files
echo -e "${YELLOW}🧹 Cleaning up temporary files...${NC}"
rm -f "$PROJECT_DIR/function.zip"
echo -e "${GREEN}✓ Cleanup complete${NC}"
echo ""

# Summary
echo "=================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All Lambda functions deployed successfully!${NC}"
else
    echo -e "${RED}❌ $FAILED function(s) failed to deploy${NC}"
    exit 1
fi
echo ""
echo -e "${YELLOW}💡 Tips:${NC}"
echo "- View logs: aws logs tail /aws/lambda/<FUNCTION_NAME> --follow"
echo "- Test: ./scripts/test-all.sh"
