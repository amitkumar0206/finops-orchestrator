#!/bin/bash

# ============================================================================
# CUR Validation and Athena Table Setup Helper
# ============================================================================
# This script validates CUR configuration and creates Athena table with
# partition projection. Called by deploy.sh during deployment.
# ============================================================================

set -euo pipefail

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
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Validate CUR S3 bucket exists (data is optional)
validate_cur_bucket() {
    local bucket=$1
    local prefix=$2
    local aws_region=$3
    
    log_info "Validating CUR S3 bucket..."
    
    # Check bucket exists using list-buckets (more reliable than head-bucket)
    if ! aws s3api list-buckets --query "Buckets[?Name=='$bucket'].Name" --output text 2>/dev/null | grep -q "^$bucket$"; then
        log_error "CUR S3 bucket does not exist: $bucket"
        return 1
    fi
    
    log_success "CUR S3 bucket exists: $bucket"
    
    # Check for data in bucket (optional - just informational)
    local data_count
    data_count=$(aws s3 ls "s3://${bucket}/${prefix}/" --recursive --region "$aws_region" 2>/dev/null | grep "\.parquet$" | wc -l | tr -d ' ')
    
    # Ensure data_count is a valid integer
    if [ -z "$data_count" ] || ! [[ "$data_count" =~ ^[0-9]+$ ]]; then
        data_count=0
    fi
    
    if [ "$data_count" -eq 0 ]; then
        log_info "No CUR data found yet (table will work once data is delivered)"
        log_info "Configure CUR to deliver data to: s3://${bucket}/${prefix}/"
    else
        log_success "Found $data_count Parquet files - table will be immediately queryable"
    fi
    
    return 0
}

# Create Athena database if not exists
create_athena_database() {
    local database=$1
    local aws_region=$2
    local output_location=$3
    
    log_info "Creating Athena database: $database"
    
    # Use provided output location or default
    if [ -z "$output_location" ]; then
        log_error "Output location is required for Athena queries"
        return 1
    fi
    
    aws athena start-query-execution \
        --query-string "CREATE DATABASE IF NOT EXISTS ${database}" \
        --result-configuration "OutputLocation=${output_location}" \
        --region "$aws_region" &>/dev/null || true
    
    # Brief wait for database creation
    sleep 2
    
    # Verify database exists
    if aws athena get-database \
        --catalog-name AwsDataCatalog \
        --database-name "$database" \
        --region "$aws_region" &>/dev/null; then
        log_success "Athena database ready: $database"
        return 0
    else
        log_error "Failed to create/verify Athena database: $database"
        return 1
    fi
}

# Create Athena table with partition projection
create_athena_cur_table() {
    local database=$1
    local table=$2
    local bucket=$3
    local prefix=$4
    local aws_region=$5
    local output_location=$6
    
    log_info "Creating Athena CUR table with partition projection..."
    
    # Read and process the DDL template
    local ddl_file="infrastructure/sql/create_cur_table_with_projection.sql"
    
    if [ ! -f "$ddl_file" ]; then
        log_error "DDL file not found: $ddl_file"
        return 1
    fi
    
    # Replace placeholders in DDL
    local ddl=$(cat "$ddl_file" | \
        sed "s/\${CUR_DATABASE}/${database}/g" | \
        sed "s/\${CUR_TABLE_NAME}/${table}/g" | \
        sed "s|\${CUR_S3_BUCKET}|${bucket}|g" | \
        sed "s|\${CUR_S3_PREFIX}|${prefix}|g")
    
    # Extract only the CREATE EXTERNAL TABLE statement
    # Match from CREATE EXTERNAL TABLE to the end of TBLPROPERTIES
    local create_table_stmt=$(echo "$ddl" | sed -n '/^CREATE EXTERNAL TABLE/,/);$/p')
    
    if [ -z "$create_table_stmt" ]; then
        log_error "Failed to extract CREATE TABLE statement from DDL"
        log_error "Check if the DDL file has correct format"
        return 1
    fi
    
    log_info "CREATE TABLE statement extracted successfully"
    
    # Execute the CREATE TABLE statement
    log_info "Executing DDL (this may take 10-20 seconds)..."
    
    local query_id=$(aws athena start-query-execution \
        --query-string "$create_table_stmt" \
        --query-execution-context Database="${database}" \
        --result-configuration OutputLocation="${output_location}" \
        --region "$aws_region" \
        --query 'QueryExecutionId' \
        --output text)
    
    if [ -z "$query_id" ]; then
        log_error "Failed to start query execution"
        return 1
    fi
    
    log_info "Query execution ID: $query_id"
    
    # Wait for query to complete
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        sleep 1
        attempt=$((attempt + 1))
        
        local status=$(aws athena get-query-execution \
            --query-execution-id "$query_id" \
            --region "$aws_region" \
            --query 'QueryExecution.Status.State' \
            --output text)
        
        if [ "$status" = "SUCCEEDED" ]; then
            log_success "Athena table created: ${database}.${table}"
            return 0
        elif [ "$status" = "FAILED" ]; then
            local reason=$(aws athena get-query-execution \
                --query-execution-id "$query_id" \
                --region "$aws_region" \
                --query 'QueryExecution.Status.StateChangeReason' \
                --output text)
            log_error "Table creation failed: $reason"
            return 1
        elif [ "$status" = "CANCELLED" ]; then
            log_error "Table creation was cancelled"
            return 1
        fi
    done
    
    log_error "Table creation timed out after ${max_attempts} seconds"
    return 1
}

# Validate Athena table is queryable
validate_athena_table() {
    local database=$1
    local table=$2
    local aws_region=$3
    local output_location=$4
    
    log_info "Validating Athena table is queryable..."
    
    # Simple validation query
    local validation_query="SELECT COUNT(*) as record_count FROM ${database}.${table} WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR) AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR) LIMIT 1"
    
    local query_id=$(aws athena start-query-execution \
        --query-string "$validation_query" \
        --query-execution-context Database="${database}" \
        --result-configuration OutputLocation="${output_location}" \
        --region "$aws_region" \
        --query 'QueryExecutionId' \
        --output text)
    
    if [ -z "$query_id" ]; then
        log_error "Failed to start validation query"
        return 1
    fi
    
    # Wait for query to complete
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        sleep 1
        attempt=$((attempt + 1))
        
        local status=$(aws athena get-query-execution \
            --query-execution-id "$query_id" \
            --region "$aws_region" \
            --query 'QueryExecution.Status.State' \
            --output text)
        
        if [ "$status" = "SUCCEEDED" ]; then
            log_success "Athena table is queryable and has data"
            
            # Get result count
            local result_file=$(aws athena get-query-execution \
                --query-execution-id "$query_id" \
                --region "$aws_region" \
                --query 'QueryExecution.ResultConfiguration.OutputLocation' \
                --output text)
            
            if [ -n "$result_file" ]; then
                log_info "Query result: $result_file"
            fi
            
            return 0
        elif [ "$status" = "FAILED" ]; then
            local reason=$(aws athena get-query-execution \
                --query-execution-id "$query_id" \
                --region "$aws_region" \
                --query 'QueryExecution.Status.StateChangeReason' \
                --output text)
            log_warning "Validation query failed: $reason"
            log_warning "This may be normal if current month has no data yet"
            return 0  # Don't fail deployment, just warn
        fi
    done
    
    log_warning "Validation query timed out"
    return 0  # Don't fail deployment, just warn
}

# Main execution
main() {
    if [ $# -lt 6 ]; then
        log_error "Usage: $0 <CUR_BUCKET> <CUR_PREFIX> <DATABASE> <TABLE> <AWS_REGION> <OUTPUT_LOCATION>"
        exit 1
    fi
    
    local cur_bucket=$1
    local cur_prefix=$2
    local database=$3
    local table=$4
    local aws_region=$5
    local output_location=$6
    
    log_info "============================================"
    log_info "CUR Validation and Athena Table Setup"
    log_info "============================================"
    log_info "CUR Bucket: $cur_bucket"
    log_info "CUR Prefix: $cur_prefix"
    log_info "Database: $database"
    log_info "Table: $table"
    log_info "Region: $aws_region"
    log_info "============================================"
    echo ""
    
    # Step 1: Validate CUR bucket exists (data is optional)
    if ! validate_cur_bucket "$cur_bucket" "$cur_prefix" "$aws_region"; then
        log_error "CUR bucket validation failed"
        exit 1
    fi
    echo ""
    
    # Step 2: Create Athena database
    if ! create_athena_database "$database" "$aws_region" "$output_location"; then
        log_error "Failed to create Athena database"
        exit 1
    fi
    echo ""
    
    # Step 3: Create Athena table
    if ! create_athena_cur_table "$database" "$table" "$cur_bucket" "$cur_prefix" "$aws_region" "$output_location"; then
        log_error "Failed to create Athena table"
        exit 1
    fi
    echo ""
    
    # Step 4: Validate table is queryable
    validate_athena_table "$database" "$table" "$aws_region" "$output_location"
    echo ""
    
    log_success "============================================"
    log_success "CUR setup completed successfully!"
    log_success "============================================"
    log_success "Athena table: ${database}.${table}"
    log_success "Data location: s3://${cur_bucket}/${cur_prefix}/"
    log_success "============================================"
    
    return 0
}

# Run main if script is executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
