"""
Response Formatter - Structured response generation following FinOps presentation template
Implements: Summary, Scope, Results, Insights, Recommended Charts, Next steps
"""

from typing import Dict, List, Any, Optional, Union, Tuple
from datetime import datetime, date
import re
import structlog

from backend.utils.date_parser import date_parser
from backend.agents.intent_classifier import IntentType
from backend.services.column_constants import DIMENSION_VALUE, SERVICE, REGION, COST_USD, RESOURCE_TYPE

logger = structlog.get_logger(__name__)


class FinOpsResponseFormatter:
    """
    Formats analysis results into beautiful, structured FinOps responses.
    Follows the standard template: Summary → Scope → Results → Insights → Charts → Next steps
    """
    
    def __init__(self):
        """Initialize formatter"""
        pass
    
    def format_response(
        self,
        intent: str,
        query: str,
        data_results: List[Dict[str, Any]],
        extracted_params: Dict[str, Any],
        insights: Optional[List[str]] = None,
        chart_data: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        spec: Optional["QuerySpec"] = None  # Unified spec if available
    ) -> str:
        """
        Format complete FinOps response following the template.
        
        Args:
            intent: Query intent type
            query: Original user query
            data_results: Query results from Athena
            extracted_params: Extracted parameters (time_range, services, etc.)
            insights: Generated insights
            chart_data: Built chart data ready for frontend rendering (Chart.js format)
            metadata: Additional metadata (execution time, etc.)
            spec: QuerySpec instance (preferred source of metadata)
            
        Returns:
            Markdown-formatted response string
        """
        # Prefer metadata from QuerySpec if available
        if spec and hasattr(spec, 'metadata'):
            params_metadata = {**extracted_params.get("metadata", {}), **spec.metadata}
        else:
            params_metadata = extracted_params.get("metadata", {}) or {}
        explanation_request = params_metadata.get("explanation_request")
        if metadata:
            explanation_request = explanation_request or metadata.get("explanation_request")

        # Initialize the response lines list
        lines = []

        def add_section(title: str, content: Optional[Union[str, List[str]]]) -> None:
            """Append a section header and its lines with tight spacing"""
            if content is None:
                return
            if isinstance(content, str):
                raw_lines = [line.rstrip() for line in content.strip().splitlines() if line.strip()]
            else:
                raw_lines = [line.rstrip() for line in content if line and line.strip()]
            if not raw_lines:
                return
            if lines:
                lines.append("")
            lines.append(f"**{title}:**")
            lines.extend(raw_lines)
        
        # 1. Summary (1-2 sentences with key numbers)
        summary = self._generate_summary(intent, query, data_results, extracted_params).strip()
        add_section("Summary", summary)
        
        # 1.5. Data Availability Warning (if applicable)
        availability_warning = self._check_data_availability(data_results, extracted_params)
        if availability_warning:
            lines.append("")
            lines.append(f"⚠️ **Data Availability Notice:** {availability_warning}")
        
        # 2. Insights (present early for quick wins)
        if insights and len(insights) > 0:
            insights_section = self._format_insights(insights)
        else:
            insights_section = self._generate_default_insights(intent, data_results, extracted_params)
        add_section("Insights", insights_section)
        
        # 3. Results - Skip table if we have charts (charts will visualize the data)
        # Only show a simple data summary instead of full table
        if not chart_data or len(chart_data) == 0:
            # No charts available, show table
            results_table = self._generate_results_table(intent, data_results, extracted_params)
            add_section("Results", results_table)
        else:
            # Charts available, show simple summary instead of table
            results_summary = self._generate_results_summary(intent, data_results, extracted_params)
            add_section("Results", results_summary)
        
        # 4. Methodology (for explanation-style breakdowns)
        methodology_section = self._generate_breakdown_methodology(data_results, extracted_params)
        add_section("Methodology", methodology_section)
        
        # 4. Scope (period + filters)
        scope = self._generate_scope(extracted_params, data_results)
        add_section("Scope", scope)
        
        # 5. Generate next steps for clickable suggestions (don't add to text - redundant)
        _, next_steps_array = self._generate_next_steps(intent, data_results, extracted_params)
        
        # Store next steps array for API to extract as clickable suggestions
        self._last_next_steps = next_steps_array
        
        return "\n".join(lines).strip()
    
    def get_suggestions(self) -> List[str]:
        """Get the last generated next steps as clickable suggestions"""
        return getattr(self, '_last_next_steps', [])
    
    def _generate_summary(
        self,
        intent: str,
        query: str,
        data_results: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> str:
        """Generate 1-2 sentence summary with key numbers"""
        from agents.intent_classifier import IntentType
        
        period_suffix = self._format_period_suffix(params)
        
        if intent == IntentType.TOP_N_RANKING:
            # Top N ranking summary
            top_n = params.get("top_n", len(data_results))
            params_metadata = params.get("metadata", {}) or {}
            
            # Check if this is actually a breakdown of a single top service (top_n=1 enriched with breakdown)
            top_service_breakdown = params_metadata.get("top_service_breakdown")
            if top_service_breakdown:
                # This is a breakdown scenario - use the breakdown summary instead
                service_name = self._humanize_service_name(top_service_breakdown.get("service"))
                total_cost = top_service_breakdown.get("total_cost", 0)
                count = len(data_results)
                
                # Get top cost driver
                if data_results:
                    top_driver = data_results[0]
                    driver_name = (
                        top_driver.get("dimension_value") or 
                        top_driver.get("usage_type") or 
                        top_driver.get("region") or
                        "item"
                    )
                    driver_cost = top_driver.get("cost_usd", 0)
                    driver_pct = top_driver.get("pct_of_service", 0)
                    
                    return (
                        f"**{service_name}** was your highest costing service at **${total_cost:,.2f}**{period_suffix}. "
                        f"Top contributor: **{driver_name}** at **${driver_cost:,.2f}** ({driver_pct:.1f}% of total)."
                    )
                else:
                    return (
                        f"Your highest costing service is **{service_name}** at **${total_cost:,.2f}**{period_suffix}."
                    )
            
            # Regular TOP_N_RANKING summary
            if data_results:
                top_item = data_results[0]
                service_name = top_item.get("service", top_item.get("dimension_value", "service"))
                cost = top_item.get("cost_usd", top_item.get("total_cost", 0))
                pct = top_item.get("pct_of_total", 0)
                
                # Calculate percentage manually if not provided or if it's 0
                total_shown = sum(r.get("cost_usd", r.get("total_cost", 0)) for r in data_results)
                if total_shown > 0:  # Ensure we don't divide by zero
                    if pct == 0 and cost > 0:
                        pct = (cost / total_shown) * 100
                        logger.info(
                            "Calculated percentage manually for top item",
                            service=service_name,
                            cost=cost,
                            total=total_shown,
                            calculated_pct=pct
                        )
                else:
                    logger.warning(
                        "Cannot calculate percentage - total_shown is zero",
                        data_results_count=len(data_results)
                    )
                    pct = 0
                
                # Adjust wording based on whether there's only one item or multiple
                if len(data_results) == 1:
                    return (
                        f"Your highest costing service is **{service_name}** at **${cost:,.2f}**{period_suffix}."
                    )
                else:
                    return (
                        f"**Which service was the costliest?** Your top {min(top_n, len(data_results))} cost drivers total "
                        f"**${total_shown:,.2f}**{period_suffix}, "
                        f"with **{service_name}** leading at **${cost:,.2f}** ({pct:.1f}% of total). "
                        f"The cost was accumulated by these subservices as shown in the breakdown."
                    )
        
        elif intent == IntentType.COST_BREAKDOWN:
            # Breakdown summary
            params_metadata = params.get("metadata", {}) or {}
            
            # Check if this is a top service breakdown (top 1 query showing cost drivers)
            top_service_breakdown = params_metadata.get("top_service_breakdown")
            if top_service_breakdown:
                service_name = self._humanize_service_name(top_service_breakdown.get("service"))
                total_cost = top_service_breakdown.get("total_cost", 0)
                count = len(data_results)
                
                # Get top cost driver
                if data_results:
                    top_driver = data_results[0]
                    driver_name = (
                        top_driver.get("dimension_value") or 
                        top_driver.get("usage_type") or 
                        top_driver.get("region") or
                        "item"
                    )
                    driver_cost = top_driver.get("cost_usd", 0)
                    driver_pct = top_driver.get("pct_of_service", 0)
                    
                    return (
                        f"**{service_name}** was your highest costing service at **${total_cost:,.2f}**{period_suffix}. "
                        f"Top cost driver: **{driver_name}** at **${driver_cost:,.2f}** ({driver_pct:.1f}% of {service_name} total)."
                    )
                else:
                    return (
                        f"Your top cost driver is **{service_name}** totaling **${total_cost:,.2f}**{period_suffix}."
                    )
            
            # Try to get the service total from metadata (set by orchestrator from context)
            # This is important for follow-up queries like "breakdown CloudWatch"
            service_total = params_metadata.get("breakdown_service_total")
            
            # If not in metadata, sum the breakdown results
            if service_total is None:
                total_cost = sum(r.get("cost_usd", 0) for r in data_results)
            else:
                total_cost = service_total
            
            dimension = params.get("dimensions", ["service"])[0] if params.get("dimensions") else "category"
            dimension = params_metadata.get("breakdown_dimension", dimension)
            dimension_label = params_metadata.get("breakdown_dimension_label_override") or dimension.replace("_", " ").title()
            count = len(data_results)
            
            # Handle ARN fallback scenario (when direct ARN has no costs but related resources do)
            if params_metadata.get("arn_fallback"):
                original_arn = params_metadata.get("original_arn", "the specified ARN")
                fallback_msg = params_metadata.get("fallback_message", "")
                resource_type_explanation = params_metadata.get("resource_type_explanation", "related resources")
                
                # Use standardized column name for service
                service_name = data_results[0].get(SERVICE, data_results[0].get("service", "Unknown")) if data_results else "Unknown"
                service_name = self._humanize_service_name(service_name)
                
                if count > 0:
                    # Extract resource types using standardized column name
                    resource_types = set()
                    for row in data_results:
                        rt = row.get(RESOURCE_TYPE, row.get("resource_type", "Resource"))
                        resource_types.add(rt)
                    resource_type_list = ", ".join(sorted(resource_types)[:3])
                    
                    # Parse cluster name from ARN for better context
                    cluster_name = "your cluster"
                    if ":cluster/" in original_arn:
                        cluster_name = original_arn.split("cluster/")[-1]
                    
                    return (
                        f"**{service_name}** cluster **{cluster_name}** breakdown across {count} {resource_type_list} "
                        f"totals **${total_cost:,.2f}**{period_suffix}. "
                        f"ℹ️ _Note: ECS clusters are free—costs come from tasks and services running on them._"
                    )
                else:
                    return (
                        f"ℹ️ **Note:** The ARN `{original_arn}` doesn't generate direct costs, "
                        f"and no related resources with costs were found{period_suffix}. "
                        f"This may be a container resource (like an ECS cluster or VPC) where costs "
                        f"are attributed to child resources (tasks, instances, etc.)."
                    )
            
            if params_metadata.get("explanation_request"):
                service_name = self._humanize_service_name(params_metadata.get("breakdown_service"))
                return (
                    f"I broke down **{service_name}** spend by **{dimension_label}**"
                    f"{period_suffix}, producing {count} components totaling **${total_cost:,.2f}**."
                )
            
            # For service breakdowns, mention the service name
            breakdown_service = params_metadata.get("breakdown_service")
            if breakdown_service:
                service_name = self._humanize_service_name(breakdown_service)
                return (
                    f"**{service_name}** breakdown across {count} {dimension_label}s totals **${total_cost:,.2f}**"
                    f"{period_suffix}."
                )
            
            return (
                f"Cost breakdown across {count} {dimension_label}s totals **${total_cost:,.2f}**"
                f"{period_suffix}."
            )
        
        elif intent == IntentType.ANOMALY_ANALYSIS:
            # Anomaly summary
            if data_results:
                anomalies = [r for r in data_results if r.get("z_score", 0) > 2.0]
                if anomalies:
                    top_anomaly = anomalies[0]
                    service = top_anomaly.get("service", "service")
                    cost = top_anomaly.get("cost_usd", 0)
                    expected = top_anomaly.get("expected", 0)
                    delta = cost - expected
                    return (
                        f"Detected **{len(anomalies)} significant anomalies**{period_suffix}, "
                        f"with **{service}** showing the largest spike at **${cost:,.2f}** "
                        f"(${delta:,.2f} above expected)."
                    )
                else:
                    return f"No significant anomalies detected{period_suffix}. Costs are within normal variation."
        
        elif intent == IntentType.COST_TREND:
            # Trend summary
            if len(data_results) >= 2:
                first_period = data_results[-1]
                last_period = data_results[0]
                # COST_TREND queries return total_cost_usd, not cost_usd
                first_cost = first_period.get("total_cost_usd", first_period.get("cost_usd", 0))
                last_cost = last_period.get("total_cost_usd", last_period.get("cost_usd", 0))
                change = last_cost - first_cost
                change_pct = (change / first_cost * 100) if first_cost > 0 else 0
                direction = "increased" if change > 0 else "decreased"
                
                return (
                    f"Costs have **{direction} by ${abs(change):,.2f}** ({abs(change_pct):.1f}%) "
                    f"from **${first_cost:,.2f}** to **${last_cost:,.2f}**{period_suffix}."
                )
        
        elif intent == IntentType.COMPARATIVE:
            # Comparison summary
            if len(data_results) >= 1:
                first_row = data_results[0]
                # Check if this is period-over-period comparison (has current_period_cost and previous_period_cost columns)
                if "current_period_cost" in first_row and "previous_period_cost" in first_row:
                    # Period-over-period comparison
                    total_current = sum(r.get("current_period_cost", 0) for r in data_results)
                    total_previous = sum(r.get("previous_period_cost", 0) for r in data_results)
                    total_change = total_current - total_previous
                    pct_change = (total_change / total_previous * 100) if total_previous != 0 else 0
                    
                    # Get date ranges
                    current_start = first_row.get("current_start_date", "")
                    current_end = first_row.get("current_end_date", "")
                    previous_start = first_row.get("previous_start_date", "")
                    previous_end = first_row.get("previous_end_date", "")
                    
                    # Handle negative costs (credits/refunds) properly
                    if total_current < 0 and total_previous < 0:
                        # Both periods have credits - talk about credit amounts
                        current_credit = abs(total_current)
                        previous_credit = abs(total_previous)
                        credit_change = current_credit - previous_credit
                        direction = "decreased" if credit_change > 0 else "increased"
                        emoji = "📉" if credit_change > 0 else "📈"
                        
                        return (
                            f"{emoji} **Credits/refunds** {direction} from **${previous_credit:,.2f}** "
                            f"({previous_start} → {previous_end}) to **${current_credit:,.2f}** "
                            f"({current_start} → {current_end}). "
                            f"Analyzed {len(data_results)} service(s) with credit activity."
                        )
                    else:
                        # Normal cost comparison
                        direction = "increased" if total_change > 0 else "decreased"
                        emoji = "📈" if total_change > 0 else "📉" if total_change < 0 else "➡️"
                        
                        return (
                            f"{emoji} Costs **{direction} by ${abs(total_change):,.2f}** ({abs(pct_change):.1f}%) "
                            f"from **${total_previous:,.2f}** ({previous_start} → {previous_end}) "
                            f"to **${total_current:,.2f}** ({current_start} → {current_end}). "
                            f"Analyzed {len(data_results)} service(s) for growth trends."
                        )
                
                # Monthly trend for longer periods (>90 days)
                elif "month" in first_row and "cost_usd" in first_row:
                    total_cost = sum(r.get("cost_usd", 0) for r in data_results)
                    months = [r.get("month") for r in data_results if r.get("month")]
                    if months:
                        start_month = min(months)
                        end_month = max(months)
                        service_name = self._humanize_service_name(first_row.get("service", "services"))
                        # Find highest and lowest months
                        sorted_by_cost = sorted(data_results, key=lambda x: x.get("cost_usd", 0), reverse=True)
                        highest_month = sorted_by_cost[0]
                        lowest_month = sorted_by_cost[-1]
                        return (
                            f"📊 **{service_name}** monthly trend from **{start_month}** to **{end_month}** "
                            f"(total: ${total_cost:,.2f}). Highest: **{highest_month.get('month')}** (${highest_month.get('cost_usd', 0):,.2f}), "
                            f"Lowest: **{lowest_month.get('month')}** (${lowest_month.get('cost_usd', 0):,.2f})."
                        )
                
                # Environment or tag-based comparison
                groups = {}
                for r in data_results:
                    env = r.get("env", r.get("tag_value", "unknown"))
                    groups[env] = groups.get(env, 0) + r.get("cost_usd", 0)
                
                if len(groups) == 2:
                    envs = list(groups.keys())
                    cost1, cost2 = groups[envs[0]], groups[envs[1]]
                    ratio = cost1 / cost2 if cost2 > 0 else 0
                    return (
                        f"Comparing **{envs[0]}** (${cost1:,.2f}) vs **{envs[1]}** (${cost2:,.2f})"
                        f"{period_suffix} shows a **{ratio:.1f}x** cost difference."
                    )
        
        elif intent == IntentType.OPTIMIZATION:
            # Optimization summary (savings focused)
            savings_field = self._detect_savings_field(data_results[0])
            if savings_field:
                total_savings = sum(r.get(savings_field, 0) or 0 for r in data_results)
                top_item = data_results[0]
                driver = top_item.get("family") or top_item.get("service") or top_item.get("dimension_value", "top opportunity")
                top_savings = top_item.get(savings_field, 0) or 0
                return (
                    f"Identified **${total_savings:,.2f}** optimization headroom{period_suffix}, "
                    f"with **{driver}** contributing **${top_savings:,.2f}** in estimated savings."
                )
        
        # Default generic summary
        total_cost = self._sum_costs(data_results)
        return (
            f"Analysis shows **${total_cost:,.2f}** in total costs across {len(data_results)} items"
            f"{period_suffix or ' for the specified scope'}."
        )
    
    def _detect_savings_field(self, sample_row: Dict[str, Any]) -> Optional[str]:
        """Identify savings column in result set"""
        for key in sample_row.keys():
            key_lower = key.lower()
            if "saving" in key_lower and key_lower.endswith(("usd", "_usd")):
                return key
            if key_lower in {"est_savings", "potential_savings_usd"}:
                return key
        return None

    def _detect_cost_field(self, sample_row: Dict[str, Any]) -> Optional[str]:
        """Identify the most relevant cost column in result set"""
        priority_fields = [
            "current_period_cost",
            "cost_usd",
            "total_cost",
            "unblended_cost",
            "amount",
            "cost",
        ]
        for field in priority_fields:
            if field in sample_row and isinstance(sample_row[field], (int, float)):
                return field
        for key, value in sample_row.items():
            if isinstance(value, (int, float)) and any(token in key.lower() for token in ["cost", "amount", "spend", "value"]):
                return key
        return None

    def _safe_number(self, value: Any) -> float:
        try:
            if value is None:
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _sum_costs(self, data_results: List[Dict[str, Any]]) -> float:
        if not data_results:
            return 0.0
        field = self._detect_cost_field(data_results[0])
        if field:
            return round(sum(self._safe_number(row.get(field)) for row in data_results), 2)
        total = 0.0
        for row in data_results:
            value = next(
                (
                    self._safe_number(row.get(key))
                    for key in row.keys()
                    if isinstance(key, str) and "cost" in key.lower()
                ),
                0.0,
            )
            total += value
        return round(total, 2)
    
    def _format_period_suffix(self, params: Dict[str, Any]) -> str:
        """Format period for summary sentences"""
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        
        time_range = params.get("time_range") or {}
        source = time_range.get("source")
        
        if start_date and end_date:
            period_text = f" for **{start_date} → {end_date}**"
            if source == "inherited_followup":
                period_text += " (same period as previous query)"
            return period_text
        
        description = time_range.get("description")
        if description:
            period_text = f" for {description}"
            if source == "inherited_followup":
                period_text += " (same period as previous query)"
            return period_text
        
        return ""
    
    def _check_data_availability(
        self,
        data_results: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> Optional[str]:
        """
        Check if actual data availability matches requested time range.
        Returns warning message if there's a significant mismatch.
        """
        from datetime import datetime, timedelta
        
        requested_start = params.get("start_date")
        requested_end = params.get("end_date")
        
        if not requested_start or not requested_end or not data_results:
            return None
        
        try:
            # Parse requested dates
            if isinstance(requested_start, str):
                req_start_dt = datetime.strptime(requested_start, "%Y-%m-%d").date()
            else:
                req_start_dt = requested_start
            
            if isinstance(requested_end, str):
                req_end_dt = datetime.strptime(requested_end, "%Y-%m-%d").date()
            else:
                req_end_dt = requested_end
            
            requested_days = (req_end_dt - req_start_dt).days
            
            # Try to extract actual date range from results
            date_fields = ["usage_date", "date", "day", "billing_period", "time_period"]
            actual_dates = []
            
            for row in data_results:
                for field in date_fields:
                    if field in row and row[field]:
                        try:
                            if isinstance(row[field], str):
                                # Try parsing different date formats
                                for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"]:
                                    try:
                                        actual_date = datetime.strptime(row[field], fmt).date()
                                        actual_dates.append(actual_date)
                                        break
                                    except ValueError:
                                        continue
                            elif hasattr(row[field], 'date'):
                                actual_dates.append(row[field].date())
                            else:
                                actual_dates.append(row[field])
                        except:
                            pass
            
            if not actual_dates:
                # Can't determine actual date range, skip warning
                return None
            
            actual_min = min(actual_dates)
            actual_max = max(actual_dates)
            actual_days = (actual_max - actual_min).days + 1
            
            # Calculate coverage
            coverage_ratio = actual_days / requested_days if requested_days > 0 else 1.0
            
            # Check if actual data starts significantly after requested start
            days_missing_start = (actual_min - req_start_dt).days
            
            # Generate warning if coverage is poor
            if coverage_ratio < 0.3 and requested_days > 7:
                # Less than 30% coverage
                return (
                    f"Data is only available for **{actual_days} days** "
                    f"({actual_min} to {actual_max}), but you requested **{requested_days} days**. "
                    f"Coverage: {coverage_ratio*100:.0f}%"
                )
            elif days_missing_start > 7 and requested_days > 14:
                # Data starts more than a week after requested start
                return (
                    f"Requested data from {requested_start}, but actual data starts from **{actual_min}**. "
                    f"Missing approximately **{days_missing_start} days** of historical data."
                )
            
            return None
            
        except Exception as e:
            logger.warning(f"Error checking data availability: {e}")
            return None
    
    def _generate_scope(
        self,
        params: Dict[str, Any],
        data_results: List[Dict[str, Any]]
    ) -> str:
        """Generate scope section (period + filters) with absolute dates"""
        scope_parts = []
        
        # Period - always show absolute dates
        time_range = params.get("time_range", {})
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        
        if start_date and end_date:
            # Format with nice date display
            period_display = date_parser.format_scope_period(start_date, end_date, time_range.get("metadata", {}))
            description = time_range.get("description", "")
            source = time_range.get("source")
            
            if description:
                period_text = f"- Period: {period_display} ({description})"
                if source == "inherited_followup":
                    period_text += " - same period as previous query"
                scope_parts.append(period_text)
            else:
                period_text = f"- Period: {period_display}"
                if source == "inherited_followup":
                    period_text += " - same period as previous query"
                scope_parts.append(period_text)
        elif time_range:
            period_desc = time_range.get("description", "custom period")
            source = time_range.get("source")
            period_text = f"- Period: {period_desc}"
            if source == "inherited_followup":
                period_text += " - same period as previous query"
            scope_parts.append(period_text)
        else:
            scope_parts.append("- Period: Last 30 days (default)")

        # Filters
        filters = []
        if params.get("services"):
            services_list = params['services']
            if len(services_list) <= 3:
                filters.append(f"Services: {', '.join(services_list)}")
            else:
                filters.append(f"Services: {', '.join(services_list[:3])} (+{len(services_list)-3} more)")
        
        if params.get("regions"):
            regions_list = params['regions']
            filters.append(f"Regions: {', '.join(regions_list)}")
        
        if params.get("accounts"):
            accounts_list = params['accounts']
            if len(accounts_list) <= 2:
                filters.append(f"Accounts: {', '.join(accounts_list)}")
            else:
                filters.append(f"Accounts: {len(accounts_list)} accounts")
        
        if params.get("tags"):
            tags = params['tags']
            # Defensive check: ensure tags is a dict
            if not isinstance(tags, dict):
                logger.warning(f"tags parameter is not a dict, got {type(tags)}, skipping tags filter display")
            else:
                tag_strs = []
                for key, raw_values in tags.items():
                    if isinstance(raw_values, (list, tuple, set)):
                        value_str = ",".join(str(v) for v in raw_values)
                    else:
                        value_str = str(raw_values)
                    tag_strs.append(f"{key}={value_str}")
                filters.append(f"Tags: {', '.join(tag_strs)}")
        
        if params.get("exclude_services"):
            filters.append(f"Excluded: {', '.join(params['exclude_services'])}")
        
        if params.get("exclude_line_item_types"):
            filters.append(f"Excluded charges: {', '.join(params['exclude_line_item_types'])}")
        if params.get("include_line_item_types"):
            filters.append(f"Charge focus: {', '.join(params['include_line_item_types'])}")
        if params.get("purchase_options"):
            filters.append(f"Purchase options: {', '.join(params['purchase_options'])}")
        if params.get("platforms"):
            filters.append(f"Platforms: {', '.join(params['platforms'])}")
        if params.get("database_engines"):
            filters.append(f"DB engines: {', '.join(params['database_engines'])}")
        
        if filters:
            scope_parts.append(f"- Filters: {' | '.join(filters)}")
        else:
            scope_parts.append("- Filters: All resources")
        
        return "\n".join(scope_parts)
    
    def _generate_results_summary(
        self,
        intent: str,
        data_results: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> str:
        """Generate a brief text summary or detailed breakdown (when charts are available)"""
        if not data_results:
            return "_No data available_"
        
        from agents.intent_classifier import IntentType
        
        count = len(data_results)
        total_cost = sum(r.get("cost_usd", 0) for r in data_results)
        metadata = params.get("metadata", {}) or {}
        
        # For breakdown queries, show detailed table in addition to chart
        if intent == IntentType.COST_BREAKDOWN:
            dimension = metadata.get("breakdown_dimension", (params.get("dimensions") or ["category"])[0])
            dimension_label = metadata.get("breakdown_dimension_label_override") or dimension
            dimension_label = dimension_label.replace("_", " ").title()
            
            # Build a detailed breakdown table
            lines = []
            lines.append(f"Analysis shows **{count} items** with total costs of **${total_cost:,.2f}**. See charts on left for detailed breakdown.\n")
            
            # Add table header with Rank column
            lines.append(f"| Rank | {dimension_label} | Cost (USD) | % of Total |")
            lines.append("|---:|---|---:|---:|")
            
            # Add rows (show all items for breakdown queries)
            for i, row in enumerate(data_results[:20], start=1):  # Start numbering from 1
                # Debug: Log what we're seeing in the row
                if i == 1:
                    logger.info(
                        "First row in breakdown table",
                        row_keys=list(row.keys()),
                        dimension_value=row.get("dimension_value"),
                        service=row.get("service"),
                        dimension_param=row.get(dimension)
                    )
                
                dim_value = row.get("dimension_value") or row.get("service") or row.get(dimension) or "Unknown"
                cost = row.get("cost_usd", 0)
                pct = row.get("pct_of_service", row.get("pct_of_total", 0))
                
                # Format dimension value (truncate if too long)
                if isinstance(dim_value, str) and len(dim_value) > 50:
                    dim_value = dim_value[:47] + "..."
                
                lines.append(f"| {i} | {dim_value} | ${cost:,.2f} | {pct:.1f}% |")
            
            if len(data_results) > 20:
                lines.append(f"\n_Showing top 20 of {count} results_")
            
            return "\n".join(lines)
        
        # Check if chart aggregation was applied
        chart_aggregation_note = ""
        if metadata.get("chart_shows_top_5"):
            total_items = metadata.get("total_items_available", count)
            hidden_items = metadata.get("items_aggregated_into_others", 0)
            chart_aggregation_note = f" Chart shows top 5 items with {hidden_items} others aggregated for clarity."
        
        # Create a simple summary based on intent
        if intent == IntentType.TOP_N_RANKING:
            return f"Analysis shows **{count} items** with total costs of **${total_cost:,.2f}**. See charts on left for detailed breakdown.{chart_aggregation_note}"
        elif intent == IntentType.COST_TREND:
            return f"Analyzed **{count} time periods** showing cost trends over time. See charts on left for visualization.{chart_aggregation_note}"
        else:
            return f"Retrieved **{count} results** totaling **${total_cost:,.2f}**. See charts on left for detailed visualization.{chart_aggregation_note}"

    def _generate_results_table(
        self,
        intent: str,
        data_results: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> str:
        """Generate markdown table for results"""
        if not data_results:
            return "_No data available_"
        
        # Detect table structure from first result
        sample = data_results[0]
        columns = list(sample.keys())
        
        # Check if this is a period-over-period comparison table
        is_period_comparison = ("current_period_cost" in columns and "previous_period_cost" in columns)
        if is_period_comparison and intent == IntentType.COMPARATIVE:
            return self._generate_comparison_table(data_results)
        
        # Check if this is a time-series breakdown (has both 'month' and 'service' columns)
        has_month = 'month' in columns
        has_service = 'service' in columns
        is_time_series_breakdown = has_month and has_service
        
        # For time-series breakdowns, create a pivot table (services as rows, months as columns)
        if is_time_series_breakdown:
            return self._generate_pivot_table(data_results)
        
        # Build standard table header
        header = "| " + " | ".join(self._format_column_name(col) for col in columns) + " |"
        separator = "| " + " | ".join("---" for _ in columns) + " |"
        
        # For COST_BREAKDOWN intent with many items, match chart logic: show top 5 + Others row
        is_breakdown = intent == IntentType.COST_BREAKDOWN
        show_limit = 6  # Top 5 + Others row
        
        # For COST_TREND, show ALL data points (don't limit to 6)
        # For other intents, limit to avoid overwhelming tables
        if intent == IntentType.COST_TREND:
            items_to_show = data_results  # Show all monthly data
        elif is_breakdown and len(data_results) > 5:
            items_to_show = data_results[:5]  # Top 5 for breakdown
        else:
            items_to_show = data_results[:show_limit]  # Default limit
        
        # Build table rows
        rows = []
        for i, row in enumerate(items_to_show):
            formatted_values = []
            for col in columns:
                value = row.get(col)
                formatted_values.append(self._format_cell_value(col, value))
            rows.append("| " + " | ".join(formatted_values) + " |")
        
        # Add "Others" aggregation row if breakdown with > 5 items (matching chart behavior)
        if is_breakdown and len(data_results) > 5:
            others_items = data_results[5:]
            others_count = len(others_items)
            
            # Calculate aggregated values for "Others" row
            others_row_values = []
            for col in columns:
                # Special handling for rank column to avoid duplicate rank "5"
                # Show the correct sequential rank position for the aggregated row (6)
                # rather than the number of hidden items. This fixes UI displaying
                # "Rank 5" twice when an "Others" aggregation row is added.
                if col == "rank":
                    # Top segment above limited by earlier logic (items_to_show). Aggregated row follows sequentially.
                    others_row_values.append(str(len(items_to_show) + 1))
                    continue
                if col in ["service", "dimension_value", "category", "driver", "account", "region"]:
                    # Label column
                    others_row_values.append(f"Others ({others_count} items)")
                elif "cost" in col.lower() or "amount" in col.lower():
                    # Sum cost columns
                    total = sum(float(item.get(col, 0) or 0) for item in others_items)
                    others_row_values.append(f"${total:,.2f}")
                elif "pct" in col.lower() or "percent" in col.lower():
                    # Sum percentage columns
                    total = sum(float(item.get(col, 0) or 0) for item in others_items)
                    others_row_values.append(f"{total:.1f}%")
                else:
                    # Other columns show count or dash
                    others_row_values.append(f"{others_count}")
            
            rows.append("| " + " | ".join(others_row_values) + " |")
        
        # Build complete table with compact spacing
        table_lines = [header, separator] + rows
        
        # No truncation note needed - we always show complete picture with Others row
        
        return "\n".join(table_lines)
    
    def _generate_pivot_table(self, data_results: List[Dict[str, Any]]) -> str:
        """Generate a pivot table with services as rows and months as columns."""
        from collections import defaultdict
        from datetime import datetime
        
        # Organize data by service and month
        service_data = defaultdict(dict)
        months_with_dates = []  # Store (month_label, month_date) tuples
        
        for row in data_results:
            service = row.get('service', 'Unknown')
            month = row.get('month', '')
            cost = row.get('cost_usd', 0)
            
            # Format month as "Nov 2025" or similar
            if month:
                try:
                    month_obj = datetime.strptime(str(month)[:10], '%Y-%m-%d')
                    month_label = month_obj.strftime('%b %Y')
                    months_with_dates.append((month_label, month_obj))
                except:
                    month_label = str(month)[:7]  # YYYY-MM format
                    months_with_dates.append((month_label, None))
            else:
                month_label = 'Unknown'
                months_with_dates.append((month_label, None))
            
            service_data[service][month_label] = cost
        
        # Sort months chronologically and deduplicate
        unique_months = {}
        for month_label, month_date in months_with_dates:
            if month_label not in unique_months:
                unique_months[month_label] = month_date
        
        sorted_months = sorted(
            unique_months.keys(),
            key=lambda m: unique_months[m] if unique_months[m] else datetime.now()
        )
        
        # Limit to top services by total cost
        service_totals = {
            service: sum(costs.values()) 
            for service, costs in service_data.items()
        }
        top_services = sorted(service_totals.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Build header (limit Service column width with CSS hint)
        header = "| Service | " + " | ".join(sorted_months) + " | Total |"
        separator = "| :--- | " + " | ".join(["---:" for _ in sorted_months]) + " | ---: |"
        
        # Build rows
        rows = []
        for service, total in top_services:
            costs = service_data[service]
            row_values = [service]
            
            for month in sorted_months:
                cost = costs.get(month, 0)
                row_values.append(f"${cost:,.2f}" if cost > 0 else "-")
            
            row_values.append(f"${total:,.2f}")
            rows.append("| " + " | ".join(row_values) + " |")
        
        # Add note if there are more services
        note = ""
        if len(service_data) > 10:
            note = f"\n\n_Showing top 10 services out of {len(service_data)} total. Table is horizontally scrollable._"
        
        return "\n".join([header, separator] + rows) + note
    
    def _generate_comparison_table(self, data_results: List[Dict[str, Any]]) -> str:
        """Generate a compact period-over-period comparison table showing only essential columns."""
        # Simplified columns: Service, Current Period, Previous Period, Change, % Change
        # Drop the date columns which make the table cramped
        
        header = "| Service | Current Period | Previous Period | Change | % Change |"
        separator = "| --- | ---: | ---: | ---: | ---: |"
        
        rows = []
        for row in data_results:
            service = row.get("service", "Unknown")
            current = row.get("current_period_cost", 0)
            previous = row.get("previous_period_cost", 0)
            change = row.get("cost_change", current - previous)
            pct_change = row.get("pct_change", 0)
            
            # Format current and previous as currency
            current_str = f"${abs(current):,.2f}" if current >= 0 else f"$({abs(current):,.2f})"
            previous_str = f"${abs(previous):,.2f}" if previous >= 0 else f"$({abs(previous):,.2f})"
            
            # Format change with arrow indicator
            if change > 0:
                change_str = f"↗ ${change:,.2f}"
            elif change < 0:
                change_str = f"↘ ${abs(change):,.2f}"
            else:
                change_str = "→ $0.00"
            
            # Format percentage change
            if pct_change > 0:
                pct_str = f"+{pct_change:.1f}%"
            elif pct_change < 0:
                pct_str = f"{pct_change:.1f}%"
            else:
                pct_str = "0.0%"
            
            rows.append(f"| {service} | {current_str} | {previous_str} | {change_str} | {pct_str} |")
        
        return "\n".join([header, separator] + rows)
    
    def _generate_breakdown_methodology(
        self,
        data_results: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> Optional[str]:
        """Generate explanatory text describing how a breakdown was produced."""
        metadata = params.get("metadata", {}) or {}
        if not metadata.get("explanation_request"):
            return None
        
        service_name = self._humanize_service_name(metadata.get("breakdown_service"))
        dimension_key = metadata.get("breakdown_dimension") or (params.get("dimensions") or ["category"])[0]
        dimension_label = metadata.get("breakdown_dimension_label_override") or dimension_key.replace("_", " ").title()
        dimension_column_map = {
            "usage_type": "`line_item_usage_type`",
            "operation": "`line_item_operation`",
            "account": "`bill_payer_account_id`",
            "region": "`product_region`",
            "service": "`product_product_name`",
        }
        dimension_column = dimension_column_map.get(dimension_key, "`dimension_value`")
        
        time_range = params.get("time_range", {})
        start_date = params.get("start_date") or time_range.get("start_date")
        end_date = params.get("end_date") or time_range.get("end_date")
        period_display = ""
        if start_date and end_date:
            period_display = f"{start_date} → {end_date}"
        elif time_range.get("description"):
            period_display = time_range["description"]
        
        lines: List[str] = []
        if period_display:
            lines.append(
                f"I aggregated **{service_name}** spend for **{period_display}** and grouped it by **{dimension_label}**."
            )
        else:
            lines.append(
                f"I aggregated **{service_name}** spend and grouped it by **{dimension_label}**."
            )
        
        lines.append(
            f"Each row represents values from the CUR field {dimension_column}, showing how each component contributes to the total."
        )
        lines.append(
            "Costs reflect net spend, using Savings Plan or Reservation effective cost when available, "
            "and falling back to unblended cost otherwise."
        )
        
        # Highlight top 3 components for quick reference
        top_components = data_results[:3] if data_results else []
        if top_components:
            component_lines = []
            for row in top_components:
                label = row.get("dimension_value") or row.get("service") or row.get("driver") or "Component"
                cost = row.get("cost_usd", row.get("total_cost", 0))
                display_cost: Optional[float]
                try:
                    display_cost = float(cost) if cost is not None else None
                except (TypeError, ValueError):
                    display_cost = None
                pct = row.get("pct_of_service", row.get("pct_of_total"))
                entry = f"- **{label}**" + (f": ${display_cost:,.2f}" if display_cost is not None else "")
                if pct is not None:
                    try:
                        entry += f" ({float(pct):.1f}%)"
                    except (TypeError, ValueError):
                        pass
                component_lines.append(entry)
            
            if component_lines:
                lines.append("Top cost components:\n" + "\n".join(component_lines))
        
        return "\n".join(lines)
    
    def _format_column_name(self, col: str) -> str:
        """Format column name for table header"""
        # Convert snake_case to Title Case
        return col.replace("_", " ").title()
    
    def _format_cell_value(self, col: str, value: Any) -> str:
        """Format cell value based on column type"""
        if value is None:
            return "-"
        
        # Cost/money columns - handle negative values (credits) with parentheses
        if "cost" in col.lower() or "amount" in col.lower() or "saving" in col.lower():
            try:
                num_val = float(value)
                # Display negative costs (credits) with parentheses: $-5.58 becomes $(5.58)
                if num_val < 0:
                    return f"$({abs(num_val):,.2f})"
                return f"${num_val:,.2f}"
            except (ValueError, TypeError):
                return str(value)
        
        # Percentage columns
        elif "pct" in col.lower() or "percent" in col.lower() or col.endswith("_pct"):
            try:
                return f"{float(value):.1f}%"
            except (ValueError, TypeError):
                return str(value)
        
        # Change columns - show +/- with proper sign
        elif "change" in col.lower() or "delta" in col.lower():
            try:
                val = float(value)
                prefix = "+" if val > 0 else ""
                return f"{prefix}{val:,.2f}"
            except (ValueError, TypeError):
                return str(value)
        
        # Numeric columns
        elif isinstance(value, (int, float)):
            try:
                if isinstance(value, float) and value != int(value):
                    return f"{value:,.2f}"
                else:
                    return f"{int(value):,}"
            except (ValueError, TypeError):
                return str(value)
        
        # Default: string
        return str(value)
    
    def _humanize_service_name(self, raw_service: Optional[str]) -> str:
        """Convert internal CUR service names into a more readable form."""
        if not raw_service:
            return "the requested service"
        
        service = raw_service.strip()
        normalized = service.lower().replace(" ", "")
        friendly_map = {
            "amazoncloudwatch": "CloudWatch",
            "awslambda": "AWS Lambda",
            "amazonelasticcomputecloud": "Amazon EC2",
            "amazonsimplestorageservice": "Amazon S3",
            "amazonrelationaldatabaseservice": "Amazon RDS",
        }
        if normalized in friendly_map:
            return friendly_map[normalized]
        
        # If the service already contains spaces, return as-is
        if " " in service:
            return service
        
        # Insert spaces before capital letters (e.g., AmazonCloudWatch -> Amazon Cloud Watch)
        spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", service).strip()
        # Collapse any doubled spaces that might occur
        spaced = re.sub(r"\s{2,}", " ", spaced)
        return spaced
    
    def _generate_default_insights(
        self,
        intent: str,
        data_results: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> str:
        """Generate default insights from data"""
        from agents.intent_classifier import IntentType
        
        insights = []
        metadata = params.get("metadata", {}) or {}
        
        # Special insights for ARN fallback queries
        if metadata.get("arn_fallback"):
            resource_type_explanation = metadata.get("resource_type_explanation", "resources")
            
            # Analyze resource types
            if data_results:
                resource_types = {}
                for row in data_results:
                    rt = row.get(RESOURCE_TYPE, row.get("resource_type", "Unknown"))
                    cost = row.get("cost_usd", 0)
                    resource_types[rt] = resource_types.get(rt, 0) + cost
                
                # Find dominant resource type
                if resource_types:
                    dominant_type = max(resource_types.items(), key=lambda x: x[1])
                    dominant_pct = (dominant_type[1] / sum(resource_types.values()) * 100) if sum(resource_types.values()) > 0 else 0
                    insights.append(f"**Primary resource type**: **{dominant_type[0]}** accounts for **{dominant_pct:.1f}%** of costs")
                
                # Count unique resources
                unique_resources = len(set(r.get("dimension_value", "") for r in data_results))
                insights.append(f"**Active resources**: {unique_resources} distinct resources generated costs during this period")
                
                # Top cost generator
                if len(data_results) > 1:
                    top_resource = data_results[0]
                    top_cost = top_resource.get("cost_usd", 0)
                    total_cost = sum(r.get("cost_usd", 0) for r in data_results)
                    top_pct = (top_cost / total_cost * 100) if total_cost > 0 else 0
                    insights.append(f"**Highest cost resource**: Single {top_resource.get(RESOURCE_TYPE, 'resource')} generated **${top_cost:.2f}** ({top_pct:.1f}% of total)")
            
            return "\n".join(f"- {insight}" for insight in insights) if insights else ""
        
        no_change_meta = metadata.get("no_additional_cost_change")
        if no_change_meta:
            requested_period = no_change_meta.get("requested_period") or {}
            previous_period = no_change_meta.get("previous_period") or {}
            current_total = no_change_meta.get("current_total", metadata.get("current_total_cost", 0.0))
            requested_desc = requested_period.get("description") or "the expanded window"
            previous_desc = previous_period.get("description") or "the prior window"
            gap_start = requested_period.get("start_date")
            gap_end = previous_period.get("start_date")
            
            gap_note = ""
            if gap_start and gap_end and gap_start != gap_end:
                gap_note = f" No spend was recorded between **{gap_start}** and **{gap_end}**, so totals mirror the {previous_desc.lower()}."
            
            insights.append(
                f"**No additional spend**: Extending to {requested_desc} added no new charges—costs remain **${current_total:,.2f}** "
                f"(unchanged from {previous_desc}).{gap_note}"
            )
        
        if intent == IntentType.TOP_N_RANKING:
            # Top N insights
            # Check if this is actually a breakdown of a single service (top_n=1 enriched)
            params_metadata = params.get("metadata", {}) or {}
            top_service_breakdown = params_metadata.get("top_service_breakdown")
            
            if top_service_breakdown:
                # This is a breakdown - show breakdown-specific insights
                if len(data_results) >= 2:
                    top2_cost = sum(r.get("cost_usd", 0) for r in data_results[:2])
                    total_cost = sum(r.get("cost_usd", 0) for r in data_results)
                    concentration = (top2_cost / total_cost * 100) if total_cost > 0 else 0
                    insights.append(f"**High concentration**: Top 2 items account for **{concentration:.1f}%** of total costs")
                
                # Get the top component
                if data_results:
                    top_driver = data_results[0]
                    driver_name = (
                        top_driver.get("dimension_value") or 
                        top_driver.get("usage_type") or 
                        top_driver.get("region") or
                        "component"
                    )
                    insights.append(f"**Leading driver**: **{driver_name}** is the primary cost contributor")
                
                if len(data_results) >= 3:
                    insights.append(f"**Optimization focus**: Concentrate efforts on the top 3 components for maximum impact")
            else:
                # Regular top N ranking insights
                if len(data_results) >= 2:
                    top2_cost = sum(r.get("cost_usd", 0) for r in data_results[:2])
                    total_cost = sum(r.get("cost_usd", 0) for r in data_results)
                    concentration = (top2_cost / total_cost * 100) if total_cost > 0 else 0
                    insights.append(f"**High concentration**: Top 2 items account for **{concentration:.1f}%** of total costs")
                
                # Identify services - only say "leading" if there are multiple services
                if data_results:
                    top_service = data_results[0].get("service", data_results[0].get("dimension_value"))
                    if len(data_results) > 1:
                        insights.append(f"**Leading driver**: **{top_service}** is the primary cost contributor")
                    else:
                        insights.append(f"**Primary driver**: **{top_service}** is your main cost contributor")
                
                if len(data_results) >= 3:
                    insights.append(f"**Optimization focus**: Concentrate efforts on the top 3 services for maximum impact")
        
        elif intent == IntentType.COST_BREAKDOWN:
            # Breakdown insights
            total_cost = sum(r.get("cost_usd", 0) for r in data_results)
            avg_cost = total_cost / len(data_results) if data_results else 0
            
            # Find outliers
            outliers = [r for r in data_results if r.get("cost_usd", 0) > avg_cost * 2]
            if outliers:
                insights.append(f"**Cost outliers**: {len(outliers)} categories significantly above average")
            
            # Distribution analysis
            if data_results:
                top_pct = data_results[0].get("pct_of_total", data_results[0].get("pct_of_ec2", 0))
                if top_pct > 50:
                    insights.append(f"**Highly concentrated**: Top category represents **{top_pct:.1f}%** of costs")
        
        elif intent == IntentType.COST_TREND:
            # Trend insights
            if len(data_results) >= 2:
                # Calculate growth rate
                ordered = list(reversed(data_results))
                # COST_TREND queries return total_cost_usd, not cost_usd
                costs = [r.get("total_cost_usd", r.get("cost_usd", 0)) for r in ordered]
                deltas = [
                    (costs[i] - costs[i-1]) / costs[i-1] * 100
                    for i in range(1, len(costs))
                    if costs[i-1] > 0
                ]
                avg_growth = sum(deltas) / len(deltas) if deltas else 0
                
                if avg_growth > 10:
                    insights.append(f"**Rapid growth**: Average period-over-period growth of **{avg_growth:.1f}%** requires attention")
                elif avg_growth < -10:
                    insights.append(f"**Cost reduction**: Costs declining at **{abs(avg_growth):.1f}%** per period - optimization working")
                else:
                    insights.append(f"**Stable trend**: Costs relatively stable with **{abs(avg_growth):.1f}%** average change")
        
        elif intent == IntentType.OPTIMIZATION:
            savings_field = self._detect_savings_field(data_results[0])
            if savings_field:
                total_savings = sum(r.get(savings_field, 0) or 0 for r in data_results)
                top_three = data_results[:3]
                contributions = [
                    f"{item.get('family', item.get('service', 'opportunity'))}: ${item.get(savings_field, 0):,.2f}"
                    for item in top_three
                ]
                insights.append(f"**Savings runway**: Top opportunities deliver **${total_savings:,.2f}** in aggregate")
                insights.append(f"**Concentration**: {', '.join(contributions)}")
                
                pct_field = next((k for k in data_results[0].keys() if "pct" in k.lower()), None)
                if pct_field and data_results[0].get(pct_field) is not None:
                    insights.append(f"**Discount model**: Projections assume ~{data_results[0].get(pct_field):.1f}% savings vs. on-demand")
            else:
                # General optimization insights (from cost_optimization_analysis)
                top_costs = data_results[:3]
                total_cost = sum(r.get("cost_usd", 0) for r in data_results)
                
                # Identify high-cost opportunities
                high_cost_items = [r for r in data_results if r.get("cost_usd", 0) > 100]
                if high_cost_items:
                    insights.append(f"**High-cost resources**: {len(high_cost_items)} resources with costs >$100, totaling **${sum(r.get('cost_usd', 0) for r in high_cost_items):,.2f}**")
                
                # Identify low utilization opportunities
                low_util_items = [r for r in data_results if r.get("utilization_pct", 100) < 50]
                if low_util_items:
                    insights.append(f"**Low utilization**: {len(low_util_items)} resources used <50% of the period - consider rightsizing or scheduling")
                
                # Estimate total savings potential
                est_savings = sum(r.get("est_savings_30pct", 0) for r in data_results)
                if est_savings > 0:
                    insights.append(f"**Estimated savings**: Up to **${est_savings:,.2f}** potential through optimization (30% reduction target)")
                
                # Top service recommendations
                if top_costs:
                    top_service = top_costs[0].get("service", "top resource")
                    insights.append(f"**Priority focus**: Start with **{top_service}** for maximum impact")
        
        elif intent == IntentType.ANOMALY_ANALYSIS:
            # Anomaly insights
            anomalies = [r for r in data_results if abs(r.get("z_score", 0)) > 2.0]
            if anomalies:
                insights.append(f"**Anomalies detected**: {len(anomalies)} significant deviations from expected patterns")
                
                # Top anomaly details
                top = max(anomalies, key=lambda x: abs(x.get("z_score", 0)))
                service = top.get("service", "Unknown")
                delta = top.get("delta", 0)
                insights.append(f"**Largest spike**: **{service}** with **${abs(delta):,.2f}** deviation")
        
        # Generic insights if none generated
        if not insights:
            total_scope = self._sum_costs(data_results)
            insights.append(f"**Total scope**: ${total_scope:,.2f} across {len(data_results)} items")
            insights.append("**Data quality**: All requested data successfully retrieved and analyzed")
        
        return "\n".join(
            f"- {insight.strip()}"
            for insight in insights
            if insight and insight.strip()
        )
    
    def _format_insights(self, insights: List[str]) -> str:
        """Format provided insights as clean lines"""
        formatted = []
        for insight in insights[:6]:  # Max 6 insights
            cleaned = insight.strip()
            if cleaned.startswith(("-", "•")):
                cleaned = cleaned.lstrip("-•").strip()
            if not cleaned:
                continue
            formatted.append(f"- {cleaned}")
        return "\n".join(formatted)
    
    def _format_chart_recommendations(self, chart_specs: List[Dict[str, Any]]) -> str:
        """Format chart recommendations"""
        if not chart_specs:
            return ""
        
        chart_lines = []
        for i, spec in enumerate(chart_specs[:2], 1):  # Max 2 charts
            chart_type = spec.get("type", "bar")
            x_field = spec.get("x", "category")
            y_field = spec.get("y", "value")
            series = spec.get("series")
            
            if series:
                chart_lines.append(f"{i}. **{chart_type.title()} chart**: x={x_field}, y={y_field}, series={series}")
            else:
                chart_lines.append(f"{i}. **{chart_type.title()} chart**: x={x_field}, y={y_field}")
        
        return "\n".join(chart_lines)
    
    def _generate_next_steps(
        self,
        intent: str,
        data_results: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> Tuple[str, List[str]]:
        """Generate actionable next steps - returns (formatted_text, raw_array)"""
        from agents.intent_classifier import IntentType
        
        steps = []
        
        if intent == IntentType.TOP_N_RANKING:
            # Next steps for rankings
            if data_results:
                top_service = data_results[0].get("service", data_results[0].get("dimension_value"))
                steps.append(f"Drill down into {top_service} to identify specific cost drivers by region or account")
            steps.append("Compare with previous period to identify growth trends")
        
        elif intent == IntentType.COST_BREAKDOWN:
            # Next steps for breakdowns
            steps.append("Investigate top cost categories for optimization opportunities")
            if not params.get("regions"):
                steps.append("Add regional breakdown to identify geographic cost patterns")
        
        elif intent == IntentType.ANOMALY_ANALYSIS:
            # Next steps for anomalies
            anomalies = [r for r in data_results if abs(r.get("z_score", 0)) > 2.0]
            if anomalies:
                steps.append("Investigate root causes for detected anomalies with detailed logs")
                steps.append("Set up alerts to catch similar patterns in the future")
            else:
                steps.append("Expand time window to 30+ days for more comprehensive anomaly detection")
        
        elif intent == IntentType.COST_TREND:
            # Next steps for trends
            steps.append("Forecast future costs based on observed trends")
            steps.append("Identify correlation with business metrics or usage patterns")
        
        elif intent == IntentType.OPTIMIZATION:
            # Next steps for optimization - tailored based on data
            if data_results:
                # Check if RI/SP data or general optimization
                has_ri_data = any("family" in r or "est_savings_pct" in r for r in data_results)
                
                if has_ri_data:
                    steps.append("Evaluate Reserved Instances or Savings Plans for top instance families")
                    steps.append("Use AWS Cost Explorer RI/SP recommendations for detailed purchasing guidance")
                else:
                    # General optimization
                    low_util = [r for r in data_results if r.get("utilization_pct", 100) < 50]
                    high_cost = [r for r in data_results if r.get("cost_usd", 0) > 100]
                    
                    if low_util:
                        steps.append("Review low-utilization resources for rightsizing or scheduling opportunities")
                    if high_cost:
                        steps.append("Analyze high-cost resources for potential Reserved Instance or Savings Plan purchases")
                    if not low_util and not high_cost:
                        steps.append("Implement cost allocation tags for better tracking and optimization")
                        steps.append("Set up AWS Budgets and alerts to prevent cost overruns")
            else:
                steps.append("Implement top recommendations and track savings realization")
                steps.append("Schedule monthly reviews to identify new optimization opportunities")
        
        # Generic next steps if none
        if not steps:
            steps.append("Set up regular monitoring to track cost changes over time")
            steps.append("Consider enabling AWS Cost Anomaly Detection for automated alerts")
        
        normalized_steps = [
            step.strip()
            for step in steps
            if step and step.strip()
        ][:2]  # Max 2 next steps
        
        if not normalized_steps:
            return "", []
        
        # Return both formatted text (with markdown bullets) and raw array (without bold markdown)
        formatted_text = "\n".join(f"- {step}" for step in normalized_steps)
        # Remove markdown formatting for clickable suggestions
        raw_array = [step.replace("**", "") for step in normalized_steps]
        
        return formatted_text, raw_array
    
    def _format_no_data_response(
        self,
        intent: str,
        params: Dict[str, Any]
    ) -> str:
        """Format response when no data is found"""
        lines: List[str] = []

        def add_section(title: str, content: Optional[Union[str, List[str]]]) -> None:
            if content is None:
                return
            if isinstance(content, str):
                raw_lines = [line.rstrip() for line in content.strip().splitlines() if line.strip()]
            else:
                raw_lines = [line.rstrip() for line in content if line and line.strip()]
            if not raw_lines:
                return
            if lines:
                lines.append("")
            lines.append(f"**{title}:**")
            lines.append("")  # Add blank line before content
            lines.extend(raw_lines)

        add_section("Summary", "No significant data found for your query.")
        
        # Scope
        time_range = params.get("time_range", {})
        period = time_range.get("description", "specified period") if time_range else "rolling"
        scope_lines = [f"- Period: {period}"]
        
        if params.get("services"):
            scope_lines.append(f"- Services: {', '.join(params['services'])}")
        
        if params.get("resource_arns"):
            arns = params["resource_arns"]
            if len(arns) > 0:
                arn_info = arns[0]
                scope_lines.append(f"- Resource: {arn_info.get('resource_id', 'unknown')}")
                scope_lines.append(f"- Service: {arn_info.get('service', 'unknown')}")
        
        add_section("Scope", "\n".join(scope_lines))
        
        # No results message
        add_section("Results", "_No cost data matches your criteria._")
        
        # Suggestions - tailored based on query type
        suggestions = []
        
        if params.get("resource_arns"):
            suggestions.append("**Resource not found**: The specified resource ARN may not exist or has no cost data in this period")
            suggestions.append("**Check resource ID**: Verify the resource ID or table name is correct")
            suggestions.append("**Widen time range**: Try expanding to a longer period (e.g., last 30 days, last quarter)")
        else:
            suggestions.append("**Widen time range**: Try expanding to a longer period (e.g., last 30 days, last quarter)")
            suggestions.append("**Check filters**: Verify service names, regions, or tags are correct")
            suggestions.append("**Data availability**: Confirm CUR data is being ingested for this period")
        
        next_step_content = "\n".join(
            f"- {suggestion.strip()}"
            for suggestion in suggestions[:2]
            if suggestion and suggestion.strip()
        )
        add_section("Next steps", next_step_content)
        
        return "\n".join(lines).strip()


# Global formatter instance
response_formatter = FinOpsResponseFormatter()
