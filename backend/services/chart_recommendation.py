"""
Chart Recommendation Engine - Intelligent visualization suggestions based on query intent and data
Recommends 1-2 appropriate chart types with specifications
"""

from typing import Dict, List, Any, Optional
import structlog

logger = structlog.get_logger(__name__)


class ChartType:
    """Chart type constants"""
    BAR = "bar"
    COLUMN = "column"
    LINE = "line"
    STACKED_BAR = "stacked_bar"
    CLUSTERED_BAR = "clustered_bar"
    HEATMAP = "heatmap"
    SCATTER = "scatter"
    PIE = "pie"
    AREA = "area"


class ChartRecommendationEngine:
    """
    Intelligent chart recommendation based on intent, data structure, and cardinality.
    Follows best practices: max 1-2 charts, appropriate for data type and story.
    """
    
    def __init__(self):
        """Initialize chart recommendation rules"""
        self.chart_rules = self._build_chart_rules()
    
    def _normalize_intent(self, intent: str) -> str:
        """
        Normalize intent strings to IntentType enum values.
        Handles both string literals from multi-agent workflow and IntentType enums.
        """
        from backend.agents.intent_classifier import IntentType
        
        # If already an IntentType enum, return it
        if hasattr(IntentType, 'value') and hasattr(intent, 'value'):
            return intent
        
        # Map string literals to IntentType enums
        intent_mapping = {
            "top_services": IntentType.TOP_N_RANKING,
            "top_n": IntentType.TOP_N_RANKING,
            "ranking": IntentType.TOP_N_RANKING,
            "breakdown": IntentType.COST_BREAKDOWN,
            "cost_breakdown": IntentType.COST_BREAKDOWN,
            "regional": IntentType.COST_BREAKDOWN,  # Regional breakdown same as cost breakdown
            "comparison": IntentType.COMPARATIVE,
            "compare": IntentType.COMPARATIVE,
            "trend": IntentType.COST_TREND,
            "cost_trend": IntentType.COST_TREND,
            "time_series": IntentType.COST_TREND,
            "anomaly": IntentType.ANOMALY_ANALYSIS,
            "anomaly_analysis": IntentType.ANOMALY_ANALYSIS,
            "utilization": IntentType.UTILIZATION,
            "optimization": IntentType.OPTIMIZATION,
            "savings": IntentType.OPTIMIZATION,
            "cost_summary": IntentType.COST_BREAKDOWN,
            "summary": IntentType.COST_BREAKDOWN,
            "data_metadata": IntentType.DATA_METADATA,
            "metadata": IntentType.DATA_METADATA
        }
        
        # Convert string intent to lowercase for case-insensitive matching
        intent_str = str(intent).lower() if intent else ""
        
        return intent_mapping.get(intent_str, intent)
    
    def _build_chart_rules(self) -> Dict[str, Any]:
        """Build chart selection rules by intent"""
        from backend.agents.intent_classifier import IntentType
        
        return {
            IntentType.TOP_N_RANKING: {
                "primary": ChartType.COLUMN,
                "alternative": ChartType.PIE,
                "rationale": "Rankings are best shown with bar/column charts for easy comparison"
            },
            IntentType.COST_BREAKDOWN: {
                # Use vertical columns so category names appear on x-axis
                "primary": ChartType.COLUMN,
                "alternative": ChartType.PIE,
                "rationale": "Breakdowns benefit from stacked charts to show part-to-whole relationships"
            },
            IntentType.COST_TREND: {
                "primary": ChartType.LINE,
                "alternative": ChartType.SCATTER,
                "rationale": "Time series data is best displayed with line or scatter charts"
            },
            IntentType.ANOMALY_ANALYSIS: {
                "primary": ChartType.LINE,
                "alternative": ChartType.SCATTER,
                "rationale": "Anomalies are visible in line charts with spike callouts"
            },
            IntentType.COMPARATIVE: {
                "primary": ChartType.CLUSTERED_BAR,  # For two-period comparisons
                "alternative": ChartType.LINE,  # For monthly trends (>90 days)
                "rationale": "Short periods use side-by-side bars, longer periods use line charts for trends"
            },
            IntentType.UTILIZATION: {
                "primary": ChartType.SCATTER,
                "alternative": ChartType.BAR,
                "rationale": "Utilization vs cost relationships shown in scatter plots"
            },
            IntentType.OPTIMIZATION: {
                "primary": ChartType.COLUMN,
                "alternative": ChartType.PIE,
                "rationale": "Savings opportunities are easiest to compare with bar charts"
            },
            IntentType.DATA_METADATA: {
                "primary": ChartType.LINE,
                "alternative": None,
                "rationale": "Record counts over time tracked with line charts"
            }
        }
    
    def recommend_charts(
        self,
        intent: str,
        data_results: List[Dict[str, Any]],
        extracted_params: Dict[str, Any],
        query: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Recommend 1-2 charts based on intent and data characteristics.
        
        Args:
            intent: Query intent type
            data_results: Query results
            extracted_params: Extracted parameters
            query: Original query text
            
        Returns:
            List of chart specifications (max 2)
        """
        if not data_results:
            return []
        
        # Check if user explicitly doesn't want charts
        if any(phrase in query.lower() for phrase in ["no chart", "no graph", "text only"]):
            logger.info("User explicitly requested no charts")
            return []
        
        # Check for ARN fallback - show pie chart by resource type
        metadata = extracted_params.get("metadata", {})
        if metadata.get("arn_fallback"):
            logger.info("ARN fallback detected - using pie chart by resource type")
            # For ARN breakdown showing related resources, use pie chart by resource_type
            return [{
                "chart_type": ChartType.PIE,
                "x_field": "resource_type",
                "y_field": "cost_usd",
                "title": "Cost by Resource Type",
                "description": "Distribution of costs across resource types"
            }]
        
        # Auto-detect drill-down scenario: if we have usage_type as dimension, prefer PIE chart
        if len(data_results) >= 2:
            columns = list(data_results[0].keys())
            # Check if this is a usage_type breakdown (drill-down scenario)
            if 'usage_type' in columns or 'line_item_usage_type' in columns:
                logger.info("Detected usage_type breakdown - recommending PIE chart")
                pie_chart = self._generate_pie_chart_for_usage_breakdown(data_results)
                if pie_chart:
                    return [pie_chart]
        
        # Check for top service breakdown - use pie chart to show how cost is accumulated
        top_service_breakdown = metadata.get("top_service_breakdown")
        if top_service_breakdown:
            logger.info(
                f"Detected top service breakdown - using pie chart",
                service=top_service_breakdown.get("service")
            )
            # For single service breakdown showing cost drivers, pie chart is most intuitive
            pie_chart = self._generate_pie_chart_for_breakdown(
                data_results,
                top_service_breakdown
            )
            if pie_chart:
                return [pie_chart]
        
        # Normalize intent - handle both string literals and IntentType enums
        normalized_intent = self._normalize_intent(intent)
        
        # Get chart rules for this intent
        rules = self.chart_rules.get(normalized_intent, {})
        if not rules:
            logger.info(f"No chart rules for intent: {intent} (normalized: {normalized_intent})")
            return []
        
        # Analyze data structure
        data_structure = self._analyze_data_structure(data_results)
        
        # Generate chart specs
        chart_specs = []
        
        # Primary chart
        primary_chart = self._generate_chart_spec(
            rules["primary"],
            data_results,
            data_structure,
            extracted_params,
            intent
        )
        if primary_chart:
            chart_specs.append(primary_chart)
        
        # Secondary chart (only if beneficial)
        if self._should_add_secondary_chart(intent, data_structure, query):
            alternative = rules.get("alternative")
            if alternative and alternative != rules["primary"]:
                secondary_chart = self._generate_chart_spec(
                    alternative,
                    data_results,
                    data_structure,
                    extracted_params,
                    intent
                )
                if secondary_chart:
                    chart_specs.append(secondary_chart)
        
        logger.info(f"Recommended {len(chart_specs)} charts for intent: {intent}")
        return chart_specs
    
    def _analyze_data_structure(self, data_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze data structure and characteristics"""
        if not data_results:
            return {}
        
        sample = data_results[0]
        columns = list(sample.keys())
        
        # Identify column types
        dimension_cols = []
        metric_cols = []
        time_cols = []
        
        for col in columns:
            col_lower = col.lower()
            
            # Skip rank/row_number columns - they're not useful as chart dimensions
            if col_lower in ["rank", "row_number", "row_num", "rn"]:
                continue
            # Skip metadata date columns from period comparisons (not actual time series data)
            elif col_lower in ["start_date", "end_date", "query_start_date", "query_end_date"]:
                # These are metadata columns, not time-series x-axis values
                continue
            # Time columns (actual time-series data points)
            elif any(t in col_lower for t in ["date", "time", "month", "week", "day", "year"]) and "period" not in col_lower:
                time_cols.append(col)
            # Metric columns (numeric)
            elif any(m in col_lower for m in ["cost", "amount", "count", "total", "pct", "percent", "usage", "hours"]):
                metric_cols.append(col)
            # Dimension columns
            else:
                dimension_cols.append(col)
        
        # Determine cardinality
        cardinality = len(data_results)
        
        # Determine if there are multiple series
        has_multiple_series = len(metric_cols) > 1 or self._has_grouping_column(data_results)
        
        # Detect period-over-period comparison data structure
        is_period_comparison = (
            "current_period_cost" in columns and 
            "previous_period_cost" in columns
        )
        
        return {
            "columns": columns,
            "dimension_cols": dimension_cols,
            "metric_cols": metric_cols,
            "time_cols": time_cols,
            "is_period_comparison": is_period_comparison,
            "cardinality": cardinality,
            "has_time_series": len(time_cols) > 0,
            "has_multiple_series": has_multiple_series,
            "sample": sample
        }
    
    def _has_grouping_column(self, data_results: List[Dict[str, Any]]) -> bool:
        """Check if data has a grouping/series column"""
        if len(data_results) < 2:
            return False
        
        # Check for common grouping columns
        sample = data_results[0]
        grouping_cols = ["env", "environment", "service", "region", "account", "tag_value"]
        
        for col in grouping_cols:
            if col in sample:
                # Check if values repeat (indicating grouping)
                values = set(r.get(col) for r in data_results)
                if len(values) < len(data_results):
                    return True
        
        return False
    
    def _generate_chart_spec(
        self,
        chart_type: str,
        data_results: List[Dict[str, Any]],
        data_structure: Dict[str, Any]
,
        params: Dict[str, Any],
        intent: str
    ) -> Optional[Dict[str, Any]]:
        """Generate chart specification"""
        from backend.agents.intent_classifier import IntentType
        
        if not data_results:
            return None
        
        # For COMPARATIVE intent, detect if this is monthly trend data (>90 days)
        # If so, override chart type to LINE instead of CLUSTERED_BAR
        if intent == IntentType.COMPARATIVE and chart_type == ChartType.CLUSTERED_BAR:
            first_row = data_results[0]
            # Monthly trend has "month" column instead of "current_period_cost"
            if "month" in first_row and "cost_usd" in first_row:
                logger.info("COMPARATIVE with monthly trend data - switching to LINE chart")
                chart_type = ChartType.LINE
                # Update data structure to indicate time series
                data_structure["has_time_series"] = True
                if "month" not in data_structure["time_cols"]:
                    data_structure["time_cols"].append("month")
        
        # Determine x and y axes
        x_field = None
        y_field = None
        series_field = None
        
        # Time series charts
        if chart_type in [ChartType.LINE, ChartType.AREA] and data_structure.get("has_time_series"):
            x_field = data_structure["time_cols"][0] if data_structure["time_cols"] else None
            y_field = data_structure["metric_cols"][0] if data_structure["metric_cols"] else "cost_usd"

            # If there is only a single time bucket, a line chart looks odd.
            # Downgrade to a simple column chart for clearer presentation.
            if x_field:
                unique_x = {str(r.get(x_field)) for r in data_results if r.get(x_field) is not None}
                if len(unique_x) <= 1:
                    logger.info(
                        "Single data point in time series - switching to COLUMN chart for clarity",
                        x_field=x_field,
                        y_field=y_field,
                        unique_points=len(unique_x)
                    )
                    chart_type = ChartType.COLUMN
                    # Prefer a human-readable categorical x-axis if present
                    if "dimension_value" in data_results[0]:
                        x_field = "dimension_value"
                    elif "service" in data_results[0]:
                        x_field = "service"
                    else:
                        # Fall back to time bucket label
                        x_field = x_field
                    series_field = None
                else:
                    # Check for series grouping when we truly have time series
                    if data_structure.get("has_multiple_series"):
                        series_field = self._find_series_field(data_results)
                        # CRITICAL FIX: If we have time-series with many services, switch to stacked area or limit data
                        if series_field:
                            unique_series = set(r.get(series_field) for r in data_results)
                            if len(unique_series) > 10:
                                if chart_type == ChartType.AREA:
                                    logger.info(f"Time-series with {len(unique_series)} series - limiting to top 10 for stacked area")
                                else:
                                    logger.info(f"Time-series with {len(unique_series)} series - disabling series grouping for line chart")
                                    series_field = None
        
        # Ranking/breakdown charts
        elif chart_type in [ChartType.BAR, ChartType.COLUMN]:
            # X is dimension, Y is metric
            dimension_col = data_structure["dimension_cols"][0] if data_structure["dimension_cols"] else None
            metric_col = data_structure["metric_cols"][0] if data_structure["metric_cols"] else "cost_usd"
            
            # CRITICAL FIX: Prefer 'dimension_value' for service breakdown queries
            # When service_cost_breakdown returns data, it uses 'dimension_value' as the column name
            if "dimension_value" in data_results[0]:
                x_field = "dimension_value"
            elif dimension_col:
                x_field = dimension_col
            elif "service" in data_results[0]:
                x_field = "service"
            else:
                x_field = dimension_col or "category"
            
            y_field = metric_col
            
            logger.info(
                "Chart spec for bar/column",
                x_field=x_field,
                y_field=y_field,
                available_cols=list(data_results[0].keys()) if data_results else []
            )
        
        # Stacked charts
        elif chart_type == ChartType.STACKED_BAR:
            x_field = data_structure["dimension_cols"][0] if data_structure["dimension_cols"] else "category"
            y_field = data_structure["metric_cols"][0] if data_structure["metric_cols"] else "cost_usd"
            series_field = self._find_series_field(data_results)
        
        # Clustered charts (for comparisons)
        elif chart_type == ChartType.CLUSTERED_BAR:
            # For period comparisons, use service as x-axis
            if data_structure.get("is_period_comparison"):
                x_field = "service"
                y_field = "current_period_cost"  # Will handle both periods in _build_period_comparison_chart
                series_field = None  # Period comparison chart builder handles this
            else:
                x_field = data_structure["dimension_cols"][0] if data_structure["dimension_cols"] else "service"
                y_field = data_structure["metric_cols"][0] if data_structure["metric_cols"] else "cost_usd"
                series_field = self._find_series_field(data_results) or "env"
        
        # Scatter plots
        elif chart_type == ChartType.SCATTER:
            # X and Y are both metrics
            if len(data_structure["metric_cols"]) >= 2:
                x_field = data_structure["metric_cols"][0]
                y_field = data_structure["metric_cols"][1]
            else:
                x_field = "usage"
                y_field = "cost_usd"
        
        # Heatmap
        elif chart_type == ChartType.HEATMAP:
            # Need two dimensions
            if len(data_structure["dimension_cols"]) >= 2:
                x_field = data_structure["dimension_cols"][0]
                y_field = data_structure["dimension_cols"][1]
            else:
                return None  # Can't create heatmap without 2 dimensions
        
        if not x_field or not y_field:
            logger.warning(f"Could not determine axes for chart type: {chart_type}")
            return None
        
        # Build chart spec
        spec = {
            "type": chart_type,
            "x": x_field,
            "y": y_field,
            "title": self._generate_chart_title(intent, x_field, y_field, params)
        }
        
        if series_field:
            spec["series"] = series_field
        
        # Add data-specific configuration
        if data_structure["cardinality"] > 20:
            spec["limit"] = 20
            spec["note"] = "Showing top 20 items"
        
        return spec
    
    def _find_series_field(self, data_results: List[Dict[str, Any]]) -> Optional[str]:
        """Find the field that acts as series grouping"""
        if not data_results:
            return None
        
        sample = data_results[0]
        
        # Prioritized list of potential series fields
        series_candidates = [
            "env", "environment", "service", "region", "account",
            "tag_value", "instance_type", "driver", "category"
        ]
        
        for candidate in series_candidates:
            if candidate in sample:
                return candidate
        
        # Fallback: first non-metric column
        for key in sample.keys():
            if not any(m in key.lower() for m in ["cost", "amount", "count", "total", "pct"]):
                return key
        
        return None
    
    def _generate_chart_title(
        self,
        intent: str,
        x_field: str,
        y_field: str,
        params: Dict[str, Any]
    ) -> str:
        """Generate descriptive chart title"""
        from backend.agents.intent_classifier import IntentType
        
        # Clean field names
        x_clean = x_field.replace("_", " ").title()
        y_clean = y_field.replace("_", " ").title()
        
        if intent == IntentType.TOP_N_RANKING:
            top_n = params.get("top_n", 10)
            return f"Top {top_n} by {y_clean}"
        
        elif intent == IntentType.COST_TREND:
            return f"{y_clean} Over Time"
        
        elif intent == IntentType.COST_BREAKDOWN:
            return f"{y_clean} by {x_clean}"
        
        elif intent == IntentType.ANOMALY_ANALYSIS:
            return f"{y_clean} with Anomalies"
        
        elif intent == IntentType.COMPARATIVE:
            return f"{y_clean} Comparison"
        
        else:
            return f"{y_clean} by {x_clean}"
    
    def _should_add_secondary_chart(
        self,
        intent: str,
        data_structure: Dict[str, Any],
        query: str
    ) -> bool:
        """Determine if a secondary chart would add value"""
        from backend.agents.intent_classifier import IntentType
        
        # Don't add secondary chart for simple queries
        if data_structure["cardinality"] < 5:
            return False
        
        # Add secondary for complex analyses
        if intent == IntentType.COST_TREND and data_structure.get("has_multiple_series"):
            return True
        
        if intent == IntentType.COST_BREAKDOWN and data_structure["cardinality"] > 10:
            return True
        
        # Explicit request for multiple views
        if any(phrase in query.lower() for phrase in ["both", "multiple", "different view", "also show"]):
            return True
        
        return False
    
    def get_chart_data_format(
        self,
        chart_type: str,
        data_results: List[Dict[str, Any]],
        x_field: str,
        y_field: str,
        series_field: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format data for specific chart type.
        
        Args:
            chart_type: Type of chart
            data_results: Raw data
            x_field: X-axis field
            y_field: Y-axis field
            series_field: Series grouping field (optional)
            
        Returns:
            Formatted chart data
        """
        if chart_type in [ChartType.LINE, ChartType.AREA]:
            # Time series format
            return self._format_time_series_data(data_results, x_field, y_field, series_field)
        
        elif chart_type in [ChartType.BAR, ChartType.COLUMN]:
            # Simple bar/column format
            return self._format_categorical_data(data_results, x_field, y_field)
        
        elif chart_type in [ChartType.STACKED_BAR, ChartType.CLUSTERED_BAR]:
            # Grouped/stacked format
            return self._format_grouped_data(data_results, x_field, y_field, series_field)
        
        elif chart_type == ChartType.SCATTER:
            # Scatter plot format
            return self._format_scatter_data(data_results, x_field, y_field)
        
        else:
            # Default format
            return {
                "x": [r.get(x_field) for r in data_results],
                "y": [r.get(y_field) for r in data_results],
                "type": chart_type
            }
    
    def _format_time_series_data(
        self,
        data_results: List[Dict[str, Any]],
        x_field: str,
        y_field: str,
        series_field: Optional[str]
    ) -> Dict[str, Any]:
        """Format data for time series charts"""
        if series_field:
            # Multiple series
            series_data = {}
            for row in data_results:
                series_name = row.get(series_field, "Unknown")
                if series_name not in series_data:
                    series_data[series_name] = {"x": [], "y": []}
                series_data[series_name]["x"].append(row.get(x_field))
                series_data[series_name]["y"].append(row.get(y_field))
            return {"type": "multi_series", "series": series_data}
        else:
            # Single series
            return {
                "type": "single_series",
                "x": [r.get(x_field) for r in data_results],
                "y": [r.get(y_field) for r in data_results]
            }
    
    def _format_categorical_data(
        self,
        data_results: List[Dict[str, Any]],
        x_field: str,
        y_field: str
    ) -> Dict[str, Any]:
        """Format data for categorical charts"""
        return {
            "type": "categorical",
            "labels": [str(r.get(x_field)) for r in data_results],
            "values": [r.get(y_field) for r in data_results]
        }
    
    def _format_grouped_data(
        self,
        data_results: List[Dict[str, Any]],
        x_field: str,
        y_field: str,
        series_field: Optional[str]
    ) -> Dict[str, Any]:
        """Format data for grouped/stacked charts"""
        if not series_field:
            return self._format_categorical_data(data_results, x_field, y_field)
        
        # Group by x_field and series_field
        grouped = {}
        for row in data_results:
            x_val = row.get(x_field)
            series_val = row.get(series_field)
            y_val = row.get(y_field)
            
            if x_val not in grouped:
                grouped[x_val] = {}
            grouped[x_val][series_val] = y_val
        
        return {
            "type": "grouped",
            "categories": list(grouped.keys()),
            "series": grouped
        }
    
    def _format_scatter_data(
        self,
        data_results: List[Dict[str, Any]],
        x_field: str,
        y_field: str
    ) -> Dict[str, Any]:
        """Format data for scatter plots"""
        return {
            "type": "scatter",
            "points": [
                {"x": r.get(x_field), "y": r.get(y_field)}
                for r in data_results
            ]
        }
    
    def _generate_pie_chart_for_breakdown(
        self,
        data_results: List[Dict[str, Any]],
        top_service_info: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generate pie chart for top service breakdown showing cost accumulation"""
        if not data_results:
            return None
        
        service_name = top_service_info.get("service", "Service")
        total_cost = top_service_info.get("total_cost", 0)
        
        # Find dimension and cost fields
        sample = data_results[0]
        dimension_field = None
        cost_field = None
        
        # Find dimension field (usage_type, region, operation, etc.)
        for col in sample.keys():
            if "dimension" in col.lower() or "usage_type" in col.lower() or col in ["region", "operation", "account"]:
                dimension_field = col
                break
        
        # Find cost field
        for col in sample.keys():
            if any(term in col.lower() for term in ["cost_usd", "cost", "total"]):
                cost_field = col
                break
        
        if not dimension_field or not cost_field:
            return None
        
        return {
            "type": "pie",
            "title": f"{service_name} Cost Breakdown (${total_cost:.2f} total)",
            "x": dimension_field,
            "y": cost_field,
            "series": None
        }

    def _generate_pie_chart_for_usage_breakdown(
        self,
        data_results: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Generate pie chart for usage_type breakdown (drill-down scenario)"""
        if not data_results:
            return None
        
        # Calculate total cost
        total_cost = sum(float(row.get('cost_usd', row.get('cost', 0)) or 0) for row in data_results)
        
        # Find the usage_type and cost fields
        sample = data_results[0]
        usage_field = None
        cost_field = None
        
        for col in sample.keys():
            col_lower = col.lower()
            if 'usage_type' in col_lower or 'usage' in col_lower:
                usage_field = col
            elif 'cost' in col_lower and cost_field is None:
                cost_field = col
        
        if not usage_field or not cost_field:
            logger.warning("Could not find usage_type or cost fields for pie chart")
            return None
        
        return {
            "type": "pie",
            "chart_type": "pie",
            "title": f"Cost by Usage Type (${total_cost:,.2f} total)",
            "x": usage_field,
            "y": cost_field,
            "x_field": usage_field,
            "y_field": cost_field,
            "description": "Distribution of costs across different usage types",
            "series": None
        }


# Global chart recommendation engine instance
chart_engine = ChartRecommendationEngine()
