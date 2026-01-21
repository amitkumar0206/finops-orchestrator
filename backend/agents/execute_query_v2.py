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
from datetime import datetime
import asyncio
import boto3

from backend.services.text_to_sql_service import text_to_sql_service
from backend.services.response_formatter import response_formatter
from backend.services.chart_recommendation import chart_engine
from backend.services.chart_data_builder import chart_data_builder
from backend.config.settings import get_settings
from backend.utils.sql_validation import (
    validate_service_code,
    validate_resource_id,
    validate_date,
    ValidationError,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


class AthenaExecutor:
    """Simplified Athena executor for text-to-SQL generated queries"""
    
    def __init__(self):
        self.athena_client = boto3.client('athena', region_name=settings.aws_region)
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
                    'Database': 'cost_usage_db'
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
        
        # Step 1: Generate SQL from natural language
        sql_query, metadata = await text_to_sql_service.generate_sql(
            user_query=query,
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

        results = await executor.execute_sql(sql_query)
        
        # Auto-drill-down: If single service/resource result, fetch breakdown by usage_type
        should_drill_down = False
        original_service_name = None
        original_resource_id = None
        
        if results and len(results) == 1:
            # Check if this is a service-level or resource-level query
            first_row = results[0]
            columns = list(first_row.keys())
            
            # Detect if we have a service column
            if 'service' in columns or 'product_code' in columns or 'line_item_product_code' in columns:
                service_col = next((c for c in ['service', 'product_code', 'line_item_product_code'] if c in columns), None)
                original_service_name = first_row.get(service_col)
                should_drill_down = True
                logger.info(f"Single service result detected: {original_service_name}, drilling down to usage types")
            
            # Detect if we have a resource_id column
            elif 'resource_id' in columns or 'line_item_resource_id' in columns:
                resource_col = next((c for c in ['resource_id', 'line_item_resource_id'] if c in columns), None)
                original_resource_id = first_row.get(resource_col)
                should_drill_down = True
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
FROM cost_usage_db.cur_data
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
                
                logger.info(f"Executing drill-down query for usage types")
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
        
        if not results or len(results) == 0:
            # Use metadata from SQL generation for context-aware messaging
            filters = metadata.get('filters', {})
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
        chart_specs = chart_engine.recommend_charts(
            intent=metadata.get("query_type", "unknown"),
            data_results=results,
            extracted_params={}
        )
        
        charts_with_data = chart_data_builder.build_chart_data(
            chart_specs=chart_specs,
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
            "last_query": query,
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
