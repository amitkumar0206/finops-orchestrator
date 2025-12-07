#!/bin/bash

# Cleanup Orphaned FinOps Resources
# This script removes orphaned VPCs, security groups, and network interfaces
# that weren't deleted by CloudFormation

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

AWS_REGION="us-east-1"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo ""
echo "======================================================================"
echo "           Cleanup Orphaned FinOps Resources"
echo "======================================================================"
echo ""

# Find all finops-related VPCs
log_info "Finding orphaned VPCs..."
VPCS=$(aws ec2 describe-vpcs --region "$AWS_REGION" \
    --filters "Name=tag:Name,Values=*finops*" \
    --query 'Vpcs[].VpcId' --output text 2>/dev/null || echo "")

if [ -z "$VPCS" ]; then
    log_success "No orphaned VPCs found"
    exit 0
fi

VPC_ARRAY=($VPCS)
log_warning "Found ${#VPC_ARRAY[@]} orphaned VPC(s): ${VPCS}"

echo ""
echo "The following resources will be deleted:"
for vpc in $VPCS; do
    VPC_NAME=$(aws ec2 describe-vpcs --region "$AWS_REGION" --vpc-ids "$vpc" \
        --query 'Vpcs[0].Tags[?Key==`Name`].Value' --output text 2>/dev/null || echo "Unknown")
    echo "  - VPC: $vpc ($VPC_NAME)"
    
    # List security groups in this VPC
    SG_COUNT=$(aws ec2 describe-security-groups --region "$AWS_REGION" \
        --filters "Name=vpc-id,Values=$vpc" "Name=group-name,Values=finops-*" \
        --query 'SecurityGroups[].GroupId' --output text 2>/dev/null | wc -w)
    echo "    └─ Security Groups: $SG_COUNT"
done

echo ""
read -p "Do you want to proceed with cleanup? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    log_info "Cleanup cancelled"
    exit 0
fi

echo ""
log_info "Starting cleanup process..."

# Process each VPC
for vpc in $VPCS; do
    log_info "Processing VPC: $vpc"
    
    # 1. Delete NAT Gateways
    log_info "  Checking for NAT Gateways..."
    NAT_GATEWAYS=$(aws ec2 describe-nat-gateways --region "$AWS_REGION" \
        --filter "Name=vpc-id,Values=$vpc" "Name=state,Values=available" \
        --query 'NatGateways[].NatGatewayId' --output text 2>/dev/null || echo "")
    
    if [ -n "$NAT_GATEWAYS" ]; then
        for nat in $NAT_GATEWAYS; do
            log_info "    Deleting NAT Gateway: $nat"
            aws ec2 delete-nat-gateway --nat-gateway-id "$nat" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete NAT Gateway: $nat"
        done
        log_info "    Waiting for NAT Gateways to delete (this may take a few minutes)..."
        sleep 30
    fi
    
    # 2. Release Elastic IPs
    log_info "  Checking for Elastic IPs..."
    EIP_ALLOCS=$(aws ec2 describe-addresses --region "$AWS_REGION" \
        --filters "Name=domain,Values=vpc" \
        --query 'Addresses[?NetworkInterfaceId==`null`].AllocationId' --output text 2>/dev/null || echo "")
    
    if [ -n "$EIP_ALLOCS" ]; then
        for alloc in $EIP_ALLOCS; do
            log_info "    Releasing Elastic IP: $alloc"
            aws ec2 release-address --allocation-id "$alloc" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to release EIP: $alloc"
        done
    fi
    
    # 3. Delete Network Interfaces
    log_info "  Checking for Network Interfaces..."
    ENIS=$(aws ec2 describe-network-interfaces --region "$AWS_REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'NetworkInterfaces[?Status!=`in-use`].NetworkInterfaceId' --output text 2>/dev/null || echo "")
    
    if [ -n "$ENIS" ]; then
        for eni in $ENIS; do
            log_info "    Deleting ENI: $eni"
            aws ec2 delete-network-interface --network-interface-id "$eni" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete ENI: $eni (may be in use)"
        done
    fi
    
    # 4. Delete Load Balancers
    log_info "  Checking for Load Balancers..."
    LBAS=$(aws elbv2 describe-load-balancers --region "$AWS_REGION" \
        --query "LoadBalancers[?VpcId=='$vpc'].LoadBalancerArn" --output text 2>/dev/null || echo "")
    
    if [ -n "$LBAS" ]; then
        for lb in $LBAS; do
            log_info "    Deleting Load Balancer: $lb"
            aws elbv2 delete-load-balancer --load-balancer-arn "$lb" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete Load Balancer: $lb"
        done
        log_info "    Waiting for Load Balancers to delete..."
        sleep 30
    fi
    
    # 5. Delete Target Groups
    log_info "  Checking for Target Groups..."
    TGS=$(aws elbv2 describe-target-groups --region "$AWS_REGION" \
        --query "TargetGroups[?VpcId=='$vpc'].TargetGroupArn" --output text 2>/dev/null || echo "")
    
    if [ -n "$TGS" ]; then
        for tg in $TGS; do
            log_info "    Deleting Target Group: $tg"
            aws elbv2 delete-target-group --target-group-arn "$tg" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete Target Group: $tg"
        done
    fi
    
    # 6. Delete RDS Instances
    log_info "  Checking for RDS Instances..."
    RDS_INSTANCES=$(aws rds describe-db-instances --region "$AWS_REGION" \
        --query "DBInstances[?DBSubnetGroup.VpcId=='$vpc'].DBInstanceIdentifier" --output text 2>/dev/null || echo "")
    
    if [ -n "$RDS_INSTANCES" ]; then
        for db in $RDS_INSTANCES; do
            log_info "    Deleting RDS Instance: $db"
            aws rds delete-db-instance --db-instance-identifier "$db" \
                --skip-final-snapshot --delete-automated-backups \
                --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete RDS Instance: $db"
        done
        log_info "    Waiting for RDS instances to delete (this may take several minutes)..."
        sleep 60
    fi
    
    # 7. Delete Security Groups (non-default)
    log_info "  Deleting Security Groups..."
    
    # Get all security groups except default
    SG_IDS=$(aws ec2 describe-security-groups --region "$AWS_REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'SecurityGroups[?GroupName!=`default`].GroupId' --output text 2>/dev/null || echo "")
    
    if [ -n "$SG_IDS" ]; then
        # First pass: Remove all ingress rules to break dependencies
        for sg in $SG_IDS; do
            log_info "    Removing ingress rules from: $sg"
            aws ec2 revoke-security-group-ingress --group-id "$sg" \
                --security-group-rule-ids $(aws ec2 describe-security-group-rules \
                    --region "$AWS_REGION" \
                    --filters "Name=group-id,Values=$sg" \
                    --query 'SecurityGroupRules[?IsEgress==`false`].SecurityGroupRuleId' \
                    --output text 2>/dev/null) \
                --region "$AWS_REGION" 2>/dev/null || true
        done
        
        # Second pass: Delete security groups
        for sg in $SG_IDS; do
            SG_NAME=$(aws ec2 describe-security-groups --region "$AWS_REGION" \
                --group-ids "$sg" --query 'SecurityGroups[0].GroupName' --output text 2>/dev/null || echo "Unknown")
            log_info "    Deleting Security Group: $sg ($SG_NAME)"
            aws ec2 delete-security-group --group-id "$sg" --region "$AWS_REGION" 2>/dev/null && \
                log_success "      ✓ Deleted" || \
                log_error "      ✗ Failed (may have dependencies)"
        done
    fi
    
    # 8. Delete Subnets
    log_info "  Deleting Subnets..."
    SUBNETS=$(aws ec2 describe-subnets --region "$AWS_REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'Subnets[].SubnetId' --output text 2>/dev/null || echo "")
    
    if [ -n "$SUBNETS" ]; then
        for subnet in $SUBNETS; do
            log_info "    Deleting Subnet: $subnet"
            aws ec2 delete-subnet --subnet-id "$subnet" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete Subnet: $subnet"
        done
    fi
    
    # 9. Detach and Delete Internet Gateways
    log_info "  Checking for Internet Gateways..."
    IGWS=$(aws ec2 describe-internet-gateways --region "$AWS_REGION" \
        --filters "Name=attachment.vpc-id,Values=$vpc" \
        --query 'InternetGateways[].InternetGatewayId' --output text 2>/dev/null || echo "")
    
    if [ -n "$IGWS" ]; then
        for igw in $IGWS; do
            log_info "    Detaching Internet Gateway: $igw"
            aws ec2 detach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$vpc" --region "$AWS_REGION" 2>/dev/null || true
            log_info "    Deleting Internet Gateway: $igw"
            aws ec2 delete-internet-gateway --internet-gateway-id "$igw" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete Internet Gateway: $igw"
        done
    fi
    
    # 10. Delete Route Tables (non-main)
    log_info "  Deleting Route Tables..."
    ROUTE_TABLES=$(aws ec2 describe-route-tables --region "$AWS_REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'RouteTables[?Associations[0].Main!=`true`].RouteTableId' --output text 2>/dev/null || echo "")
    
    if [ -n "$ROUTE_TABLES" ]; then
        for rt in $ROUTE_TABLES; do
            log_info "    Deleting Route Table: $rt"
            aws ec2 delete-route-table --route-table-id "$rt" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete Route Table: $rt"
        done
    fi
    
    # 11. Delete VPC Endpoints
    log_info "  Checking for VPC Endpoints..."
    VPC_ENDPOINTS=$(aws ec2 describe-vpc-endpoints --region "$AWS_REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'VpcEndpoints[].VpcEndpointId' --output text 2>/dev/null || echo "")
    
    if [ -n "$VPC_ENDPOINTS" ]; then
        for endpoint in $VPC_ENDPOINTS; do
            log_info "    Deleting VPC Endpoint: $endpoint"
            aws ec2 delete-vpc-endpoints --vpc-endpoint-ids "$endpoint" --region "$AWS_REGION" 2>/dev/null || \
                log_warning "    Failed to delete VPC Endpoint: $endpoint"
        done
    fi
    
    # 12. Finally, delete the VPC
    log_info "  Deleting VPC: $vpc"
    aws ec2 delete-vpc --vpc-id "$vpc" --region "$AWS_REGION" 2>/dev/null && \
        log_success "  ✓ VPC deleted successfully" || \
        log_error "  ✗ Failed to delete VPC (may still have dependencies)"
    
    echo ""
done

log_success "Cleanup process completed!"
echo ""
log_info "Verifying remaining resources..."

# Final verification
REMAINING_VPCS=$(aws ec2 describe-vpcs --region "$AWS_REGION" \
    --filters "Name=tag:Name,Values=*finops*" \
    --query 'Vpcs[].VpcId' --output text 2>/dev/null || echo "")

if [ -z "$REMAINING_VPCS" ]; then
    log_success "✓ All orphaned VPCs have been removed"
else
    log_warning "⚠ Some VPCs could not be deleted: $REMAINING_VPCS"
    log_info "You may need to manually investigate and remove remaining dependencies"
fi

REMAINING_SGS=$(aws ec2 describe-security-groups --region "$AWS_REGION" \
    --filters "Name=group-name,Values=finops-*" \
    --query 'SecurityGroups[].GroupId' --output text 2>/dev/null || echo "")

if [ -z "$REMAINING_SGS" ]; then
    log_success "✓ All orphaned security groups have been removed"
else
    log_warning "⚠ Some security groups could not be deleted: $REMAINING_SGS"
fi

echo ""
echo "======================================================================"
echo "                    Cleanup Summary Complete"
echo "======================================================================"
