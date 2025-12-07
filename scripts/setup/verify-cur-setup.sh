#!/bin/bash

# FinOps Platform - CUR Setup Verification Script
# This script checks what CUR-related resources have been created

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

echo ""
echo "======================================================================"
echo "     FinOps Platform - CUR Setup Verification"
echo "======================================================================"
echo ""

# Load configuration if it exists
if [ -f "cur-config.env" ]; then
    source cur-config.env
    log_info "Loaded configuration from cur-config.env"
    echo ""
else
    log_warning "cur-config.env not found - CUR may not have been configured"
    CUR_BUCKET_NAME=""
    EXPORT_NAME="finops-cost-export"
    GLUE_CRAWLER="finops-cost-export-crawler"
fi

echo "📊 Checking CUR Resources..."
echo ""

# 1. Check CUR Reports
log_info "Checking CUR Reports..."
CUR_REPORTS=$(aws cur describe-report-definitions --region us-east-1 --output json 2>/dev/null || echo '{"ReportDefinitions":[]}')
CUR_COUNT=$(echo "$CUR_REPORTS" | jq -r '.ReportDefinitions | length')

if [ "$CUR_COUNT" -gt 0 ]; then
    log_success "Found $CUR_COUNT CUR report(s)"
    echo "$CUR_REPORTS" | jq -r '.ReportDefinitions[] | "  - \(.ReportName): s3://\(.S3Bucket)/\(.S3Prefix) (\(.Format))"'
    
    if [ -n "$EXPORT_NAME" ]; then
        if echo "$CUR_REPORTS" | jq -r '.ReportDefinitions[].ReportName' | grep -q "^${EXPORT_NAME}$"; then
            log_success "Target CUR report '$EXPORT_NAME' exists"
        else
            log_warning "Target CUR report '$EXPORT_NAME' NOT found"
        fi
    fi
else
    log_error "No CUR reports found"
    log_info "CUR must be created for historical data access"
fi
echo ""

# 2. Check S3 Buckets
log_info "Checking S3 Buckets..."
if [ -n "$CUR_BUCKET_NAME" ]; then
    if aws s3 ls "s3://$CUR_BUCKET_NAME" &>/dev/null; then
        log_success "S3 bucket exists: $CUR_BUCKET_NAME"
        
        # Check for CUR data
        CUR_DATA_COUNT=$(aws s3 ls "s3://$CUR_BUCKET_NAME/cost-exports/" --recursive 2>/dev/null | wc -l || echo "0")
        if [ "$CUR_DATA_COUNT" -gt 0 ]; then
            log_success "Found $CUR_DATA_COUNT CUR data files in bucket"
        else
            log_warning "No CUR data files found yet (wait 24 hours after CUR creation)"
        fi
    else
        log_error "S3 bucket NOT found: $CUR_BUCKET_NAME"
    fi
else
    log_warning "No bucket name in config"
fi
echo ""

# 3. Check Glue Database
log_info "Checking Glue Database..."
if aws glue get-database --name cost_usage_db --region us-east-1 &>/dev/null; then
    log_success "Glue database exists: cost_usage_db"
    
    # Check for tables
    TABLE_COUNT=$(aws glue get-tables --database-name cost_usage_db --region us-east-1 2>/dev/null | jq -r '.TableList | length' || echo "0")
    if [ "$TABLE_COUNT" -gt 0 ]; then
        log_success "Found $TABLE_COUNT table(s) in Glue database"
        aws glue get-tables --database-name cost_usage_db --region us-east-1 | jq -r '.TableList[] | "  - \(.Name) (\(.StorageDescriptor.Location))"'
    else
        log_warning "No tables found (run Glue crawler after CUR data is generated)"
    fi
else
    log_error "Glue database NOT found: cost_usage_db"
fi
echo ""

# 4. Check Glue Crawlers
log_info "Checking Glue Crawlers..."
if [ -n "$GLUE_CRAWLER" ]; then
    CRAWLER_INFO=$(aws glue get-crawler --name "$GLUE_CRAWLER" --region us-east-1 2>/dev/null || echo "{}")
    if echo "$CRAWLER_INFO" | jq -e '.Crawler' &>/dev/null; then
        log_success "Glue crawler exists: $GLUE_CRAWLER"
        CRAWLER_STATE=$(echo "$CRAWLER_INFO" | jq -r '.Crawler.State')
        LAST_CRAWL=$(echo "$CRAWLER_INFO" | jq -r '.Crawler.LastCrawl.Status // "Never run"')
        echo "  - State: $CRAWLER_STATE"
        echo "  - Last crawl: $LAST_CRAWL"
    else
        log_error "Glue crawler NOT found: $GLUE_CRAWLER"
    fi
else
    log_warning "No crawler name in config"
fi
echo ""

# 5. Check Athena Workgroup
log_info "Checking Athena Workgroup..."
if aws athena get-work-group --work-group finops-workgroup --region us-east-1 &>/dev/null; then
    log_success "Athena workgroup exists: finops-workgroup"
else
    log_error "Athena workgroup NOT found: finops-workgroup"
fi
echo ""

# Summary
echo "======================================================================"
echo "     Summary"
echo "======================================================================"
echo ""

ALL_GOOD=true

if [ "$CUR_COUNT" -eq 0 ]; then
    log_error "CUR Report: NOT CONFIGURED"
    ALL_GOOD=false
else
    log_success "CUR Report: CONFIGURED"
fi

if [ -n "$CUR_BUCKET_NAME" ] && aws s3 ls "s3://$CUR_BUCKET_NAME" &>/dev/null; then
    log_success "S3 Bucket: EXISTS"
else
    log_error "S3 Bucket: NOT FOUND"
    ALL_GOOD=false
fi

if aws glue get-database --name cost_usage_db --region us-east-1 &>/dev/null; then
    log_success "Glue Database: EXISTS"
else
    log_error "Glue Database: NOT FOUND"
    ALL_GOOD=false
fi

if aws athena get-work-group --work-group finops-workgroup --region us-east-1 &>/dev/null; then
    log_success "Athena Workgroup: EXISTS"
else
    log_error "Athena Workgroup: NOT FOUND"
    ALL_GOOD=false
fi

echo ""

if [ "$ALL_GOOD" = true ]; then
    log_success "✅ All CUR infrastructure is set up correctly!"
    echo ""
    if [ "$CUR_DATA_COUNT" -gt 0 ]; then
        log_success "✅ CUR data is available - ready for queries"
    else
        log_warning "⏰ Waiting for first CUR data (up to 24 hours)"
        log_info "Once data arrives, run: aws glue start-crawler --name $GLUE_CRAWLER --region us-east-1"
    fi
else
    log_error "❌ Some CUR resources are missing"
    echo ""
    log_info "To fix, run: scripts/setup/setup-cur.sh"
fi

echo ""
log_info "💡 Platform works with Cost Explorer API (13 months) even without CUR"
echo ""
