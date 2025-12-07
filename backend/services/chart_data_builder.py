"""
Chart Data Builder - Converts chart specifications into Chart.js-compatible data structures
"""

from typing import Dict, List, Any, Optional
import structlog
from datetime import datetime

from backend.services.column_constants import (
    DIMENSION_VALUE, SERVICE, REGION, COST_USD, CHART_REQUIRED_COLUMNS
)

logger = structlog.get_logger(__name__)


class ChartDataBuilder:
    """
    Builds Chart.js-compatible chart data from specifications and query results.
    Converts raw data + chart spec → ready-to-render Chart.js format.
    """
    
    def __init__(self):
        """Initialize chart data builder"""
        self.color_palette = [
            'rgba(102, 126, 234, 0.8)',  # Purple
            'rgba(237, 100, 166, 0.8)',   # Pink
            'rgba(255, 159, 64, 0.8)',    # Orange
            'rgba(75, 192, 192, 0.8)',    # Teal
            'rgba(153, 102, 255, 0.8)',   # Violet
            'rgba(255, 99, 132, 0.8)',    # Red
            'rgba(54, 162, 235, 0.8)',    # Blue
            'rgba(255, 206, 86, 0.8)',    # Yellow
            'rgba(231, 233, 237, 0.8)',   # Gray
        ]
    
    def build_chart_data(
        self,
        chart_specs: List[Dict[str, Any]],
        data_results: List[Dict[str, Any]],
        conv_context: Any = None
    ) -> List[Dict[str, Any]]:
        """
        Build Chart.js-compatible chart data from specifications.
        
        Args:
            chart_specs: Chart specifications from chart_recommendation engine
            data_results: Raw query results from Athena
            conv_context: Optional conversation context for tracking aggregation
            
        Returns:
            List of Chart.js-ready chart data objects
        """
        if not chart_specs or not data_results:
            logger.warning(
                "No chart specs or data results provided",
                has_specs=bool(chart_specs),
                specs_count=len(chart_specs) if chart_specs else 0,
                has_data=bool(data_results),
                data_count=len(data_results) if data_results else 0
            )
            return []
        
        logger.info(
            "Building charts",
            specs_count=len(chart_specs),
            data_count=len(data_results),
            first_spec=chart_specs[0] if chart_specs else None
        )
        
        charts = []
        for idx, spec in enumerate(chart_specs):
            try:
                logger.info(f"Building chart {idx+1}/{len(chart_specs)}", spec=spec)
                chart_data = self._build_single_chart(spec, data_results, conv_context)
                if chart_data:
                    charts.append(chart_data)
                    logger.info(f"Successfully built chart: {chart_data.get('title')}")
                else:
                    logger.warning(f"Chart {idx+1} returned None", spec=spec)
            except Exception as e:
                logger.error(f"Failed to build chart {idx+1}: {e}", spec=spec, exc_info=True)
        
        logger.info(f"Built {len(charts)} charts from {len(chart_specs)} specs")
        return charts
    
    def _build_single_chart(
        self,
        spec: Dict[str, Any],
        data_results: List[Dict[str, Any]],
        conv_context: Any = None
    ) -> Optional[Dict[str, Any]]:
        """Build a single chart from spec and data"""
        chart_type = spec.get("type")
        x_field = spec.get("x")
        y_field = spec.get("y")
        series_field = spec.get("series")
        title = spec.get("title", "Chart")
        
        # DEBUG: Log spec and data structure
        logger.info(f"CHART SPEC DEBUG: type={chart_type}, x={x_field}, y={y_field}, series={series_field}")
        if data_results:
            sample_row = data_results[0]
            logger.info(f"CHART DATA DEBUG: Sample row keys: {list(sample_row.keys())}")
            logger.info(f"CHART DATA DEBUG: Sample row: {sample_row}")
            
            # Defensive validation: check if specified fields exist in data
            missing_fields = []
            if x_field not in sample_row:
                missing_fields.append(x_field)
                # Try fallback to standardized column name
                if x_field == "dimension_value" and DIMENSION_VALUE in sample_row:
                    x_field = DIMENSION_VALUE
                    logger.info(f"Using fallback x_field: {DIMENSION_VALUE}")
            if y_field not in sample_row:
                missing_fields.append(y_field)
                # Try fallback to standardized column name
                if y_field == "cost_usd" and COST_USD in sample_row:
                    y_field = COST_USD
                    logger.info(f"Using fallback y_field: {COST_USD}")
            
            if missing_fields:
                logger.warning(
                    "Chart spec references missing fields - attempting to continue with available fields",
                    missing_fields=missing_fields,
                    available_fields=list(sample_row.keys()),
                    spec_x=spec.get("x"),
                    spec_y=spec.get("y"),
                    actual_x=x_field,
                    actual_y=y_field
                )
        
        if not chart_type or not x_field or not y_field:
            logger.warning("Incomplete chart spec", spec=spec)
            return None
        
        # Apply limit if specified
        # For time-series charts (line/area), skip limit to allow proper aggregation
        # Limit will be applied after aggregation if needed
        limit = spec.get("limit", 20)
        is_time_series = chart_type in ["line", "area"] and not series_field
        use_full_dataset = chart_type in ["bar", "column"]
        limited_data = data_results if (is_time_series or use_full_dataset) else data_results[:limit]
        
        # Build based on chart type
        if chart_type in ["line", "area"]:
            return self._build_line_chart(title, chart_type, x_field, y_field, series_field, limited_data)
        elif chart_type in ["bar", "column"]:
            return self._build_bar_chart(title, chart_type, x_field, y_field, limited_data, conv_context)
        elif chart_type == "stacked_bar":
            return self._build_stacked_bar_chart(title, x_field, y_field, series_field, limited_data)
        elif chart_type == "clustered_bar":
            return self._build_clustered_bar_chart(title, x_field, y_field, series_field, limited_data)
        elif chart_type == "pie":
            return self._build_pie_chart(title, x_field, y_field, limited_data)
        elif chart_type == "scatter":
            return self._build_scatter_chart(title, x_field, y_field, limited_data)
        else:
            logger.warning(f"Unsupported chart type: {chart_type}")
            return None
    
    def _format_chart_label(self, value: Any, field_name: str) -> str:
        """Format chart labels for better display, especially for dates/months"""
        value_str = str(value)
        
        # Detect date patterns like "2025-04-01" or "2025-04-01 00:00:00"
        if field_name in ['date', 'month', 'period'] and '-' in value_str:
            try:
                # Try to parse as date
                from datetime import datetime as dt
                # Handle both date and datetime strings
                if ' ' in value_str:
                    parsed = dt.strptime(value_str.split()[0], '%Y-%m-%d')
                else:
                    parsed = dt.strptime(value_str, '%Y-%m-%d')
                # Format as "April 2025" for first of month, otherwise "Apr 1, 2025"
                if parsed.day == 1:
                    return parsed.strftime('%B %Y')  # "April 2025"
                else:
                    return parsed.strftime('%b %-d, %Y')  # "Apr 1, 2025"
            except:
                pass
        
        return value_str
    
    def _add_chart_buffers(self, labels: List[str], values: List[float], field_name: str) -> tuple:
        """Add buffer periods before first and after last data points for better chart display"""
        if not labels or len(labels) < 2:
            return labels, values
        
        # Only add buffers for date/month fields
        if field_name not in ['date', 'month', 'period']:
            return labels, values
        
        try:
            from datetime import datetime as dt
            from dateutil.relativedelta import relativedelta
            
            # Try to parse first and last labels to detect if they're months
            first_label = labels[0]
            last_label = labels[-1]
            
            # Try parsing as "Month Year" format (e.g., "April 2025")
            try:
                first_date = dt.strptime(first_label, '%B %Y')
                last_date = dt.strptime(last_label, '%B %Y')
                
                # Add previous month before first
                prev_month = first_date - relativedelta(months=1)
                prev_label = prev_month.strftime('%B %Y')
                
                # Add next month after last
                next_month = last_date + relativedelta(months=1)
                next_label = next_month.strftime('%B %Y')
                
                # Prepend and append buffer periods with null values
                buffered_labels = [prev_label] + labels + [next_label]
                buffered_values = [None] + values + [None]
                
                logger.info(f"Added buffer periods: {prev_label} (before) and {next_label} (after)")
                return buffered_labels, buffered_values
            except:
                # If not month format, return original
                pass
                
        except ImportError:
            logger.warning("dateutil not available, skipping chart buffers")
        except Exception as e:
            logger.warning(f"Could not add chart buffers: {e}")
        
        return labels, values
    
    def _build_line_chart(
        self,
        title: str,
        chart_type: str,
        x_field: str,
        y_field: str,
        series_field: Optional[str],
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build line/area chart"""
        if series_field:
            # Multi-series line chart
            series_map = {}
            for row in data:
                series_name = str(row.get(series_field, "Unknown"))
                if series_name not in series_map:
                    series_map[series_name] = {"x": [], "y": []}
                
                # Defensive check: verify fields exist in row
                x_value = row.get(x_field)
                y_value = row.get(y_field)
                
                if x_value is None or y_value is None:
                    logger.warning(
                        f"Missing chart field in row: x_field={x_field} (value={x_value}), "
                        f"y_field={y_field} (value={y_value}), available_keys={list(row.keys())}"
                    )
                    continue  # Skip this row
                
                series_map[series_name]["x"].append(x_value)
                series_map[series_name]["y"].append(y_value)
            
            # Build datasets
            datasets = []
            for i, (series_name, series_data) in enumerate(series_map.items()):
                color = self.color_palette[i % len(self.color_palette)]
                datasets.append({
                    "label": series_name,
                    "data": series_data["y"],
                    "borderColor": color,
                    "backgroundColor": color.replace('0.8', '0.2') if chart_type == "area" else 'transparent',
                    "fill": chart_type == "area",
                    "tension": 0.4
                })
            
            return {
                "type": "line",
                "title": title,
                "data": {
                    "labels": series_map[list(series_map.keys())[0]]["x"],
                    "datasets": datasets
                },
                "config": {
                    "plugins": {
                        "legend": {
                            "display": True,
                            "position": "top"
                        },
                        "datalabels": {
                            "display": False  # Disable data labels on line charts to prevent overlap
                        }
                    },
                    "scales": {
                        "y": {
                            "beginAtZero": True,
                            "title": {
                                "display": True,
                                "text": "Cost (USD)"
                            }
                        }
                    }
                }
            }
        else:
            # Single series line chart - aggregate by x_field if there are duplicates
            # This handles cases where data has multiple rows per x-value (e.g., multiple services per month)
            aggregated = {}
            for row in data:
                # Defensive check: verify fields exist
                x_val = row.get(x_field)
                y_val = row.get(y_field)
                
                if x_val is None or y_val is None:
                    logger.warning(
                        f"Missing chart field in row: x_field={x_field} (value={x_val}), "
                        f"y_field={y_field} (value={y_val}), available_keys={list(row.keys())}"
                    )
                    continue  # Skip this row
                
                # Format date/month labels for better readability
                x_val_str = self._format_chart_label(x_val, x_field)
                if x_val_str in aggregated:
                    aggregated[x_val_str] += y_val
                else:
                    aggregated[x_val_str] = y_val
            
            # Sort by x_field (important for time series)
            sorted_items = sorted(aggregated.items(), key=lambda x: x[0])
            labels = [item[0] for item in sorted_items]
            values = [item[1] for item in sorted_items]
            
            # Add buffer labels before and after for better chart display
            labels, values = self._add_chart_buffers(labels, values, x_field)
            
            logger.info(f"Single-series line chart: aggregated {len(data)} rows into {len(labels)} unique x-values (with buffers)")
            
            return {
                "type": "line",
                "title": title,
                "data": {
                    "labels": labels,
                    "datasets": [{
                        "label": y_field.replace("_", " ").title(),
                        "data": values,
                        "borderColor": self.color_palette[0],
                        "backgroundColor": self.color_palette[0].replace('0.8', '0.2') if chart_type == "area" else 'transparent',
                        "fill": chart_type == "area",
                        "tension": 0.4,
                        "spanGaps": False  # Don't connect across null values
                    }]
                },
                "config": {
                    "plugins": {
                        "legend": {
                            "display": False  # Single series doesn't need legend
                        },
                        "datalabels": {
                            "display": False  # Disable data labels on line charts to prevent overlap
                        }
                    },
                    "scales": {
                        "y": {
                            "beginAtZero": True,
                            "title": {
                                "display": True,
                                "text": "Cost (USD)"
                            }
                        }
                    }
                }
            }
    
    def _build_bar_chart(
        self,
        title: str,
        chart_type: str,
        x_field: str,
        y_field: str,
        data: List[Dict[str, Any]],
        conv_context: Any = None
    ) -> Dict[str, Any]:
        """Build bar/column chart with smart aggregation based on query intent"""
        
        # First, extract and convert all values
        items = []
        for row in data:
            label = str(row.get(x_field, ""))
            val = row.get(y_field, 0)
            try:
                value = float(val) if val is not None else 0
            except (ValueError, TypeError):
                value = 0
            items.append({"label": label, "value": value})
        
        # Sort by value descending (highest cost first)
        items.sort(key=lambda x: x["value"], reverse=True)
        
        # Determine if this is a breakdown/drill-down query (user wants details)
        is_breakdown_query = False
        if conv_context:
            # Check if last query intent was breakdown or if we're in a follow-up drill-down
            last_intent = getattr(conv_context, 'last_intent', None)
            last_query = getattr(conv_context, 'last_query', '').lower()
            
            # IMPORTANT: Only detect breakdown for COST_BREAKDOWN intent
            # Don't confuse with TOP_N_RANKING which should still aggregate
            if last_intent == 'cost_breakdown':
                is_breakdown_query = True
            # Removed explicit breakdown keyword check - let intent classification handle it
        
        # Also check title for breakdown indicators (but NOT for service breakdowns)
        # Service breakdowns should still use top 5 + Others aggregation
        title_lower = title.lower()
        if any(word in title_lower for word in ['by usage', 'by operation']) and 'service' not in title_lower:
            is_breakdown_query = True
        
        # Smart aggregation logic:
        # - For breakdown queries: Show up to 15 items (no "Others" aggregation)
        # - For top-level queries AND service breakdowns: Show top 5 + "Others" for clarity
        should_aggregate = not is_breakdown_query and len(items) > 5
        
        if should_aggregate:
            # Top-level query: aggregate to top 5 + "Others"
            top_5 = items[:5]
            others_items = items[5:]
            others_sum = sum(item["value"] for item in others_items)
            others_count = len(others_items)
            
            # Track hidden items in conversation context for drill-down
            if conv_context:
                conv_context.last_shown_top_items = [item["label"] for item in top_5]
                conv_context.last_hidden_items = others_items
                conv_context.last_chart_aggregated = True
                logger.info(
                    "Stored hidden items in conversation context for potential drill-down",
                    hidden_count=len(others_items)
                )
            
            # Add "Others" as 6th item
            labels = [item["label"] for item in top_5]
            values = [item["value"] for item in top_5]
            labels.append(f"Others ({others_count} items)")
            values.append(others_sum)
            
            logger.info(
                f"BAR CHART: Aggregating for cleaner UI (top-level query)",
                total_items=len(items),
                showing_top=5,
                others_count=others_count,
                others_total=round(others_sum, 2)
            )
        elif is_breakdown_query and len(items) > 15:
            # Breakdown query with too many items: show top 15 (no "Others")
            items = items[:15]
            labels = [item["label"] for item in items]
            values = [item["value"] for item in items]
            
            if conv_context:
                conv_context.last_chart_aggregated = False
                conv_context.last_hidden_items = []
                conv_context.last_shown_top_items = labels
            
            logger.info(
                f"BAR CHART: Breakdown query - showing top 15 items without aggregation",
                total_items=len(items),
                is_breakdown=True
            )
        else:
            # Show all items (breakdown query with reasonable count, or <= 5 items)
            labels = [item["label"] for item in items]
            values = [item["value"] for item in items]
            
            # Clear aggregation tracking
            if conv_context:
                conv_context.last_chart_aggregated = False
                conv_context.last_hidden_items = []
                conv_context.last_shown_top_items = labels
            
            logger.info(
                f"BAR CHART: Showing all {len(items)} items (breakdown query or small dataset)",
                is_breakdown=is_breakdown_query
            )
        
        # DEBUG: Log chart data details
        logger.info(f"BAR CHART DEBUG: x_field={x_field}, y_field={y_field}")
        logger.info(f"BAR CHART DEBUG: Labels: {labels}")
        logger.info(f"BAR CHART DEBUG: Values: {values}")
        
        # Use gradient colors based on values
        colors = self._generate_gradient_colors(len(values))
        
        return {
            "type": "bar",
            "title": title,
            "data": {
                "labels": labels,
                "datasets": [{
                    "label": y_field.replace("_", " ").title(),
                    "data": values,
                    "backgroundColor": colors,
                    "borderColor": [c.replace('0.8', '1.0') for c in colors],
                    "borderWidth": 1
                }]
            },
            "config": {
                "indexAxis": "x" if chart_type == "column" else "y",
                "plugins": {
                    "legend": {
                        "display": False
                    }
                }
            }
        }
    
    def _build_stacked_bar_chart(
        self,
        title: str,
        x_field: str,
        y_field: str,
        series_field: Optional[str],
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build stacked bar chart"""
        # If series_field is same as x_field, it's not really a stacked chart
        # Just show individual bars for each category
        if not series_field or series_field == x_field:
            # Fallback to vertical columns so categories are on x-axis
            return self._build_bar_chart(title, "column", x_field, y_field, data)
        
        # Group data by x_field and series_field
        categories = []
        series_map = {}
        
        for row in data:
            x_val = str(row.get(x_field, ""))
            series_val = str(row.get(series_field, "Unknown"))
            y_val = row.get(y_field, 0)
            
            if x_val not in categories:
                categories.append(x_val)
            
            if series_val not in series_map:
                series_map[series_val] = {}
            series_map[series_val][x_val] = y_val
        
        # Build datasets
        datasets = []
        for i, (series_name, series_data) in enumerate(series_map.items()):
            color = self.color_palette[i % len(self.color_palette)]
            datasets.append({
                "label": series_name,
                "data": [series_data.get(cat, 0) for cat in categories],
                "backgroundColor": color,
                "borderColor": color.replace('0.8', '1.0'),
                "borderWidth": 1
            })
        
        return {
            "type": "bar",
            "title": title,
            "data": {
                "labels": categories,
                "datasets": datasets
            },
            "config": {
                "plugins": {
                    "legend": {
                        "display": True,
                        "position": "top"
                    }
                },
                "scales": {
                    "x": {
                        "stacked": True
                    },
                    "y": {
                        "stacked": True
                    }
                }
            }
        }
    
    def _build_clustered_bar_chart(
        self,
        title: str,
        x_field: str,
        y_field: str,
        series_field: Optional[str],
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build clustered (grouped) bar chart"""
        # Check if this is period-over-period comparison data
        # (has current_period_cost and previous_period_cost columns)
        if data and "current_period_cost" in data[0] and "previous_period_cost" in data[0]:
            logger.info("Detected period-over-period comparison data, building comparison chart")
            return self._build_period_comparison_chart(title, data)
        
        # Similar to stacked but without stacking
        if not series_field:
            return self._build_bar_chart(title, "bar", x_field, y_field, data)
        
        categories = []
        series_map = {}
        
        for row in data:
            x_val = str(row.get(x_field, ""))
            series_val = str(row.get(series_field, "Unknown"))
            y_val = row.get(y_field, 0)
            
            if x_val not in categories:
                categories.append(x_val)
            
            if series_val not in series_map:
                series_map[series_val] = {}
            series_map[series_val][x_val] = y_val
        
        # Build datasets
        datasets = []
        for i, (series_name, series_data) in enumerate(series_map.items()):
            color = self.color_palette[i % len(self.color_palette)]
            datasets.append({
                "label": series_name,
                "data": [series_data.get(cat, 0) for cat in categories],
                "backgroundColor": color,
                "borderColor": color.replace('0.8', '1.0'),
                "borderWidth": 1
            })
        
        return {
            "type": "bar",
            "title": title,
            "data": {
                "labels": categories,
                "datasets": datasets
            },
            "config": {
                "plugins": {
                    "legend": {
                        "display": True,
                        "position": "top"
                    }
                }
            }
        }
    
    def _build_period_comparison_chart(
        self,
        title: str,
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build chart for period-over-period comparison data"""
        # Extract services and their costs for both periods
        services = []
        current_costs = []
        previous_costs = []
        
        for row in data:
            service = row.get("service", "Unknown")
            current_cost = row.get("current_period_cost", 0)
            previous_cost = row.get("previous_period_cost", 0)
            
            services.append(service)
            current_costs.append(current_cost)
            previous_costs.append(previous_cost)
        
        # Get period labels from data
        first_row = data[0] if data else {}
        current_label = f"Current Period ({first_row.get('current_start_date', '')} → {first_row.get('current_end_date', '')})"
        previous_label = f"Previous Period ({first_row.get('previous_start_date', '')} → {first_row.get('previous_end_date', '')})"
        
        datasets = [
            {
                "label": current_label,
                "data": current_costs,
                "backgroundColor": "rgba(59, 130, 246, 0.8)",  # Blue
                "borderColor": "rgb(59, 130, 246)",
                "borderWidth": 1
            },
            {
                "label": previous_label,
                "data": previous_costs,
                "backgroundColor": "rgba(156, 163, 175, 0.8)",  # Gray
                "borderColor": "rgb(156, 163, 175)",
                "borderWidth": 1
            }
        ]
        
        return {
            "type": "bar",
            "title": title,
            "data": {
                "labels": services,
                "datasets": datasets
            },
            "config": {
                "plugins": {
                    "legend": {
                        "display": True,
                        "position": "top"
                    },
                    "tooltip": {
                        "callbacks": {
                            "afterLabel": "(context) => { const idx = context.dataIndex; const change = " + 
                                          str([round((c - p) / p * 100, 1) if p > 0 else 0 
                                               for c, p in zip([row.get("current_period_cost", 0) for row in data],
                                                             [row.get("previous_period_cost", 0) for row in data])]) +
                                          "[idx]; return `Change: ${change}%`; }"
                        }
                    }
                },
                "scales": {
                    "y": {
                        "beginAtZero": True,
                        "title": {
                            "display": True,
                            "text": "Cost (USD)"
                        }
                    },
                    "x": {
                        "title": {
                            "display": True,
                            "text": "Service"
                        }
                    }
                }
            }
        }
    
    
    def _build_pie_chart(
        self,
        title: str,
        x_field: str,
        y_field: str,
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build pie chart"""
        labels = [str(row.get(x_field, "")) for row in data]
        values = [row.get(y_field, 0) for row in data]
        
        # Limit to top 10 for readability
        if len(labels) > 10:
            labels = labels[:10]
            values = values[:10]
        
        colors = [self.color_palette[i % len(self.color_palette)] for i in range(len(labels))]
        
        return {
            "type": "pie",
            "title": title,
            "data": {
                "labels": labels,
                "datasets": [{
                    "data": values,
                    "backgroundColor": colors,
                    "borderColor": [c.replace('0.8', '1.0') for c in colors],
                    "borderWidth": 2
                }]
            },
            "options": {
                "plugins": {
                    "legend": {
                        "position": "right",
                        "labels": {
                            "boxWidth": 12,
                            "padding": 8,
                            "font": {"size": 11}
                        }
                    },
                    "tooltip": {
                        "callbacks": {
                            "label": "function(context) { return context.label + ': $' + context.parsed.toFixed(2); }"
                        }
                    }
                },
                "layout": {
                    "padding": 10
                }
            }
        }
    
    def _build_scatter_chart(
        self,
        title: str,
        x_field: str,
        y_field: str,
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build scatter plot"""
        points = [
            {"x": row.get(x_field, 0), "y": row.get(y_field, 0)}
            for row in data
        ]
        
        return {
            "type": "scatter",
            "title": title,
            "data": {
                "datasets": [{
                    "label": f"{y_field} vs {x_field}",
                    "data": points,
                    "backgroundColor": self.color_palette[0],
                    "borderColor": self.color_palette[0].replace('0.8', '1.0'),
                    "pointRadius": 5,
                    "pointHoverRadius": 7
                }]
            }
        }
    
    def _generate_gradient_colors(self, count: int) -> List[str]:
        """Generate gradient colors for bar charts"""
        if count <= len(self.color_palette):
            return self.color_palette[:count]
        
        # Repeat colors if needed
        colors = []
        for i in range(count):
            colors.append(self.color_palette[i % len(self.color_palette)])
        return colors


# Global instance
chart_data_builder = ChartDataBuilder()
