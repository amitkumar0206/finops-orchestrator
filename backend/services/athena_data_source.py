"""
Athena data source implementation.

Wraps the existing athena_executor into the unified DataSource interface.
Handles all Athena/CUR queries through a single fetch() method.
"""
from typing import Dict, Any, List
import time
from backend.services.data_source import DataSource, DataSourceError
from backend.services.query_spec import QuerySpec
from backend.services.query_result import QueryResult, ResultMetadata
from backend.services.athena_templates import AthenaCURTemplates
import structlog

logger = structlog.get_logger(__name__)


class AthenaDataSource(DataSource):
    """
    Athena/CUR data source implementation.
    
    This wraps the existing athena query functionality into the unified interface,
    allowing the orchestrator to use it without knowing Athena-specific details.
    """
    
    def __init__(self, athena_executor=None):
        """
        Initialize Athena data source.
        
        Args:
            athena_executor: Existing athena executor (for backward compatibility)
        """
        if athena_executor is None:
            # Import here to avoid circular dependency
            from backend.services.athena_executor import athena_executor as default_executor
            athena_executor = default_executor
        
        self.executor = athena_executor
        self.templates = AthenaCURTemplates()
    
    def get_name(self) -> str:
        """Return data source name."""
        return "athena"
    
    async def health_check(self) -> bool:
        """Check if Athena is available."""
        try:
            # Simple query to check connectivity
            return True  # TODO: Implement actual health check
        except Exception as e:
            logger.warning("Athena health check failed", error=str(e))
            return False
    
    async def fetch(self, spec: QuerySpec) -> QueryResult:
        """
        Execute Athena query and return standardized result.
        
        This is the unified entry point for ALL Athena queries.
        It delegates to the existing executor but wraps the response.
        """
        start_time = time.time()
        
        try:
            logger.info(
                "Athena fetch starting",
                query_id=spec.query_id,
                intent=spec.intent,
                services=spec.services,
                dimensions=spec.dimensions
            )
            
            # Use existing executor - it already handles all query types
            results, sql_query = await self.executor.execute_query_spec(spec)
            
            execution_time_ms = (time.time() - start_time) * 1000
            
            # Build metadata from spec and results
            metadata = ResultMetadata(
                data_source="athena",
                execution_time_ms=execution_time_ms,
                query_id=spec.query_id,
                sql_query=sql_query,
                arn_fallback=spec.metadata.get("arn_fallback", False),
                original_arn=spec.metadata.get("original_arn"),
                breakdown_dimension=spec.metadata.get("breakdown_dimension"),
                breakdown_dimension_label=spec.metadata.get("breakdown_dimension_label"),
                top_service_breakdown=spec.metadata.get("top_service_breakdown"),
                resource_type_explanation=spec.metadata.get("resource_type_explanation"),
                extra=spec.metadata.copy()
            )
            
            # Create standardized result
            result = QueryResult(
                data=results,
                metadata=metadata
            )
            
            logger.info(
                "Athena fetch completed",
                query_id=spec.query_id,
                row_count=result.row_count,
                total_cost=result.total_cost,
                execution_time_ms=execution_time_ms
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "Athena fetch failed",
                query_id=spec.query_id,
                error=str(e),
                error_type=type(e).__name__
            )
            
            # Return error result instead of raising (allows graceful fallback)
            return QueryResult(
                data=[],
                metadata=ResultMetadata(
                    data_source="athena",
                    execution_time_ms=(time.time() - start_time) * 1000,
                    query_id=spec.query_id
                ),
                error=str(e)
            )
