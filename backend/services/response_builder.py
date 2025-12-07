"""
Response builder - presentation layer.

Takes QueryResult and builds unified response for frontend.
Knows nothing about data sources or business logic - purely presentation.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import structlog
from backend.services.query_result import QueryResult
from backend.services.query_spec import QuerySpec

logger = structlog.get_logger(__name__)


@dataclass
class ChartSpec:
    """Specification for chart visualization."""
    type: str  # "column", "line", "pie", "area"
    title: str
    x: str  # X-axis field name
    y: str  # Y-axis field name
    series: Optional[str] = None  # Series field for multi-series charts
    data: List[Dict[str, Any]] = None  # Chart data (may be aggregated)


@dataclass
class UnifiedResponse:
    """
    Unified response format for frontend.
    
    This is the single contract between backend and frontend.
    Frontend only needs to understand this structure.
    """
    summary: str  # Human-readable summary
    data: List[Dict[str, Any]]  # Table data
    charts: List[ChartSpec]  # Chart specifications with data
    suggestions: List[str]  # Follow-up suggestions
    metadata: Dict[str, Any]  # Execution metadata
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "summary": self.summary,
            "data": self.data,
            "charts": [
                {
                    "type": chart.type,
                    "title": chart.title,
                    "x": chart.x,
                    "y": chart.y,
                    "series": chart.series,
                    "data": chart.data
                }
                for chart in self.charts
            ],
            "suggestions": self.suggestions,
            "metadata": self.metadata
        }


class ResponseBuilder:
    """
    Builds unified response from query result.
    
    Coordinates summary generation, chart building, and suggestions.
    """
    
    def __init__(self):
        """Initialize response builder with sub-components."""
        # Lazy import to avoid circular dependencies
        self._summary_generator = None
        self._chart_builder = None
        self._suggestion_generator = None
    
    @property
    def summary_generator(self):
        """Lazy-load summary generator."""
        if self._summary_generator is None:
            from backend.services.response_formatter import ResponseFormatter
            self._summary_generator = ResponseFormatter()
        return self._summary_generator
    
    @property
    def chart_builder(self):
        """Lazy-load chart builder."""
        if self._chart_builder is None:
            from backend.services.chart_recommendation import ChartRecommendationEngine
            from backend.services.chart_data_builder import ChartDataBuilder
            self._chart_builder = {
                "recommendation": ChartRecommendationEngine(),
                "data": ChartDataBuilder()
            }
        return self._chart_builder
    
    def build(
        self,
        result: QueryResult,
        spec: QuerySpec,
        query_text: str
    ) -> UnifiedResponse:
        """
        Build unified response from query result.
        
        Args:
            result: Query result from orchestrator
            spec: Original query spec
            query_text: Original user query text
            
        Returns:
            UnifiedResponse: Complete response ready for frontend
        """
        logger.info(
            "Building unified response",
            query_id=spec.query_id,
            has_data=result.has_data,
            row_count=result.row_count
        )
        
        # Handle empty results
        if not result.has_data:
            return self._build_empty_response(result, spec, query_text)
        
        # Generate summary
        summary = self._generate_summary(result, spec, query_text)
        
        # Build charts
        charts = self._build_charts(result, spec)
        
        # Generate suggestions
        suggestions = self._generate_suggestions(result, spec)
        
        # Build metadata
        metadata = self._build_metadata(result, spec)
        
        response = UnifiedResponse(
            summary=summary,
            data=result.data,
            charts=charts,
            suggestions=suggestions,
            metadata=metadata
        )
        
        logger.info(
            "Unified response built",
            query_id=spec.query_id,
            summary_length=len(summary),
            chart_count=len(charts),
            suggestion_count=len(suggestions)
        )
        
        return response
    
    def _generate_summary(
        self,
        result: QueryResult,
        spec: QuerySpec,
        query_text: str
    ) -> str:
        """Generate human-readable summary."""
        
        # Build parameters for formatter (backwards compatibility)
        extracted_params = {
            "services": spec.services,
            "time_range": {
                "start_date": spec.time_range.start_date,
                "end_date": spec.time_range.end_date,
                "description": getattr(spec.time_range, "description", None),
                "source": getattr(spec.time_range, "source", None)
            },
            "regions": spec.regions,
            "dimensions": spec.dimensions if spec.dimensions else [],
            "dimension": spec.dimensions[0] if spec.dimensions else None,
            "metadata": result.metadata.__dict__
        }
        
        # Use existing formatter
        summary = self.summary_generator.format_response(
            intent=spec.intent,
            query=query_text,
            data_results=result.data,
            extracted_params=extracted_params,
            insights=None,
            chart_data=None,
            metadata={"query_type": self._intent_to_query_type(spec.intent)}
        )
        
        return summary
    
    def _build_charts(
        self,
        result: QueryResult,
        spec: QuerySpec
    ) -> List[ChartSpec]:
        """Build chart specifications."""
        
        # Build parameters for chart engine
        extracted_params = {
            "services": spec.services,
            "time_range": {
                "start_date": spec.time_range.start_date,
                "end_date": spec.time_range.end_date
            },
            "dimension": spec.dimensions[0] if spec.dimensions else None,
            "metadata": result.metadata.__dict__
        }
        
        # Get chart recommendations
        query_type = self._intent_to_query_type(spec.intent)
        chart_specs = self.chart_builder["recommendation"].recommend_charts(
            intent=query_type,
            data_results=result.data,
            extracted_params=extracted_params
        )
        
        # Build chart data
        charts_with_data = self.chart_builder["data"].build_chart_data(
            chart_specs=chart_specs,
            data_results=result.data,
            conv_context=None
        )
        
        # Convert to ChartSpec objects
        charts = []
        for chart in charts_with_data:
            charts.append(ChartSpec(
                type=chart.get("type", "column"),
                title=chart.get("title", "Chart"),
                x=chart.get("x", "dimension_value"),
                y=chart.get("y", "cost_usd"),
                series=chart.get("series"),
                data=chart.get("data", [])
            ))
        
        return charts
    
    def _generate_suggestions(
        self,
        result: QueryResult,
        spec: QuerySpec
    ) -> List[str]:
        """Generate follow-up suggestions."""
        
        # Use existing suggestion logic from formatter
        suggestions = self.summary_generator.get_suggestions()
        
        # Add smart suggestions based on result
        if result.metadata.arn_fallback:
            suggestions.insert(
                0,
                "💡 Tip: Container resources like ECS clusters don't generate direct costs. "
                "Costs come from tasks and services running on them."
            )
        
        if result.metadata.cost_explorer_fallback:
            suggestions.insert(
                0,
                "ℹ️ Note: Showing Cost Explorer data. "
                "For more detailed breakdowns, try querying a specific service."
            )
        
        return suggestions
    
    def _build_metadata(
        self,
        result: QueryResult,
        spec: QuerySpec
    ) -> Dict[str, Any]:
        """Build metadata for response."""
        return {
            "query_id": spec.query_id,
            "data_source": result.metadata.data_source,
            "execution_time_ms": result.metadata.execution_time_ms,
            "row_count": result.row_count,
            "total_cost": result.total_cost,
            "arn_fallback": result.metadata.arn_fallback,
            "cost_explorer_fallback": result.metadata.cost_explorer_fallback,
            "sql_query": result.metadata.sql_query
        }
    
    def _build_empty_response(
        self,
        result: QueryResult,
        spec: QuerySpec,
        query_text: str
    ) -> UnifiedResponse:
        """Build response for empty results."""
        
        # Generate helpful "no data" message
        summary = self._generate_no_data_message(spec)
        
        return UnifiedResponse(
            summary=summary,
            data=[],
            charts=[],
            suggestions=self._get_no_data_suggestions(spec),
            metadata=self._build_metadata(result, spec)
        )
    
    def _generate_no_data_message(self, spec: QuerySpec) -> str:
        """Generate helpful message for no data."""
        
        context = ""
        if spec.arn:
            context = f"The ARN `{spec.arn}` may not generate direct costs, or the resource may not exist."
        elif spec.services:
            context = f"No activity found for {', '.join(spec.services)} in this time period."
        elif spec.time_range:
            desc = getattr(spec.time_range, "description", "this period")
            context = f"No cost data for {desc}."
        else:
            context = "Your query returned no matching cost data."
        
        return f"""Your query returned no matching cost data.

{context}

**This could be because:**

- The resource doesn't generate direct costs (e.g., ECS clusters, VPCs are free)
- The time period has no activity
- The service or resource name may need adjustment
- Data may not be available for this time range

**Try these:**

- Expand to last 30 days for broader visibility
- Check related resources (tasks instead of clusters, NAT Gateways instead of VPCs)
- View overall costs across all services

What would you like to explore?"""
    
    def _get_no_data_suggestions(self, spec: QuerySpec) -> List[str]:
        """Get suggestions for when there's no data."""
        return [
            "Show me my AWS costs for the last 30 days",
            "What are my top 5 most expensive services?",
            "Break down my costs by service"
        ]
    
    def _intent_to_query_type(self, intent: str) -> str:
        """Map intent to query type for backwards compatibility."""
        from backend.agents.intent_classifier import IntentType
        
        mapping = {
            IntentType.COST_TREND: "trend",
            IntentType.TOP_N_RANKING: "top_services",
            IntentType.COST_BREAKDOWN: "breakdown",
            IntentType.COMPARATIVE: "comparison"
        }
        
        return mapping.get(intent, "breakdown")
