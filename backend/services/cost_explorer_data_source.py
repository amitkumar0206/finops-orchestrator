"""
Cost Explorer data source implementation.

Provides fallback data source when Athena is unavailable or returns no results.
"""
from typing import Dict, Any, List
import time
from backend.services.data_source import DataSource
from backend.services.query_spec import QuerySpec
from backend.services.query_result import QueryResult, ResultMetadata
from backend.agents.intent_classifier import IntentType
import structlog

logger = structlog.get_logger(__name__)


class CostExplorerDataSource(DataSource):
    """
    AWS Cost Explorer data source implementation.
    
    Used as fallback when Athena is unavailable or returns no data.
    Only supports high-level cost summaries (not detailed breakdowns).
    """
    
    def __init__(self):
        """Initialize Cost Explorer data source."""
        self.processor = None  # Will be lazy-loaded
    
    def get_name(self) -> str:
        """Return data source name."""
        return "cost_explorer"
    
    async def health_check(self) -> bool:
        """Check if Cost Explorer is available."""
        try:
            return True  # TODO: Implement actual health check
        except Exception as e:
            logger.warning("Cost Explorer health check failed", error=str(e))
            return False
    
    async def fetch(self, spec: QuerySpec) -> QueryResult:
        """
        Execute Cost Explorer query and return standardized result.
        
        Cost Explorer only supports:
        - Top N services (COST_BREAKDOWN, TOP_N_RANKING)
        - Overall cost summaries
        - No ARN queries, no detailed dimensions
        """
        start_time = time.time()
        
        try:
            # Lazy load processor to avoid circular imports
            if self.processor is None:
                from backend.agents.cost_data_processor_agent import CostDataProcessorAgent
                self.processor = CostDataProcessorAgent()
            
            logger.info(
                "Cost Explorer fetch starting",
                query_id=spec.query_id,
                intent=spec.intent,
                services=spec.services
            )
            
            # Check if this query is supported by Cost Explorer
            if not self._is_supported(spec):
                logger.warning(
                    "Query not supported by Cost Explorer",
                    intent=spec.intent,
                    dimensions=spec.dimensions
                )
                return QueryResult(
                    data=[],
                    metadata=ResultMetadata(
                        data_source="cost_explorer",
                        execution_time_ms=(time.time() - start_time) * 1000,
                        query_id=spec.query_id
                    ),
                    error="Cost Explorer does not support this query type"
                )
            
            # Execute query using existing processor
            results = await self.processor.get_service_costs(
                start_date=spec.time_range.start_date,
                end_date=spec.time_range.end_date,
                services=spec.services if spec.services else None
            )
            
            execution_time_ms = (time.time() - start_time) * 1000
            
            # Build metadata
            metadata = ResultMetadata(
                data_source="cost_explorer",
                execution_time_ms=execution_time_ms,
                query_id=spec.query_id,
                cost_explorer_fallback=True,
                extra={"fallback_reason": "athena_unavailable_or_empty"}
            )
            
            # Create standardized result
            result = QueryResult(
                data=results,
                metadata=metadata
            )
            
            logger.info(
                "Cost Explorer fetch completed",
                query_id=spec.query_id,
                row_count=result.row_count,
                total_cost=result.total_cost,
                execution_time_ms=execution_time_ms
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "Cost Explorer fetch failed",
                query_id=spec.query_id,
                error=str(e),
                error_type=type(e).__name__
            )
            
            return QueryResult(
                data=[],
                metadata=ResultMetadata(
                    data_source="cost_explorer",
                    execution_time_ms=(time.time() - start_time) * 1000,
                    query_id=spec.query_id
                ),
                error=str(e)
            )
    
    def _is_supported(self, spec: QuerySpec) -> bool:
        """
        Check if this query is supported by Cost Explorer.
        
        Cost Explorer limitations:
        - No ARN queries
        - No detailed dimensions (usage_type, region, etc.)
        - Only service-level summaries
        """
        # No ARN support
        if spec.arn:
            return False
        
        # No dimension support except 'service'
        if spec.dimensions and spec.dimensions != ["service"]:
            return False
        
        # Only these intents supported
        supported_intents = [
            IntentType.COST_BREAKDOWN,
            IntentType.TOP_N_RANKING,
            IntentType.COST_TREND
        ]
        
        if spec.intent not in supported_intents:
            return False
        
        return True
