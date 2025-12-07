"""
Enhanced Athena Query Executor - Executes queries using templates and returns structured results
Integrates with AthenaCURTemplates for query generation
"""

import asyncio
import time
import os
from typing import Dict, List, Any, Optional, Tuple
import boto3
from botocore.exceptions import ClientError
import structlog

from backend.config.settings import get_settings
from backend.services.athena_cur_templates import AthenaCURTemplates
from backend.services.service_resolver import ServiceResolver, ResolutionResult
from backend.agents.intent_classifier import IntentType
from backend.models.schemas import AgentType
from backend.utils.date_parser import date_parser

logger = structlog.get_logger(__name__)
settings = get_settings()

# Service name mapping: User-friendly names -> CUR line_item_product_code values
# This is critical for CloudWatch and other services where user says "CloudWatch" 
# but CUR uses "CloudWatch" (not "AmazonCloudWatch")
SERVICE_NAME_TO_PRODUCT_CODE = {
    # CloudWatch services
    "amazoncloudwatch": "AmazonCloudWatch",
    "cloudwatch": "AmazonCloudWatch",
    "amazon cloudwatch": "AmazonCloudWatch",
    
    # EC2 and compute
    "amazonec2": "AmazonEC2",
    "ec2": "AmazonEC2",
    "amazon ec2": "AmazonEC2",
    "elastic compute cloud": "AmazonEC2",
    
    # S3 storage
    "amazons3": "AmazonS3",
    "s3": "AmazonS3",
    "amazon s3": "AmazonS3",
    "simple storage service": "AmazonS3",
    
    # RDS
    "amazonrds": "AmazonRDS",
    "rds": "AmazonRDS",
    "amazon rds": "AmazonRDS",
    "relational database service": "AmazonRDS",
    
    # Lambda
    "awslambda": "AWSLambda",
    "lambda": "AWSLambda",
    "aws lambda": "AWSLambda",
    
    # DynamoDB
    "amazondynamodb": "AmazonDynamoDB",
    "dynamodb": "AmazonDynamoDB",
    "amazon dynamodb": "AmazonDynamoDB",
    
    # CloudFront
    "amazoncloudfront": "AmazonCloudFront",
    "cloudfront": "AmazonCloudFront",
    "amazon cloudfront": "AmazonCloudFront",
    
    # ECS
    "amazonecs": "AmazonECS",
    "ecs": "AmazonECS",
    "amazon ecs": "AmazonECS",
    "elastic container service": "AmazonECS",
    
    # EKS
    "amazoneks": "AmazonEKS",
    "eks": "AmazonEKS",
    "amazon eks": "AmazonEKS",
    
    # VPC
    "amazonvpc": "AmazonVPC",
    "vpc": "AmazonVPC",
    "amazon vpc": "AmazonVPC",
    "virtual private cloud": "AmazonVPC",
    "amazonvirtualprivatecloud": "AmazonVPC",
    
    # Route53
    "amazonroute53": "AmazonRoute53",
    "route53": "AmazonRoute53",
    "route 53": "AmazonRoute53",
    
    # SNS
    "amazonsns": "AmazonSNS",
    "sns": "AmazonSNS",
    "simple notification service": "AmazonSNS",
    
    # SQS
    "amazonsqs": "AmazonSQS",
    "sqs": "AmazonSQS",
    "simple queue service": "AmazonSQS",
    
    # Kinesis
    "amazonkinesis": "AmazonKinesis",
    "kinesis": "AmazonKinesis",
    
    # Athena
    "amazonathena": "AmazonAthena",
    "athena": "AmazonAthena",
    
    # Glue
    "awsglue": "AWSGlue",
    "glue": "AWSGlue",
    
    # Default: pass through as-is
}


class EnhancedAthenaQueryExecutor:
    """
    Execute Athena queries against CUR data with template-based query generation.
    Handles query execution, result retrieval, and error management.
    """
    
    def __init__(self):
        """Initialize Athena clients and templates with connection pooling"""
        try:
            # Configure boto3 with retry logic
            from botocore.config import Config
            
            retry_config = Config(
                region_name=settings.aws_region,
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'  # Adaptive retry mode for better handling of throttling
                },
                max_pool_connections=50  # Connection pooling
            )
            
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                session = boto3.Session(
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                    region_name=settings.aws_region
                )
            else:
                session = boto3.Session(region_name=settings.aws_region)
            
            self.athena_client = session.client('athena', config=retry_config)
            self.s3_client = session.client('s3', config=retry_config)
            
            # Get database and table from settings (with validation)
            self.database = settings.aws_cur_database
            self.table = settings.aws_cur_table
            self.output_location = settings.athena_output_location
            self.workgroup = settings.athena_workgroup
            
            # Initialize templates
            # Legacy CUR uses lowercase column names with underscores
            self.templates = AthenaCURTemplates(self.database, self.table, use_lowercase_columns=True)
            
            logger.info(
                "Enhanced Athena Query Executor initialized",
                database=self.database,
                table=self.table,
                output_location=self.output_location,
                workgroup=self.workgroup
            )
            # Initialize service resolver with LLM support (dict + fuzzy + LLM fallback)
            from services.llm_service import llm_service
            self._service_resolver = ServiceResolver(SERVICE_NAME_TO_PRODUCT_CODE, llm_service=llm_service)
            self._cur_codes_loaded = False
            self._cur_codes_last_loaded = 0.0
            
        except Exception as e:
            logger.error(f"Failed to initialize Athena executor: {e}", exc_info=True)
            self.athena_client = None
            self.s3_client = None
            self.templates = None
    
    async def execute_query_for_intent(
        self,
        intent: str,
        extracted_params: Dict[str, Any],
        query_text: str = ""
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Deprecated: prefer execute_query_spec(QuerySpec)."""
        """
        Execute appropriate query based on intent and parameters.
        
        Args:
            intent: Classified query intent
            extracted_params: Extracted parameters (time_range, services, etc.)
            query_text: Original query text for context
            
        Returns:
            Tuple of (results_list, sql_query_used)
        """
        if not self.athena_client or not self.templates:
            logger.error(
                "DIAGNOSTIC CRITICAL: Athena client or templates not initialized - returning mock data",
                athena_client_present=bool(self.athena_client),
                templates_present=bool(self.templates),
                database=getattr(self, 'database', 'unknown'),
                table=getattr(self, 'table', 'unknown')
            )
            return self._generate_mock_data(intent, extracted_params), "-- Mock query --"
        
        try:
            # Calculate date range
            start_date, end_date = self._resolve_date_range(extracted_params)
            
            # Check if we should use Cost Explorer for long time ranges
            from datetime import date
            if isinstance(start_date, str):
                from datetime import datetime
                start_date_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            else:
                start_date_dt = start_date
            
            if isinstance(end_date, str):
                from datetime import datetime
                end_date_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
            else:
                end_date_dt = end_date
            
            days_range = (end_date_dt - start_date_dt).days
            
            # IMPORTANT: ALWAYS use Athena (CUR) for all queries
            # Cost Explorer fallback removed per Task 2.2 - it was causing:
            # 1. "AWS Cost Explorer" appearing as a cost driver (API usage fees)
            # 2. Missing account-level details
            # 3. Incorrect data for service breakdowns
            from backend.agents.intent_classifier import IntentType
            
            logger.info(
                "Using Athena (CUR) for query",
                days_range=days_range,
                intent=intent
            )
            
            # Generate SQL based on intent
            sql_query = self._generate_sql_for_intent(
                intent,
                extracted_params,
                start_date,
                end_date,
                query_text
            )
            
            if not sql_query:
                logger.error(f"Could not generate SQL for intent: {intent}")
                return [], ""
            
            logger.info(
                "Executing Athena query",
                intent=intent,
                start_date=start_date,
                end_date=end_date,
                query_length=len(sql_query)
            )
            
            # Execute query
            results = await self._execute_athena_query(sql_query)
            
            # Filter out meta-services (services that are not actual infrastructure)
            # These include Cost Explorer API usage fees, Support charges, etc.
            if results:
                meta_services = {"aws cost explorer", "cost explorer", "support"}
                before_count = len(results)
                results = [
                    r for r in results
                    if not (r.get("service") and r["service"].lower() in meta_services)
                ]
                if len(results) < before_count:
                    logger.info(
                        "Filtered out meta-services from results",
                        removed_count=before_count - len(results),
                        meta_services=list(meta_services)
                    )
            
            # If Athena query failed or returned no results, log and return empty
            if not results or len(results) == 0:
                logger.error(
                    "Athena query returned no results",
                    intent=intent,
                    start_date=start_date,
                    end_date=end_date,
                    sql_preview=sql_query[:500] if sql_query else None
                )
                # Return empty results - do NOT fall back to Cost Explorer
                return [], sql_query or ""

            # ARN Fallback: If ARN query returned no results, search for related resources
            if (extracted_params.get("dimensions") and "arn" in extracted_params.get("dimensions", []) 
                and (not results or len(results) == 0)):
                
                arn_val = extracted_params.get("arn")
                if arn_val:
                    logger.warning(
                        "ARN returned no direct cost data, searching for related resources",
                        arn=arn_val
                    )
                    
                    # Generate fallback query for related resources
                    fallback_query = self.templates.find_related_resources_by_arn_pattern(
                        start_date=start_date,
                        end_date=end_date,
                        arn=arn_val
                    )
                    
                    # Execute fallback query
                    results = await self._execute_athena_query(fallback_query)
                    sql_query = fallback_query  # Update SQL for logging
                    
                    # Add metadata to indicate fallback was used
                    if "metadata" not in extracted_params:
                        extracted_params["metadata"] = {}
                    
                    # Extract resource type from ARN for better explanation
                    resource_type = "resources"
                    breakdown_dimension = "resource_type"  # Default dimension for charts
                    
                    if ":cluster/" in arn_val:
                        resource_type = "tasks and services"
                        breakdown_dimension = "resource_type"  # Group by resource type for pie chart
                    elif ":vpc-" in arn_val or ":vpc/" in arn_val:
                        resource_type = "resources (the VPC itself is free - costs from NAT Gateway, VPN, etc.)"
                        breakdown_dimension = "resource_type"
                    elif ":securitygroup" in arn_val or ":sg-" in arn_val:
                        resource_type = "associated resources (security groups are free)"
                        breakdown_dimension = "resource_type"
                    
                    extracted_params["metadata"]["arn_fallback"] = True
                    extracted_params["metadata"]["original_arn"] = arn_val
                    extracted_params["metadata"]["resource_type_explanation"] = resource_type
                    extracted_params["metadata"]["breakdown_dimension"] = breakdown_dimension
                    extracted_params["metadata"]["breakdown_dimension_label_override"] = "Resource Type"
                    extracted_params["metadata"]["fallback_message"] = (
                        f"The ARN you specified doesn't generate direct costs. "
                        f"Showing related {resource_type} with costs:"
                    )
                    
                    logger.info(
                        "ARN fallback query executed",
                        related_resources_found=len(results)
                    )
            
            # DIAGNOSTIC LOGGING: Log SQL and result summary for production debugging
            cost_fields = ["cost_usd", "total_cost", "cost", "unblended_cost", "effective_cost"]
            total_from_results = 0
            for row in results:
                for field in cost_fields:
                    if field in row and row[field] is not None:
                        try:
                            total_from_results += float(row[field])
                        except (ValueError, TypeError):
                            pass
            
            logger.info(
                "DIAGNOSTIC: Query execution completed",
                intent=intent,
                results_count=len(results),
                computed_total_cost=round(total_from_results, 2),
                first_3_rows=results[:3] if results else [],
                sql_query_preview=sql_query[:500] if sql_query else ""
            )
            # END DIAGNOSTIC LOGGING
            
            logger.info(f"Query returned {len(results)} results")
            
            # Store params used for context
            extracted_params["start_date"] = start_date
            extracted_params["end_date"] = end_date
            
            return results, sql_query
            
        except Exception as e:
            logger.error(f"Error executing query for intent {intent}: {e}", exc_info=True)
            return [], ""
    
    # Cost Explorer fallback removed - Athena is the single source of truth
    # If Athena fails, we return empty results rather than inconsistent CE data
    
    def _generate_sql_for_intent(
        self,
        intent: str,
        params: Dict[str, Any],
        start_date: str,
        end_date: str,
        query_text: str
    ) -> Optional[str]:
        """Generate SQL query based on intent.
        
        ARCHITECTURAL NOTE - LLM-First Approach:
        This method prioritizes LLM-extracted parameters from UPS (Universal Parameter Schema)
        over hardcoded pattern matching. The LLM extracts structured data including:
        - dimensions: what to group/break down by (service, region, account, etc.)
        - services/regions/accounts: specific filters
        - top_n: ranking count
        - aggregation: how to aggregate data
        
        Hardcoded pattern matching (checking query_lower) is used only as:
        1. Fallback for edge cases the LLM might miss
        2. Legacy compatibility during transition
        3. Specific domain logic (e.g., "week" triggers weekly breakdown)
        
        Preference: Check params (LLM-extracted) BEFORE query_lower patterns.
        """
        query_lower = (query_text or "").lower()
        instance_types = params.get("instance_types") or []
        
        # ARN propagation fallback: if query contains ARN pattern but dimensions is empty, inject ARN dimension
        # This handles UPS→executor dimension loss observed in ECS/RDS queries
        import re
        arn_pattern = re.compile(r'arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[^\s]+')
        dimensions = params.get("dimensions") or []
        if not dimensions and arn_pattern.search(query_text or ""):
            match = arn_pattern.search(query_text)
            if match:
                arn_value = match.group(0)
                params["dimensions"] = ["arn"]
                params["arn"] = arn_value
                logger.info(
                    "UPS→executor ARN propagation: detected ARN in query text, setting dimensions=['arn']",
                    arn=arn_value,
                    query_snippet=query_text[:80]
                )
        
        # Handle data transfer requests regardless of classified intent
        if "data transfer" in query_lower:
            min_cost = 10000 if any(keyword in query_lower for keyword in [">10k", ">$10k", "greater than 10k", "over 10k"]) else 0
            return self.templates.data_transfer_by_region(start_date, end_date, min_cost)
        
        if intent == IntentType.TOP_N_RANKING:
            # Top N services or days
            # No default - require explicit top_n from UPS extraction
            top_n = params.get("top_n")
            if not top_n:
                raise ValueError(
                    "TOP_N_RANKING query requires explicit number (e.g., 'top 5', 'top 10'). "
                    "Please specify how many results you'd like to see."
                )
            dimension = params.get("dimension")
            exclude = params.get("exclude_services")
            exclude_types = params.get("exclude_charge_types")
            include_types = params.get("include_charge_types")
            include_services = params.get("services")  # Filter to specific services if provided
            
            # Extract advanced filter parameters
            purchase_options = params.get("purchase_options")
            tags = params.get("tags")
            platforms = params.get("platforms")
            database_engines = params.get("database_engines")
            
            if dimension == "day":
                # Top N days by cost
                return self.templates.top_n_days(start_date, end_date, top_n, exclude_types)
            else:
                # Top N services (default)
                return self.templates.top_n_services(
                    start_date, end_date, top_n, exclude, exclude_types, include_services, include_types,
                    purchase_options, tags, platforms, database_engines
                )
        
        elif intent == IntentType.COST_BREAKDOWN:
            # Cost breakdown
            dimensions = params.get("dimensions", [])
            services = params.get("services") or []
            
            if instance_types:
                instance_type = instance_types[0]
                
                if "week" in query_lower or "wow" in query_lower:
                    return self.templates.weekly_breakdown_for_instance_type(start_date, end_date, instance_type)
                
                if "account" in query_lower or "payer" in query_lower or "account" in dimensions:
                    return self.templates.account_drilldown_for_instance_type(start_date, end_date, instance_type)
                
                if "region" in query_lower or "region" in dimensions:
                    return self.templates.region_drilldown_for_instance_type(start_date, end_date, instance_type)
                
                return self.templates.ec2_cost_by_instance_type(start_date, end_date, instance_type)
            
            if "instance_type" in dimensions and not services:
                return self.templates.ec2_cost_by_instance_type(start_date, end_date)
            
            if services:
                # Breakdown for specific service
                service = services[0]
                
                # CRITICAL FIX: Normalize service name to CUR product_code
                # User says "CloudWatch" but CUR uses "CloudWatch" (not "AmazonCloudWatch")
                normalized_service = self._normalize_service_name(service)
                logger.info(
                    "Service breakdown requested",
                    original_service=service,
                    normalized_service=normalized_service,
                    intent=intent
                )
                
                # Extract advanced filter parameters
                purchase_options = params.get("purchase_options")
                tags = params.get("tags")
                platforms = params.get("platforms")
                database_engines = params.get("database_engines")
                include_types = params.get("include_charge_types") or params.get("include_line_item_types")
                exclude_types = params.get("exclude_charge_types") or params.get("exclude_line_item_types")
                
                # If the query explicitly asks for ARN grouping, honor it even if UPS missed
                if (not dimensions or dimensions[0] != "arn") and (" arn" in f" {query_lower}" or "by arn" in query_lower or "grouping by arn" in query_lower):
                    logger.info(
                        "Overriding dimensions to ['arn'] based on query wording",
                        query=query_lower
                    )
                    dimensions = ["arn"]
                dimension, inferred = self._determine_service_breakdown_dimension(normalized_service, dimensions, query_lower)
                
                # If dimension is None, ask for clarification rather than defaulting
                if dimension is None:
                    logger.warning(
                        "No breakdown dimension provided for COST_BREAKDOWN; asking for clarification",
                        service=normalized_service
                    )
                    raise ValueError(
                        "Ambiguous breakdown: please specify a dimension (e.g., by region, by account, by instance type, by ARN)."
                    )
                
                logger.info(
                    "Dimension determined for service breakdown",
                    service=normalized_service,
                    dimension=dimension,
                    inferred=inferred
                )

                # Preserve breakdown metadata for downstream formatting/explanations
                metadata = params.setdefault("metadata", {})  # Reuse existing metadata container if present
                metadata["breakdown_service"] = normalized_service  # Use normalized name
                metadata["breakdown_dimension"] = dimension
                if inferred:
                    metadata["breakdown_dimension_inferred"] = True

                # If ARN breakdown requested, query directly by line_item_resource_id
                if dimension == "arn":
                    arn_val = params.get("arn")
                    if not arn_val:
                        raise ValueError("Please provide the specific ARN to query.")
                    
                    # Query CUR data directly using line_item_resource_id
                    # This works without any resource inventory or ARN resolver
                    # NOTE: Don't pass service filter - ARN is already unique identifier
                    logger.info(
                        "ARN breakdown: querying CUR by line_item_resource_id",
                        arn=arn_val
                    )
                    
                    # Store ARN metadata for fallback handling after execution
                    metadata["queried_arn"] = arn_val
                    metadata["arn_query_dates"] = {"start": start_date, "end": end_date}
                    
                    return self.templates.resource_cost_by_arn(
                        start_date=start_date,
                        end_date=end_date,
                        resource_id=arn_val,
                        service=None,  # Don't filter by service - ARN is unique
                        group_by_day=False
                    )
                else:
                    return self.templates.service_cost_breakdown(
                        start_date, end_date, normalized_service, dimension, include_types,
                        purchase_options, tags, platforms, database_engines
                    )
            
            # No explicit service - default to top services breakdown
            logger.warning(
                "No services specified for COST_BREAKDOWN intent - falling back to top services",
                intent=intent,
                params_services=params.get("services"),
                query=query_lower[:100]
            )
            # No default - if top_n specified, use it; otherwise show all services
            top_n = params.get("top_n")
            # For COST_TREND, top_n is optional - None means show all services in trend
            exclude = params.get("exclude_services")
            exclude_types = params.get("exclude_charge_types")
            include_types = params.get("include_charge_types")
            include_services = params.get("services")  # Filter to specific services if provided
            
            # Extract advanced filter parameters
            purchase_options = params.get("purchase_options")
            tags = params.get("tags")
            platforms = params.get("platforms")
            database_engines = params.get("database_engines")
            
            return self.templates.top_n_services(
                start_date, end_date, top_n, exclude, exclude_types, include_services, include_types,
                purchase_options, tags, platforms, database_engines
            )
        
        elif intent == IntentType.OPTIMIZATION:
            # Check if this is a general optimization request or specific RI/SP request
            is_ri_sp_specific = any(term in query_lower for term in ["reserved", "ri", "savings plan", "sp", "commitment"])
            
            # Check if user is asking for COST of RIs (spending), not savings opportunity
            is_cost_query = any(term in query_lower for term in ["cost", "spend", "spending", "pay", "paid"])
            
            if is_ri_sp_specific:
                if is_cost_query:
                    # User wants to know how much they are SPENDING on RIs/SPs (fees)
                    # Redirect to top services/breakdown with RI Fee filtering
                    logger.info("Redirecting RI/SP cost query to breakdown with Fee filtering", query=query_lower)
                    
                    # Include RIFee, Fee (for SPs), and potentially DiscountedUsage if they want to see coverage cost
                    # But usually "how much spending on RIs" means the fees.
                    include_types = ['RIFee', 'Fee']
                    
                    return self.templates.top_n_services(
                        start_date, 
                        end_date, 
                        limit=10,
                        include_line_item_types=include_types
                    )
                
                # Specific RI/SP savings projection
                discount = self._infer_savings_discount(query_lower)
                families: List[str] = []
                if instance_types:
                    families = sorted({token.split('.')[0].lower() for token in instance_types})
                elif params.get("services"):
                    # Focus on EC2 if explicitly requested
                    if any("EC2" in service.upper() or "COMPUTE" in service.upper() for service in params["services"]):
                        families = []
                
                return self.templates.ec2_reserved_savings_projection(
                    start_date,
                    end_date,
                    assumed_discount=discount,
                    families=families or None
                )
            else:
                # General optimization analysis
                service = params.get("services")[0] if params.get("services") else None
                
                # Extract advanced filter parameters
                purchase_options = params.get("purchase_options")
                tags = params.get("tags")
                platforms = params.get("platforms")
                database_engines = params.get("database_engines")
                
                return self.templates.cost_optimization_analysis(
                    start_date,
                    end_date,
                    service=service,
                    purchase_options=purchase_options,
                    tags=tags,
                    platforms=platforms,
                    database_engines=database_engines
                )
        
        elif intent == IntentType.COST_TREND:
            # Month-over-month trend
            top_only = params.get("top_n", 6) if "top" in query_lower else None
            
            # Check if LLM extracted dimensions indicating user wants service breakdown
            dimensions = params.get("dimensions", [])
            wants_service_breakdown = any(
                dim.lower() in ["service", "services", "product"] 
                for dim in dimensions
            )
            
            # If user asks for monthly costs with no service filter and no dimension request,
            # return aggregated monthly total instead of service breakdown.
            wants_monthly_total = (
                ("monthly" in query_lower and "comparison" in query_lower) or
                ("monthly" in query_lower and ("cost" in query_lower or "data" in query_lower)) or
                ("month by month" in query_lower) or
                ("monthly costs" in query_lower) or
                ("monthly cost" in query_lower) or
                ("compare" in query_lower and "monthly" in query_lower)
            )
            services_filter = params.get("services")
            
            # Use aggregated total only if: monthly query, no specific services, and no dimension breakdown requested
            if wants_monthly_total and not services_filter and not wants_service_breakdown:
                logger.info("Using aggregated month_over_month_total template for COST_TREND", start=start_date, end=end_date)
                return self.templates.month_over_month_total(start_date, end_date)
            
            # Otherwise give service breakdown, optionally filtered to specific service
            service_param = services_filter[0] if services_filter and len(services_filter) > 0 else None
            if service_param:
                # Normalize service name for CUR data (e.g., EC2 -> AmazonEC2)
                service_param = self._normalize_service_name(service_param)
                logger.info(f"COST_TREND with service filter: {service_param}", start=start_date, end=end_date)
            return self.templates.month_over_month_by_service(start_date, end_date, top_only, service=service_param)

        elif intent == IntentType.COMPARATIVE:
            # Explicit period-over-period comparison (current vs previous)
            # Determine current period boundaries (already normalized as start_date/end_date)
            from datetime import datetime, timedelta, date
            try:
                if isinstance(start_date, str):
                    current_start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
                else:
                    current_start_dt = start_date
                    
                if isinstance(end_date, str):
                    current_end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
                else:
                    current_end_dt = end_date
            except ValueError:
                # Fallback: if parsing fails, just return month-over-month by service
                logger.warning("Invalid dates for COMPARATIVE intent; falling back to COST_TREND", start_date=start_date, end_date=end_date)
                return self.templates.month_over_month_by_service(start_date, end_date, None)

            period_days = (current_end_dt - current_start_dt).days + 1
            
            # For longer periods (>90 days / 3 months), show monthly trend instead of two-period comparison
            # This provides much better visibility into cost patterns over time
            services_filter = params.get("services")
            if period_days > 90:
                logger.info(
                    "Using monthly trend for COMPARATIVE (period > 90 days)",
                    period_days=period_days,
                    start_date=start_date,
                    end_date=end_date,
                    services=services_filter
                )
                # Return month-by-month breakdown as a line chart
                return self.templates.month_over_month_by_service(
                    start_date=start_date,
                    end_date=end_date,
                    service=services_filter[0] if services_filter else None
                )
            
            previous_end_dt = current_start_dt - timedelta(days=1)
            previous_start_dt = previous_end_dt - timedelta(days=period_days - 1)

            previous_start = previous_start_dt.strftime("%Y-%m-%d")
            previous_end = previous_end_dt.strftime("%Y-%m-%d")

            top_n = params.get("top_n", 5)
            services_filter = params.get("services")
            
            # CRITICAL: Normalize service names (e.g., "S3" -> "AmazonS3", "Lambda" -> "AWSLambda")
            normalized_services = None
            if services_filter:
                normalized_services = [self._normalize_service_name(s) for s in services_filter]
                logger.info(
                    "Normalized service names for COMPARATIVE",
                    original_services=services_filter,
                    normalized_services=normalized_services
                )

            # Extract Phase 2 advanced filters
            purchase_options = params.get("purchase_options")
            tags = params.get("tags")
            platforms = params.get("platforms")
            database_engines = params.get("database_engines")
            exclude_line_item_types = params.get("exclude_charge_types")
            include_line_item_types = params.get("include_charge_types")

            logger.info(
                "Generating period-over-period comparison SQL",
                current_start=start_date,
                current_end=end_date,
                previous_start=previous_start,
                previous_end=previous_end,
                period_days=period_days,
                top_n=top_n,
                services=normalized_services or services_filter,
                purchase_options=purchase_options,
                platforms=platforms,
                tags=tags
            )

            return self.templates.period_over_period_comparison(
                current_start=start_date,
                current_end=end_date,
                previous_start=previous_start,
                previous_end=previous_end,
                top_n=top_n,
                services=normalized_services or services_filter,
                purchase_options=purchase_options,
                tags=tags,
                platforms=platforms,
                database_engines=database_engines,
                exclude_line_item_types=exclude_line_item_types,
                include_line_item_types=include_line_item_types
            )
        
        elif intent == IntentType.ANOMALY_ANALYSIS:
            # Anomaly detection
            service = params.get("services")[0] if params.get("services") else None
            return self.templates.daily_anomaly_detection(start_date, end_date, service)
        
        elif intent == IntentType.GOVERNANCE:
            # Governance checks
            if "untagged" in query_text.lower():
                tag_key = params.get("tags", {}).keys() if params.get("tags") else ["Environment"]
                tag_key = list(tag_key)[0] if tag_key else "Environment"
                return self.templates.top_untagged_resources(start_date, end_date, tag_key, 10)
        
        elif intent == IntentType.DATA_METADATA:
            # CUR metadata
            return self.templates.cur_record_count_by_day(start_date, end_date)
        
        # Default fallback
        logger.warning(f"No specific template for intent {intent}, using top services")
        return self.templates.top_n_services(start_date, end_date, 5)
    
    def _load_cur_product_codes(self, force: bool = False) -> None:
        """Load distinct product codes from CUR for fuzzy resolution (one-time)."""
        if (self._cur_codes_loaded and not force) or not self.athena_client:
            return
        try:
            sql = f"SELECT DISTINCT line_item_product_code FROM {self.database}.{self.table} WHERE line_item_product_code <> '' LIMIT 5000"
            response = self.athena_client.start_query_execution(
                QueryString=sql,
                QueryExecutionContext={'Database': self.database},
                ResultConfiguration={'OutputLocation': self.output_location}
                # WorkGroup removed - causes "Queries of this type are not supported" errors
            )
            qid = response['QueryExecutionId']
            attempts = 0
            while attempts < 30:
                attempts += 1
                time.sleep(1)
                status = self.athena_client.get_query_execution(QueryExecutionId=qid)['QueryExecution']['Status']['State']
                if status == 'SUCCEEDED':
                    break
                if status in ['FAILED','CANCELLED']:
                    logger.warning("Product code discovery query failed", status=status)
                    return
            if attempts >= 30:
                logger.warning("Timed out waiting for product code discovery query")
                return
            # Fetch results
            results = self.athena_client.get_query_results(QueryExecutionId=qid)
            rows = results.get('ResultSet', {}).get('Rows', [])
            codes = []
            # Skip header row
            for row in rows[1:]:
                data = row.get('Data', [])
                if data and data[0].get('VarCharValue'):
                    codes.append(data[0]['VarCharValue'])
            if codes:
                self._service_resolver.update_product_codes(codes)
                self._cur_codes_loaded = True
                self._cur_codes_last_loaded = time.time()
                logger.info("Loaded CUR product codes for service resolution", count=len(codes))
        except Exception:
            logger.warning("Failed loading CUR product codes", exc_info=True)

    def _normalize_service_name(self, service_name: str) -> str:
        """Resolve user-entered service phrase to a CUR product code using resolver."""
        if not service_name:
            return service_name
        # Lazy load codes
        # Refresh codes every 6 hours or first use
        now = time.time()
        if (not self._cur_codes_loaded) or (now - self._cur_codes_last_loaded > 21600):
            self._load_cur_product_codes(force=True)
        result: ResolutionResult = self._service_resolver.resolve(service_name)
        logger.info(
            "Service resolution",
            original=result.original,
            normalized_key=result.normalized,
            chosen=result.product_code,
            method=result.method,
            confidence=result.confidence,
            top_candidates=result.candidates
        )
        if result.method == 'ambiguous' and result.needs_clarification:
            logger.warning(
                "Ambiguous service phrase requires clarification",
                phrase=service_name,
                candidates=result.candidates
            )
        return result.product_code or service_name

    def _determine_service_breakdown_dimension(
        self,
        service: str,
        dimensions: Optional[List[str]],
        query_lower: str
    ) -> Tuple[str, bool]:
        """
        Determine the most appropriate breakdown dimension for a single-service drilldown.
        
        Returns a tuple of (dimension, inferred) where `inferred` indicates whether the
        dimension was inferred (True) or explicitly requested (False).
        """
        # Normalize service for heuristics
        normalized_service = (service or "").lower()

        # Honor explicit dimension requests first
        if dimensions:
            # EXCEPTION: For CloudWatch, override 'region' to 'usage_type' (CloudWatch is global, no meaningful region breakdown)
            # BUT: Allow 'account' dimension to pass through for account-level cost attribution
            if "cloudwatch" in normalized_service and dimensions[0] == "region":
                logger.info(
                    f"Overriding requested 'region' dimension to 'usage_type' for CloudWatch (global service)",
                    service=service
                )
                return "usage_type", False
            logger.info(
                f"Using explicitly requested dimension for service breakdown",
                service=service,
                dimension=dimensions[0]
            )
            return dimensions[0], False

        query_lower = query_lower or ""

        # Direct keyword hints in the query
        if any(term in query_lower for term in ["account", "payer", "linked account"]):
            logger.info(f"Inferring 'account' dimension from query keywords", service=service)
            return "account", False
        if "usage type" in query_lower or "usage_type" in query_lower or "usage" in query_lower:
            logger.info(f"Inferring 'usage_type' dimension from query keywords", service=service)
            return "usage_type", False
        if any(term in query_lower for term in ["operation", "api", "call", "request"]):
            logger.info(f"Inferring 'operation' dimension from query keywords", service=service)
            return "operation", False

        # Service-specific heuristics
        if "cloudwatch log" in query_lower:
            # User is drilling into CloudWatch logs specifically; show API operations
            logger.info(f"Using 'operation' dimension for CloudWatch Logs drill-down", service=service)
            return "operation", False
        if "cloudwatch" in normalized_service:
            # CloudWatch costs are most meaningful when broken down by usage type (Logs, Metrics, etc.)
            logger.info(
                f"Using 'usage_type' dimension for CloudWatch service breakdown",
                service=service,
                normalized_service=normalized_service
            )
            return "usage_type", True
        if "lambda" in normalized_service:
            logger.info(f"Using 'usage_type' dimension for Lambda service breakdown", service=service)
            return "usage_type", True
        if any(token in normalized_service for token in ["s3", "storage", "glacier"]):
            logger.info(f"Using 'usage_type' dimension for storage service breakdown", service=service)
            return "usage_type", True

        # Default fallback - ASK FOR CLARIFICATION instead of assuming region
        logger.warning(
            f"No explicit dimension for service breakdown - should request clarification",
            service=service
        )
        return None, False
    
    def _infer_savings_discount(self, query_lower: str) -> float:
        """Infer reserved instance discount assumption from query text"""
        # NO DEFAULT - only infer if explicitly mentioned
        discount = None
        
        if "3-year" in query_lower or "3yr" in query_lower:
            discount = 0.6  # deeper discount for 3-year commitments
        elif "1-year" in query_lower or "1yr" in query_lower:
            discount = 0.35
        
        # Only apply payment modifiers if base discount exists
        if discount is not None:
            if "no upfront" in query_lower:
                discount = max(discount - 0.05, 0.2)
            elif "all upfront" in query_lower:
                discount = min(discount + 0.05, 0.7)
            elif "partial upfront" in query_lower:
                discount = min(discount + 0.03, 0.55)
        
        # If no discount mentioned, return None to trigger clarification
        if discount is None:
            logger.warning(
                "Optimization query missing RI discount assumption - should request clarification"
            )
        
        return discount
    
    def _resolve_date_range(self, params: Dict[str, Any]) -> Tuple[str, str]:
        """Resolve date range from parameters - always returns valid dates"""
        # Check for explicit dates in time_range
        time_range = params.get("time_range", {})
        if time_range:
            start_date = time_range.get("start_date")
            end_date = time_range.get("end_date")
            
            if start_date and end_date:
                # DIAGNOSTIC: Log the time range resolution
                logger.info(
                    "DIAGNOSTIC: Resolving date range",
                    start_date=start_date,
                    end_date=end_date,
                    time_range_source=time_range.get("source"),
                    time_range_description=time_range.get("description"),
                    full_time_range=time_range
                )
                logger.info(f"Using explicit date range: {start_date} to {end_date}")
                return start_date, end_date
        
        # Fallback: parse from query or use default (last 30 days)
        # This should never be reached if intent_classifier is working properly
        logger.warning("DIAGNOSTIC: No time range in params, using default last 30 days")
        start_date, end_date, metadata = date_parser._default_last_30_days()
        return start_date, end_date
    
    async def _execute_athena_query(self, sql_query: str) -> List[Dict[str, Any]]:
        """Execute Athena query and wait for results"""
        try:
            # Start query execution WITHOUT WorkGroup to avoid compatibility issues
            # WorkGroups can have restrictive settings that block certain query types
            kwargs = {
                'QueryString': sql_query,
                'QueryExecutionContext': {'Database': self.database},
                'ResultConfiguration': {'OutputLocation': self.output_location}
            }
            # Do NOT use WorkGroup - it's causing "Queries of this type are not supported" errors
            # if getattr(self, 'workgroup', None):
            #     kwargs['WorkGroup'] = self.workgroup
            
            response = self.athena_client.start_query_execution(**kwargs)

            query_execution_id = response['QueryExecutionId']
            logger.info(f"Started Athena query execution: {query_execution_id}")
            
            # Wait for query to complete
            max_attempts = 30
            attempt = 0
            
            while attempt < max_attempts:
                attempt += 1
                await asyncio.sleep(1)  # Wait 1 second between checks
                
                status_response = self.athena_client.get_query_execution(
                    QueryExecutionId=query_execution_id
                )
                
                status = status_response['QueryExecution']['Status']['State']
                
                if status == 'SUCCEEDED':
                    logger.info(f"Query succeeded after {attempt} attempts")
                    break
                elif status in ['FAILED', 'CANCELLED']:
                    reason = status_response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
                    logger.error(f"Query {status}: {reason}")
                    return []
            
            if attempt >= max_attempts:
                logger.error("Query timed out after 30 seconds")
                return []
            
            # Get query results
            results = []
            next_token = None
            
            while True:
                if next_token:
                    result_response = self.athena_client.get_query_results(
                        QueryExecutionId=query_execution_id,
                        NextToken=next_token
                    )
                else:
                    result_response = self.athena_client.get_query_results(
                        QueryExecutionId=query_execution_id
                    )
                
                # Parse results
                rows = result_response['ResultSet']['Rows']
                
                if not results:
                    # First page - extract headers
                    headers = [col['VarCharValue'] for col in rows[0]['Data']]
                    rows = rows[1:]  # Skip header row
                else:
                    headers = list(results[0].keys()) if results else []
                
                # Convert rows to dictionaries
                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(row.get('Data', [])):
                        value = col.get('VarCharValue')
                        # Try to convert to appropriate type
                        if value is not None:
                            try:
                                # Try numeric conversion
                                if '.' in value:
                                    value = float(value)
                                elif value.isdigit():
                                    value = int(value)
                            except (ValueError, AttributeError):
                                pass  # Keep as string
                        row_dict[headers[i]] = value
                    results.append(row_dict)
                
                # Check for more pages
                next_token = result_response.get('NextToken')
                if not next_token:
                    break
            
            return results
            
        except ClientError as e:
            logger.error(f"AWS Client error executing Athena query: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Error executing Athena query: {e}", exc_info=True)
            return []
    
    def _generate_mock_data(self, intent: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate mock data when Athena is unavailable - varies based on time range for realistic testing"""
        logger.warning("Generating mock data - Athena not available")
        
        # Get time range to vary data
        time_range = params.get("time_range", {})
        start_date = time_range.get("start_date", "2025-10-01")
        end_date = time_range.get("end_date", "2025-10-31")
        
        # Calculate number of days in range to scale costs
        from datetime import datetime
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            days = (end - start).days + 1
        except:
            days = 30  # Default
        
        # Scale factor based on time range (longer periods = more cost)
        scale_factor = max(0.5, min(3.0, days / 30.0))
        
        if intent == IntentType.TOP_N_RANKING:
            base_costs = [15234.56, 8912.34, 5678.90, 2345.67, 1567.89]
            return [
                {"rank": 1, "service": "AmazonEC2", "cost_usd": round(base_costs[0] * scale_factor, 2), "pct_of_total": 45.2},
                {"rank": 2, "service": "AmazonS3", "cost_usd": round(base_costs[1] * scale_factor, 2), "pct_of_total": 26.4},
                {"rank": 3, "service": "AmazonRDS", "cost_usd": round(base_costs[2] * scale_factor, 2), "pct_of_total": 16.8},
                {"rank": 4, "service": "AmazonCloudFront", "cost_usd": round(base_costs[3] * scale_factor, 2), "pct_of_total": 7.0},
                {"rank": 5, "service": "AWSDataTransfer", "cost_usd": round(base_costs[4] * scale_factor, 2), "pct_of_total": 4.6},
            ]
        
        elif intent == IntentType.COST_BREAKDOWN:
            base_costs = [4523.12, 3234.56, 2897.34, 2045.89]
            return [
                {"instance_type": "m5.large", "cost_usd": round(base_costs[0] * scale_factor, 2), "pct_of_ec2": 35.6},
                {"instance_type": "t3.medium", "cost_usd": round(base_costs[1] * scale_factor, 2), "pct_of_ec2": 25.5},
                {"instance_type": "c5.xlarge", "cost_usd": round(base_costs[2] * scale_factor, 2), "pct_of_ec2": 22.8},
                {"instance_type": "r5.large", "cost_usd": round(base_costs[3] * scale_factor, 2), "pct_of_ec2": 16.1},
            ]
        
        elif intent == IntentType.COST_TREND:
            return [
                {"month": "2025-07", "service": "AmazonEC2", "cost_usd": round(14234.56 * scale_factor, 2), "mom_change_pct": 5.2},
                {"month": "2025-08", "service": "AmazonEC2", "cost_usd": round(14987.23 * scale_factor, 2), "mom_change_pct": 5.3},
                {"month": "2025-09", "service": "AmazonEC2", "cost_usd": round(15234.56 * scale_factor, 2), "mom_change_pct": 1.6},
            ]
        
        elif intent == IntentType.OPTIMIZATION:
            base_savings = [2870.0, 2135.0, 1680.0]
            return [
                {"family": "m5", "on_demand_cost": round(8200.0 * scale_factor, 2), "ri_equivalent_cost": round(5330.0 * scale_factor, 2), "est_savings_usd": round(base_savings[0] * scale_factor, 2), "est_savings_pct": 35.0},
                {"family": "c6g", "on_demand_cost": round(6100.0 * scale_factor, 2), "ri_equivalent_cost": round(3965.0 * scale_factor, 2), "est_savings_usd": round(base_savings[1] * scale_factor, 2), "est_savings_pct": 35.0},
                {"family": "r6i", "on_demand_cost": round(4800.0 * scale_factor, 2), "ri_equivalent_cost": round(3120.0 * scale_factor, 2), "est_savings_usd": round(base_savings[2] * scale_factor, 2), "est_savings_pct": 35.0},
            ]
        
        else:
            # Default mock data with time range info
            total_cost = round(741.96 * scale_factor, 2)
            return [
                {"category": "Sample Data", "cost_usd": total_cost, "time_range": f"{start_date} to {end_date}", "days": days, "note": "Mock data - Athena unavailable"}
            ]
    
    # ========================================================================
    # CONVENIENCE METHODS FOR MULTI-AGENT WORKFLOW
    # ========================================================================
    
    async def get_top_services(
        self,
        start_date: str,
        end_date: str,
        limit: int = 5
    ) -> tuple[List[Dict[str, Any]], str]:
        """Get top N most expensive services."""
        
        
        results, sql_query = await self.execute_query_for_intent(
            intent=IntentType.TOP_N_RANKING,
            extracted_params={
                "time_range": {"start_date": start_date, "end_date": end_date},
                "top_n": limit  # Fixed: was "limit", should be "top_n"
            }
        )
        return results, sql_query
    
    async def get_service_breakdown(
        self,
        service: str,
        dimension: str,
        start_date: str,
        end_date: str
    ) -> tuple[List[Dict[str, Any]], str]:
        """Get breakdown of a specific service by dimension (region, usage_type, operation)."""
        
        
        results, sql_query = await self.execute_query_for_intent(
            intent=IntentType.COST_BREAKDOWN,
            extracted_params={
                "services": [service],
                "dimensions": [dimension],  # Pass as list, not singular "dimension"
                "time_range": {"start_date": start_date, "end_date": end_date}
            }
        )
        return results, sql_query
    
    async def get_period_comparison(
        self,
        start_date: str,
        end_date: str,
        services: List[str] = None
    ) -> tuple[List[Dict[str, Any]], str]:
        """Compare costs across time periods."""
        
        
        results, sql_query = await self.execute_query_for_intent(
            intent=IntentType.COMPARATIVE,
            extracted_params={
                "services": services or [],
                "time_range": {"start_date": start_date, "end_date": end_date}
            }
        )
        return results, sql_query
    
    async def get_cost_summary(
        self,
        start_date: str,
        end_date: str,
        services: List[str] = None,
        regions: List[str] = None
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Get cost summary with optional filters.
        
        Returns:
            Tuple of (results_list, sql_query_used)
        """
        
        
        params = {
            "time_range": {"start_date": start_date, "end_date": end_date}
        }
        if services:
            params["services"] = services
        if regions:
            params["regions"] = regions
        
        results, sql_query = await self.execute_query_for_intent(
            intent=IntentType.COST_BREAKDOWN,
            extracted_params=params
        )
        return results, sql_query

    async def execute_query_spec(self, spec: "QuerySpec") -> Tuple[List[Dict[str, Any]], str]:
        """Unified entrypoint: execute a query defined by QuerySpec.
        Temporarily maps to legacy intent flow while we migrate callers.
        """
        try:
            from backend.services.query_spec import QuerySpec  # type: ignore
        except Exception:
            QuerySpec = None  # soft import for typing in runtime
        # Log spec context for observability
        if hasattr(spec, "to_log_context"):
            logger.info("Executing QuerySpec", **spec.to_log_context())
        else:
            logger.info("Executing QuerySpec", intent=getattr(spec, "intent", None))
        # Map QuerySpec -> extracted_params for legacy executor
        extracted_params = {
            "time_range": {
                "start_date": spec.time_range.start_date,
                "end_date": spec.time_range.end_date,
                "description": getattr(spec.time_range, "description", None),
                "source": getattr(spec.time_range, "source", None),
            },
            "dimensions": spec.dimensions,
            "services": spec.services,
            "regions": spec.regions,
            "accounts": spec.accounts,
            "arn": spec.arn,
            "metadata": spec.metadata,
        }
        return await self.execute_query_for_intent(spec.intent, extracted_params)


# Global executor instance
athena_executor = EnhancedAthenaQueryExecutor()
