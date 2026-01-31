"""
Athena Query Service - Generate and execute SQL queries for AWS CUR data
Provides query generation, execution, and result export functionality
"""

import asyncio
import boto3
import time
import csv
import json
import io
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timedelta, date
import structlog

from backend.config.settings import get_settings
from backend.utils.sql_validation import validate_service_code, ValidationError
from backend.utils.sql_constants import (
    SQL_QUOTED_SEPARATOR,
    build_sql_in_list,
    format_display_list,
)

if TYPE_CHECKING:
    from backend.services.request_context import RequestContext

logger = structlog.get_logger(__name__)
settings = get_settings()


class AthenaQueryService:
    """Service for generating and executing Athena SQL queries against CUR data"""
    
    def __init__(self):
        """Initialize Athena client"""
        try:
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                session = boto3.Session(
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                    region_name=settings.aws_region
                )
            else:
                session = boto3.Session(region_name=settings.aws_region)
            
            self.athena_client = session.client('athena')
            self.s3_client = session.client('s3')
            
            logger.info("Athena Query Service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Athena client: {e}")
            self.athena_client = None
            self.s3_client = None
    
    async def generate_query_for_user_request(
        self,
        user_query: str,
        time_range: Dict[str, Any],
        services: Optional[List[str]] = None,
        user_intent: str = "cost_analysis"
    ) -> Tuple[str, str]:
        """
        Generate Athena SQL query based on user's natural language request.
        
        Args:
            user_query: User's natural language query
            time_range: Time range dict with start_date and end_date
            services: Optional list of AWS services to filter
            user_intent: Intent classification from query analysis
            
        Returns:
            Tuple of (sql_query, query_description)
        """
        try:
            query_lower = user_query.lower()
            
            # Determine query type and generate appropriate SQL
            if "top" in query_lower and "service" in query_lower:
                # Top services by cost
                limit = self._extract_top_n(query_lower)
                sql_query = self._generate_top_services_query(time_range, limit)
                description = f"Top {limit} AWS services by cost for the specified period"
            
            elif "daily" in query_lower or "day by day" in query_lower:
                # Daily cost breakdown
                sql_query = self._generate_daily_costs_query(time_range, services)
                description = "Daily cost breakdown" + (f" for {format_display_list(services)}" if services else "")
            
            elif "service breakdown" in query_lower or "by service" in query_lower:
                # Cost breakdown by service
                sql_query = self._generate_service_breakdown_query(time_range, services)
                description = "Cost breakdown by AWS service"
            
            elif "region" in query_lower:
                # Cost by region
                sql_query = self._generate_region_breakdown_query(time_range)
                description = "Cost breakdown by AWS region"
            
            elif "account" in query_lower:
                # Cost by account
                sql_query = self._generate_account_breakdown_query(time_range)
                description = "Cost breakdown by AWS account"
            
            else:
                # Default: comprehensive cost summary
                sql_query = self._generate_comprehensive_query(time_range, services)
                description = "Comprehensive cost summary"
            
            logger.info(f"Generated Athena query: {description}")
            return sql_query, description
            
        except Exception as e:
            logger.error(f"Error generating Athena query: {e}")
            # Return a safe default query
            return self._generate_default_query(time_range), "Default cost summary query"
    
    def _extract_top_n(self, query: str) -> int:
        """Extract the 'N' value from 'top N' queries"""
        if "top 3" in query or "3" in query:
            return 3
        elif "top 5" in query or "5" in query:
            return 5
        elif "top 10" in query or "10" in query:
            return 10
        return 5  # Default

    def _validate_services(self, services: Optional[List[str]]) -> List[str]:
        """
        Validate service codes against allowlist to prevent SQL injection.

        Args:
            services: List of service codes to validate

        Returns:
            List of validated service codes (invalid ones are filtered out)
        """
        if not services:
            return []

        validated_services = []
        for service in services:
            try:
                validated = validate_service_code(service)
                validated_services.append(validated)
            except ValidationError as e:
                logger.warning(
                    "Invalid service filter skipped",
                    service=service[:50] if service else "",
                    error=str(e)
                )
                continue

        return validated_services
    
    def _generate_top_services_query(self, time_range: Dict[str, Any], limit: int = 5) -> str:
        """Generate SQL for top N services by cost"""
        start_date = time_range.get("start_date")
        end_date = time_range.get("end_date")
        
        query = f"""
SELECT 
    line_item_product_code as service_name,
    SUM(line_item_unblended_cost) as total_cost,
    SUM(line_item_usage_amount) as total_usage
FROM 
    {settings.aws_cur_table or 'cur_table'}
WHERE 
    line_item_usage_start_date >= DATE '{start_date}'
    AND line_item_usage_start_date <= DATE '{end_date}'
GROUP BY 
    line_item_product_code
ORDER BY 
    total_cost DESC
LIMIT {limit};
"""
        return query.strip()
    
    def _generate_daily_costs_query(
        self,
        time_range: Dict[str, Any],
        services: Optional[List[str]] = None
    ) -> str:
        """Generate SQL for daily cost breakdown"""
        start_date = time_range.get("start_date")
        end_date = time_range.get("end_date")

        # SECURITY FIX: Validate services to prevent SQL injection
        service_filter = ""
        if services:
            validated_services = self._validate_services(services)
            if validated_services:
                service_list = build_sql_in_list(validated_services)
                service_filter = f"AND line_item_product_code IN ({service_list})"

        query = f"""
SELECT
    DATE(line_item_usage_start_date) as usage_date,
    line_item_product_code as service_name,
    SUM(line_item_unblended_cost) as daily_cost
FROM
    {settings.aws_cur_table or 'cur_table'}
WHERE
    line_item_usage_start_date >= DATE '{start_date}'
    AND line_item_usage_start_date <= DATE '{end_date}'
    {service_filter}
GROUP BY
    DATE(line_item_usage_start_date),
    line_item_product_code
ORDER BY
    usage_date ASC,
    daily_cost DESC;
"""
        return query.strip()

    def _generate_service_breakdown_query(
        self,
        time_range: Dict[str, Any],
        services: Optional[List[str]] = None
    ) -> str:
        """Generate SQL for service cost breakdown"""
        start_date = time_range.get("start_date")
        end_date = time_range.get("end_date")

        # SECURITY FIX: Validate services to prevent SQL injection
        service_filter = ""
        if services:
            validated_services = self._validate_services(services)
            if validated_services:
                service_list = build_sql_in_list(validated_services)
                service_filter = f"AND line_item_product_code IN ({service_list})"
        
        query = f"""
SELECT 
    line_item_product_code as service_name,
    line_item_usage_type as usage_type,
    SUM(line_item_unblended_cost) as cost,
    SUM(line_item_usage_amount) as usage_amount,
    line_item_usage_type as usage_unit
FROM 
    {settings.aws_cur_table or 'cur_table'}
WHERE 
    line_item_usage_start_date >= DATE '{start_date}'
    AND line_item_usage_start_date <= DATE '{end_date}'
    {service_filter}
GROUP BY 
    line_item_product_code,
    line_item_usage_type
ORDER BY 
    cost DESC;
"""
        return query.strip()
    
    def _generate_region_breakdown_query(self, time_range: Dict[str, Any]) -> str:
        """Generate SQL for regional cost breakdown"""
        start_date = time_range.get("start_date")
        end_date = time_range.get("end_date")
        
        query = f"""
SELECT 
    product_region as region,
    line_item_product_code as service_name,
    SUM(line_item_unblended_cost) as cost
FROM 
    {settings.aws_cur_table or 'cur_table'}
WHERE 
    line_item_usage_start_date >= DATE '{start_date}'
    AND line_item_usage_start_date <= DATE '{end_date}'
    AND product_region IS NOT NULL
    AND product_region != ''
GROUP BY 
    product_region,
    line_item_product_code
ORDER BY 
    cost DESC;
"""
        return query.strip()
    
    def _generate_account_breakdown_query(self, time_range: Dict[str, Any]) -> str:
        """Generate SQL for account cost breakdown"""
        start_date = time_range.get("start_date")
        end_date = time_range.get("end_date")
        
        query = f"""
SELECT 
    line_item_usage_account_id as account_id,
    line_item_product_code as service_name,
    SUM(line_item_unblended_cost) as cost
FROM 
    {settings.aws_cur_table or 'cur_table'}
WHERE 
    line_item_usage_start_date >= DATE '{start_date}'
    AND line_item_usage_start_date <= DATE '{end_date}'
GROUP BY 
    line_item_usage_account_id,
    line_item_product_code
ORDER BY 
    cost DESC;
"""
        return query.strip()
    
    def _generate_comprehensive_query(
        self,
        time_range: Dict[str, Any],
        services: Optional[List[str]] = None
    ) -> str:
        """Generate comprehensive SQL query"""
        start_date = time_range.get("start_date")
        end_date = time_range.get("end_date")

        # SECURITY FIX: Validate services to prevent SQL injection
        service_filter = ""
        if services:
            validated_services = self._validate_services(services)
            if validated_services:
                service_list = build_sql_in_list(validated_services)
                service_filter = f"AND line_item_product_code IN ({service_list})"

        query = f"""
SELECT
    DATE(line_item_usage_start_date) as usage_date,
    line_item_product_code as service_name,
    product_region as region,
    SUM(line_item_unblended_cost) as cost,
    SUM(line_item_usage_amount) as usage_amount
FROM
    {settings.aws_cur_table or 'cur_table'}
WHERE
    line_item_usage_start_date >= DATE '{start_date}'
    AND line_item_usage_start_date <= DATE '{end_date}'
    {service_filter}
GROUP BY
    DATE(line_item_usage_start_date),
    line_item_product_code,
    product_region
ORDER BY
    usage_date DESC,
    cost DESC;
"""
        return query.strip()
    
    def _generate_default_query(self, time_range: Dict[str, Any]) -> str:
        """Generate default fallback query"""
        return self._generate_top_services_query(time_range, 10)
    
    async def execute_query(
        self,
        sql_query: str,
        wait_for_completion: bool = True,
        max_wait_seconds: int = 60
    ) -> Dict[str, Any]:
        """
        Execute Athena query and return results.
        
        Args:
            sql_query: SQL query to execute
            wait_for_completion: Whether to wait for query completion
            max_wait_seconds: Maximum time to wait for query completion
            
        Returns:
            Dict with query results or execution ID
        """
        if not self.athena_client:
            return {
                "error": "Athena client not initialized",
                "status": "failed"
            }
        
        try:
            # Start query execution
            response = self.athena_client.start_query_execution(
                QueryString=sql_query,
                QueryExecutionContext={
                    'Database': settings.athena_database or 'default'
                },
                ResultConfiguration={
                    'OutputLocation': f"s3://{settings.aws_s3_bucket}/query-results/"
                }
            )
            
            query_execution_id = response['QueryExecutionId']
            logger.info(f"Athena query started: {query_execution_id}")
            
            if not wait_for_completion:
                return {
                    "status": "running",
                    "query_execution_id": query_execution_id
                }
            
            # Wait for query completion
            start_time = time.time()
            while True:
                if time.time() - start_time > max_wait_seconds:
                    return {
                        "status": "timeout",
                        "query_execution_id": query_execution_id,
                        "message": "Query execution exceeded maximum wait time"
                    }
                
                status_response = self.athena_client.get_query_execution(
                    QueryExecutionId=query_execution_id
                )
                
                status = status_response['QueryExecution']['Status']['State']
                
                if status == 'SUCCEEDED':
                    # Get query results
                    results = await self._get_query_results(query_execution_id)
                    return {
                        "status": "success",
                        "query_execution_id": query_execution_id,
                        "results": results,
                        "row_count": len(results) if results else 0
                    }
                
                elif status in ['FAILED', 'CANCELLED']:
                    error_msg = status_response['QueryExecution']['Status'].get(
                        'StateChangeReason', 'Unknown error'
                    )
                    return {
                        "status": "failed",
                        "query_execution_id": query_execution_id,
                        "error": error_msg
                    }
                
                # Still running, wait before checking again
                await asyncio.sleep(2)
                
        except Exception as e:
            logger.error(f"Error executing Athena query: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def _get_query_results(self, query_execution_id: str) -> List[Dict[str, Any]]:
        """Get results from completed Athena query"""
        try:
            results = []
            paginator = self.athena_client.get_paginator('get_query_results')
            
            page_iterator = paginator.paginate(QueryExecutionId=query_execution_id)
            
            headers = None
            for page in page_iterator:
                for row in page['ResultSet']['Rows']:
                    row_data = [col.get('VarCharValue', '') for col in row['Data']]
                    
                    if headers is None:
                        # First row is headers
                        headers = row_data
                    else:
                        # Create dict from row data
                        result_dict = dict(zip(headers, row_data))
                        results.append(result_dict)
            
            return results
            
        except Exception as e:
            logger.error(f"Error getting query results: {e}")
            return []
    
    async def export_results_to_csv(
        self,
        results: List[Dict[str, Any]],
        filename: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Export query results to CSV format.
        
        Returns:
            Tuple of (csv_content, suggested_filename)
        """
        if not results:
            return "", "no_results.csv"
        
        try:
            output = io.StringIO()
            
            # Get headers from first result
            headers = list(results[0].keys())
            
            writer = csv.DictWriter(output, fieldnames=headers)
            writer.writeheader()
            writer.writerows(results)
            
            csv_content = output.getvalue()
            output.close()
            
            # Generate filename
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"athena_results_{timestamp}.csv"
            
            return csv_content, filename
            
        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            return "", "error.csv"
    
    async def export_results_to_json(
        self,
        results: List[Dict[str, Any]],
        filename: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Export query results to JSON format.
        
        Returns:
            Tuple of (json_content, suggested_filename)
        """
        try:
            json_content = json.dumps(results, indent=2, default=str)
            
            # Generate filename
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"athena_results_{timestamp}.json"
            
            return json_content, filename
            
        except Exception as e:
            logger.error(f"Error exporting to JSON: {e}")
            return "{}", "error.json"


    async def execute_query_with_scoping(
        self,
        sql_query: str,
        context: "RequestContext",
        wait_for_completion: bool = True,
        max_wait_seconds: int = 60
    ) -> Dict[str, Any]:
        """
        Execute Athena query with account scoping validation.

        This method:
        1. Validates the SQL doesn't access unauthorized accounts
        2. Injects account filter if missing
        3. Executes the query
        4. Adds scope metadata to results

        Args:
            sql_query: SQL query to execute
            context: RequestContext with user's allowed accounts
            wait_for_completion: Whether to wait for query completion
            max_wait_seconds: Maximum time to wait

        Returns:
            Dict with query results and scope information
        """
        # Validate and enforce account scoping
        if context.allowed_account_ids and not context.is_admin:
            sql_query, was_enforced = self._enforce_account_filter(
                sql_query,
                context.allowed_account_ids
            )

            # Validate no unauthorized accounts in query
            is_valid, error = self._validate_account_scope(
                sql_query,
                context.allowed_account_ids
            )
            if not is_valid:
                logger.warning(
                    "query_scope_violation",
                    user_email=context.user_email,
                    error=error,
                )
                return {
                    "status": "denied",
                    "error": error,
                    "scope": context.to_scope_dict()
                }

            if was_enforced:
                logger.info(
                    "account_filter_enforced_on_execution",
                    user_email=context.user_email,
                    account_count=len(context.allowed_account_ids),
                )

        # Execute the query
        result = await self.execute_query(
            sql_query=sql_query,
            wait_for_completion=wait_for_completion,
            max_wait_seconds=max_wait_seconds
        )

        # Add scope metadata to result
        result['scope'] = context.to_scope_dict()
        result['scoped_sql'] = sql_query

        return result

    def _enforce_account_filter(
        self,
        sql: str,
        allowed_account_ids: List[str]
    ) -> Tuple[str, bool]:
        """
        Inject account filter if missing from SQL.

        Returns:
            Tuple of (modified_sql, was_modified)
        """
        sql_upper = sql.upper()

        # Check if account filter already present
        if 'LINE_ITEM_USAGE_ACCOUNT_ID' in sql_upper:
            return sql, False

        # No account filter - inject one
        # Validate account IDs to prevent SQL injection (AWS account IDs are 12 digits)
        validated_ids = [acc for acc in allowed_account_ids if re.match(r'^[0-9]{12}$', str(acc))]
        if not validated_ids:
            logger.warning("no_valid_account_ids_for_filter")
            return sql, False

        account_list = build_sql_in_list(validated_ids)
        account_filter = f"line_item_usage_account_id IN ({account_list})"

        # Find WHERE clause and inject
        where_match = re.search(r'\bWHERE\b', sql, re.IGNORECASE)
        if where_match:
            where_end = where_match.end()
            sql = f"{sql[:where_end]} {account_filter} AND {sql[where_end:]}"
        else:
            # No WHERE - add after FROM
            from_match = re.search(
                r'\bFROM\s+[\w\.]+(?:\s+AS\s+\w+)?',
                sql,
                re.IGNORECASE
            )
            if from_match:
                from_end = from_match.end()
                sql = f"{sql[:from_end]} WHERE {account_filter} {sql[from_end:]}"

        return sql, True

    def _validate_account_scope(
        self,
        sql: str,
        allowed_account_ids: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate SQL doesn't access unauthorized accounts.

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Extract 12-digit account IDs from the query
        account_pattern = r"'(\d{12})'"
        mentioned_accounts = set(re.findall(account_pattern, sql))

        if not mentioned_accounts:
            # No explicit accounts - check for filter
            if 'LINE_ITEM_USAGE_ACCOUNT_ID' not in sql.upper():
                return False, "Query must include account filter"
            return True, None

        # Check all mentioned accounts are allowed
        allowed_set = set(allowed_account_ids)
        unauthorized = mentioned_accounts - allowed_set

        if unauthorized:
            return False, f"Access denied to accounts: {format_display_list(sorted(unauthorized))}"

        return True, None

    def inject_account_filter(
        self,
        sql: str,
        allowed_account_ids: List[str]
    ) -> str:
        """
        Public method to inject account filter into SQL.
        Use this when you need to scope a query before execution.
        """
        modified_sql, _ = self._enforce_account_filter(sql, allowed_account_ids)
        return modified_sql


# Global Athena service instance
athena_service = AthenaQueryService()
