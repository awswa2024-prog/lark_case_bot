#!/bin/bash

# Comprehensive test script - Test all Lambda functions (S3 Storage Version)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "🧪 Lark Case Bot (S3 Storage) - Comprehensive Test"
echo "================================"
echo ""

# Color definitions
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test functions
test_webhook() {
    echo -e "${YELLOW}📨 Testing Webhook Handler...${NC}"
    
    WEBHOOK_URL=$(aws cloudformation describe-stacks \
        --stack-name LarkCaseBotStack \
        --query 'Stacks[0].Outputs[?OutputKey==`webhookUrl`].OutputValue' \
        --output text)
    
    if [ -z "$WEBHOOK_URL" ]; then
        echo -e "${RED}❌ Failed to get Webhook URL${NC}"
        return 1
    fi
    
    echo "Webhook URL: $WEBHOOK_URL"
    
    # Send test request
    RESPONSE=$(curl -s -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d '{"challenge":"test123"}')
    
    if echo "$RESPONSE" | grep -q "test123"; then
        echo -e "${GREEN}✅ Webhook test passed${NC}"
        return 0
    else
        echo -e "${RED}❌ Webhook test failed${NC}"
        echo "Response: $RESPONSE"
        return 1
    fi
}

test_case_poller() {
    echo -e "${YELLOW}🔄 Testing Case Poller...${NC}"
    
    FUNCTION_NAME=$(aws lambda list-functions \
        --query 'Functions[?contains(FunctionName, `CasePoller`)].FunctionName' \
        --output text | head -1)
    
    if [ -z "$FUNCTION_NAME" ]; then
        echo -e "${RED}❌ Case Poller Lambda not found${NC}"
        return 1
    fi
    
    echo "Function: $FUNCTION_NAME"
    
    # Invoke Lambda
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload '{}' \
        /tmp/poller-response.json > /dev/null
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Case Poller invocation successful${NC}"
        cat /tmp/poller-response.json | jq '.'
        rm -f /tmp/poller-response.json
        return 0
    else
        echo -e "${RED}❌ Case Poller invocation failed${NC}"
        return 1
    fi
}

test_case_update_handler() {
    echo -e "${YELLOW}📢 Testing Case Update Handler...${NC}"
    
    FUNCTION_NAME=$(aws lambda list-functions \
        --query 'Functions[?contains(FunctionName, `CaseUpdate`)].FunctionName' \
        --output text | head -1)
    
    if [ -z "$FUNCTION_NAME" ]; then
        echo -e "${RED}❌ Case Update Handler Lambda not found${NC}"
        return 1
    fi
    
    echo "Function: $FUNCTION_NAME"
    
    # Create test event
    cat > /tmp/test-event.json <<'EOF'
{
  "version": "0",
  "id": "test-event-id",
  "detail-type": "Support Case Update",
  "source": "aws.support",
  "account": "123456789012",
  "time": "2025-11-27T10:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "event-name": "AddCommunicationToCase",
    "case-id": "case-test-123",
    "display-id": "12345678",
    "communication-id": "comm-test-123",
    "origin": "AWS"
  }
}
EOF
    
    # Invoke Lambda
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload file:///tmp/test-event.json \
        /tmp/update-response.json > /dev/null
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Case Update Handler invocation successful${NC}"
        cat /tmp/update-response.json | jq '.'
        rm -f /tmp/test-event.json /tmp/update-response.json
        return 0
    else
        echo -e "${RED}❌ Case Update Handler invocation failed${NC}"
        rm -f /tmp/test-event.json
        return 1
    fi
}

# Main test flow
main() {
    local failed=0
    
    echo "Starting tests..."
    echo ""
    
    # Test Webhook
    if ! test_webhook; then
        ((failed++))
    fi
    echo ""
    
    # Test Case Poller
    if ! test_case_poller; then
        ((failed++))
    fi
    echo ""
    
    # Test Case Update Handler
    if ! test_case_update_handler; then
        ((failed++))
    fi
    echo ""
    
    # Summary
    echo "================================"
    if [ $failed -eq 0 ]; then
        echo -e "${GREEN}✅ All tests passed!${NC}"
        return 0
    else
        echo -e "${RED}❌ $failed test(s) failed${NC}"
        return 1
    fi
}

# Run tests
main
