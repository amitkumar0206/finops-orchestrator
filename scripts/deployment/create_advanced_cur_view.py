#!/usr/bin/env python3
"""
Advanced CUR Table Creator
===========================
Creates Athena views that automatically handle AWS CUR's complex timestamped manifest structure.

Problem:
  AWS CUR creates new timestamped directories on each delivery:
  - 20241001-20241101/20251112T031856Z/file.parquet
  - 20241001-20241101/20251117T151350Z/file.parquet (newer)
  
  This results in Glue Crawler creating 25+ separate tables.

Solution:
  1. For each billing period (YYYYMMDD-YYYYMMDD), find the LATEST timestamp table
  2. Create a unified view that UNIONs all the latest tables
  3. Backend queries the view, getting complete up-to-date CUR data

Usage:
  python3 create_advanced_cur_view.py [deployment.env]
"""

import boto3
import sys
import os
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple

# Colors
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'

def log_info(msg): print(f"{BLUE}[INFO]{NC} {msg}")
def log_success(msg): print(f"{GREEN}[SUCCESS]{NC} {msg}")
def log_warning(msg): print(f"{YELLOW}[WARNING]{NC} {msg}")
def log_error(msg): print(f"{RED}[ERROR]{NC} {msg}")

def load_config(env_file='deployment.env'):
    """Load configuration from environment file"""
    config = {}
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key] = value
    
    # Set defaults
    config.setdefault('AWS_REGION', 'us-east-1')
    config.setdefault('AWS_CUR_DATABASE', 'cost_usage_db')
    config.setdefault('AWS_CUR_TABLE', 'cur_data')
    config.setdefault('CUR_S3_BUCKET', config.get('S3_BUCKET', ''))
    config.setdefault('CUR_S3_PREFIX', 'cost-exports/finops-cost-export')
    config.setdefault('ATHENA_OUTPUT_LOCATION', f"s3://{config.get('S3_BUCKET', '')}/athena-results/")
    config.setdefault('ATHENA_WORKGROUP', 'finops-workgroup')
    
    return config

def get_glue_tables(glue_client, database: str) -> List[str]:
    """Get all Glue tables in the database"""
    tables = []
    paginator = glue_client.get_paginator('get_tables')
    
    for page in paginator.paginate(DatabaseName=database):
        for table in page['TableList']:
            tables.append(table['Name'])
    
    return tables

def parse_table_name(table_name: str) -> Tuple[str, str]:
    """
    Parse Glue table name to extract billing period and timestamp.
    
    Table names from Glue Crawler follow pattern:
    - 20251112t031856z (timestamp only - represents latest across all periods)
    - 20240901_20241001 (billing period with underscore)
    
    Returns: (billing_period, timestamp) or (None, None) if not parseable
    """
    # Try timestamp-only format (e.g., "20251112t031856z")
    timestamp_pattern = r'^(\d{8}t\d{6}z)$'
    match = re.match(timestamp_pattern, table_name.lower())
    if match:
        return (None, match.group(1))
    
    # Try billing period format (e.g., "20240901_20241001")
    period_pattern = r'^(\d{8})_(\d{8})$'
    match = re.match(period_pattern, table_name)
    if match:
        return (f"{match.group(1)}-{match.group(2)}", None)
    
    return (None, None)

def get_table_location(glue_client, database: str, table_name: str) -> str:
    """Get S3 location for a Glue table"""
    try:
        response = glue_client.get_table(DatabaseName=database, Name=table_name)
        return response['Table']['StorageDescriptor']['Location']
    except:
        return None

def find_latest_tables_per_period(glue_client, database: str, tables: List[str]) -> Dict[str, str]:
    """
    For each billing period, find the table with the latest timestamp.
    
    Returns: dict mapping billing_period -> table_name
    """
    # Group tables by billing period extracted from S3 location
    period_tables = {}
    
    log_info(f"Analyzing {len(tables)} Glue tables...")
    
    for table_name in tables:
        if table_name == 'cur_data':  # Skip our own view
            continue
            
        location = get_table_location(glue_client, database, table_name)
        if not location:
            continue
        
        # Extract billing period from S3 path
        # Pattern: s3://bucket/prefix/20241001-20241101/20251112T031856Z/
        period_match = re.search(r'/(\d{8}-\d{8})/', location)
        if not period_match:
            continue
        
        billing_period = period_match.group(1)
        
        # Extract timestamp from S3 path
        timestamp_match = re.search(r'/(\d{8}T\d{6}Z)/', location, re.IGNORECASE)
        timestamp = timestamp_match.group(1).upper() if timestamp_match else table_name
        
        # Track the latest timestamp for this period
        if billing_period not in period_tables:
            period_tables[billing_period] = (table_name, timestamp)
        else:
            current_timestamp = period_tables[billing_period][1]
            if timestamp > current_timestamp:
                period_tables[billing_period] = (table_name, timestamp)
    
    # Extract just the table names
    result = {period: table for period, (table, _) in period_tables.items()}
    
    log_success(f"Found {len(result)} billing periods with CUR data")
    for period in sorted(result.keys()):
        log_info(f"  {period} → {result[period]}")
    
    return result

def get_table_schema(glue_client, database: str, table_name: str) -> List[Dict]:
    """Get the schema (columns) from a Glue table"""
    try:
        response = glue_client.get_table(DatabaseName=database, Name=table_name)
        columns = response['Table']['StorageDescriptor']['Columns']
        return [{'name': col['Name'], 'type': col['Type']} for col in columns]
    except Exception as e:
        log_error(f"Failed to get schema for {table_name}: {e}")
        return []

def get_common_columns(glue_client, database: str, tables: Dict[str, str]) -> List[str]:
    """
    Get columns that exist across ALL tables in the union.
    This handles schema evolution where newer tables might have additional columns.
    """
    log_info("Analyzing column schemas across all tables...")
    
    # Get schema for each table
    table_columns = {}
    for period, table_name in tables.items():
        schema = get_table_schema(glue_client, database, table_name)
        table_columns[table_name] = {col['name'] for col in schema}
    
    # Find intersection (common columns)
    if not table_columns:
        return []
    
    common_cols = set.intersection(*table_columns.values())
    
    # Sort to ensure consistent ordering
    common_cols = sorted(common_cols)
    
    log_info(f"  Found {len(common_cols)} common columns across all tables")
    
    # Show column count per table for debugging
    for table_name, cols in table_columns.items():
        if len(cols) != len(common_cols):
            log_warning(f"  {table_name}: {len(cols)} cols ({len(cols) - len(common_cols)} extra)")
    
    return common_cols

def create_unified_view(athena_client, glue_client, config: Dict, period_tables: Dict[str, str]):
    """Create an Athena view that UNIONs all latest period tables"""
    
    database = config['AWS_CUR_DATABASE']
    view_name = config['AWS_CUR_TABLE']
    
    if not period_tables:
        log_error("No billing period tables found!")
        return False
    
    # Get common columns across all tables
    common_columns = get_common_columns(glue_client, database, period_tables)
    
    if not common_columns:
        log_error("No common columns found across tables!")
        return False
    
    # Build column list for SELECT
    column_list = ', '.join(f'"{col}"' for col in common_columns)
    
    # Build UNION ALL query
    union_parts = []
    for period in sorted(period_tables.keys()):
        table_name = period_tables[period]
        # Quote table names to handle names starting with numbers or special chars
        union_parts.append(f'SELECT {column_list} FROM {database}."{table_name}"')
    
    union_query = "\nUNION ALL\n".join(union_parts)
    
    # Create view SQL
    view_sql = f"""
CREATE OR REPLACE VIEW {database}.{view_name} AS
{union_query}
"""
    
    log_info(f"Creating unified view: {database}.{view_name}")
    log_info(f"  Combines {len(period_tables)} billing periods")
    
    # Execute CREATE VIEW
    try:
        response = athena_client.start_query_execution(
            QueryString=view_sql,
            QueryExecutionContext={'Database': database},
            ResultConfiguration={'OutputLocation': config['ATHENA_OUTPUT_LOCATION']},
            WorkGroup=config['ATHENA_WORKGROUP']
        )
        
        query_id = response['QueryExecutionId']
        log_info(f"View creation query ID: {query_id}")
        
        # Wait for completion
        import time
        for i in range(60):
            status_response = athena_client.get_query_execution(QueryExecutionId=query_id)
            status = status_response['QueryExecution']['Status']['State']
            
            if status == 'SUCCEEDED':
                log_success(f"✅ View created successfully: {view_name}")
                return True
            elif status in ['FAILED', 'CANCELLED']:
                error = status_response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
                log_error(f"View creation failed: {error}")
                return False
            
            time.sleep(1)
        
        log_error("View creation timed out")
        return False
        
    except Exception as e:
        log_error(f"Failed to create view: {e}")
        return False

def validate_view(athena_client, config: Dict):
    """Validate the view returns data"""
    database = config['AWS_CUR_DATABASE']
    view_name = config['AWS_CUR_TABLE']
    
    log_info("Validating CUR view with test query...")
    
    # Get recent data from last 2 months
    end_date = date.today()
    start_date = end_date - timedelta(days=60)
    
    validation_sql = f"""
SELECT 
  DATE(line_item_usage_start_date) as usage_date,
  line_item_product_code,
  CAST(SUM(line_item_unblended_cost) AS DECIMAL(10,2)) as total_cost,
  COUNT(*) as line_items
FROM {database}.{view_name}
WHERE line_item_usage_start_date >= TIMESTAMP '{start_date.isoformat()}'
  AND line_item_usage_start_date < TIMESTAMP '{end_date.isoformat()}'
  AND line_item_line_item_type = 'Usage'
  AND line_item_unblended_cost > 0
GROUP BY DATE(line_item_usage_start_date), line_item_product_code
ORDER BY total_cost DESC
LIMIT 10
"""
    
    try:
        response = athena_client.start_query_execution(
            QueryString=validation_sql,
            QueryExecutionContext={'Database': database},
            ResultConfiguration={'OutputLocation': config['ATHENA_OUTPUT_LOCATION']},
            WorkGroup=config['ATHENA_WORKGROUP']
        )
        
        query_id = response['QueryExecutionId']
        
        # Wait for completion
        import time
        for i in range(60):
            status_response = athena_client.get_query_execution(QueryExecutionId=query_id)
            status = status_response['QueryExecution']['Status']['State']
            
            if status == 'SUCCEEDED':
                # Get results
                results = athena_client.get_query_results(QueryExecutionId=query_id)
                rows = results['ResultSet']['Rows']
                
                if len(rows) > 1:
                    log_success(f"✅ View validation successful! Found {len(rows)-1} cost records")
                    
                    # Show sample data
                    log_info("Sample CUR data from view:")
                    for row in rows[1:6]:  # Show top 5
                        data = row['Data']
                        usage_date = data[0].get('VarCharValue', '')
                        service = data[1].get('VarCharValue', '')
                        cost = data[2].get('VarCharValue', '')
                        items = data[3].get('VarCharValue', '')
                        log_info(f"  {usage_date} | {service}: ${cost} ({items} items)")
                    
                    return True
                else:
                    log_warning("View created but returned 0 records")
                    return False
                    
            elif status in ['FAILED', 'CANCELLED']:
                error = status_response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
                log_error(f"Validation query failed: {error}")
                return False
            
            time.sleep(1)
        
        log_error("Validation query timed out")
        return False
        
    except Exception as e:
        log_error(f"Validation failed: {e}")
        return False

def main():
    env_file = sys.argv[1] if len(sys.argv) > 1 else 'deployment.env'
    config = load_config(env_file)
    
    log_info("=" * 80)
    log_info("Advanced CUR Table Creator")
    log_info("=" * 80)
    log_info(f"Database: {config['AWS_CUR_DATABASE']}")
    log_info(f"View Name: {config['AWS_CUR_TABLE']}")
    log_info(f"Region: {config['AWS_REGION']}")
    
    # Initialize AWS clients
    glue_client = boto3.client('glue', region_name=config['AWS_REGION'])
    athena_client = boto3.client('athena', region_name=config['AWS_REGION'])
    
    # Step 1: Get all Glue tables
    log_info("\n[1/4] Discovering Glue tables...")
    tables = get_glue_tables(glue_client, config['AWS_CUR_DATABASE'])
    log_info(f"Found {len(tables)} tables in database")
    
    # Step 2: Find latest table for each billing period
    log_info("\n[2/4] Identifying latest tables per billing period...")
    period_tables = find_latest_tables_per_period(glue_client, config['AWS_CUR_DATABASE'], tables)
    
    if not period_tables:
        log_error("No billing period tables found! Ensure Glue Crawler has run.")
        sys.exit(1)
    
    # Step 3: Create unified view
    log_info("\n[3/4] Creating unified CUR view...")
    if create_unified_view(athena_client, glue_client, config, period_tables):
        # Validate
        log_info("\n[4/4] Validating view...")
        if validate_view(athena_client, config):
            print("\n" + "=" * 80)
            log_success("✅ Advanced CUR Setup Complete!")
            print("=" * 80)
            log_success(f"View: {config['AWS_CUR_DATABASE']}.{config['AWS_CUR_TABLE']}")
            log_success(f"Billing Periods: {len(period_tables)}")
            log_success("Your backend can now query complete CUR data!")
            print("=" * 80)
            print()
            log_info("Next steps:")
            log_info("  1. Restart backend ECS service")
            log_info("  2. Backend will automatically use CUR data")
            log_info("  3. Test queries in the UI")
            print()
            return 0
        else:
            log_warning("View created but validation had issues")
            return 1
    else:
        log_error("Failed to create unified view")
        return 1

if __name__ == '__main__':
    sys.exit(main())
