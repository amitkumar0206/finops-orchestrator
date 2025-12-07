"""
Athena CUR SQL Templates - Comprehensive query templates for AWS Cost and Usage Reports
Implements all SQL patterns from APPENDIX B with safe partitioning and effective cost calculations
Updated: 2025-12-02 05:30 UTC - Force cache invalidation for ARN cost filter fixes
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import structlog

from backend.services.column_constants import (
    DIMENSION_VALUE, SERVICE, REGION, COST_USD, DAYS_WITH_USAGE, RESOURCE_TYPE
)

logger = structlog.get_logger(__name__)


class AthenaCURTemplates:
    """
    SQL template generator for AWS CUR data queries.
    Implements best practices: partition pruning, effective cost calculation, explicit date filtering.
    Supports both standard AWS CUR column names and Glue-normalized lowercase names.
    """
    
    def __init__(self, database: str, table: str, use_lowercase_columns: bool = True):
        """
        Initialize with CUR database and table names.
        
        Args:
            database: Athena database name (e.g., 'cost_usage_db')
            table: CUR table name (e.g., 'cur_dazn_linked')
            use_lowercase_columns: If True, use lowercase column names (e.g., lineitem_usagestartdate)
                                   If False, use standard CUR names (e.g., line_item_usage_start_date)
        """
        self.database = database
        self.table = table
        self.full_table = f"{database}.{table}"
        self.use_lowercase = use_lowercase_columns
        # Column name mappings - standard name -> actual CUR schema name
        # Note: Glue crawler keeps underscores, so most columns are unchanged
        # Key difference: product_product_name -> product_servicecode
        self.col_map = {
            # Line Item columns - these are correct as-is
            'line_item_usage_start_date': 'line_item_usage_start_date',
            'line_item_usage_end_date': 'line_item_usage_end_date',
            'line_item_unblended_cost': 'line_item_unblended_cost',
            'line_item_usage_amount': 'line_item_usage_amount',
            'line_item_usage_type': 'line_item_usage_type',
            'line_item_line_item_type': 'line_item_line_item_type',
            'line_item_operation': 'line_item_operation',
            'line_item_resource_id': 'line_item_resource_id',
            'line_item_product_code': 'line_item_product_code',
            
            # Product columns - KEY: product_product_name doesn't exist!
            # Use product_servicecode for service name matching
            'product_product_name': 'product_servicecode',
            'product_instance_type': 'product_instance_type',
            'product_region': 'product_region_code',
            'product_availability_zone': 'product_availability_zone',
            'product_operation': 'product_operation',
            'product_usage_type': 'product_usagetype',
            'product_servicecode': 'product_servicecode',
            
            # Bill columns
            'bill_payer_account_id': 'bill_payer_account_id',
            'bill_billing_period_start_date': 'bill_billing_period_start_date',
            
            # Savings Plan columns - CUR 2.0 uses savings_plan_ prefix (with underscore)
            'savings_plan_effective_cost': 'savings_plan_savings_plan_effective_cost',
            'savings_plan_savings_plan_effective_cost': 'savings_plan_savings_plan_effective_cost',
            
            # Reservation columns - CUR 2.0 compatible
            'reservation_effective_cost': 'reservation_effective_cost',
            'reservation_reservation_arn': 'reservation_reservation_a_r_n',
            
            # Resource Tags
            'resource_tags': 'resource_tags',
        }
    
    def _col(self, standard_name: str) -> str:
        """Get the appropriate column name based on naming convention."""
        if self.use_lowercase and standard_name in self.col_map:
            return self.col_map[standard_name]
        return standard_name
    
    def _effective_cost_expr(self) -> str:
        """Generate effective cost calculation expression"""
        # Use column mapping to support both standard and lowercase column names
        # Use NULLIF to treat 0.0 as NULL so COALESCE falls through to line_item_unblended_cost
        sp_cost = self._col('savings_plan_savings_plan_effective_cost')
        res_cost = self._col('reservation_effective_cost')
        unblended_cost = self._col('line_item_unblended_cost')
        return f"COALESCE(NULLIF({sp_cost}, 0), NULLIF({res_cost}, 0), {unblended_cost})"
    
    def _line_item_type_clause(
        self,
        exclude_line_item_types: Optional[List[str]] = None,
        include_line_item_types: Optional[List[str]] = None
    ) -> str:
        """
        Build optional clause filtering line item types.
        By default returns an empty string so all line item types are included.
        """
        if include_line_item_types:
            include_types = ", ".join(f"'{t}'" for t in include_line_item_types)
            return f"AND line_item_line_item_type IN ({include_types})"
        
        if exclude_line_item_types:
            exclude_types = ", ".join(f"'{t}'" for t in exclude_line_item_types)
            return f"AND line_item_line_item_type NOT IN ({exclude_types})"
        
        return ""
    
    def _build_purchase_option_filter(
        self,
        purchase_options: Optional[List[str]] = None
    ) -> str:
        """
        Build filter for purchase options (On-Demand, Reserved, Savings Plan, Spot).
        Uses pricing_term and savings_plan_savings_plan_a_r_n columns.
        """
        if not purchase_options:
            return ""
        
        # Normalize purchase options to lowercase for case-insensitive matching
        normalized = [opt.lower() for opt in purchase_options]
        conditions = []
        
        if "on-demand" in normalized or "ondemand" in normalized:
            conditions.append("(pricing_term IS NULL OR pricing_term = '' OR pricing_term LIKE '%OnDemand%')")
        
        if "reserved" in normalized or "ri" in normalized:
            conditions.append("pricing_term LIKE '%Reserved%'")
        
        if "savings plan" in normalized or "savingsplan" in normalized or "sp" in normalized:
            conditions.append("savings_plan_savings_plan_a_r_n IS NOT NULL")
        
        if "spot" in normalized:
            conditions.append("pricing_term LIKE '%Spot%'")
        
        if not conditions:
            return ""
        
        # Combine with OR (include any matching purchase option)
        combined = " OR ".join(conditions)
        return f"AND ({combined})"
    
    def _build_tag_filter(
        self,
        tags: Optional[Dict[str, List[str]]] = None
    ) -> str:
        """
        Build filter for resource tags.
        Tags format: {"Environment": ["prod", "staging"], "CostCenter": ["media"]}
        """
        if not tags:
            return ""
        
        conditions = []
        for tag_key, tag_values in tags.items():
            if not tag_values:
                continue
            
            # Normalize tag key to lowercase for column name
            normalized_key = tag_key.lower()
            
            if len(tag_values) == 1:
                # Single value - simple equality
                conditions.append(f"resource_tags_user_{normalized_key} = '{tag_values[0]}'")
            else:
                # Multiple values - IN clause
                values_str = ", ".join(f"'{v}'" for v in tag_values)
                conditions.append(f"resource_tags_user_{normalized_key} IN ({values_str})")
        
        if not conditions:
            return ""
        
        # Combine with AND (all tag filters must match)
        combined = " AND ".join(conditions)
        return f"AND ({combined})"
    
    def _build_platform_filter(
        self,
        platforms: Optional[List[str]] = None
    ) -> str:
        """
        Build filter for platforms/operating systems (Linux, Windows, etc.).
        Uses product_operating_system column.
        """
        if not platforms:
            return ""
        
        # Normalize to title case to match CUR values (e.g., "Linux", "Windows")
        normalized = [p.title() for p in platforms]
        
        if len(normalized) == 1:
            return f"AND product_operating_system = '{normalized[0]}'"
        else:
            platforms_str = ", ".join(f"'{p}'" for p in normalized)
            return f"AND product_operating_system IN ({platforms_str})"
    
    def _build_database_engine_filter(
        self,
        database_engines: Optional[List[str]] = None
    ) -> str:
        """
        Build filter for RDS database engines (MySQL, PostgreSQL, etc.).
        Uses product_database_engine column.
        """
        if not database_engines:
            return ""
        
        # Normalize to lowercase for case-insensitive matching
        normalized = [engine.lower() for engine in database_engines]
        
        # Build LIKE conditions for partial matching (e.g., "mysql" matches "MySQL 8.0")
        conditions = []
        for engine in normalized:
            conditions.append(f"LOWER(product_database_engine) LIKE '%{engine}%'")
        
        if len(conditions) == 1:
            return f"AND {conditions[0]}"
        else:
            combined = " OR ".join(conditions)
            return f"AND ({combined})"
    
    def _build_partition_filter(self, start_date: str, end_date: str) -> Tuple[str, List[str], List[str]]:
        """
        Build partition filter for date range.
        
        Note: CUR tables partitioned by billing_period (YYYYMM format), not year/month separately.
        Since date filtering is done via line_item_usage_start_date in WHERE clause,
        we return a simple 1=1 to avoid partition column errors.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            Tuple of (where_clause, years, months) - returns 1=1 and empty lists
        """
        # Return 1=1 (always true) since we filter by date in WHERE clause
        # and the table doesn't have year/month partitions
        return "1=1", [], []
    
    def ec2_cost_by_instance_type(
        self,
        start_date: str,
        end_date: str,
        instance_type: Optional[str] = None
    ) -> str:
        """
        EC2 cost breakdown by instance type.
        FEW-SHOT EXAMPLE 1: Break down EC2 costs by instance type
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        line_item_type_clause = self._line_item_type_clause()
        
        instance_filter = f"AND {self._col('product_instance_type')} = '{instance_type}'" if instance_type else ""
        
        query = f"""
SELECT
  {self._col('product_instance_type')} AS instance_type,
  ROUND(SUM({effective_cost}), 2) AS cost_usd,
  ROUND(SUM({effective_cost}) * 100.0 / SUM(SUM({effective_cost})) OVER (), 2) AS pct_of_ec2
FROM {self.full_table}
WHERE {self._col('product_product_name')} = 'AmazonEC2'
  AND CAST({self._col('line_item_usage_start_date')} AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {instance_filter}
GROUP BY 1
ORDER BY cost_usd DESC;
"""
        return query.strip()
    
    def region_drilldown_for_instance_type(
        self,
        start_date: str,
        end_date: str,
        instance_type: str
    ) -> str:
        """
        Region breakdown for specific instance type.
        FEW-SHOT EXAMPLE 1a: Which region had most expensive m5.large?
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        query = f"""
SELECT
  product_region AS region,
  ROUND(SUM({effective_cost}), 2) AS cost_usd,
  ROUND(SUM({effective_cost}) * 100.0 / SUM(SUM({effective_cost})) OVER (), 2) AS share_of_instance
FROM {self.full_table}
WHERE product_product_name = 'AmazonEC2'
  AND product_instance_type = '{instance_type}'
  AND CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
GROUP BY 1
ORDER BY cost_usd DESC;
"""
        return query.strip()
    
    def account_drilldown_for_instance_type(
        self,
        start_date: str,
        end_date: str,
        instance_type: str
    ) -> str:
        """
        Account breakdown for specific instance type.
        FEW-SHOT EXAMPLE 1b: Drill into m5.large by account
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        query = f"""
SELECT
  bill_payer_account_id AS payer_account_id,
  ROUND(SUM({effective_cost}), 2) AS cost_usd,
  ROUND(SUM({effective_cost}) * 100.0 / SUM(SUM({effective_cost})) OVER (), 2) AS pct_of_instance
FROM {self.full_table}
WHERE product_product_name = 'AmazonEC2'
  AND product_instance_type = '{instance_type}'
  AND CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
GROUP BY 1
ORDER BY cost_usd DESC;
"""
        return query.strip()
    
    def weekly_breakdown_for_instance_type(
        self,
        start_date: str,
        end_date: str,
        instance_type: str
    ) -> str:
        """
        Week-over-week view for specific instance type.
        FEW-SHOT EXAMPLE 1c: Show week-over-week for m5.large
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        query = f"""
WITH weekly_costs AS (
  SELECT
    date_trunc('week', CAST(line_item_usage_start_date AS DATE)) AS week_start,
    ROUND(SUM({effective_cost}), 2) AS cost_usd
  FROM {self.full_table}
  WHERE product_product_name = 'AmazonEC2'
    AND product_instance_type = '{instance_type}'
    AND CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    AND {partition_filter}
    {line_item_type_clause}
  GROUP BY 1
)
SELECT
  week_start,
  cost_usd,
  ROUND((cost_usd - LAG(cost_usd) OVER (ORDER BY week_start)) * 100.0 / NULLIF(LAG(cost_usd) OVER (ORDER BY week_start), 0), 2) AS wow_change_pct
FROM weekly_costs
ORDER BY week_start;
"""
        return query.strip()
    
    def s3_spike_analysis(
        self,
        aug_start: str,
        aug_end: str,
        sep_start: str,
        sep_end: str
    ) -> str:
        """
        S3 spike driver analysis comparing two periods.
        FEW-SHOT EXAMPLE 2: Why did S3 costs spike in September?
        """
        # Build partition filters for both periods
        all_start = min(aug_start, sep_start)
        all_end = max(aug_end, sep_end)
        partition_filter, _, _ = self._build_partition_filter(all_start, all_end)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        query = f"""
WITH cost_by_driver AS (
  SELECT
    CASE
      WHEN line_item_usage_type LIKE '%Requests%' THEN 'Requests'
      WHEN line_item_usage_type LIKE '%DataTransfer%' THEN 'DataTransfer'
      WHEN line_item_usage_type LIKE '%TimedStorage-%' THEN 'Storage'
      WHEN line_item_usage_type LIKE '%Glacier%' OR line_item_operation LIKE '%Restore%' THEN 'Glacier/Restore'
      ELSE 'Other'
    END AS driver,
    date_trunc('month', CAST(line_item_usage_start_date AS DATE)) AS mth,
    SUM({effective_cost}) AS cost
  FROM {self.full_table}
  WHERE product_product_name = 'AmazonS3'
    AND CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{all_start}' AND DATE '{all_end}'
    AND {partition_filter}
    {line_item_type_clause}
  GROUP BY 1, 2
)
SELECT
  driver,
  ROUND(SUM(CASE WHEN mth = DATE '{sep_start}' THEN cost ELSE 0 END), 2) AS sept_cost,
  ROUND(SUM(CASE WHEN mth = DATE '{aug_start}' THEN cost ELSE 0 END), 2) AS aug_cost,
  ROUND(SUM(CASE WHEN mth = DATE '{sep_start}' THEN cost ELSE 0 END) - SUM(CASE WHEN mth = DATE '{aug_start}' THEN cost ELSE 0 END), 2) AS delta_usd,
  ROUND((SUM(CASE WHEN mth = DATE '{sep_start}' THEN cost ELSE 0 END) - SUM(CASE WHEN mth = DATE '{aug_start}' THEN cost ELSE 0 END)) * 100.0 / NULLIF(SUM(CASE WHEN mth = DATE '{aug_start}' THEN cost ELSE 0 END), 0), 2) AS delta_pct
FROM cost_by_driver
GROUP BY 1
ORDER BY delta_usd DESC;
"""
        return query.strip()
    
    def top_n_services(
        self,
        start_date: str,
        end_date: str,
        limit: int = 5,
        exclude_services: Optional[List[str]] = None,
        exclude_line_item_types: Optional[List[str]] = None,
        include_services: Optional[List[str]] = None,
        include_line_item_types: Optional[List[str]] = None,
        purchase_options: Optional[List[str]] = None,
        tags: Optional[Dict[str, List[str]]] = None,
        platforms: Optional[List[str]] = None,
        database_engines: Optional[List[str]] = None
    ) -> str:
        """
        Top N services by cost.
        FEW-SHOT EXAMPLE 3: Top 5 services by cost for Q3 2025
        
        Supports advanced filters:
        - purchase_options: ["On-Demand", "Reserved", "Savings Plan", "Spot"]
        - tags: {"Environment": ["prod"], "CostCenter": ["media"]}
        - platforms: ["Linux", "Windows"]
        - database_engines: ["MySQL", "PostgreSQL"]
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        
        service_filter = ""
        if include_services:
            # Filter to ONLY these services
            services_str = ", ".join(f"'{s}'" for s in include_services)
            service_filter = f"AND line_item_product_code IN ({services_str})"
        elif exclude_services:
            # Exclude specific services
            services_str = ", ".join(f"'{s}'" for s in exclude_services)
            service_filter = f"AND line_item_product_code NOT IN ({services_str})"
        
        # Exclude/Include specific line item types (e.g., Tax, Fee, Credit)
        line_item_type_clause = self._line_item_type_clause(exclude_line_item_types, include_line_item_types)
        
        # Advanced filters
        purchase_option_filter = self._build_purchase_option_filter(purchase_options)
        tag_filter = self._build_tag_filter(tags)
        platform_filter = self._build_platform_filter(platforms)
        database_engine_filter = self._build_database_engine_filter(database_engines)
        
        query = f"""
WITH service_costs AS (
  SELECT
    line_item_product_code AS service,
    SUM({effective_cost}) AS cost
  FROM {self.full_table}
  WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '{start_date}'
    AND CAST(line_item_usage_start_date AS DATE) <= DATE '{end_date}'
    {line_item_type_clause}
    {service_filter}
    {purchase_option_filter}
    {tag_filter}
    {platform_filter}
    {database_engine_filter}
  GROUP BY 1
)
SELECT
  service,
  ROUND(cost, 2) AS cost_usd,
  ROUND(cost * 100.0 / (SELECT SUM(cost) FROM service_costs), 2) AS pct_of_total
FROM service_costs
WHERE service IS NOT NULL
ORDER BY cost DESC
LIMIT {limit};
"""
        return query.strip()
    
    def top_n_days(
        self,
        start_date: str,
        end_date: str,
        limit: int = 5,
        exclude_line_item_types: Optional[List[str]] = None
    ) -> str:
        """
        Find top N days by total cost with service breakdown for the highest cost day.
        Example: "Which day in last 12 months has the highest cost"
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        # Exclude specific line item types (e.g., Tax, Fee, Credit)
        line_item_type_clause = self._line_item_type_clause(exclude_line_item_types)
        
        query = f"""
WITH daily_costs AS (
  SELECT
    CAST(line_item_usage_start_date AS DATE) AS usage_date,
    line_item_product_code AS service,
    SUM({effective_cost}) AS cost
  FROM {self.full_table}
  WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    AND {partition_filter}
    {line_item_type_clause}
  GROUP BY 1, 2
),
day_totals AS (
  SELECT
    usage_date,
    SUM(cost) AS total_cost
  FROM daily_costs
  GROUP BY 1
  ORDER BY SUM(cost) DESC
  LIMIT {limit}
),
top_day_services AS (
  SELECT
    dc.usage_date,
    dc.service,
    ROUND(dc.cost, 2) AS cost_usd,
    ROUND(dc.cost * 100.0 / dt.total_cost, 2) AS pct_of_day
  FROM daily_costs dc
  JOIN day_totals dt ON dc.usage_date = dt.usage_date
)
SELECT
  dt.usage_date,
  ROUND(dt.total_cost, 2) AS total_cost_usd
FROM day_totals dt
ORDER BY dt.total_cost DESC;
"""
        return query.strip()
    
    def ec2_reserved_savings_projection(
        self,
        start_date: str,
        end_date: str,
        assumed_discount: float = 0.35,
        families: Optional[List[str]] = None
    ) -> str:
        """
        Estimate EC2 savings opportunities by instance family using reserved instance assumptions.
        FEW-SHOT EXAMPLE 5: EC2 RI/SP savings estimation.
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        discount = max(min(assumed_discount, 0.85), 0.05)  # clamp between 5% and 85%
        ri_factor = 1 - discount
        
        family_filter = ""
        if families:
            normalized = {family.lower() for family in families}
            values = ", ".join(f"'{value}'" for value in sorted(normalized))
            family_filter = f"  AND LOWER(SPLIT_PART(product_instance_type, '.', 1)) IN ({values})\n"
        
        query = f"""
SELECT
  COALESCE(SPLIT_PART(product_instance_type, '.', 1), 'unknown') AS family,
  ROUND(SUM({effective_cost}), 2) AS on_demand_cost,
  ROUND(SUM({effective_cost}) * {ri_factor:.2f}, 2) AS ri_equivalent_cost,
  ROUND(SUM({effective_cost}) - SUM({effective_cost}) * {ri_factor:.2f}, 2) AS est_savings_usd,
  ROUND(({discount:.2f}) * 100, 2) AS est_savings_pct
FROM {self.full_table}
WHERE product_product_name = 'AmazonEC2'
  AND line_item_usage_type LIKE '%%BoxUsage%%'
  AND CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
{family_filter}GROUP BY 1
HAVING SUM({effective_cost}) > 0
ORDER BY est_savings_usd DESC
LIMIT 10;
"""
        return query.strip()
    
    def month_over_month_by_service(
        self,
        start_date: str,
        end_date: str,
        top_services_only: Optional[int] = None,
        service: Optional[str] = None
    ) -> str:
        """
        Month-over-month cost growth by service.
        FEW-SHOT EXAMPLE 13: MoM cost growth by service since 2023-01
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        # Service filter if specific service requested
        service_filter = ""
        if service:
            service_filter = f"AND {self._col('line_item_product_code')} = '{service}'"
        
        top_filter = ""
        if top_services_only and not service:  # Don't apply top filter if specific service requested
            top_filter = f"""
AND product_product_name IN (
  SELECT product_product_name
  FROM {self.full_table}
  WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '{end_date}' - INTERVAL '30' DAY
    AND {partition_filter}
  GROUP BY 1
  ORDER BY SUM({effective_cost}) DESC
  LIMIT {top_services_only}
)
"""
        
        query = f"""
WITH monthly_costs AS (
  SELECT
    date_trunc('month', CAST(line_item_usage_start_date AS DATE)) AS month,
    product_product_name AS service,
    ROUND(SUM({effective_cost}), 2) AS cost_usd
  FROM {self.full_table}
  WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    AND {partition_filter}
    {line_item_type_clause}
    {service_filter}
    {top_filter}
    AND product_product_name IS NOT NULL  -- Exclude rows with null service (e.g., credits without service attribution)
    AND product_product_name != ''  -- Exclude empty service names
  GROUP BY 1, 2
)
SELECT
  month,
  service,
  cost_usd,
  ROUND((cost_usd - LAG(cost_usd) OVER (PARTITION BY service ORDER BY month)) * 100.0 / NULLIF(LAG(cost_usd) OVER (PARTITION BY service ORDER BY month), 0), 2) AS mom_change_pct
FROM monthly_costs
ORDER BY month ASC, service;
"""
        return query.strip()

    def month_over_month_total(self, start_date: str, end_date: str) -> str:
        """Monthly total AWS cost (all services aggregated).

        Provides a clean time series for trend visualization when user asks for
        "monthly comparison" or "monthly costs" without requesting a breakdown.
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        query = f"""
SELECT
  date_trunc('month', CAST(line_item_usage_start_date AS DATE)) AS month,
  ROUND(SUM({effective_cost}), 2) AS total_cost_usd
FROM {self.full_table}
WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
GROUP BY 1
ORDER BY month ASC;
"""
        return query.strip()
    
    def data_transfer_by_region(
        self,
        start_date: str,
        end_date: str,
        min_cost: float = 0.0
    ) -> str:
        """
        Data transfer costs breakdown by region and type.
        FEW-SHOT EXAMPLE 6: Data transfer costs by region for Oct 2025
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        query = f"""
SELECT
  product_region AS region,
  ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%IntraAZ%' THEN {effective_cost} ELSE 0 END), 2) AS intra_az,
  ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%InterAZ%' OR line_item_usage_type LIKE '%Inter-AZ%' THEN {effective_cost} ELSE 0 END), 2) AS inter_az,
  ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%InterRegion%' OR line_item_usage_type LIKE '%Inter-Region%' THEN {effective_cost} ELSE 0 END), 2) AS inter_region,
  ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%DataTransfer-Out-Bytes%' OR line_item_usage_type LIKE '%ToInternet%' THEN {effective_cost} ELSE 0 END), 2) AS internet_egress,
  ROUND(SUM({effective_cost}), 2) AS dt_total_usd
FROM {self.full_table}
  WHERE (product_product_name = 'AWSDataTransfer' OR line_item_usage_type LIKE '%DataTransfer%')
  AND CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
GROUP BY 1
HAVING SUM({effective_cost}) > {min_cost}
ORDER BY dt_total_usd DESC;
"""
        return query.strip()
    
    def cost_by_tag(
        self,
        start_date: str,
        end_date: str,
        tag_key: str,
        tag_values: Optional[List[str]] = None
    ) -> str:
        """
        Cost breakdown by resource tag.
        FEW-SHOT EXAMPLE 9: Cost from Environment=Dev last month
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        tag_filter = ""
        if tag_values:
            values_str = ", ".join(f"'{v}'" for v in tag_values)
            tag_filter = f"AND resource_tags_user_{tag_key} IN ({values_str})"
        
        query = f"""
SELECT
  COALESCE(NULLIF(resource_tags_user_{tag_key}, ''), 'UNSPECIFIED') AS tag_value,
  product_product_name AS service,
  ROUND(SUM({effective_cost}), 2) AS cost_usd,
  ROUND(SUM({effective_cost}) * 100.0 / SUM(SUM({effective_cost})) OVER (PARTITION BY resource_tags_user_{tag_key}), 2) AS share_of_tag
FROM {self.full_table}
WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
  {tag_filter}
GROUP BY 1, 2
ORDER BY tag_value, cost_usd DESC;
"""
        return query.strip()
    
    def top_untagged_resources(
        self,
        start_date: str,
        end_date: str,
        tag_key: str,
        limit: int = 10
    ) -> str:
        """
        Top untagged resources by cost.
        FEW-SHOT EXAMPLE 11: Top 10 untagged resources
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        query = f"""
SELECT
  COALESCE(line_item_resource_id, CONCAT(product_product_name, ':', line_item_usage_type)) AS resource_key,
  product_product_name AS service,
  ROUND(SUM({effective_cost}), 2) AS est_monthly_cost
FROM {self.full_table}
WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
  AND (resource_tags_user_{tag_key} IS NULL OR resource_tags_user_{tag_key} = '')
GROUP BY 1, 2
ORDER BY est_monthly_cost DESC
LIMIT {limit};
"""
        return query.strip()
    
    def cur_record_count_by_day(
        self,
        start_date: str,
        end_date: str
    ) -> str:
        """
        CUR record count per day for ingest health monitoring.
        FEW-SHOT EXAMPLE 10: CUR record count per day for last 14 days
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        
        query = f"""
SELECT
  CAST(line_item_usage_start_date AS DATE) AS dt,
  COUNT(1) AS record_count
FROM {self.full_table}
WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
GROUP BY 1
ORDER BY dt;
"""
        return query.strip()
    
    def daily_anomaly_detection(
        self,
        start_date: str,
        end_date: str,
        service: Optional[str] = None
    ) -> str:
        """
        Daily cost anomaly detection using z-score.
        FEW-SHOT EXAMPLE 14: Any cost anomaly in last 10 days?
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        service_filter = f"AND product_product_name = '{service}'" if service else ""
        
        query = f"""
WITH daily_costs AS (
  SELECT
    CAST(line_item_usage_start_date AS DATE) AS dt,
    product_product_name AS service,
    ROUND(SUM({effective_cost}), 2) AS cost_usd
  FROM {self.full_table}
  WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    AND {partition_filter}
    {line_item_type_clause}
    {service_filter}
  GROUP BY 1, 2
),
stats AS (
  SELECT
    dt,
    service,
    cost_usd,
    AVG(cost_usd) OVER (PARTITION BY service ORDER BY dt ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS mu,
    STDDEV_SAMP(cost_usd) OVER (PARTITION BY service ORDER BY dt ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS sigma
  FROM daily_costs
)
SELECT
  dt,
  service,
  cost_usd,
  ROUND(mu, 2) AS expected,
  ROUND(cost_usd - mu, 2) AS delta,
  CASE 
    WHEN sigma IS NULL OR sigma = 0 THEN NULL 
    ELSE ROUND((cost_usd - mu) / sigma, 2) 
  END AS z_score
FROM stats
WHERE ABS((cost_usd - mu) / NULLIF(sigma, 0)) > 2.0  -- Flag anomalies > 2 std devs
ORDER BY dt DESC, ABS(z_score) DESC NULLS LAST;
"""
        return query.strip()
    
    def environment_comparison(
        self,
        start_date: str,
        end_date: str,
        tag_key: str,
        env1: str,
        env2: str
    ) -> str:
        """
        Compare costs between two environments (e.g., Dev vs Prod).
        FEW-SHOT EXAMPLE 15: EC2 usage Staging vs Production
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        query = f"""
SELECT
  resource_tags_user_{tag_key} AS env,
  product_product_name AS service,
  ROUND(SUM(line_item_usage_amount), 2) AS usage_hours,
  ROUND(SUM({effective_cost}), 2) AS cost_usd
FROM {self.full_table}
WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
  AND resource_tags_user_{tag_key} IN ('{env1}', '{env2}')
GROUP BY 1, 2
ORDER BY env, cost_usd DESC;
"""
        return query.strip()
    
    def date_comparison(
        self,
        dates: List[str],
        services: Optional[List[str]] = None
    ) -> str:
        """
        Compare costs between specific dates (e.g., "feb 6 and sep 6").
        Each date is treated as a single day.
        Example: "compare ec2 cost on feb 6 and sep 6"
        """
        from utils.date_parser import DateParser
        parser = DateParser()
        
        # Parse each date string to get actual dates
        date_ranges = []
        for date_str in dates:
            start, end, _ = parser.parse_time_range(date_str)
            date_ranges.append((start, end, date_str))
        
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        line_item_type_clause = self._line_item_type_clause()
        
        # Build UNION query for each date
        union_parts = []
        for i, (start, end, label) in enumerate(date_ranges):
            partition_filter, _, _ = self._build_partition_filter(start, end)
            service_filter = ""
            if services:
                services_str = ", ".join(f"'{s}'" for s in services)
                service_filter = f"AND product_product_name IN ({services_str})"
            
            union_parts.append(f"""
  SELECT
    '{label}' AS comparison_date,
    product_product_name AS service,
    ROUND(SUM({effective_cost}), 2) AS cost_usd
	  FROM {self.full_table}
	  WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'
	    AND {partition_filter}
	    {line_item_type_clause}
	    {service_filter}
	  GROUP BY 1, 2
	""")
        
        query = "\nUNION ALL\n".join(union_parts) + "\nORDER BY service, comparison_date;"
        return query.strip()
    
    def service_cost_breakdown(
        self,
        start_date: str,
        end_date: str,
        service: str,
        dimension: str = "region",
        include_line_item_types: Optional[List[str]] = None,
        purchase_options: Optional[List[str]] = None,
        tags: Optional[Dict[str, List[str]]] = None,
        platforms: Optional[List[str]] = None,
        database_engines: Optional[List[str]] = None
    ) -> str:
        """
        Generic service cost breakdown by dimension.
        Supports: region, account, usage_type, operation
        
        Advanced filters:
        - purchase_options: ["On-Demand", "Reserved", "Savings Plan", "Spot"]
        - tags: {"Environment": ["prod"], "CostCenter": ["media"]}
        - platforms: ["Linux", "Windows"]
        - database_engines: ["MySQL", "PostgreSQL"]
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause(include_line_item_types=include_line_item_types)
        
        # Advanced filters
        purchase_option_filter = self._build_purchase_option_filter(purchase_options)
        tag_filter = self._build_tag_filter(tags)
        platform_filter = self._build_platform_filter(platforms)
        database_engine_filter = self._build_database_engine_filter(database_engines)
        
        dimension_map = {
            "region": self._col("product_region"),
            "account": self._col("line_item_usage_account_id"),
            "usage_type": self._col("line_item_usage_type"),
            "operation": self._col("line_item_operation"),
        }
        
        dim_col = dimension_map.get(dimension, self._col("product_region"))
        
        # Log what we're querying for debugging
        logger.info(
            "Generating service cost breakdown query",
            service=service,
            dimension=dimension,
            dimension_column=dim_col,
            start_date=start_date,
            end_date=end_date,
            purchase_options=purchase_options,
            tags=tags,
            platforms=platforms,
            database_engines=database_engines
        )
        
        query = f"""
SELECT
  COALESCE(NULLIF(TRIM({dim_col}), ''), 'Unspecified') AS dimension_value,
  ROUND(SUM({effective_cost}), 2) AS cost_usd,
  ROUND(SUM({effective_cost}) * 100.0 / SUM(SUM({effective_cost})) OVER (), 2) AS pct_of_service
FROM {self.full_table}
WHERE {self._col('line_item_product_code')} = '{service}'
  AND CAST({self._col('line_item_usage_start_date')} AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  {line_item_type_clause}
  {purchase_option_filter}
  {tag_filter}
  {platform_filter}
  {database_engine_filter}
  AND {dim_col} IS NOT NULL
  AND TRIM({dim_col}) != ''
GROUP BY 1
ORDER BY cost_usd DESC;
"""
        return query.strip()

    def service_cost_by_arn(
        self,
        start_date: str,
        end_date: str,
        service: str,
        include_line_item_types: Optional[List[str]] = None,
        purchase_options: Optional[List[str]] = None,
        tags: Optional[Dict[str, List[str]]] = None,
        platforms: Optional[List[str]] = None,
        database_engines: Optional[List[str]] = None
    ) -> str:
        """
        Cost grouped by ARN for a specific service by joining CUR with a resource inventory.

        Resource inventory is expected at `resource_inventory.resources` with columns:
          account_id, region, service, resource_id, arn

        CUR must include `resource_id` (enable resource IDs in CUR configuration).
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause(include_line_item_types=include_line_item_types)

        # Advanced filters
        purchase_option_filter = self._build_purchase_option_filter(purchase_options)
        tag_filter = self._build_tag_filter(tags)
        platform_filter = self._build_platform_filter(platforms)
        database_engine_filter = self._build_database_engine_filter(database_engines)

        logger.info(
            "Generating service cost by ARN query",
            service=service,
            start_date=start_date,
            end_date=end_date,
            purchase_options=purchase_options,
            platforms=platforms,
            database_engines=database_engines
        )

        query = f"""
WITH cur AS (
  SELECT
    {self._col('line_item_usage_account_id')} AS account_id,
    {self._col('product_region')} AS region,
    {self._col('line_item_product_code')} AS service,
    {self._col('resource_id')} AS resource_id,
    {effective_cost} AS cost
  FROM {self.full_table}
  WHERE CAST({self._col('line_item_usage_start_date')} AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    AND {self._col('line_item_product_code')} = '{service}'
    AND {partition_filter}
    {line_item_type_clause}
    {purchase_option_filter}
    {tag_filter}
    {platform_filter}
    {database_engine_filter}
), inv AS (
  SELECT account_id, region, service, resource_id, arn
  FROM resource_inventory.resources
)
SELECT
  inv.arn AS arn,
  ROUND(SUM(cur.cost), 2) AS cost_usd
FROM cur
JOIN inv
  ON inv.account_id = cur.account_id
 AND inv.region = cur.region
 AND inv.service = cur.service
 AND inv.resource_id = cur.resource_id
GROUP BY inv.arn
ORDER BY cost_usd DESC;
"""
        return query.strip()

    def cost_optimization_analysis(
        self,
        start_date: str,
        end_date: str,
        service: Optional[str] = None,
        purchase_options: Optional[List[str]] = None,
        tags: Optional[Dict[str, List[str]]] = None,
        platforms: Optional[List[str]] = None,
        database_engines: Optional[List[str]] = None
    ) -> str:
        """
        General cost optimization analysis showing top opportunities.
        Returns top services/resources with cost, usage patterns, and optimization potential.
        
        Advanced filters:
        - purchase_options: Focus optimization on specific purchase types
        - tags: Scope optimization to specific environments/cost centers
        - platforms: Analyze optimization for specific OS types
        - database_engines: RDS-specific optimization analysis
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause()
        
        # Advanced filters
        purchase_option_filter = self._build_purchase_option_filter(purchase_options)
        tag_filter = self._build_tag_filter(tags)
        platform_filter = self._build_platform_filter(platforms)
        database_engine_filter = self._build_database_engine_filter(database_engines)
        
        service_filter = ""
        if service:
            service_filter = f"AND product_product_name = '{service}'"
        
        query = f"""
WITH resource_costs AS (
  SELECT
    product_product_name AS service,
    COALESCE(product_instance_type, product_usage_type, 'N/A') AS resource_type,
    COALESCE(product_region, 'global') AS region,
    SUM({effective_cost}) AS total_cost_usd,
    SUM(line_item_usage_amount) AS total_usage,
    COUNT(DISTINCT DATE(line_item_usage_start_date)) AS days_used,
    DATE_DIFF('day', DATE '{start_date}', DATE '{end_date}') + 1 AS period_days
  FROM {self.full_table}
  WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    AND {partition_filter}
    {line_item_type_clause}
    {service_filter}
    {purchase_option_filter}
    {tag_filter}
    {platform_filter}
    {database_engine_filter}
  GROUP BY 1, 2, 3
  HAVING SUM({effective_cost}) > 1.0
)
SELECT
  service,
  resource_type,
  region,
  ROUND(total_cost_usd, 2) AS cost_usd,
  ROUND(total_usage, 2) AS usage_amount,
  days_used,
  period_days,
  ROUND(CAST(days_used AS DOUBLE) / CAST(period_days AS DOUBLE) * 100, 1) AS utilization_pct,
  ROUND(total_cost_usd * 0.30, 2) AS est_savings_30pct,
  CASE
    WHEN CAST(days_used AS DOUBLE) / CAST(period_days AS DOUBLE) < 0.5 THEN 'Low Utilization'
    WHEN total_cost_usd > 1000 THEN 'High Cost'
    ELSE 'Optimize'
  END AS opportunity_type,
  ROUND(total_cost_usd * 100.0 / SUM(total_cost_usd) OVER (), 2) AS pct_of_total
FROM resource_costs
ORDER BY total_cost_usd DESC
LIMIT 20;
"""
        return query.strip()
    
    def period_over_period_comparison(
        self,
        current_start: str,
        current_end: str,
        previous_start: str,
        previous_end: str,
        top_n: int = 5,
        services: Optional[List[str]] = None,
        purchase_options: Optional[List[str]] = None,
        tags: Optional[Dict[str, List[str]]] = None,
        platforms: Optional[List[str]] = None,
        database_engines: Optional[List[str]] = None,
        exclude_line_item_types: Optional[List[str]] = None,
        include_line_item_types: Optional[List[str]] = None
    ) -> str:
        """
        Compare costs between current period and previous period.
        Shows service costs for both periods with growth metrics.
        
        Args:
            current_start: Start date of current period (YYYY-MM-DD)
            current_end: End date of current period (YYYY-MM-DD)
            previous_start: Start date of previous period (YYYY-MM-DD)
            previous_end: End date of previous period (YYYY-MM-DD)
            top_n: Number of top services to compare (default 5)
            services: Optional list of specific services to compare
            purchase_options: Filter by purchase option ["On-Demand", "Reserved", "Savings Plan", "Spot"]
            tags: Filter by resource tags {"Environment": ["prod"], "CostCenter": ["media"]}
            platforms: Filter by platform ["Linux", "Windows"]
            database_engines: Filter by database engine ["MySQL", "PostgreSQL"]
            exclude_line_item_types: Exclude charge types ["Tax", "Credit"]
            include_line_item_types: Include only specific charge types ["Usage"]
            
        Returns:
            SQL query that returns comparison data with growth metrics
        """
        effective_cost = self._effective_cost_expr()
        line_item_type_clause = self._line_item_type_clause(exclude_line_item_types, include_line_item_types)
        
        # Advanced filters
        purchase_option_filter = self._build_purchase_option_filter(purchase_options)
        tag_filter = self._build_tag_filter(tags)
        platform_filter = self._build_platform_filter(platforms)
        database_engine_filter = self._build_database_engine_filter(database_engines)
        
        # Build service filter if provided
        service_filter = ""
        if services:
            services_str = ", ".join(f"'{s}'" for s in services)
            service_filter = f"AND {self._col('line_item_product_code')} IN ({services_str})"
        
        # Build partition filters for both periods
        curr_partition, _, _ = self._build_partition_filter(current_start, current_end)
        prev_partition, _, _ = self._build_partition_filter(previous_start, previous_end)
        
        # Modified logic: select top services from combined current+previous periods to avoid empty current_period edge case
        query = f"""
WITH current_period AS (
  SELECT
    {self._col('line_item_product_code')} AS service,
    ROUND(SUM({effective_cost}), 2) AS cost_usd
  FROM {self.full_table}
  WHERE CAST({self._col('line_item_usage_start_date')} AS DATE) 
        BETWEEN DATE '{current_start}' AND DATE '{current_end}'
    AND {curr_partition}
    {line_item_type_clause}
    {service_filter}
    {purchase_option_filter}
    {tag_filter}
    {platform_filter}
    {database_engine_filter}
  GROUP BY 1
),
previous_period AS (
  SELECT
    {self._col('line_item_product_code')} AS service,
    ROUND(SUM({effective_cost}), 2) AS cost_usd
  FROM {self.full_table}
  WHERE CAST({self._col('line_item_usage_start_date')} AS DATE) 
        BETWEEN DATE '{previous_start}' AND DATE '{previous_end}'
    AND {prev_partition}
    {line_item_type_clause}
    {service_filter}
    {purchase_option_filter}
    {tag_filter}
    {platform_filter}
    {database_engine_filter}
  GROUP BY 1
),
combined_services AS (
  SELECT COALESCE(c.service, p.service) AS service,
         COALESCE(c.cost_usd, 0) AS current_cost,
         COALESCE(p.cost_usd, 0) AS previous_cost
  FROM current_period c
  FULL OUTER JOIN previous_period p ON c.service = p.service
),
top_services AS (
  SELECT service
  FROM combined_services
  ORDER BY current_cost DESC, previous_cost DESC
  LIMIT {top_n}
)
SELECT
  cs.service AS service,
  cs.current_cost AS current_period_cost,
  cs.previous_cost AS previous_period_cost,
  ROUND(cs.current_cost - cs.previous_cost, 2) AS cost_change,
  ROUND(
    CASE 
      WHEN cs.previous_cost = 0 THEN CASE WHEN cs.current_cost > 0 THEN 100.0 ELSE 0.0 END
      ELSE ((cs.current_cost - cs.previous_cost) / cs.previous_cost) * 100
    END,
    2
  ) AS percent_change,
  '{current_start}' AS current_start_date,
  '{current_end}' AS current_end_date,
  '{previous_start}' AS previous_start_date,
  '{previous_end}' AS previous_end_date
FROM combined_services cs
WHERE cs.service IN (SELECT service FROM top_services)
ORDER BY current_period_cost DESC NULLS LAST;
"""
        return query.strip()

    def resource_cost_by_arn(
        self,
        start_date: str,
        end_date: str,
        resource_id: str,
        service: Optional[str] = None,
        group_by_day: bool = True
    ) -> str:
        """
        Get cost for specific resource by resource ID.
        Useful for ARN-based queries.
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        
        service_filter = ""
        if service:
            service_filter = f"AND product_product_name = '{service}'"
        
        if group_by_day:
            query = f"""
SELECT
  DATE(line_item_usage_start_date) AS usage_date,
  line_item_resource_id AS resource_id,
  product_product_name AS service,
  COALESCE(product_region, 'global') AS region,
  ROUND(SUM({effective_cost}), 2) AS cost_usd
FROM {self.full_table}
WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  AND line_item_resource_id = '{resource_id}'
  {service_filter}
GROUP BY 1, 2, 3, 4
ORDER BY usage_date
"""
        else:
            # Standardized output: dimension_value, service, region, cost_usd, total_usage
            query = f"""
SELECT
  line_item_usage_type AS {DIMENSION_VALUE},
  product_product_name AS {SERVICE},
  COALESCE(product_region, 'global') AS {REGION},
  ROUND(SUM({effective_cost}), 2) AS {COST_USD},
  ROUND(SUM(line_item_usage_amount), 2) AS total_usage
FROM {self.full_table}
WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  AND line_item_resource_id = '{resource_id}'
  {service_filter}
GROUP BY 1, 2, 3
ORDER BY {COST_USD} DESC
"""
        return query.strip()

    def find_related_resources_by_arn_pattern(
        self,
        start_date: str,
        end_date: str,
        arn: str
    ) -> str:
        """
        Find related resources when an ARN returns no direct cost data.
        Uses pattern matching to discover child resources, tasks, or related services.
        
        Example: arn:aws:ecs:us-east-1:123:cluster/my-cluster
        Finds: arn:aws:ecs:us-east-1:123:task/my-cluster/...
        """
        partition_filter, _, _ = self._build_partition_filter(start_date, end_date)
        effective_cost = self._effective_cost_expr()
        
        # Parse ARN components
        # Format: arn:aws:SERVICE:REGION:ACCOUNT:RESOURCE
        parts = arn.split(':')
        if len(parts) >= 6:
            service = parts[2]  # e.g., 'ecs', 's3', 'rds'
            region = parts[3]
            account = parts[4]
            resource_part = ':'.join(parts[5:])  # Everything after account
            
            # Extract resource name for pattern matching
            # Handle formats: resource-type/name, resource-type:name, or just name
            if '/' in resource_part:
                resource_name = resource_part.split('/')[-1]  # Get last segment
            elif ':' in resource_part:
                resource_name = resource_part.split(':')[-1]
            else:
                resource_name = resource_part
            
            # Build flexible LIKE patterns
            # Pattern 1: Same service + resource name fragment
            service_pattern = f"%{service}%{resource_name}%"
            # Pattern 2: Same service + region + account (broader)
            broad_pattern = f"%{service}%{region}%{account}%"
        else:
            # Fallback for unusual ARN formats
            service_pattern = f"%{arn.split(':')[2] if len(arn.split(':')) > 2 else 'unknown'}%"
            broad_pattern = service_pattern
        
        # Standardized ARN fallback output using column constants
        query = f"""
SELECT
  line_item_resource_id AS {DIMENSION_VALUE},
  product_product_name AS {SERVICE},
  COALESCE(product_region, 'global') AS {REGION},
  ROUND(SUM({effective_cost}), 2) AS {COST_USD},
  COUNT(DISTINCT DATE(line_item_usage_start_date)) AS {DAYS_WITH_USAGE},
  CASE 
    WHEN line_item_resource_id LIKE '%:task/%' THEN 'ECS Task'
    WHEN line_item_resource_id LIKE '%:service/%' THEN 'ECS Service'
    WHEN line_item_resource_id LIKE '%:instance/%' THEN 'EC2 Instance'
    WHEN line_item_resource_id LIKE '%:db:%' THEN 'RDS Database'
    WHEN line_item_resource_id LIKE '%:loadbalancer/%' THEN 'Load Balancer'
    WHEN line_item_resource_id LIKE '%:function:%' THEN 'Lambda Function'
    WHEN line_item_resource_id LIKE '%:natgateway/%' THEN 'NAT Gateway'
    ELSE 'Resource'
  END AS {RESOURCE_TYPE}
FROM {self.full_table}
WHERE CAST(line_item_usage_start_date AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND {partition_filter}
  AND (
    line_item_resource_id LIKE '{service_pattern}'
    OR line_item_resource_id LIKE '{broad_pattern}'
  )
  AND line_item_resource_id != '{arn}'
  AND {effective_cost} > 0
GROUP BY 1, 2, 3, 6
HAVING SUM({effective_cost}) > 0
ORDER BY {COST_USD} DESC
LIMIT 20
"""
        return query.strip()


# Helper function to calculate date ranges for common periods
def calculate_date_range(period: str, reference_date: Optional[date] = None) -> Tuple[str, str]:
    """
    Calculate start and end dates for common time periods.
    
    Args:
        period: Period identifier (last_month, last_week, q3, etc.)
        reference_date: Reference date (defaults to today)
        
    Returns:
        Tuple of (start_date, end_date) in YYYY-MM-DD format
    """
    if reference_date is None:
        reference_date = date.today()
    
    if period == "last_month":
        # First day of last month
        first_of_this_month = reference_date.replace(day=1)
        last_month_end = first_of_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start.strftime("%Y-%m-%d"), last_month_end.strftime("%Y-%m-%d")
    
    elif period == "last_week":
        # Last 7 days
        end_date = reference_date - timedelta(days=1)
        start_date = end_date - timedelta(days=6)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
    
    elif period == "last_7_days":
        end_date = reference_date
        start_date = end_date - timedelta(days=7)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
    
    elif period == "last_30_days":
        end_date = reference_date
        start_date = end_date - timedelta(days=30)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
    
    elif period in ["q1", "q2", "q3", "q4"]:
        # Calculate quarter based on current or previous year
        year = reference_date.year
        quarter_map = {
            "q1": ("01-01", "03-31"),
            "q2": ("04-01", "06-30"),
            "q3": ("07-01", "09-30"),
            "q4": ("10-01", "12-31"),
        }
        start_month_day, end_month_day = quarter_map[period]
        return f"{year}-{start_month_day}", f"{year}-{end_month_day}"
    
    elif period == "last_quarter":
        # Previous quarter
        current_quarter = (reference_date.month - 1) // 3 + 1
        prev_quarter = current_quarter - 1 if current_quarter > 1 else 4
        year = reference_date.year if current_quarter > 1 else reference_date.year - 1
        
        quarter_map = {
            1: ("01-01", "03-31"),
            2: ("04-01", "06-30"),
            3: ("07-01", "09-30"),
            4: ("10-01", "12-31"),
        }
        start_month_day, end_month_day = quarter_map[prev_quarter]
        return f"{year}-{start_month_day}", f"{year}-{end_month_day}"
    
    elif period == "this_month":
        first_of_month = reference_date.replace(day=1)
        return first_of_month.strftime("%Y-%m-%d"), reference_date.strftime("%Y-%m-%d")
    
    elif period == "yesterday":
        yesterday = reference_date - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d")
    
    elif period == "today":
        return reference_date.strftime("%Y-%m-%d"), reference_date.strftime("%Y-%m-%d")
    
    else:
        # Default: last 30 days
        logger.warning(f"Unknown period '{period}', defaulting to last 30 days")
        end_date = reference_date
        start_date = end_date - timedelta(days=30)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


class AthenaCURTemplatesExtensions(AthenaCURTemplates):
    """Extension methods for AthenaCURTemplates that were previously misplaced."""
    pass
