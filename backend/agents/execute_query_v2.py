"""
Simplified Query Execution - Pure LLM Text-to-SQL Approach (Option A)

This replaces the complex parameter extraction + template generation workflow.
The LLM directly generates SQL, we execute it, format the response.

Flow:
1. User query → LLM generates SQL
2. Execute SQL in Athena
3. Format response with charts
4. Return to user

No parameter extraction. No templates. Just LLM → SQL → Results.
"""

import structlog
from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta
import asyncio
import re
from backend.services.text_to_sql_service import text_to_sql_service
from backend.services.chart_recommendation import chart_engine
from backend.services.chart_data_builder import chart_data_builder
from backend.utils.followup_query import build_contextual_followup_query
from backend.config.settings import get_settings
from backend.utils.aws_session import create_aws_session
from backend.utils.aws_constants import AwsService
from backend.utils.sql_validation import (
    validate_service_code,
    validate_resource_id,
    validate_date,
    ValidationError,
)

logger = structlog.get_logger(__name__)
settings = get_settings()
COST_EXPLORER_REGION = "us-east-1"
CUR_DATABASE = settings.aws_cur_database or "cost_usage_db"
CUR_TABLE = settings.aws_cur_table or "cur_data"
CUR_TABLE_REF = f"{CUR_DATABASE}.{CUR_TABLE}"
# Kept for backward compatibility — points to same table so retries are no-ops
DEMO_FALLBACK_CUR_TABLE_REF = CUR_TABLE_REF


def _rewrite_legacy_cur_ref(sql_query: str) -> str:
    """No-op: primary and fallback table are the same in current deployments."""
    return sql_query


def _uses_legacy_cur_ref(sql_query: str) -> bool:
    """Always returns False — legacy retry path is disabled."""
    return False


def _fallback_chart_intent(results: List[Dict[str, Any]]) -> str:
    """Infer chart intent when LLM query_type is weak/unknown."""
    if not results:
        return "unknown"

    first = results[0]
    keys = {str(k).lower() for k in first.keys()}

    has_cost = any(k in keys for k in ["cost_usd", "cost", "total_cost_usd"])
    if not has_cost:
        return "unknown"

    if any(k in keys for k in ["usage_date", "date", "month", "day"]):
        return "time_series"
    if "region" in keys or "product_region_code" in keys:
        return "regional"
    if "service" in keys or "service_name" in keys or "line_item_product_code" in keys:
        return "top_services"
    return "breakdown"


def _chart_specs_from_llm_metadata(metadata: Dict[str, Any], results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build chart specs from LLM-provided chart suggestions when available."""
    if not results:
        return []

    raw_specs = metadata.get("chart_suggestions")
    if not isinstance(raw_specs, list) or not raw_specs:
        return []

    first_row = results[0]
    available_fields = {str(k) for k in first_row.keys()}
    allowed_types = {"bar", "column", "line", "area", "pie", "scatter", "stacked_bar", "clustered_bar"}

    # For period comparison datasets, force a known-good rendering shape.
    if {"service", "current_period_cost", "previous_period_cost"}.issubset(available_fields):
        return [{
            "type": "clustered_bar",
            "x": "service",
            "y": "current_period_cost",
            "title": "Current vs Previous Cost by Service",
        }]

    chart_specs: List[Dict[str, Any]] = []
    for raw in raw_specs[:3]:
        if not isinstance(raw, dict):
            continue

        chart_type = str(raw.get("type") or raw.get("chart_type") or "").strip().lower()
        if chart_type not in allowed_types:
            continue

        x_field = raw.get("x") or raw.get("x_field")
        y_field = raw.get("y") or raw.get("y_field")
        series_field = raw.get("series") or raw.get("series_field")

        if x_field not in available_fields or y_field not in available_fields:
            continue
        if series_field and series_field not in available_fields:
            series_field = None

        # Reject specs where y_field is non-numeric (e.g. LLM picks "usage_type" instead of "cost")
        sample_y = first_row.get(y_field)
        if sample_y is not None:
            try:
                float(sample_y)
            except (ValueError, TypeError):
                logger.warning(
                    "LLM chart spec y_field is non-numeric, skipping spec",
                    y_field=y_field,
                    sample_value=sample_y,
                )
                continue

        chart_spec: Dict[str, Any] = {
            "type": chart_type,
            "x": x_field,
            "y": y_field,
            "title": str(raw.get("title") or f"{y_field} by {x_field}"),
        }
        if series_field:
            chart_spec["series"] = series_field

        chart_specs.append(chart_spec)

    return chart_specs


def _is_period_comparison_query(query: str, previous_context: Optional[Dict[str, Any]]) -> bool:
    """Return True for explicit comparison asks with period context available."""
    if not query:
        return False
    q = query.lower()
    has_compare_text = any(token in q for token in ["compare", " vs ", "versus", "month over month", "mom"]) 
    has_compare_context = bool((previous_context or {}).get("comparison_time_range"))
    return has_compare_text and has_compare_context


def _build_period_comparison_sql_and_metadata(
    query: str,
    previous_context: Optional[Dict[str, Any]],
) -> Optional[tuple[str, Dict[str, Any]]]:
    """Build deterministic service-level period comparison query from resolved time ranges."""
    ctx = previous_context or {}
    current_tr = ctx.get("time_range") or {}
    previous_tr = ctx.get("comparison_time_range") or {}

    current_start = current_tr.get("start_date")
    current_end = current_tr.get("end_date")
    previous_start = previous_tr.get("start_date")
    previous_end = previous_tr.get("end_date")

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if not all([current_start, current_end, previous_start, previous_end]):
        return None
    if not all(date_re.match(str(d)) for d in [current_start, current_end, previous_start, previous_end]):
        return None

    sql = f"""
SELECT
    line_item_product_code AS service,
    ROUND(SUM(
        CASE
            WHEN CAST(line_item_usage_start_date AS DATE) >= DATE '{current_start}'
             AND CAST(line_item_usage_start_date AS DATE) <= DATE '{current_end}'
            THEN line_item_unblended_cost
            ELSE 0
        END
    ), 2) AS current_period_cost,
    ROUND(SUM(
        CASE
            WHEN CAST(line_item_usage_start_date AS DATE) >= DATE '{previous_start}'
             AND CAST(line_item_usage_start_date AS DATE) <= DATE '{previous_end}'
            THEN line_item_unblended_cost
            ELSE 0
        END
    ), 2) AS previous_period_cost
FROM {CUR_TABLE_REF}
WHERE (
    CAST(line_item_usage_start_date AS DATE) >= DATE '{previous_start}'
    AND CAST(line_item_usage_start_date AS DATE) <= DATE '{current_end}'
)
AND line_item_product_code IS NOT NULL
AND line_item_product_code != ''
GROUP BY 1
HAVING
    ROUND(SUM(
        CASE
            WHEN CAST(line_item_usage_start_date AS DATE) >= DATE '{current_start}'
             AND CAST(line_item_usage_start_date AS DATE) <= DATE '{current_end}'
            THEN line_item_unblended_cost
            ELSE 0
        END
    ), 2) > 0
    OR
    ROUND(SUM(
        CASE
            WHEN CAST(line_item_usage_start_date AS DATE) >= DATE '{previous_start}'
             AND CAST(line_item_usage_start_date AS DATE) <= DATE '{previous_end}'
            THEN line_item_unblended_cost
            ELSE 0
        END
    ), 2) > 0
ORDER BY current_period_cost DESC
LIMIT 20
""".strip()

    metadata = {
        "explanation": (
            "**Summary:** Service-wise month comparison between the selected current and previous periods.\n\n"
            "**Insights:**\n\n"
            "- **Service Movement**: Each row shows current vs previous period cost for the same service\n"
            "- **Largest Drivers**: Top rows are sorted by current period cost to highlight major contributors\n"
            "- **Comparison Ready**: Data is shaped for side-by-side comparison charts"
        ),
        "result_columns": ["service", "current_period_cost", "previous_period_cost"],
        "query_type": "comparison",
        "chart_suggestions": [
            {
                "type": "clustered_bar",
                "x": "service",
                "y": "current_period_cost",
                "title": "Current vs Previous Cost by Service",
            }
        ],
        "generated_via": "deterministic_period_comparison",
        "status": "ok",
    }
    return sql, metadata


class AthenaExecutor:
    """Simplified Athena executor for text-to-SQL generated queries"""
    
    def __init__(self):
        self.athena_client = create_aws_session().client(AwsService.ATHENA)
        self.database = CUR_DATABASE
        # Extract bucket from athena_output_location setting
        output_loc = settings.athena_output_location
        if not output_loc.endswith('/'):
            output_loc += '/'
        self.output_location = output_loc
    
    async def execute_sql(self, sql_query: str) -> List[Dict[str, Any]]:
        """
        Execute SQL query in Athena and return results.
        
        Args:
            sql_query: Complete SQL query string
            
        Returns:
            List of result rows as dictionaries
        """
        try:
            logger.info(
                "Executing Athena SQL query",
                query_preview=sql_query[:200],
                query_length=len(sql_query)
            )
            
            # Start query execution
            response = self.athena_client.start_query_execution(
                QueryString=sql_query,
                QueryExecutionContext={
                    'Database': self.database
                },
                ResultConfiguration={
                    'OutputLocation': self.output_location
                }
            )
            
            query_execution_id = response['QueryExecutionId']
            logger.info(f"Started Athena query: {query_execution_id}")
            
            # Wait for query to complete
            max_attempts = 30
            attempt = 0
            
            while attempt < max_attempts:
                await asyncio.sleep(1)
                attempt += 1
                
                status_response = self.athena_client.get_query_execution(
                    QueryExecutionId=query_execution_id
                )
                
                status = status_response['QueryExecution']['Status']['State']
                
                if status == 'SUCCEEDED':
                    break
                elif status in ['FAILED', 'CANCELLED']:
                    error_msg = status_response['QueryExecution']['Status'].get(
                        'StateChangeReason', 'Unknown error'
                    )
                    logger.error(f"Athena query failed: {error_msg}")
                    raise Exception(f"Query {status}: {error_msg}")
            
            if attempt >= max_attempts:
                raise Exception("Query timeout - took longer than 30 seconds")
            
            logger.info(f"Query succeeded after {attempt} attempts")
            
            # Get results
            results_response = self.athena_client.get_query_results(
                QueryExecutionId=query_execution_id,
                MaxResults=1000
            )
            
            # Parse results into list of dicts
            rows = results_response['ResultSet']['Rows']
            
            if not rows or len(rows) < 2:
                logger.warning("Query returned no data rows")
                return []
            
            # First row is headers
            headers = [col['VarCharValue'] for col in rows[0]['Data']]
            
            # Convert remaining rows to dicts
            results = []
            for row in rows[1:]:
                row_dict = {}
                for i, col in enumerate(row['Data']):
                    value = col.get('VarCharValue')
                    # Try to convert numeric strings to numbers
                    if value and value.replace('.', '', 1).replace('-', '', 1).replace('e', '', 1).replace('E', '', 1).replace('+', '', 1).isdigit():
                        try:
                            row_dict[headers[i]] = float(value) if '.' in value else int(value)
                        except:
                            row_dict[headers[i]] = value
                    else:
                        row_dict[headers[i]] = value
                results.append(row_dict)
            
            logger.info(f"Query returned {len(results)} rows")
            return results
            
        except Exception as e:
            logger.error(
                "Athena query execution failed",
                error=str(e),
                error_type=type(e).__name__
            )
            raise


async def _fetch_cost_explorer_fallback(
    previous_context: Optional[Dict[str, Any]],
    *,
    max_rows: int = 10,
) -> List[Dict[str, Any]]:
    """Fetch a service cost breakdown from Cost Explorer as a fallback."""
    context = previous_context or {}
    tr = context.get("time_range") or {}
    start_date = tr.get("start_date") or (date.today() - timedelta(days=30)).isoformat()
    end_date = tr.get("end_date") or date.today().isoformat()
    account_ids = [a for a in (context.get("account_ids") or []) if a]

    ce_client = create_aws_session(region_name=COST_EXPLORER_REGION).client(AwsService.COST_EXPLORER)
    def _build_rows(req: Dict[str, Any]) -> List[Dict[str, Any]]:
        response = ce_client.get_cost_and_usage(**req)
        rows: List[Dict[str, Any]] = []
        for period in response.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                try:
                    amount = float(((group.get("Metrics") or {}).get("BlendedCost") or {}).get("Amount") or 0)
                except (TypeError, ValueError):
                    amount = 0.0
                if amount <= 0:
                    continue
                keys = group.get("Keys") or []
                rows.append({
                    "service": keys[0] if keys else "Unknown",
                    "cost_usd": round(amount, 2),
                })
        rows.sort(key=lambda r: float(r.get("cost_usd") or 0), reverse=True)
        return rows[:max_rows]

    req: Dict[str, Any] = {
        "TimePeriod": {"Start": start_date, "End": end_date},
        "Granularity": "MONTHLY",
        "Metrics": ["BlendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    if account_ids:
        req["Filter"] = {
            "Dimensions": {
                "Key": "LINKED_ACCOUNT",
                "Values": account_ids,
            }
        }

    out = _build_rows(req)
    if out:
        return out

    # Demo mode often uses synthetic scoped account IDs; retry unfiltered so
    # users still get a meaningful high-level cost view when scope is non-real.
    if account_ids and (settings.demo_mode or settings.config_demo_auth_enabled):
        req.pop("Filter", None)
        logger.info("Cost Explorer fallback retrying without account filter in demo mode")
        return _build_rows(req)

    return out


async def execute_query_simple(
    query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    previous_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Simplified query execution using pure text-to-SQL approach.
    
    Args:
        query: Natural language query from user
        conversation_history: Previous messages
        previous_context: Context from previous query
        
    Returns:
        Response dict with message, charts, suggestions
    """
    try:
        logger.info("Executing query with text-to-SQL approach", query=query[:100])

        # Preserve prior drill-down scope for terse time-only follow-ups.
        rewrite_context: Dict[str, Any] = dict(previous_context or {})
        if conversation_history and "conversation_history" not in rewrite_context:
            rewrite_context["conversation_history"] = conversation_history

        effective_query = build_contextual_followup_query(query, rewrite_context)
        if effective_query != query:
            logger.info(
                "Rewrote follow-up query with prior context",
                original_query=query[:120],
                effective_query=effective_query[:160],
            )
        
        # Step 1: Generate SQL from natural language (or deterministic comparison path)
        deterministic = None
        if _is_period_comparison_query(effective_query, previous_context):
            deterministic = _build_period_comparison_sql_and_metadata(effective_query, previous_context)

        if deterministic:
            sql_query, metadata = deterministic
        else:
            sql_query, metadata = await text_to_sql_service.generate_sql(
                user_query=effective_query,
                conversation_history=conversation_history,
                previous_context=previous_context
            )
        
        logger.info(
            "SQL generated",
            query_type=metadata.get("query_type"),
            explanation=metadata.get("explanation")
        )
        
        # Step 2: Execute SQL in Athena (only if we have a valid SQL)
        executor = AthenaExecutor()
        if not sql_query:
            # Return a clarification/error payload without executing
            status = metadata.get("status")
            suggestions = []
            clar_qs = metadata.get("clarification") or []
            if isinstance(clar_qs, list):
                suggestions.extend(clar_qs)
            suggestions.extend([
                "Show me my AWS costs for the last 30 days",
                "Show November 2025 costs by service",
                "Break it down by resource"
            ])
            return {
                "message": "",
                "summary": "",
                "insights": [],
                "recommendations": [],
                "results": [],
                "charts": [],
                "suggestions": suggestions,
                "athena_query": None,
                "metadata": metadata,
                "context": {"last_query": query, "timestamp": datetime.now().isoformat()}
            }

        try:
            results = await executor.execute_sql(sql_query)
        except Exception as execute_error:
            error_text = str(execute_error)
            fallback_markers = [
                "SCHEMA_NOT_FOUND",
                "Unable to verify/create output bucket",
                "The S3 location provided to save your query results is invalid",
            ]
            if any(marker in error_text for marker in fallback_markers):
                # First retry: legacy demo reference can still exist in runtime env.
                # If so, rewrite to the current demo view and retry Athena directly.
                if _uses_legacy_cur_ref(sql_query):
                    rewritten_sql = _rewrite_legacy_cur_ref(sql_query)
                    if rewritten_sql != sql_query:
                        try:
                            logger.warning(
                                "Retrying Athena query with demo CUR table rewrite",
                                from_table="cost_usage_db.cur_data",
                                to_table=DEMO_FALLBACK_CUR_TABLE_REF,
                            )
                            sql_query = rewritten_sql
                            results = await executor.execute_sql(sql_query)
                        except Exception as rewrite_error:
                            logger.warning(
                                "Athena retry with rewritten CUR table failed",
                                error=str(rewrite_error),
                            )
                            results = []
                        else:
                            metadata["rewritten_cur_source"] = True
                            metadata["cur_table_ref"] = DEMO_FALLBACK_CUR_TABLE_REF

                if results:
                    pass
                else:
                    logger.warning(
                        "Athena execution failed, using Cost Explorer fallback",
                        error=error_text,
                    )
                    results = await _fetch_cost_explorer_fallback(previous_context)
                    if results:
                        metadata["generated_via"] = "cost_explorer_fallback"
                        metadata["status"] = "ok"
                        metadata["fallback_reason"] = error_text
                        metadata["query_type"] = "top_services"
                        metadata["explanation"] = (
                            "**Cost Explorer Fallback**\n\n"
                            "Athena results were temporarily unavailable for this account, so I used AWS Cost Explorer "
                            "to provide a service-level cost breakdown for the requested period."
                        )
            else:
                raise
        
        # Auto-drill-down is opt-in only. Default behavior should follow LLM query_type
        # and return the exact result set produced by SQL.
        should_drill_down = bool(metadata.get("enable_auto_drilldown"))
        original_service_name = None
        original_resource_id = None
        
        if should_drill_down and results and len(results) == 1:
            # Check if this is a service-level or resource-level query
            first_row = results[0]
            columns = list(first_row.keys())
            
            # Detect if we have a service column
            if 'service' in columns or 'product_code' in columns or 'line_item_product_code' in columns:
                service_col = next((c for c in ['service', 'product_code', 'line_item_product_code'] if c in columns), None)
                original_service_name = first_row.get(service_col)
                logger.info(f"Single service result detected: {original_service_name}, drilling down to usage types")
            
            # Detect if we have a resource_id column
            elif 'resource_id' in columns or 'line_item_resource_id' in columns:
                resource_col = next((c for c in ['resource_id', 'line_item_resource_id'] if c in columns), None)
                original_resource_id = first_row.get(resource_col)
                logger.info(f"Single resource result detected: {original_resource_id}, drilling down to usage types")
        
        # Execute drill-down query if needed
        if should_drill_down:
            try:
                # Build drill-down SQL to get usage_type breakdown
                drill_down_sql = f"""
SELECT 
    line_item_usage_type AS usage_type,
    ROUND(SUM(
        CASE 
            WHEN line_item_line_item_type = 'Usage' THEN line_item_unblended_cost
            WHEN line_item_line_item_type = 'DiscountedUsage' THEN line_item_unblended_cost
            WHEN line_item_line_item_type = 'Fee' THEN line_item_unblended_cost
            ELSE 0
        END
    ), 2) AS cost_usd
FROM {CUR_TABLE_REF}
WHERE 1=1
"""
                # Add service filter if we have it - VALIDATE to prevent SQL injection
                if original_service_name:
                    try:
                        validated_service = validate_service_code(str(original_service_name))
                        drill_down_sql += f"\n  AND line_item_product_code = '{validated_service}'"
                    except ValidationError as e:
                        logger.warning("Invalid service name in drill-down, skipping filter", service=str(original_service_name)[:50], error=str(e))

                # Add resource filter if we have it - VALIDATE to prevent SQL injection
                if original_resource_id:
                    try:
                        validated_resource = validate_resource_id(str(original_resource_id))
                        drill_down_sql += f"\n  AND line_item_resource_id = '{validated_resource}'"
                    except ValidationError as e:
                        logger.warning("Invalid resource ID in drill-down, skipping filter", resource=str(original_resource_id)[:50], error=str(e))

                # Extract time range from original SQL (simple pattern matching)
                import re
                date_match = re.search(r"line_item_usage_start_date.*?>=.*?DATE '(\d{4}-\d{2}-\d{2})'", sql_query, re.IGNORECASE)
                if date_match:
                    extracted_start_date = date_match.group(1)
                    try:
                        validated_start = validate_date(extracted_start_date)
                        drill_down_sql += f"\n  AND CAST(line_item_usage_start_date AS DATE) >= DATE '{validated_start}'"
                    except ValidationError as e:
                        logger.warning("Invalid start date in drill-down", date=extracted_start_date, error=str(e))

                date_match = re.search(r"line_item_usage_start_date.*?<=.*?DATE '(\d{4}-\d{2}-\d{2})'", sql_query, re.IGNORECASE)
                if date_match:
                    extracted_end_date = date_match.group(1)
                    try:
                        validated_end = validate_date(extracted_end_date)
                        drill_down_sql += f"\n  AND CAST(line_item_usage_start_date AS DATE) <= DATE '{validated_end}'"
                    except ValidationError as e:
                        logger.warning("Invalid end date in drill-down", date=extracted_end_date, error=str(e))
                
                drill_down_sql += """
GROUP BY line_item_usage_type
HAVING SUM(
    CASE 
        WHEN line_item_line_item_type = 'Usage' THEN line_item_unblended_cost
        WHEN line_item_line_item_type = 'DiscountedUsage' THEN line_item_unblended_cost
        WHEN line_item_line_item_type = 'Fee' THEN line_item_unblended_cost
        ELSE 0
    END
) > 0
ORDER BY cost_usd DESC
LIMIT 20
"""
                
                logger.info("Executing drill-down query for usage types")
                drill_down_results = await executor.execute_sql(drill_down_sql)
                
                # Use drill-down results if we got multiple rows
                if drill_down_results and len(drill_down_results) > 1:
                    logger.info(f"Drill-down successful: {len(drill_down_results)} usage types found")
                    results = drill_down_results
                    # Update metadata to reflect drill-down
                    metadata['query_type'] = 'cost_breakdown'
                    metadata['drilled_down'] = True
                    metadata['original_service'] = original_service_name
                    metadata['original_resource'] = original_resource_id
                    
                    # Update explanation to mention drill-down
                    original_explanation = metadata.get('explanation', '')
                    entity_name = original_service_name or original_resource_id
                    metadata['explanation'] = (
                        f"**Breakdown by Usage Type for {entity_name}**\n\n"
                        f"{original_explanation}\n\n"
                        f"**Drill-Down Analysis**: Since you queried a single {'service' if original_service_name else 'resource'}, "
                        f"I'm showing you the breakdown by usage type to give you more actionable insights."
                    )
            except Exception as e:
                logger.warning(f"Drill-down query failed, using original results: {e}")
                # Continue with original results
                pass
        
        # Secondary retry path: some legacy queries can return empty rows even
        # when data exists in the modern demo view. Retry once with rewritten SQL.
        if (not results or len(results) == 0) and _uses_legacy_cur_ref(sql_query):
            rewritten_sql = _rewrite_legacy_cur_ref(sql_query)
            if rewritten_sql != sql_query:
                try:
                    logger.warning(
                        "No rows from legacy CUR table, retrying with demo CUR view",
                        from_table="cost_usage_db.cur_data",
                        to_table=DEMO_FALLBACK_CUR_TABLE_REF,
                    )
                    retry_results = await executor.execute_sql(rewritten_sql)
                    if retry_results:
                        results = retry_results
                        sql_query = rewritten_sql
                        metadata["rewritten_cur_source"] = True
                        metadata["cur_table_ref"] = DEMO_FALLBACK_CUR_TABLE_REF
                except Exception as retry_error:
                    logger.warning(
                        "Retry after no-row legacy query failed",
                        error=str(retry_error),
                    )

        if not results or len(results) == 0:
            # Use metadata from SQL generation for context-aware messaging
            filters = metadata.get('filters', {})
            if not isinstance(filters, dict):
                filters = {}
            service_filter = filters.get('service', '')
            time_period = metadata.get('time_period', 'the requested period')
            scope = metadata.get('scope', 'Overall')
            
            # Build contextual no-data message using metadata
            service_text = f" for {service_filter}" if service_filter else ""
            scope_text = f" ({scope})" if scope != 'Overall' else ""
            
            return {
                "message": (
                    f"**No Cost Data Found**\n\n"
                    f"**Summary:** No cost data found{service_text}{scope_text} during {time_period}.\n\n"
                    f"**Possible Reasons:**\n\n"
                    f"- **No usage**: The queried resources had no billable activity during this period\n"
                    f"- **Data delay**: CUR data typically has 24-48 hour lag; recent dates may be incomplete\n"
                    f"- **Filter mismatch**: Specific service/region/resource filters may be too restrictive\n"
                    f"- **Time window**: The selected period may fall outside available data (Sept 2024 - present)\n\n"
                    f"**Suggested Actions:**\n\n"
                    f"1. **Expand time range**: Try 'last 30 days' or 'last 3 months'\n"
                    f"2. **Broaden scope**: Query 'overall AWS costs' or 'top services'\n"
                    f"3. **Verify filters**: Check if service/region filters match actual usage\n"
                    f"4. **Check recent data**: Query 'costs for last complete month'"
                ),
                "charts": [],
                "suggestions": [
                    "Show me overall AWS costs for last 30 days",
                    "What are my top 5 most expensive services?",
                    "Show me costs for last complete month"
                ],
                "athena_query": sql_query,
                "metadata": metadata,
                "results": []
            }
        
        # Step 3: Generate charts from results
        # Prefer explicit chart suggestions from LLM metadata; fallback to heuristics if absent/invalid.
        chart_specs = _chart_specs_from_llm_metadata(metadata, results)

        if not chart_specs:
            # Force comparison chart intent for dual-period result sets so UI renders side-by-side bars.
            chart_intent = metadata.get("query_type", "unknown")
            if results and all(
                col in results[0] for col in ["current_period_cost", "previous_period_cost"]
            ):
                chart_intent = "comparison"

            if chart_intent in ["unknown", None, ""]:
                chart_intent = _fallback_chart_intent(results)

            chart_specs = chart_engine.recommend_charts(
                intent=chart_intent,
                data_results=results,
                extracted_params={}
            )

            if not chart_specs and results:
                chart_specs = chart_engine.recommend_charts(
                    intent=_fallback_chart_intent(results),
                    data_results=results,
                    extracted_params={}
                )

        charts_with_data = chart_data_builder.build_chart_data(
            chart_specs=chart_specs,
            data_results=results,
            conv_context=None
        )

        # Last safety net: if LLM-directed specs produced no renderable charts, use heuristic recommendations.
        if not charts_with_data and results:
            fallback_intent = metadata.get("query_type") or _fallback_chart_intent(results)
            fallback_specs = chart_engine.recommend_charts(
                intent=fallback_intent,
                data_results=results,
                extracted_params={}
            )
            if not fallback_specs:
                fallback_specs = chart_engine.recommend_charts(
                    intent=_fallback_chart_intent(results),
                    data_results=results,
                    extracted_params={}
                )
            charts_with_data = chart_data_builder.build_chart_data(
                chart_specs=fallback_specs,
                data_results=results,
                conv_context=None
            )
        
        # Step 4: Use LLM's explanation as the response
        # The LLM already provides rich analysis, insights, and recommendations in the explanation
        formatted_response = metadata.get("explanation", "Here are your results.")

        # Add a simple data summary if the explanation doesn't include numbers
        if results:
            # Helper to extract cost from any cost column
            def _get_cost(row):
                cost_columns = ['cost_usd', 'cost', 'total_cost_usd', 'daily_cost_usd', 'monthly_cost_usd', 'hourly_cost_usd']
                for col in cost_columns:
                    if col in row:
                        return float(row.get(col) or 0)
                return 0.0
            
            total_cost = sum(_get_cost(row) for row in results)

            # Replace standardized ${Variable} placeholders with actual values from results
            try:
                import re

                # Compute metrics from results
                def _extract_dim_and_cost(r):
                    # List of known cost column patterns
                    cost_columns = ['cost_usd', 'cost', 'total_cost_usd', 'daily_cost_usd', 'monthly_cost_usd', 'hourly_cost_usd']
                    # List of known non-dimension columns (time, cost, percentages, etc.)
                    excluded_columns = cost_columns + ['pct_of_total', 'date', 'usage_date', 'month', 'week', 'day', 'year', 'time', 'timestamp', 'period']
                    
                    # Find the dimension column (first column that's not cost/time/percentage)
                    dim_col = next((k for k in r.keys() if k not in excluded_columns), None)
                    
                    # Find the cost value from any cost column
                    cost_val = None
                    for cost_col in cost_columns:
                        if cost_col in r:
                            cost_val = r.get(cost_col)
                            break
                    
                    return dim_col, r.get(dim_col) if dim_col else None, float(cost_val or 0)

                # Extract top items and their costs
                top_items = []
                if results:
                    dim_costs = [_extract_dim_and_cost(r) for r in results]
                    # Sort by cost descending
                    sorted_items = sorted(dim_costs, key=lambda t: t[2], reverse=True)
                    top_items = [(item[1], item[2]) for item in sorted_items if item[1]]

                # Calculate metrics
                num_items = len(results)
                top_item_name = top_items[0][0] if top_items else "N/A"
                top_item_cost = top_items[0][1] if top_items else 0.0
                top_pct = (top_item_cost / total_cost * 100.0) if total_cost > 0 else 0.0
                
                # Top 2 combined percentage
                top2_cost = sum(item[1] for item in top_items[:2]) if len(top_items) >= 2 else top_item_cost
                top2_pct = (top2_cost / total_cost * 100.0) if total_cost > 0 else 0.0
                
                # Top 3 combined percentage
                top3_cost = sum(item[1] for item in top_items[:3]) if len(top_items) >= 3 else top2_cost
                top3_pct = (top3_cost / total_cost * 100.0) if total_cost > 0 else 0.0
                
                # Top 5 combined percentage
                top5_cost = sum(item[1] for item in top_items[:5]) if len(top_items) >= 5 else top3_cost
                top5_pct = (top5_cost / total_cost * 100.0) if total_cost > 0 else 0.0

                # Standardized placeholder mapping (${Variable} format)
                placeholder_values = {
                    'TotalCost': f"${total_cost:,.2f}",
                    'TopItem': top_item_name,
                    'TopCost': f"${top_item_cost:,.2f}",
                    'TopPct': f"{top_pct:.0f}%",
                    'Top2Pct': f"{top2_pct:.0f}%",
                    'Top3Pct': f"{top3_pct:.0f}%",
                    'Top5Pct': f"{top5_pct:.0f}%",
                    'NumItems': str(num_items),
                    'Item1': top_items[0][0] if len(top_items) > 0 else "N/A",
                    'Item2': top_items[1][0] if len(top_items) > 1 else "N/A",
                    'Item3': top_items[2][0] if len(top_items) > 2 else "N/A",
                    'Item1Cost': f"${top_items[0][1]:,.2f}" if len(top_items) > 0 else "$0.00",
                    'Item2Cost': f"${top_items[1][1]:,.2f}" if len(top_items) > 1 else "$0.00",
                    'Item3Cost': f"${top_items[2][1]:,.2f}" if len(top_items) > 2 else "$0.00",
                    'Item4Cost': f"${top_items[3][1]:,.2f}" if len(top_items) > 3 else "$0.00",
                    'Item5Cost': f"${top_items[4][1]:,.2f}" if len(top_items) > 4 else "$0.00",
                }
                
                # Month-over-month comparison placeholders (2 data points with date/month field)
                if len(results) == 2:
                    has_date_field = any(k in results[0] for k in ['date', 'month', 'period'])
                    if has_date_field:
                        # Extract costs for both periods
                        period1_cost = float(results[0].get('cost_usd', results[0].get('cost', 0)))
                        period2_cost = float(results[1].get('cost_usd', results[1].get('cost', 0)))
                        
                        # Calculate difference and trend
                        if period1_cost > 0:
                            diff_pct = ((period2_cost - period1_cost) / period1_cost) * 100
                        else:
                            diff_pct = 0
                        
                        trend_direction = "increased" if diff_pct > 0 else "decreased" if diff_pct < 0 else "remained stable"
                        
                        # Extract period names (month, date, etc.)
                        period1_name = str(results[0].get('month', results[0].get('date', results[0].get('period', 'Period 1'))))
                        period2_name = str(results[1].get('month', results[1].get('date', results[1].get('period', 'Period 2'))))
                        
                        # Add month/period-specific placeholders
                        placeholder_values.update({
                            'Difference': f"{abs(diff_pct):.1f}",
                            'TrendDirection': trend_direction,
                            'Period1Cost': f"${period1_cost:,.2f}",
                            'Period2Cost': f"${period2_cost:,.2f}",
                            'AprilCost': f"${period1_cost:,.2f}",  # Alias for first period
                            'MayCost': f"${period2_cost:,.2f}",     # Alias for second period
                            'FirstPeriod': period1_name,
                            'SecondPeriod': period2_name,
                        })

                # Replace ${Variable} placeholders (handles both ${Var} and ${{Var}} formats)
                for var_name, var_value in placeholder_values.items():
                    formatted_response = formatted_response.replace(f"${{{var_name}}}", str(var_value))  # Single braces
                    formatted_response = formatted_response.replace(f"${{{{{var_name}}}}}", str(var_value))  # Double braces

            except Exception as e:
                # Non-blocking: Log but don't fail on placeholder replacement errors
                logger.warning(f"Placeholder replacement failed: {e}")
                pass

            # Only add summary if explanation is very short (LLM didn't provide rich content)
            if len(formatted_response) < 100:
                formatted_response += f"\n\n**Total Cost**: ${total_cost:,.2f}\n\n**Top Results**:\n"
                for i, row in enumerate(results[:5], 1):
                    # Find the dimension column
                    dim_col = next((k for k in row.keys() if k not in ['cost_usd', 'cost', 'pct_of_total', 'date', 'total_cost_usd']), None)
                    if dim_col:
                        dim_value = row.get(dim_col, 'Unknown')
                        cost = row.get('cost_usd', row.get('cost', row.get('total_cost_usd', 0)))
                        formatted_response += f"{i}. **{dim_value}**: ${cost:,.2f}\n"
        
        # Step 5: Generate follow-up suggestions
        suggestions = _generate_suggestions(query, results, metadata)
        
        # Extract context for next query
        updated_context = {
            "last_query": effective_query,
            "last_sql": sql_query,
            "last_query_type": metadata.get("query_type"),
            "result_columns": metadata.get("result_columns", []),
            "timestamp": datetime.now().isoformat()
        }
        
        # Extract service from results if present
        if results and "service" in results[0]:
            updated_context["last_service"] = results[0]["service"]
        
        logger.info(
            "Query execution successful",
            rows=len(results),
            charts=len(charts_with_data)
        )
        
        # Parse structured response from formatted text
        structured_response = _parse_structured_response(formatted_response)
        
        logger.info(
            "Structured response parsed",
            has_summary=bool(structured_response.get("summary")),
            num_insights=len(structured_response.get("insights", [])),
            num_recommendations=len(structured_response.get("recommendations", [])),
            summary_preview=structured_response.get("summary", "")[:100] if structured_response.get("summary") else ""
        )
        
        # Ensure metadata always has period, scope, filters, recommendations
        metadata.setdefault("time_period", metadata.get("time_period") or None)
        metadata.setdefault("scope", metadata.get("scope") or None)
        metadata.setdefault("filters", metadata.get("filters") or None)
        metadata.setdefault("recommendations", metadata.get("recommendations") or None)
        return {
            "message": formatted_response,  # Keep for backward compatibility
            "summary": structured_response.get("summary", ""),
            "insights": structured_response.get("insights", []),
            "recommendations": structured_response.get("recommendations", []),
            "results": results,  # Raw data for frontend to render table
            "charts": charts_with_data,
            "suggestions": suggestions,
            "athena_query": sql_query,
            "metadata": metadata,
            "context": updated_context
        }
        
    except Exception as e:
        error_str = str(e)
        logger.error(
            "Query execution failed",
            error=error_str,
            query=query[:100]
        )
        
        # Detect common SQL/Athena errors and provide helpful guidance
        status = "llm_error"
        clarifications = []
        
        if "COLUMN_NOT_FOUND" in error_str or "cannot be resolved" in error_str:
            clarifications = [
                "The query tried to use a column that doesn't exist in the data. This might be too complex for automatic generation.",
                "Try simplifying your request (e.g., 'Show EC2 costs by instance type' instead of 'Compare Linux vs Windows')."
            ]
        elif "SYNTAX_ERROR" in error_str or "mismatched input" in error_str:
            clarifications = [
                "The generated query has a syntax error. Please rephrase your question more simply.",
                "Example: 'Show me EC2 costs for October 2025 by region'"
            ]
        elif "PERMISSION" in error_str or "not authorized" in error_str:
            clarifications = [
                "Access to the requested data may be restricted. Try a simpler cost breakdown query."
            ]
        else:
            clarifications = [
                "I couldn't complete your request reliably. Please rephrase or specify a time period.",
                "Example: 'Show me my top 5 AWS services by cost for November 2025'"
            ]
        
        return {
            "message": "",
            "summary": "",
            "insights": [],
            "recommendations": [],
            "results": [],
            "charts": [],
            "suggestions": clarifications + [
                "Show me my AWS costs for the last 30 days",
                "What are my top 5 most expensive services?"
            ],
            "athena_query": None,
            "metadata": {
                "status": status,
                "clarification": clarifications,
                "error": error_str
            },
            "context": {"last_query": query, "timestamp": datetime.now().isoformat()}
        }


def _parse_structured_response(formatted_text: str) -> Dict[str, Any]:
    """
    Parse formatted markdown response into structured sections.
    Extracts Summary, Insights, and Recommendations into separate fields.
    """
    import re
    
    result = {
        "summary": "",
        "insights": [],
        "recommendations": []
    }
    
    # Extract Summary (text after **Summary:** until next section or end)
    summary_match = re.search(r'\*\*Summary:\*\*\s*([^\n]+)', formatted_text)
    if summary_match:
        result["summary"] = summary_match.group(1).strip()
    
    # Extract Insights (bullet points under **Insights:**)
    insights_section = re.search(r'\*\*Insights:\*\*\s*\n((?:[-•*]\s*\*\*[^:]+\*\*:[^\n]+\n?)+)', formatted_text)
    if insights_section:
        insight_lines = insights_section.group(1).strip().split('\n')
        for line in insight_lines:
            # Match: - **Category**: Description
            insight_match = re.match(r'^[-•*]\s*\*\*([^:]+)\*\*:\s*(.+)$', line.strip())
            if insight_match:
                result["insights"].append({
                    "category": insight_match.group(1).strip(),
                    "description": insight_match.group(2).strip()
                })
    
    # Extract Recommendations (numbered list under **Recommendations:**)
    recommendations_section = re.search(r'\*\*Recommendations:\*\*\s*\n((?:\d+\.\s*\*\*[^:]+\*\*:[^\n]+\n?)+)', formatted_text)
    if recommendations_section:
        rec_lines = recommendations_section.group(1).strip().split('\n')
        for line in rec_lines:
            # Match: 1. **Action**: Description
            rec_match = re.match(r'^\d+\.\s*\*\*([^:]+)\*\*:\s*(.+)$', line.strip())
            if rec_match:
                result["recommendations"].append({
                    "action": rec_match.group(1).strip(),
                    "description": rec_match.group(2).strip()
                })
    
    return result


def _generate_suggestions(
    query: str,
    results: List[Dict[str, Any]],
    metadata: Dict[str, Any]
) -> List[str]:
    """Generate contextual follow-up suggestions based on results"""
    
    suggestions = []
    query_type = metadata.get("query_type", "unknown")
    
    # If we returned services, suggest drilling down
    if results and "service" in results[0]:
        top_service = results[0]["service"]
        suggestions.append(f"Break down {top_service} costs by region")
        suggestions.append(f"Show {top_service} cost trends over time")
    
    # If we showed a breakdown, suggest going deeper
    if query_type == "breakdown":
        suggestions.append("Show me usage details for the top item")
        suggestions.append("Compare this with last month")
    
    # If we showed top services, suggest optimization
    if query_type == "top_services":
        suggestions.append("How can I optimize costs for these services?")
        suggestions.append("Show cost trends for top 3 services")
    
    # Always include a general suggestion
    suggestions.append("What are my top optimization opportunities?")
    
    return suggestions[:3]  # Return max 3 suggestions
