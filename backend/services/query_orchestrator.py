"""
Query orchestrator - business logic layer.

Coordinates between data sources, handles fallback logic, ARN special cases,
and ensures every query gets answered intelligently.

This is the controller in the MVC pattern - all business logic lives here,
keeping data sources pure and presentation layer focused on formatting.
"""
from typing import Optional, List
import structlog
from backend.services.data_source import DataSource
from backend.services.query_spec import QuerySpec
from backend.services.query_result import QueryResult, ResultMetadata
from backend.agents.intent_classifier import IntentType

logger = structlog.get_logger(__name__)


class QueryOrchestrator:
    """
    Orchestrates query execution with intelligent fallback and business logic.
    
    Responsibilities:
    - Route queries to appropriate data source
    - Handle fallbacks (Athena → Cost Explorer)
    - ARN special handling (direct query → related resources)
    - Apply defaults and business rules
    - Ensure every query gets best possible answer
    
    Does NOT:
    - Know about formatting/presentation
    - Know about frontend requirements
    - Execute queries directly (delegates to data sources)
    """
    
    def __init__(
        self,
        primary_source: DataSource,
        fallback_source: Optional[DataSource] = None
    ):
        """
        Initialize orchestrator with data sources.
        
        Args:
            primary_source: Primary data source (usually Athena)
            fallback_source: Fallback data source (usually Cost Explorer)
        """
        self.primary = primary_source
        self.fallback = fallback_source
    
    async def execute(self, spec: QuerySpec) -> QueryResult:
        """
        Execute query with intelligent fallback logic.
        
        Flow:
        1. Try primary source (Athena)
        2. If empty and ARN query → try related resources
        3. If still empty and fallback-eligible → try Cost Explorer
        4. Return best result found
        
        Args:
            spec: Query specification
            
        Returns:
            QueryResult: Best available result
        """
        logger.info(
            "Orchestrator executing query",
            query_id=spec.query_id,
            intent=spec.intent,
            arn=spec.arn,
            services=spec.services
        )
        
        # Ensure spec has metadata dict
        if not hasattr(spec, 'metadata') or spec.metadata is None:
            spec.metadata = {}
        
        # Apply defaults
        spec = self._apply_defaults(spec)
        
        # 1. Try primary source
        result = await self.primary.fetch(spec)
        
        # 2. ARN fallback: if ARN query returned nothing, search for related resources
        if result.is_empty and spec.arn and result.succeeded:
            logger.info(
                "ARN query returned no results, trying related resources",
                arn=spec.arn,
                query_id=spec.query_id
            )
            
            related_spec = self._create_related_resources_spec(spec)
            related_result = await self.primary.fetch(related_spec)
            
            if related_result.has_data:
                logger.info(
                    "Found related resources",
                    count=related_result.row_count,
                    total_cost=related_result.total_cost
                )
                # Mark as fallback result
                related_result.metadata.arn_fallback = True
                related_result.metadata.original_arn = spec.arn
                result = related_result
        
        # 3. Cost Explorer fallback: if still empty and query is eligible
        if result.is_empty and self.fallback and self._should_use_fallback(spec):
            logger.info(
                "Primary source returned no data, trying fallback source",
                primary=self.primary.get_name(),
                fallback=self.fallback.get_name(),
                query_id=spec.query_id
            )
            
            fallback_result = await self.fallback.fetch(spec)
            
            if fallback_result.has_data:
                logger.info(
                    "Fallback source returned data",
                    source=self.fallback.get_name(),
                    row_count=fallback_result.row_count,
                    total_cost=fallback_result.total_cost
                )
                result = fallback_result
        
        logger.info(
            "Orchestrator execution complete",
            query_id=spec.query_id,
            has_data=result.has_data,
            row_count=result.row_count,
            data_source=result.metadata.data_source,
            arn_fallback=result.metadata.arn_fallback,
            cost_explorer_fallback=result.metadata.cost_explorer_fallback
        )
        
        return result
    
    def _apply_defaults(self, spec: QuerySpec) -> QuerySpec:
        """
        Apply business defaults to query spec.
        
        Examples:
        - top_n defaults to 5 for TOP_N_RANKING
        - time range defaults to last 30 days if missing
        """
        # Default top_n for ranking queries
        if spec.intent == IntentType.TOP_N_RANKING:
            if "top_n" not in spec.metadata or not spec.metadata.get("top_n"):
                spec.metadata["top_n"] = 5
                logger.info("Applied default top_n=5 for TOP_N_RANKING query")
        
        # Default time range if missing
        if not spec.time_range or not spec.time_range.start_date:
            from datetime import datetime, timedelta
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            
            from backend.services.query_spec import TimeRange
            spec.time_range = TimeRange(
                start_date=start_date,
                end_date=end_date,
                description="last 30 days",
                explicit=False,
                source="default"
            )
            logger.info(
                "Applied default time range",
                start_date=start_date,
                end_date=end_date
            )
        
        return spec
    
    def _should_use_fallback(self, spec: QuerySpec) -> bool:
        """
        Determine if Cost Explorer fallback should be used.
        
        Criteria:
        - High-level summaries only (no specific filters)
        - COST_BREAKDOWN or TOP_N_RANKING intent
        - No ARN (ARN queries not supported by CE)
        - No specific dimensions (only service-level)
        """
        # Don't fallback for ARN queries
        if spec.arn:
            return False
        
        # Only these intents eligible
        if spec.intent not in [IntentType.COST_BREAKDOWN, IntentType.TOP_N_RANKING]:
            return False
        
        # Only if no specific services filter (or just want top services)
        # Cost Explorer can handle "top N services" but not specific service breakdowns
        if spec.services and len(spec.services) > 0:
            # If asking for specific services, don't fallback (need CUR granularity)
            return False
        
        # Only if no specific dimensions (or just 'service')
        if spec.dimensions and spec.dimensions != ["service"]:
            return False
        
        logger.info(
            "Query eligible for Cost Explorer fallback",
            intent=spec.intent,
            services=spec.services,
            dimensions=spec.dimensions
        )
        
        return True
    
    def _create_related_resources_spec(self, spec: QuerySpec) -> QuerySpec:
        """
        Create query spec for finding resources related to an ARN.
        
        For example:
        - ECS cluster ARN → find tasks and services in that cluster
        - VPC ARN → find NAT Gateways, VPN connections, etc.
        """
        from backend.services.query_spec import QuerySpec as QS
        
        # Extract resource type from ARN for context
        resource_type = "resources"
        breakdown_dimension = "resource_type"
        
        if ":cluster/" in spec.arn:
            resource_type = "tasks and services"
            breakdown_dimension = "resource_type"
        elif ":vpc-" in spec.arn or ":vpc/" in spec.arn:
            resource_type = "VPC resources (NAT Gateway, VPN, etc.)"
            breakdown_dimension = "resource_type"
        elif ":securitygroup" in spec.arn or ":sg-" in spec.arn:
            resource_type = "associated resources"
            breakdown_dimension = "resource_type"
        
        # Create new spec for related resources
        related_spec = QS(
            intent=IntentType.COST_BREAKDOWN,
            time_range=spec.time_range,
            dimensions=["resource_type"],  # Group by resource type
            services=spec.services,
            regions=spec.regions,
            accounts=spec.accounts,
            arn=spec.arn,  # Keep ARN to use in query pattern matching
            metadata={
                **spec.metadata,
                "related_resources_query": True,
                "resource_type_explanation": resource_type,
                "breakdown_dimension": breakdown_dimension,
                "breakdown_dimension_label": "Resource Type"
            }
        )
        
        logger.info(
            "Created related resources spec",
            original_arn=spec.arn,
            resource_type=resource_type,
            breakdown_dimension=breakdown_dimension
        )
        
        return related_spec
