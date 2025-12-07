#!/bin/bash

# Verification script to check deployment.env has all required values
# including the database password

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo "  Deployment Configuration Verification"
echo "============================================"
echo ""

# Check if deployment.env exists
if [ ! -f deployment.env ]; then
    echo -e "${RED}✗ deployment.env not found${NC}"
    echo ""
    echo "Run './deploy.sh' first to create the deployment configuration"
    exit 1
fi

echo -e "${GREEN}✓ deployment.env exists${NC}"
echo ""

# Check required variables
REQUIRED_VARS=("STACK_NAME" "S3_BUCKET" "BEDROCK_MODEL" "BACKEND_IMAGE_URI" "FRONTEND_IMAGE_URI" "DB_PASSWORD")
MISSING_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
    if grep -q "^${var}=" deployment.env; then
        VALUE=$(grep "^${var}=" deployment.env | cut -d'=' -f2-)
        if [ -z "$VALUE" ]; then
            echo -e "${RED}✗ ${var} is empty${NC}"
            MISSING_VARS+=("$var")
        else
            if [ "$var" = "DB_PASSWORD" ]; then
                echo -e "${GREEN}✓ ${var} is set (length: ${#VALUE} chars)${NC}"
            else
                echo -e "${GREEN}✓ ${var}=${VALUE}${NC}"
            fi
        fi
    else
        echo -e "${RED}✗ ${var} not found${NC}"
        MISSING_VARS+=("$var")
    fi
done

echo ""

# Check if DB password matches SSM Parameter Store
echo "Comparing DB_PASSWORD with SSM Parameter Store..."
STACK_NAME=$(grep "^STACK_NAME=" deployment.env | cut -d'=' -f2-)
DB_PASSWORD_LOCAL=$(grep "^DB_PASSWORD=" deployment.env | cut -d'=' -f2-)

SSM_PASSWORD=$(aws ssm get-parameter \
    --name "/${STACK_NAME}/database/password" \
    --with-decryption \
    --region us-east-1 \
    --query 'Parameter.Value' \
    --output text 2>/dev/null || echo "")

if [ -z "$SSM_PASSWORD" ]; then
    echo -e "${YELLOW}⚠ Could not retrieve password from SSM Parameter Store${NC}"
    echo "  This is OK if you haven't deployed yet"
elif [ "$DB_PASSWORD_LOCAL" = "$SSM_PASSWORD" ]; then
    echo -e "${GREEN}✓ DB_PASSWORD matches SSM Parameter Store${NC}"
else
    echo -e "${RED}✗ DB_PASSWORD MISMATCH!${NC}"
    echo "  deployment.env password: ${DB_PASSWORD_LOCAL:0:10}..."
    echo "  SSM Parameter password:  ${SSM_PASSWORD:0:10}..."
    echo ""
    echo -e "${YELLOW}  Fix: Update deployment.env with correct password from SSM${NC}"
    MISSING_VARS+=("DB_PASSWORD_MISMATCH")
fi

echo ""
echo "============================================"

if [ ${#MISSING_VARS[@]} -eq 0 ]; then
    echo -e "${GREEN}✓ All configuration checks passed!${NC}"
    echo ""
    echo "Your deployment.env is correctly configured."
    exit 0
else
    echo -e "${RED}✗ Configuration issues found${NC}"
    echo ""
    echo "Please fix the above issues before redeploying."
    exit 1
fi
