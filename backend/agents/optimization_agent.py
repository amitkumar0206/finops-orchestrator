"""
Optimization Agent

Specialized agent for handling optimization-related queries in chat.
Integrates with opportunities data and provides intelligent responses
about cost optimization recommendations.

Uses LLM-based intent classification for robust query understanding,
with keyword fallback when LLM is unavailable.
"""

import structlog
import json
import re
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from uuid import UUID

from backend.config.settings import get_settings
from backend.services.opportunities_service import get_opportunities_service, OpportunitiesService
from backend.models.opportunities import (
    OpportunityFilter,
    OpportunityStatus,
    OpportunityCategory,
    OpportunitySort,
)
from backend.services.llm_service import BedrockLLMService
from backend.utils.pii_masking import mask_query_for_logging, sanitize_exception
from backend.utils.aws_session import create_aws_session
from backend.utils.aws_constants import AwsService

logger = structlog.get_logger(__name__)
settings = get_settings()


# Security: Maximum query length for LLM classification
# Prevents potential abuse and reduces token costs
MAX_QUERY_LENGTH_FOR_LLM = 2000  # characters

# LLM prompt for optimization intent classification
OPTIMIZATION_INTENT_PROMPT = """You are an expert at classifying aasmaa (cloud cost management) queries.

Analyze the user's query and determine:
1. Is this an optimization-related query? (asking about cost savings, recommendations, rightsizing, idle resources, etc.)
2. What optimization categories are relevant?
3. What AWS services are mentioned or implied?
4. Any specific request patterns (top N, details, etc.)

IMPORTANT: Be flexible with user input. Users may:
- Have typos (e.g., "rightsize" vs "rightsizing", "reccomendations" vs "recommendations")
- Use informal language (e.g., "cut costs", "save money", "waste")
- Ask indirectly (e.g., "what should I do about expensive EC2s?")

Categories (use these exact values):
- rightsizing: Queries about oversized/underutilized resources
- idle_resources: Queries about unused/idle/terminated resources
- reserved_instances: Queries about RI purchases/coverage
- savings_plans: Queries about Savings Plans
- storage_optimization: Queries about S3/EBS storage optimization
- spot_instances: Queries about Spot instance usage
- general: General optimization queries not fitting other categories

Services (use standard AWS service names):
EC2, RDS, S3, Lambda, EBS, ELB, ElastiCache, CloudWatch, DynamoDB, etc.

Respond ONLY with a valid JSON object (no markdown, no explanation):
{
  "is_optimization_query": true/false,
  "confidence": 0.0-1.0,
  "categories": ["category1", "category2"],
  "services": ["SERVICE1", "SERVICE2"],
  "limit": null or number (if user asks for "top N"),
  "wants_details": true/false (if user asks for explanations/evidence),
  "wants_top": true/false (if user asks for "top" or "biggest")
}

User Query: """


def _parse_llm_intent_response(response_text: str) -> Optional[Dict[str, Any]]:
    """Parse and validate LLM intent classification response."""
    try:
        # Try to extract JSON from response (in case LLM includes extra text)
        response_text = response_text.strip()

        # Find JSON object in response
        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group()

        data = json.loads(response_text)

        # Validate required fields
        if "is_optimization_query" not in data:
            return None

        # Ensure proper types
        result = {
            "is_optimization_query": bool(data.get("is_optimization_query", False)),
            "confidence": float(data.get("confidence", 0.5)),
            "categories": data.get("categories", []),
            "services": data.get("services", []),
            "limit": data.get("limit"),
            "wants_details": bool(data.get("wants_details", False)),
            "wants_top": bool(data.get("wants_top", False)),
        }

        # Convert category strings to enums where possible
        category_map = {
            "rightsizing": OpportunityCategory.RIGHTSIZING,
            "idle_resources": OpportunityCategory.IDLE_RESOURCES,
            "reserved_instances": OpportunityCategory.RESERVED_INSTANCES,
            "savings_plans": OpportunityCategory.SAVINGS_PLANS,
            "storage_optimization": OpportunityCategory.STORAGE_OPTIMIZATION,
            "spot_instances": OpportunityCategory.SPOT_INSTANCES,
        }

        result["category_enums"] = []
        for cat in result["categories"]:
            cat_lower = cat.lower().replace(" ", "_").replace("-", "_")
            if cat_lower in category_map:
                result["category_enums"].append(category_map[cat_lower])

        return result

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("Failed to parse LLM intent response", error=sanitize_exception(e))
        return None


class OptimizationAgent:
    """
    Agent for handling optimization queries in chat conversations.

    Responsibilities:
    - Detect optimization-related intents
    - Retrieve relevant opportunities from database
    - Generate optimization-focused responses
    - Provide actionable recommendations
    """

    # Keywords that indicate optimization intent
    OPTIMIZATION_KEYWORDS = [
        "optimize", "optimization", "optimise", "optimisation",
        "save", "savings", "reduce", "reduction", "cut",
        "rightsize", "right-size", "rightsizing",
        "recommendation", "recommend", "suggest", "suggestion",
        "opportunity", "opportunities",
        "underutilized", "under-utilized", "underused",
        "idle", "unused", "wasteful", "waste",
        "reserved instance", "ri", "savings plan", "sp",
        "spot instance", "spot",
        "cost reduction", "cost saving",
        "cheaper", "less expensive", "lower cost"
    ]

    # Service-specific optimization intents
    SERVICE_OPTIMIZATION_MAP = {
        "ec2": ["rightsize", "reserved", "spot", "idle", "terminate"],
        "rds": ["rightsize", "reserved", "idle", "aurora", "graviton"],
        "s3": ["lifecycle", "intelligent-tiering", "glacier", "storage class"],
        "lambda": ["memory", "concurrency", "optimize"],
        "ebs": ["unused", "snapshot", "gp3", "io1"],
        "elasticache": ["reserved", "rightsize"],
    }

    def __init__(self, organization_id: Optional[UUID] = None, use_llm_classification: bool = True):
        """Initialize the optimization agent

        Args:
            organization_id: Optional organization ID for multi-tenant scoping
            use_llm_classification: Whether to use LLM for intent classification (default True).
                                   Falls back to keyword matching if LLM unavailable.
        """
        self.organization_id = organization_id
        self.use_llm_classification = use_llm_classification
        self._opp_service: Optional[OpportunitiesService] = None
        self._llm_service: Optional[BedrockLLMService] = None
        self._cached_intent: Optional[Dict[str, Any]] = None  # Cache for current query

    @property
    def opp_service(self) -> OpportunitiesService:
        """Lazy initialization of opportunities service"""
        if self._opp_service is None:
            self._opp_service = get_opportunities_service(self.organization_id)
        return self._opp_service

    @property
    def llm_service(self) -> BedrockLLMService:
        """Lazy initialization of LLM service"""
        if self._llm_service is None:
            self._llm_service = BedrockLLMService()
        return self._llm_service

    async def _classify_with_llm(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Use LLM to classify query intent.

        Args:
            query: User query text

        Returns:
            Parsed intent dict or None if LLM unavailable/failed
        """
        if not self.use_llm_classification:
            return None

        try:
            if not self.llm_service.initialized:
                logger.debug("LLM service not initialized, falling back to keyword matching")
                return None

            # Security: Enforce query length limit to prevent abuse
            if len(query) > MAX_QUERY_LENGTH_FOR_LLM:
                logger.warning(
                    "Query exceeds max length for LLM classification, truncating",
                    original_length=len(query),
                    max_length=MAX_QUERY_LENGTH_FOR_LLM,
                )
                query = query[:MAX_QUERY_LENGTH_FOR_LLM]

            # Build the classification prompt
            messages = [
                {"role": "user", "content": OPTIMIZATION_INTENT_PROMPT + query}
            ]

            # Use low max_tokens since we only need a short JSON response
            context = {"max_tokens": 500, "expect_json": True}

            response = await self.llm_service._invoke_bedrock(messages, context)

            if response:
                parsed = _parse_llm_intent_response(response)
                if parsed:
                    logger.info(
                        "LLM intent classification succeeded",
                        query_preview=mask_query_for_logging(query, max_length=50),
                        is_optimization=parsed["is_optimization_query"],
                        confidence=parsed["confidence"],
                        categories=parsed["categories"]
                    )
                    return parsed

            logger.warning("LLM intent classification returned empty or unparseable response")
            return None

        except Exception as e:
            logger.warning("LLM intent classification failed, falling back to keywords", error=sanitize_exception(e))
            return None

    def is_optimization_query(self, query: str) -> bool:
        """
        Determine if the query is optimization-related using keyword matching.

        This is the synchronous version that uses keyword matching only.
        For LLM-based classification, use is_optimization_query_async.

        Args:
            query: User query text

        Returns:
            True if query is about optimization
        """
        return self._keyword_based_detection(query)

    async def is_optimization_query_async(self, query: str) -> bool:
        """
        Determine if the query is optimization-related using LLM with keyword fallback.

        Args:
            query: User query text

        Returns:
            True if query is about optimization
        """
        # Try LLM classification first
        llm_result = await self._classify_with_llm(query)
        if llm_result:
            self._cached_intent = llm_result  # Cache for later use in extract_optimization_intent
            return llm_result["is_optimization_query"]

        # Fall back to keyword matching
        return self._keyword_based_detection(query)

    def _keyword_based_detection(self, query: str) -> bool:
        """
        Keyword-based optimization query detection (fallback method).

        Args:
            query: User query text

        Returns:
            True if query contains optimization keywords
        """
        query_lower = query.lower()

        # Check for optimization keywords
        for keyword in self.OPTIMIZATION_KEYWORDS:
            if keyword in query_lower:
                return True

        return False

    def extract_optimization_intent(self, query: str) -> Dict[str, Any]:
        """
        Extract optimization intent details from query using keyword matching.

        This is the synchronous version that uses keyword matching only.
        For LLM-based extraction, use extract_optimization_intent_async.

        Args:
            query: User query text

        Returns:
            Dict with intent details (category, service, filters)
        """
        return self._keyword_based_intent_extraction(query)

    async def extract_optimization_intent_async(self, query: str) -> Dict[str, Any]:
        """
        Extract optimization intent details from query using LLM with keyword fallback.

        Args:
            query: User query text

        Returns:
            Dict with intent details (category, service, filters)
        """
        # Check if we have a cached LLM result from is_optimization_query_async
        if self._cached_intent:
            llm_intent = self._cached_intent
            self._cached_intent = None  # Clear cache after use

            return {
                "type": "optimization",
                "categories": llm_intent.get("category_enums", []),
                "services": llm_intent.get("services", []),
                "specifics": [],
                "limit": llm_intent.get("limit"),
                "wants_details": llm_intent.get("wants_details", False),
                "wants_top": llm_intent.get("wants_top", False),
                "llm_confidence": llm_intent.get("confidence", 0.0),
            }

        # Try LLM classification if not cached
        llm_result = await self._classify_with_llm(query)
        if llm_result:
            return {
                "type": "optimization",
                "categories": llm_result.get("category_enums", []),
                "services": llm_result.get("services", []),
                "specifics": [],
                "limit": llm_result.get("limit"),
                "wants_details": llm_result.get("wants_details", False),
                "wants_top": llm_result.get("wants_top", False),
                "llm_confidence": llm_result.get("confidence", 0.0),
            }

        # Fall back to keyword matching
        return self._keyword_based_intent_extraction(query)

    def _keyword_based_intent_extraction(self, query: str) -> Dict[str, Any]:
        """
        Keyword-based optimization intent extraction (fallback method).

        Args:
            query: User query text

        Returns:
            Dict with intent details (category, service, filters)
        """
        query_lower = query.lower()
        intent = {
            "type": "optimization",
            "categories": [],
            "services": [],
            "specifics": [],
            "limit": None,
            "wants_details": False,
            "wants_top": False,
        }

        # Check for top N pattern
        top_match = re.search(r"top\s+(\d+)", query_lower)
        if top_match:
            intent["limit"] = int(top_match.group(1))
            intent["wants_top"] = True

        # Check for detail request
        if any(word in query_lower for word in ["detail", "explain", "how", "why", "evidence", "show me"]):
            intent["wants_details"] = True

        # Detect category from keywords
        category_keywords = {
            OpportunityCategory.RIGHTSIZING: ["rightsize", "rightsizing", "right-size", "right-sizing", "overprovisioned", "downsize"],
            OpportunityCategory.IDLE_RESOURCES: ["idle", "unused", "underutilized", "terminate"],
            OpportunityCategory.RESERVED_INSTANCES: ["reserved", "ri ", "reservation"],
            OpportunityCategory.SAVINGS_PLANS: ["savings plan", "sp "],
            OpportunityCategory.STORAGE_OPTIMIZATION: ["storage", "s3", "ebs", "lifecycle"],
            OpportunityCategory.SPOT_INSTANCES: ["spot instance", "spot"],
        }

        for category, keywords in category_keywords.items():
            if any(kw in query_lower for kw in keywords):
                intent["categories"].append(category)

        # Detect service from keywords
        service_keywords = {
            "EC2": ["ec2", "instance", "compute"],
            "RDS": ["rds", "database", "aurora", "mysql", "postgres"],
            "S3": ["s3", "bucket", "storage"],
            "Lambda": ["lambda", "function", "serverless"],
            "EBS": ["ebs", "volume", "disk"],
            "ELB": ["elb", "load balancer", "alb", "nlb"],
            "ElastiCache": ["elasticache", "redis", "cache"],
            "CloudWatch": ["cloudwatch", "logs", "monitoring"],
        }

        for service, keywords in service_keywords.items():
            if any(kw in query_lower for kw in keywords):
                intent["services"].append(service)

        return intent

    async def get_opportunities_for_query(
        self,
        intent: Dict[str, Any],
        account_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant opportunities based on query intent.

        Args:
            intent: Parsed intent from extract_optimization_intent
            account_ids: Optional account filter

        Returns:
            List of opportunity dictionaries
        """
        # Build filter
        filter_obj = OpportunityFilter(
            statuses=[OpportunityStatus.OPEN],
            account_ids=account_ids,
        )

        if intent.get("categories"):
            filter_obj.categories = intent["categories"]

        if intent.get("services"):
            filter_obj.services = intent["services"]

        # Determine limit
        limit = intent.get("limit", 10) or 10
        if limit > 50:
            limit = 50

        # Query opportunities
        result = self.opp_service.list_opportunities(
            filter=filter_obj,
            sort=OpportunitySort.SAVINGS_DESC,
            page=1,
            page_size=limit,
            include_aggregations=True
        )

        # If user wants details, fetch full details
        opportunities = []
        for summary in result.items:
            if intent.get("wants_details"):
                detail = self.opp_service.get_opportunity(summary.id)
                if detail:
                    opportunities.append(detail.model_dump())
            else:
                opportunities.append(summary.model_dump())

        return opportunities

    def format_opportunities_response(
        self,
        opportunities: List[Dict[str, Any]],
        intent: Dict[str, Any],
        stats: Optional[Dict[str, Any]] = None,
        billing_context: Optional[Dict[str, Any]] = None,
        strategy_mode: str = "default",
    ) -> Dict[str, Any]:
        """
        Format opportunities into a chat response.

        Args:
            opportunities: List of opportunity dicts
            intent: Query intent
            stats: Optional stats summary

        Returns:
            Formatted response dict with message, insights, recommendations
        """
        if not opportunities:
            # Try billing-backed estimated opportunities first
            if billing_context:
                estimated = self._build_estimated_opportunities(intent, billing_context, strategy_mode)
                if estimated:
                    return self._build_estimated_opportunities_response(estimated, billing_context, strategy_mode)

            if strategy_mode in ["strategy", "quick_wins"]:
                return self._build_generic_guidance_response(intent)

            if self._should_return_generic_guidance(intent, stats):
                return self._build_generic_guidance_response(intent)

            return {
                "message": self._no_opportunities_message(intent),
                "summary": "No optimization opportunities found matching your criteria.",
                "insights": [],
                "recommendations": [
                    {
                        "action": "Ingest Latest Signals",
                        "description": "Run the opportunity ingestion to fetch latest recommendations from AWS."
                    }
                ],
                "results": [],
                "metadata": {
                    "type": "optimization",
                    "opportunities_count": 0
                }
            }

        # Calculate totals
        total_savings = sum(
            opp.get("estimated_monthly_savings", 0) or 0
            for opp in opportunities
        )
        annual_savings = total_savings * 12

        # Build summary
        summary = self._build_summary(opportunities, total_savings)

        # Build insights
        insights = self._build_insights(opportunities, total_savings)

        # Build recommendations list
        recommendations = self._build_recommendations(opportunities)

        # Build results table
        results = self._build_results_table(opportunities)

        # Build message
        message = self._build_message(opportunities, intent, total_savings, annual_savings)

        return {
            "message": message,
            "summary": summary,
            "insights": insights,
            "recommendations": recommendations,
            "results": results,
            "metadata": {
                "type": "optimization",
                "opportunities_count": len(opportunities),
                "total_monthly_savings": round(total_savings, 2),
                "total_annual_savings": round(annual_savings, 2),
                "categories": list(set(opp.get("category") for opp in opportunities)),
                "services": list(set(opp.get("service") for opp in opportunities))
            }
        }

    def _should_return_generic_guidance(
        self,
        intent: Dict[str, Any],
        stats: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Return generic guidance when query is broad and no ingestion data exists."""
        if not stats:
            return False

        total_opportunities = None
        if isinstance(stats, dict):
            total_opportunities = stats.get("total_opportunities")
        else:
            total_opportunities = getattr(stats, "total_opportunities", None)

        if total_opportunities != 0:
            return False

        # Broad query = no explicit optimization category filter.
        return not bool(intent.get("categories"))

    def _build_generic_guidance_response(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        """Build a practical fallback response when no signals have been ingested yet."""
        services = intent.get("services") or []
        service_label = f" for {', '.join(services)}" if services else ""

        message = (
            f"I don't see any ingested optimization signals yet{service_label}, "
            "so I can't show account-specific opportunities right now.\n\n"
            "Here are practical best practices you can apply immediately:\n\n"
            f"{self._generic_tips_for_services(services)}\n"
            "Run an ingestion when ready, and I can then rank concrete opportunities by monthly savings."
        )

        recommendations = [
            {
                "action": "Run Opportunity Ingestion",
                "description": "Fetch latest recommendations from AWS Cost Explorer, Trusted Advisor, and Compute Optimizer.",
            },
            {
                "action": "Enable Rightsizing Governance",
                "description": "Set recurring reviews for underutilized compute and storage resources.",
            },
            {
                "action": "Adopt Commitment Strategy",
                "description": "Use Savings Plans or Reserved Instances for steady-state workloads.",
            },
        ]

        return {
            "message": message,
            "summary": "No ingested optimization records found yet. Provided generic optimization guidance.",
            "insights": [
                {
                    "category": "Data Availability",
                    "description": "No optimization signals are currently ingested for this scope, so guidance is based on FinOps best practices.",
                }
            ],
            "recommendations": recommendations,
            "results": [],
            "metadata": {
                "type": "optimization",
                "opportunities_count": 0,
                "response_mode": "generic_guidance",
            },
        }

    def _generic_tips_for_services(self, services: List[str]) -> str:
        """Return concise, service-aware optimization tips."""
        normalized = {s.lower() for s in services}

        if "ec2" in normalized:
            return (
                "1. Right-size EC2 by reviewing CPU/Memory and downshifting underutilized instances.\n"
                "2. Schedule non-production instances to stop outside business hours.\n"
                "3. Purchase Savings Plans/Reserved Instances for baseline EC2 usage.\n"
                "4. Use Spot Instances for fault-tolerant or batch workloads."
            )

        if "rds" in normalized:
            return (
                "1. Right-size RDS instance classes based on utilization and query patterns.\n"
                "2. Enable storage autoscaling and remove over-provisioned IOPS where possible.\n"
                "3. Consider Reserved Instances for always-on production databases.\n"
                "4. Stop or snapshot unused dev/test databases."
            )

        if "s3" in normalized:
            return (
                "1. Apply lifecycle policies to transition infrequently accessed data to cheaper tiers.\n"
                "2. Use Intelligent-Tiering where access patterns are unpredictable.\n"
                "3. Clean up incomplete multipart uploads and orphaned objects.\n"
                "4. Review replication and retention settings to avoid unnecessary duplication."
            )

        return (
            "1. Prioritize rightsizing for consistently underutilized resources.\n"
            "2. Remove idle resources (unused volumes, IPs, snapshots, and old load balancers).\n"
            "3. Use commitment discounts for steady workloads and spot capacity for flexible jobs.\n"
            "4. Set budgets and anomaly alerts to catch waste early."
        )

    def _no_opportunities_message(self, intent: Dict[str, Any]) -> str:
        """Generate message when no opportunities found"""
        filters = []
        if intent.get("categories"):
            filters.append(f"categories: {', '.join(str(c.value) for c in intent['categories'])}")
        if intent.get("services"):
            filters.append(f"services: {', '.join(intent['services'])}")

        filter_text = f" for {' and '.join(filters)}" if filters else ""

        return (
            f"I couldn't find any open optimization opportunities{filter_text}. "
            "This could mean:\n\n"
            "1. **Your infrastructure is already well-optimized** - Great job!\n"
            "2. **Opportunities haven't been ingested yet** - Try running the ingestion to fetch latest recommendations from AWS Cost Explorer, Trusted Advisor, and Compute Optimizer.\n"
            "3. **Your filters are too restrictive** - Try broadening your search.\n\n"
            "Would you like me to show you all available opportunities, or run a fresh ingestion?"
        )

    def _build_summary(self, opportunities: List[Dict], total_savings: float) -> str:
        """Build concise summary"""
        count = len(opportunities)
        services = list(set(opp.get("service") for opp in opportunities))

        return (
            f"Found {count} optimization opportunities across {len(services)} services "
            f"with potential monthly savings of ${total_savings:,.2f}."
        )

    def _build_insights(self, opportunities: List[Dict], total_savings: float) -> List[Dict]:
        """Build structured insights"""
        insights = []

        # Category breakdown
        category_savings = {}
        for opp in opportunities:
            cat = opp.get("category", "other")
            savings = opp.get("estimated_monthly_savings", 0) or 0
            category_savings[cat] = category_savings.get(cat, 0) + savings

        if category_savings:
            top_category = max(category_savings, key=category_savings.get)
            insights.append({
                "category": "Top Optimization Category",
                "description": f"{top_category.replace('_', ' ').title()} accounts for ${category_savings[top_category]:,.2f}/month in potential savings."
            })

        # Service breakdown
        service_savings = {}
        for opp in opportunities:
            svc = opp.get("service", "Unknown")
            savings = opp.get("estimated_monthly_savings", 0) or 0
            service_savings[svc] = service_savings.get(svc, 0) + savings

        if service_savings:
            top_service = max(service_savings, key=service_savings.get)
            insights.append({
                "category": "Top Service",
                "description": f"{top_service} has the highest optimization potential at ${service_savings[top_service]:,.2f}/month."
            })

        # Effort level insight
        low_effort = [opp for opp in opportunities if opp.get("effort_level") == "low"]
        if low_effort:
            low_effort_savings = sum(opp.get("estimated_monthly_savings", 0) or 0 for opp in low_effort)
            insights.append({
                "category": "Quick Wins",
                "description": f"{len(low_effort)} opportunities are low-effort, totaling ${low_effort_savings:,.2f}/month in easy savings."
            })

        return insights

    def _build_recommendations(self, opportunities: List[Dict]) -> List[Dict]:
        """Build structured recommendations"""
        recommendations = []

        # Group by category and pick top from each
        by_category = {}
        for opp in opportunities:
            cat = opp.get("category", "other")
            if cat not in by_category:
                by_category[cat] = opp

        for cat, opp in list(by_category.items())[:3]:
            savings = opp.get("estimated_monthly_savings", 0) or 0
            recommendations.append({
                "action": opp.get("title", f"Optimize {cat}"),
                "description": (
                    f"Save ${savings:,.2f}/month by {opp.get('description', '')[:150]}..."
                    if len(opp.get('description', '')) > 150
                    else f"Save ${savings:,.2f}/month - {opp.get('description', '')}"
                )
            })

        return recommendations

    def _build_results_table(self, opportunities: List[Dict]) -> List[Dict]:
        """Build results table for display"""
        results = []

        for opp in opportunities[:20]:  # Limit to 20 for readability
            results.append({
                "title": opp.get("title", "")[:50],
                "service": opp.get("service", ""),
                "category": opp.get("category", "").replace("_", " ").title(),
                "monthly_savings": f"${opp.get('estimated_monthly_savings', 0):,.2f}",
                "effort": opp.get("effort_level", "").title() if opp.get("effort_level") else "-",
                "status": opp.get("status", "").title()
            })

        return results

    def _build_message(
        self,
        opportunities: List[Dict],
        intent: Dict[str, Any],
        total_savings: float,
        annual_savings: float
    ) -> str:
        """Build the main response message"""
        count = len(opportunities)

        header = f"## Optimization Opportunities ({count} found)\n\n"

        summary = (
            f"I found **{count} optimization opportunities** with potential savings of "
            f"**${total_savings:,.2f}/month** (${annual_savings:,.2f}/year).\n\n"
        )

        # Top opportunities list
        top_list = "### Top Opportunities by Savings\n\n"
        for i, opp in enumerate(opportunities[:5], 1):
            savings = opp.get("estimated_monthly_savings", 0) or 0
            service = opp.get("service", "")
            title = opp.get("title", "")
            effort = opp.get("effort_level", "")

            top_list += (
                f"{i}. **{title}** ({service})\n"
                f"   - Potential savings: ${savings:,.2f}/month\n"
                f"   - Effort: {effort.title() if effort else 'Unknown'}\n\n"
            )

        # Action items
        actions = "\n### Recommended Actions\n\n"
        low_effort = [opp for opp in opportunities if opp.get("effort_level") == "low"]

        if low_effort:
            actions += (
                f"- **Start with {len(low_effort)} low-effort opportunities** for quick wins\n"
            )

        actions += (
            "- Review each opportunity's evidence and implementation steps\n"
            "- Mark opportunities as 'accepted' to track implementation progress\n"
            "- Use 'dismiss' for opportunities that don't apply to your environment\n"
        )

        return header + summary + top_list + actions


    def _detect_strategy_mode(self, query: str) -> str:
        """Detect whether user asked for strategy or low-effort quick wins."""
        q = (query or "").lower()
        if any(kw in q for kw in ["quick win", "quick wins", "low-effort", "low effort", "easy fix", "easy wins"]):
            return "quick_wins"
        if any(kw in q for kw in ["strategy", "strategies", "optimization opportunities", "optimize", "optimization"]):
            return "strategy"
        return "default"

    async def _fetch_recent_billing_context(
        self,
        account_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch top services and EC2 instances from CUR for tailored fallback responses."""
        try:
            athena = create_aws_session().client(AwsService.ATHENA)
            end_date = datetime.utcnow().date()
            one_month_ago = (end_date - timedelta(days=30)).isoformat()
            account_filter = ""
            if account_ids:
                safe_ids = [aid for aid in account_ids if str(aid).isdigit()]
                if safe_ids:
                    quoted_ids = ", ".join(f"'{aid}'" for aid in safe_ids)
                    account_filter = f"AND line_item_usage_account_id IN ({quoted_ids})"

            sql_primary = (
                f"SELECT line_item_product_code AS service,"
                f" ROUND(SUM(line_item_unblended_cost), 2) AS cost_usd"
                f" FROM {settings.aws_cur_database}.{settings.aws_cur_table}"
                f" WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '{one_month_ago}'"
                f" AND line_item_product_code IS NOT NULL"
                f" AND line_item_product_code != ''"
                f" {account_filter}"
                f" GROUP BY 1 ORDER BY cost_usd DESC LIMIT 5"
            )
            sql_fallback = (
                f"SELECT product_product_name AS service,"
                f" ROUND(SUM(line_item_unblended_cost), 2) AS cost_usd"
                f" FROM {settings.aws_cur_database}.{settings.aws_cur_table}"
                f" WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '{one_month_ago}'"
                f" AND product_product_name IS NOT NULL"
                f" AND product_product_name != ''"
                f" {account_filter}"
                f" GROUP BY 1 ORDER BY cost_usd DESC LIMIT 5"
            )
            sql_ec2 = (
                f"SELECT line_item_resource_id AS instance_id,"
                f" MAX(product_instance_type) AS instance_type,"
                f" ROUND(SUM(line_item_unblended_cost), 2) AS cost_usd,"
                f" ROUND(SUM(line_item_usage_amount), 1) AS usage_hours"
                f" FROM {settings.aws_cur_database}.{settings.aws_cur_table}"
                f" WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '{one_month_ago}'"
                f" AND line_item_product_code = 'AmazonEC2'"
                f" AND line_item_line_item_type = 'Usage'"
                f" AND line_item_usage_type LIKE '%BoxUsage%'"
                f" AND line_item_resource_id LIKE 'i-%'"
                f" {account_filter}"
                f" GROUP BY 1 ORDER BY cost_usd DESC LIMIT 10"
            )

            async def _run_svc_query(sql: str) -> list:
                start_resp = athena.start_query_execution(
                    QueryString=sql,
                    QueryExecutionContext={"Database": settings.aws_cur_database},
                    ResultConfiguration={"OutputLocation": settings.athena_output_location},
                )
                qid = start_resp["QueryExecutionId"]
                for _ in range(30):
                    await asyncio.sleep(1)
                    status_resp = athena.get_query_execution(QueryExecutionId=qid)
                    state = status_resp["QueryExecution"]["Status"]["State"]
                    if state == "SUCCEEDED":
                        break
                    if state in ["FAILED", "CANCELLED"]:
                        return []
                else:
                    return []
                results_resp = athena.get_query_results(QueryExecutionId=qid, MaxResults=50)
                rows = results_resp.get("ResultSet", {}).get("Rows", [])
                if len(rows) <= 1:
                    return []
                out = []
                for row in rows[1:]:
                    cols = row.get("Data", [])
                    if len(cols) < 2:
                        continue
                    svc = cols[0].get("VarCharValue", "Unknown")
                    try:
                        cost_val = float(cols[1].get("VarCharValue", "0"))
                    except (TypeError, ValueError):
                        cost_val = 0.0
                    if cost_val > 0:
                        out.append({"service": svc, "cost_usd": round(cost_val, 2)})
                return out

            async def _run_ec2_query(sql: str) -> list:
                try:
                    start_resp = athena.start_query_execution(
                        QueryString=sql,
                        QueryExecutionContext={"Database": settings.aws_cur_database},
                        ResultConfiguration={"OutputLocation": settings.athena_output_location},
                    )
                    qid = start_resp["QueryExecutionId"]
                    for _ in range(30):
                        await asyncio.sleep(1)
                        status_resp = athena.get_query_execution(QueryExecutionId=qid)
                        state = status_resp["QueryExecution"]["Status"]["State"]
                        if state == "SUCCEEDED":
                            break
                        if state in ["FAILED", "CANCELLED"]:
                            return []
                    else:
                        return []
                    results_resp = athena.get_query_results(QueryExecutionId=qid, MaxResults=20)
                    rows = results_resp.get("ResultSet", {}).get("Rows", [])
                    if len(rows) <= 1:
                        return []
                    instances = []
                    for row in rows[1:]:
                        cols = row.get("Data", [])
                        if len(cols) < 3:
                            continue
                        iid = cols[0].get("VarCharValue", "")
                        itype = cols[1].get("VarCharValue", "") if len(cols) > 1 else ""
                        cost_text = cols[2].get("VarCharValue", "0") if len(cols) > 2 else "0"
                        hours_text = cols[3].get("VarCharValue", "0") if len(cols) > 3 else "0"
                        if not iid or not iid.startswith("i-"):
                            continue
                        try:
                            cost_val = float(cost_text)
                        except (TypeError, ValueError):
                            cost_val = 0.0
                        if cost_val <= 0:
                            continue
                        try:
                            hours_val = float(hours_text)
                        except (TypeError, ValueError):
                            hours_val = 0.0
                        instances.append({
                            "instance_id": iid,
                            "instance_type": itype,
                            "cost_usd": round(cost_val, 2),
                            "usage_hours": round(hours_val, 1),
                        })
                    return instances
                except Exception:
                    return []

            parsed = await _run_svc_query(sql_primary)
            if not parsed:
                parsed = await _run_svc_query(sql_fallback)
            if not parsed:
                parsed = self._fetch_cost_explorer_context(end_date - timedelta(days=30), end_date)
            if not parsed:
                return None
            ec2_instances = await _run_ec2_query(sql_ec2)
            return {
                "period": f"{one_month_ago} to {end_date.isoformat()}",
                "top_services": parsed,
                "ec2_instances": ec2_instances,
            }
        except Exception as e:
            logger.warning("Failed to fetch billing context for optimization fallback", error=sanitize_exception(e))
            return None

    def _fetch_cost_explorer_context(self, start_date, end_date) -> list:
        """Fallback billing lookup from AWS Cost Explorer when Athena rows are unavailable."""
        try:
            ce = create_aws_session().client(AwsService.COST_EXPLORER, region_name="us-east-1")
            response = ce.get_cost_and_usage(
                TimePeriod={
                    "Start": start_date.isoformat(),
                    "End": (end_date + timedelta(days=1)).isoformat(),
                },
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            groups = response.get("ResultsByTime") or []
            if not groups:
                return []
            service_totals: Dict[str, float] = {}
            for bucket in groups:
                for grp in bucket.get("Groups", []):
                    key = (grp.get("Keys") or ["Unknown"])[0]
                    amount_text = (((grp.get("Metrics") or {}).get("UnblendedCost") or {}).get("Amount") or "0")
                    try:
                        amount_val = float(amount_text)
                    except (TypeError, ValueError):
                        amount_val = 0.0
                    service_totals[key] = service_totals.get(key, 0.0) + amount_val
            ranked = sorted(service_totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
            return [{"service": n, "cost_usd": round(c, 2)} for n, c in ranked if c > 0]
        except Exception as e:
            logger.warning("Cost Explorer fallback lookup failed", error=sanitize_exception(e))
            return []

    def _build_estimated_opportunities(
        self,
        intent: Dict[str, Any],
        billing_context: Optional[Dict[str, Any]],
        strategy_mode: str,
    ) -> List[Dict[str, Any]]:
        """Create concrete opportunities from billing drivers when ingestion data is absent."""
        if not billing_context:
            return []
        top_services = billing_context.get("top_services", []) or []
        ec2_instances = billing_context.get("ec2_instances", []) or []
        if not top_services and not ec2_instances:
            return []

        non_actionable = ["tax", "credit", "refund", "support", "registrar", "marketplace", "shield advanced"]
        actionable = [
            "ec2", "elastic compute", "rds", "database", "s3", "cloudwatch", "vpc",
            "load balancing", "elb", "lambda", "eks", "ebs", "dynamodb", "elasticache",
            "redshift", "opensearch", "emr", "nat gateway", "route 53",
        ]

        def _is_actionable(name: str) -> bool:
            n = (name or "").lower()
            if any(k in n for k in non_actionable):
                return False
            return any(k in n for k in actionable)

        filtered_actionable = [s for s in top_services if _is_actionable(str(s.get("service", "")))]
        requested = {str(s).lower() for s in (intent.get("services") or [])}
        filtered = []
        for svc in filtered_actionable:
            name = str(svc.get("service", "")).strip()
            if not name:
                continue
            if requested:
                n = name.lower()
                if not any(r in n or n in r for r in requested):
                    continue
            filtered.append(svc)

        if requested and not filtered:
            baseline = 0.0
            if filtered_actionable:
                baseline = max(float(s.get("cost_usd", 0.0) or 0.0) for s in filtered_actionable)
            elif top_services:
                baseline = max(float(s.get("cost_usd", 0.0) or 0.0) for s in top_services)
            baseline = baseline if baseline > 0 else 100.0
            for req in requested:
                normalized = req.upper() if len(req) <= 5 else req.title()
                filtered.append({"service": normalized, "cost_usd": round(baseline, 2)})

        services_to_use = filtered or filtered_actionable or top_services
        positive_costs = [float(s.get("cost_usd", 0.0) or 0.0) for s in services_to_use if float(s.get("cost_usd", 0.0) or 0.0) > 0]
        default_baseline = max(positive_costs) if positive_costs else 100.0

        rgn = getattr(settings, "aws_region", None) or "us-east-1"
        playbook = {
            "amazonec2": [
                ("Schedule non-production EC2 instances (stop nights/weekends)", "scheduling", "low", 0.20, [
                    f"aws ec2 describe-instances --filters 'Name=tag:Environment,Values=dev,test,staging,qa' 'Name=instance-state-name,Values=running' --query 'Reservations[].Instances[].[InstanceId,InstanceType,Tags[?Key==`Name`].Value|[0]]' --output table --region {rgn}",
                    f"aws events put-rule --name StopDevEC2Nightly --schedule-expression 'cron(0 20 ? * MON-FRI *)' --state ENABLED --region {rgn}",
                    f"aws ec2 stop-instances --instance-ids $(aws ec2 describe-instances --filters 'Name=tag:Environment,Values=dev,test,staging' 'Name=instance-state-name,Values=running' --query 'Reservations[].Instances[].InstanceId' --output text --region {rgn}) --region {rgn}",
                ]),
                ("Rightsize underutilized EC2 instances", "rightsizing", "medium", 0.15, [
                    f"aws compute-optimizer get-ec2-instance-recommendations --region {rgn} --query 'instanceRecommendations[].[instanceArn,finding,recommendationOptions[0].instanceType,recommendationOptions[0].estimatedMonthlySavings.value]' --output table",
                    f"aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization --start-time $(date -u -d '-30 days' +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 2592000 --statistics Average --dimensions Name=InstanceId,Value=INSTANCE_ID --region {rgn}",
                    f"aws ec2 stop-instances --instance-ids INSTANCE_ID --region {rgn} && aws ec2 modify-instance-attribute --instance-id INSTANCE_ID --instance-type Value=<SMALLER_TYPE> --region {rgn} && aws ec2 start-instances --instance-ids INSTANCE_ID --region {rgn}",
                ]),
            ],
            "amazonrds": [
                ("Stop non-production RDS instances outside business hours", "scheduling", "low", 0.18, [
                    f"aws rds describe-db-instances --query 'DBInstances[].[DBInstanceIdentifier,DBInstanceClass,DBInstanceStatus,TagList]' --output table --region {rgn}",
                    f"aws rds stop-db-instance --db-instance-identifier DB_INSTANCE_ID --region {rgn}",
                    f"aws events put-rule --name StopDevRDSNightly --schedule-expression 'cron(0 20 ? * MON-FRI *)' --state ENABLED --region {rgn}",
                ]),
                ("Rightsize underutilized RDS instances", "rightsizing", "medium", 0.14, [
                    f"aws compute-optimizer get-rds-database-recommendations --region {rgn} --query 'rdsDBRecommendations[].[resourceArn,finding,recommendationOptions[0].dbInstanceClass,recommendationOptions[0].estimatedMonthlySavings.value]' --output table",
                    f"aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name CPUUtilization --start-time $(date -u -d '-30 days' +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 2592000 --statistics Average --dimensions Name=DBInstanceIdentifier,Value=DB_INSTANCE_ID --region {rgn}",
                    f"aws rds modify-db-instance --db-instance-identifier DB_INSTANCE_ID --db-instance-class db.t3.medium --apply-immediately --region {rgn}",
                ]),
            ],
            "amazons3": [
                ("Apply S3 lifecycle rules to move objects to cheaper storage tiers", "storage_optimization", "low", 0.16, [
                    f"aws s3api list-buckets --query 'Buckets[*].Name' --output text",
                    f"aws s3api put-bucket-lifecycle-configuration --bucket BUCKET_NAME --lifecycle-configuration '{{\"Rules\":[{{\"ID\":\"MoveToIA30d\",\"Status\":\"Enabled\",\"Transitions\":[{{\"Days\":30,\"StorageClass\":\"STANDARD_IA\"}},{{\"Days\":90,\"StorageClass\":\"GLACIER\"}}],\"Filter\":{{\"Prefix\":\"\"}}}}]}}'",
                    f"aws s3api get-bucket-lifecycle-configuration --bucket BUCKET_NAME",
                ]),
                ("Expire stale S3 object versions to cut storage costs", "storage_optimization", "low", 0.10, [
                    f"aws s3api list-bucket-versions --bucket BUCKET_NAME --query 'Versions[?IsLatest==`false`].[Key,VersionId,LastModified,Size]' --output table",
                    f"aws s3api put-bucket-lifecycle-configuration --bucket BUCKET_NAME --lifecycle-configuration '{{\"Rules\":[{{\"ID\":\"ExpireOldVersions\",\"Status\":\"Enabled\",\"NoncurrentVersionExpiration\":{{\"NoncurrentDays\":30}},\"Filter\":{{\"Prefix\":\"\"}}}}]}}'",
                    f"aws s3 ls s3://BUCKET_NAME --recursive --summarize | tail -2",
                ]),
            ],
            "amazoncloudwatch": [
                ("Set CloudWatch log retention policies to reduce log storage costs", "storage_optimization", "low", 0.20, [
                    f"aws logs describe-log-groups --query 'logGroups[?retentionInDays==`null`].[logGroupName,storedBytes]' --output table --region {rgn}",
                    f"aws logs describe-log-groups --query 'logGroups[].logGroupName' --output text --region {rgn} | tr '\\t' '\\n' | xargs -I {{}} aws logs put-retention-policy --log-group-name {{}} --retention-in-days 30 --region {rgn}",
                    f"aws logs describe-log-groups --query 'sort_by(logGroups,&storedBytes)[-5:].[logGroupName,storedBytes,retentionInDays]' --output table --region {rgn}",
                ]),
            ],
            "amazonvpc": [
                ("Identify and remove idle NAT gateways", "architecture", "medium", 0.10, [
                    f"aws ec2 describe-nat-gateways --filter 'Name=state,Values=available' --query 'NatGateways[].[NatGatewayId,SubnetId,State,CreateTime]' --output table --region {rgn}",
                    f"aws cloudwatch get-metric-statistics --namespace AWS/NATGateway --metric-name BytesOutToDestination --start-time $(date -u -d '-30 days' +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 2592000 --statistics Sum --dimensions Name=NatGatewayId,Value=NAT_GW_ID --region {rgn}",
                    f"aws ec2 delete-nat-gateway --nat-gateway-id NAT_GW_ID --region {rgn}  # after confirming BytesOutToDestination=0",
                ]),
            ],
            "awselb": [
                ("Delete idle load balancers with zero traffic", "idle_resources", "low", 0.18, [
                    f"aws elbv2 describe-load-balancers --query 'LoadBalancers[].[LoadBalancerArn,LoadBalancerName,State.Code,CreatedTime]' --output table --region {rgn}",
                    f"aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name RequestCount --start-time $(date -u -d '-30 days' +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 2592000 --statistics Sum --dimensions Name=LoadBalancer,Value=LB_NAME --region {rgn}",
                    f"aws elbv2 delete-load-balancer --load-balancer-arn LB_ARN --region {rgn}  # after confirming RequestCount=0",
                ]),
            ],
            "amazoneks": [
                ("Scale down EKS node groups outside business hours", "scheduling", "medium", 0.12, [
                    f"aws eks list-nodegroups --cluster-name CLUSTER_NAME --region {rgn}",
                    f"aws eks update-nodegroup-config --cluster-name CLUSTER_NAME --nodegroup-name NODEGROUP_NAME --scaling-config minSize=0,maxSize=5,desiredSize=0 --region {rgn}",
                    f"aws events put-rule --name ScaleDownEKSNightly --schedule-expression 'cron(0 20 ? * MON-FRI *)' --state ENABLED --region {rgn}",
                ]),
            ],
            "awslambda": [
                ("Right-size Lambda memory to reduce per-invocation cost", "rightsizing", "low", 0.15, [
                    f"aws lambda list-functions --query 'Functions[].[FunctionName,Runtime,MemorySize,Timeout]' --output table --region {rgn}",
                    f"aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Duration --start-time $(date -u -d '-30 days' +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 2592000 --statistics Average --dimensions Name=FunctionName,Value=FUNCTION_NAME --region {rgn}",
                    f"aws lambda update-function-configuration --function-name FUNCTION_NAME --memory-size 256 --region {rgn}  # reduce if avg duration is well under timeout",
                ]),
            ],
            "default": [
                ("Identify and stop idle non-production resources", "scheduling", "low", 0.10, [
                    f"aws resourcegroupstaggingapi get-resources --tag-filters 'Key=Environment,Values=dev,test,staging' --query 'ResourceTagMappingList[].[ResourceARN]' --output table --region {rgn}",
                    f"aws ec2 describe-instances --filters 'Name=instance-state-name,Values=running' --query 'Reservations[].Instances[].[InstanceId,InstanceType,LaunchTime,Tags[?Key==`Environment`].Value|[0]]' --output table --region {rgn}",
                    f"aws events put-rule --name StopNonProdNightly --schedule-expression 'cron(0 20 ? * MON-FRI *)' --state ENABLED --region {rgn}",
                ]),
                ("Use AWS Compute Optimizer to rightsize underutilized resources", "rightsizing", "medium", 0.12, [
                    f"aws compute-optimizer get-ec2-instance-recommendations --region {rgn} --query 'instanceRecommendations[].[instanceArn,finding,recommendationOptions[0].instanceType,recommendationOptions[0].estimatedMonthlySavings.value]' --output table",
                    f"aws compute-optimizer get-rds-database-recommendations --region {rgn} --query 'rdsDBRecommendations[].[resourceArn,finding,recommendationOptions[0].dbInstanceClass,recommendationOptions[0].estimatedMonthlySavings.value]' --output table",
                    f"aws ce get-rightsizing-recommendation --service AmazonEC2 --query 'RightsizingRecommendations[].[CurrentInstance.ResourceId,RightsizingType,ModifyRecommendationDetail.TargetInstances[0].ResourceDetails.EC2ResourceDetails.InstanceType]' --output table",
                ]),
            ],
        }

        estimated: List[Dict[str, Any]] = []
        max_items = 3 if strategy_mode == "quick_wins" else 5

        ec2_is_relevant = any(
            "ec2" in str(svc.get("service", "")).lower() or
            "amazonec2" in str(svc.get("service", "")).lower().replace(" ", "")
            for svc in services_to_use[:5]
        ) or any("ec2" in s.lower() for s in requested)

        if ec2_instances and ec2_is_relevant:
            region = getattr(settings, "aws_region", None) or "us-east-1"
            for inst in ec2_instances:
                if len(estimated) >= max_items:
                    break
                iid = inst["instance_id"]
                itype = inst.get("instance_type") or "unknown"
                cost = inst["cost_usd"]
                hours = inst.get("usage_hours", 0.0) or 0.0
                util_pct = round((hours / 720.0) * 100.0, 1) if hours > 0 else 0.0
                if hours == 0 or util_pct < 25:
                    title = f"Stop or terminate idle instance {iid} ({itype})"
                    effort = "low"
                    rate = 0.45
                    cat = "idle_resources"
                    steps = [
                        f"aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization --dimensions Name=InstanceId,Value={iid} --start-time $(date -u -v-14d +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 86400 --statistics Average --region {region}",
                        f"aws ec2 stop-instances --instance-ids {iid} --region {region}",
                        f"aws ec2 terminate-instances --instance-ids {iid} --region {region}  # after confirming idle 7+ days",
                    ]
                elif util_pct < 60:
                    title = f"Rightsize {iid} ({itype}) — low utilization"
                    effort = "medium"
                    rate = 0.20
                    cat = "rightsizing"
                    steps = [
                        f"aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization --dimensions Name=InstanceId,Value={iid} --start-time $(date -u -v-14d +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 86400 --statistics Average --region {region}",
                        f"aws ec2 describe-instances --instance-ids {iid} --query 'Reservations[].Instances[].InstanceType' --output text --region {region}",
                        f"aws ec2 stop-instances --instance-ids {iid} --region {region} && aws ec2 modify-instance-attribute --instance-id {iid} --instance-type {{next_smaller_type}} --region {region} && aws ec2 start-instances --instance-ids {iid} --region {region}",
                    ]
                else:
                    title = f"Purchase Savings Plan for {iid} ({itype})"
                    effort = "low"
                    rate = 0.30
                    cat = "commitment_discounts"
                    steps = [
                        "aws ce get-cost-and-usage --time-period Start=$(date -u -v-30d +%Y-%m-%d),End=$(date -u +%Y-%m-%d) --granularity MONTHLY --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE",
                        "aws ce get-savings-plans-coverage --time-period Start=$(date -u -v-30d +%Y-%m-%d),End=$(date -u +%Y-%m-%d) --granularity MONTHLY",
                        "Purchase a Compute Savings Plan via AWS Console → Savings Plans.",
                    ]
                if strategy_mode == "quick_wins" and effort != "low":
                    continue
                savings = round(cost * rate, 2)
                projected = round(max(cost - savings, 0.0), 2)
                estimated.append({
                    "title": title,
                    "service": f"Amazon EC2 ({iid})",
                    "category": cat,
                    "effort_level": effort,
                    "status": "real_instance",
                    "estimated_monthly_savings": savings,
                    "current_monthly_cost": round(cost, 2),
                    "projected_monthly_cost": projected,
                    "savings_percentage": round(rate * 100, 1),
                    "implementation_steps": steps,
                    "description": (
                        f"Instance {iid} ({itype}) costs ${cost:,.2f}/month "
                        f"with ~{util_pct:.1f}% avg CPU utilization. "
                        f"Est. savings: ${savings:,.2f}/month ({rate * 100:.1f}%)."
                    ),
                })
            if estimated:
                return estimated

        playbook_prefix_map = [
            ("ec2", "amazonec2"),
            ("rds", "amazonrds"),
            ("s3", "amazons3"),
            ("cloudwatch", "amazoncloudwatch"),
            ("vpc", "amazonvpc"),
            ("elb", "awselb"),
            ("alb", "awselb"),
            ("load balanc", "awselb"),
            ("eks", "amazoneks"),
            ("lambda", "awslambda"),
            ("serverless", "awslambda"),
        ]

        def _playbook_key(name: str) -> str:
            n = name.lower()
            exact_key = n.replace(" ", "").replace("-", "").replace("_", "")
            if exact_key in playbook:
                return exact_key
            for fragment, pk in playbook_prefix_map:
                if fragment in n:
                    return pk
            return "default"

        for svc in services_to_use:
            if len(estimated) >= max_items:
                break
            service_name = str(svc.get("service", "Unknown"))
            current_cost = float(svc.get("cost_usd", 0.0) or 0.0)
            if current_cost <= 0:
                current_cost = default_baseline
            key = _playbook_key(service_name)
            actions = playbook.get(key, playbook["default"])
            for action_title, category, effort, savings_rate, steps in actions:
                if len(estimated) >= max_items:
                    break
                if strategy_mode == "quick_wins" and effort != "low":
                    continue
                savings = round(current_cost * savings_rate, 2)
                projected = round(max(current_cost - savings, 0.0), 2)
                estimated.append({
                    "title": action_title,
                    "service": service_name,
                    "category": category,
                    "effort_level": effort,
                    "status": "estimated",
                    "estimated_monthly_savings": savings,
                    "current_monthly_cost": round(current_cost, 2),
                    "projected_monthly_cost": projected,
                    "savings_percentage": round(savings_rate * 100, 1),
                    "implementation_steps": steps,
                    "description": (
                        f"Current monthly spend is ${current_cost:,.2f}. "
                        f"Estimated savings: ${savings:,.2f}/month ({savings_rate * 100:.1f}%)."
                    ),
                })
        return estimated

    def _build_estimated_opportunities_response(
        self,
        estimated_opportunities: List[Dict[str, Any]],
        billing_context: Optional[Dict[str, Any]],
        strategy_mode: str,
    ) -> Dict[str, Any]:
        """Render opportunities with real dollar values and AWS CLI steps. No duplicate table."""
        if not estimated_opportunities:
            return self._build_generic_guidance_response({})
        period = (billing_context or {}).get("period", "the latest available billing period")
        total_current = sum(float(o.get("current_monthly_cost", 0.0) or 0.0) for o in estimated_opportunities)
        total_savings = sum(float(o.get("estimated_monthly_savings", 0.0) or 0.0) for o in estimated_opportunities)
        total_projected = max(total_current - total_savings, 0.0)
        summary = (
            f"Identified {len(estimated_opportunities)} optimization opportunities. "
            f"Current monthly spend: ${total_current:,.2f}; projected: ${total_projected:,.2f}; "
            f"estimated savings: ${total_savings:,.2f}/month."
        )
        has_real = any(o.get("status") == "real_instance" for o in estimated_opportunities)
        data_note = (
            " Costs and instance IDs are sourced from your AWS Cost and Usage Report."
            if has_real
            else " Savings estimates are based on industry benchmarks for your service mix."
        )
        lines = [
            f"I prepared an optimization plan from your recent billing profile ({period}).{data_note}",
            "",
            f"Estimated current spend: ${total_current:,.2f}/month",
            f"Estimated projected spend after fixes: ${total_projected:,.2f}/month",
            f"Estimated monthly savings: ${total_savings:,.2f}",
            "",
            "### Priority Opportunities",
            "",
        ]
        for idx, opp in enumerate(estimated_opportunities, 1):
            steps = opp.get("implementation_steps", [])
            first_step = steps[0] if steps else "Review and apply remediation in a controlled rollout"
            lines.extend([
                f"{idx}. **{opp.get('title', 'Optimization action')}** ({opp.get('service', 'Unknown')})",
                f"   - Current: ${float(opp.get('current_monthly_cost', 0.0) or 0.0):,.2f}/month",
                f"   - After fix: ${float(opp.get('projected_monthly_cost', 0.0) or 0.0):,.2f}/month",
                f"   - Savings: ${float(opp.get('estimated_monthly_savings', 0.0) or 0.0):,.2f}/month ({float(opp.get('savings_percentage', 0.0) or 0.0):.1f}%)",
                f"   - First step: `{first_step}`",
                "",
            ])
        message = "\n".join(lines).rstrip()
        results = []
        for opp in estimated_opportunities:
            steps = opp.get("implementation_steps", [])
            results.append({
                "opportunity": opp.get("title", "Optimization action"),
                "service": opp.get("service", "Unknown"),
                "current_monthly_cost": f"${float(opp.get('current_monthly_cost', 0.0) or 0.0):,.2f}",
                "projected_monthly_cost": f"${float(opp.get('projected_monthly_cost', 0.0) or 0.0):,.2f}",
                "monthly_savings": f"${float(opp.get('estimated_monthly_savings', 0.0) or 0.0):,.2f}",
                "savings_percent": f"{float(opp.get('savings_percentage', 0.0) or 0.0):.1f}%",
                "effort": str(opp.get("effort_level", "medium")).title(),
                "steps": " | ".join(steps[:3]) if steps else "Review utilization and apply remediation",
            })
        recommendations = []
        for opp in estimated_opportunities[:3]:
            steps = opp.get("implementation_steps", [])
            recommendations.append({
                "action": opp.get("title", "Optimization action"),
                "description": (
                    f"Now ${float(opp.get('current_monthly_cost', 0.0) or 0.0):,.2f}/month → "
                    f"After: ${float(opp.get('projected_monthly_cost', 0.0) or 0.0):,.2f}/month. "
                    f"Est. savings ${float(opp.get('estimated_monthly_savings', 0.0) or 0.0):,.2f}/month. "
                    f"Next: {steps[0] if steps else 'Apply in phased rollout.'}"
                ),
            })
        return {
            "message": message,
            "summary": summary,
            "insights": [{
                "category": "Data Source",
                "description": (
                    "Costs and instance IDs sourced from your AWS Cost and Usage Report."
                    if has_real
                    else "Savings estimates based on industry benchmarks for your service mix."
                ),
            }],
            "recommendations": recommendations,
            "results": results,
            "metadata": {
                "type": "optimization",
                "opportunities_count": len(estimated_opportunities),
                "total_monthly_savings": round(total_savings, 2),
                "total_annual_savings": round(total_savings * 12, 2),
                "response_mode": "estimated_opportunities",
                "strategy_mode": strategy_mode,
                "period": period,
            },
        }

    def _is_followup_explanation_query(self, query: str) -> bool:
        """Detect follow-up questions asking to explain a recommendation step (not a new plan request)."""
        q = query.lower().strip().rstrip("?")
        explanation_starters = [
            "how does", "how will", "how would", "how can",
            "why should i", "why would i", "what does",
            "explain", "what is the benefit", "what benefit",
            "tell me more about", "more details on", "elaborate on",
        ]
        has_starter = any(q.startswith(p) for p in explanation_starters)
        save_phrases = ["save", "money", "help", "benefit", "matter", "work", "reduce cost"]
        has_save = any(p in q for p in save_phrases)
        return has_starter and has_save and len(q.split()) <= 20

    async def _build_explanation_response(
        self,
        query: str,
        billing_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Use LLM to explain why a specific recommendation saves money."""
        context_str = ""
        if billing_context:
            top = billing_context.get("top_services") or []
            period = billing_context.get("period", "last 30 days")
            context_str = f" The user's top AWS services by cost in {period}: {top[:3]}."
        prompt = (
            f"A user is asking: '{query}'.{context_str}\n\n"
            "Explain concretely how this specific action saves money on AWS — "
            "what AWS pricing mechanism it targets (e.g. On-Demand hourly charges, GB-month storage), "
            "a realistic savings estimate, and give 2-3 specific next steps with actual AWS CLI commands. "
            "Be direct and specific. No generic advice. Under 200 words."
        )
        try:
            messages = [{"role": "user", "content": prompt}]
            response = await self.llm_service._invoke_bedrock(messages, {"max_tokens": 500})
            explanation = (response or "").strip() or None
        except Exception:
            explanation = None

        if not explanation:
            explanation = (
                f"Here is how that saves money:\n\n"
                "AWS On-Demand EC2/RDS instances are billed per-hour while running. "
                "Non-production workloads typically only need to run during business hours (~8h/day, 5 days/week = 40h). "
                "That means stopping them outside those windows eliminates ~65% of their running hours, "
                "cutting that portion of your bill by up to 65%.\n\n"
                "Next steps:\n"
                "1. Tag resources by Environment (dev/test/staging)\n"
                "2. Create EventBridge rules: stop at 20:00, start at 08:00 Mon-Fri\n"
                "3. Monitor the next monthly bill cycle to confirm savings."
            )
        return {
            "message": explanation,
            "results": [],
            "metadata": {"type": "optimization", "response_mode": "explanation"},
            "suggestions": [
                "Show me the EventBridge stop/start schedule commands",
                "How can I optimize my EC2 costs?",
                "What are the low-effort quick wins?",
            ],
        }

    async def process_query(
        self,
        query: str,
        account_ids: Optional[List[str]] = None,
        conversation_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process an optimization-related query.

        Uses LLM-based intent classification for robust understanding of user queries,
        with keyword fallback when LLM is unavailable.

        Args:
            query: User query
            account_ids: Optional account filter
            conversation_context: Previous conversation context

        Returns:
            Response dict with message, insights, recommendations, etc.
        """
        logger.info("Processing optimization query", query_preview=mask_query_for_logging(query))

        # Detect follow-up explanation questions ("how does X save me money?") — answer directly with LLM
        if self._is_followup_explanation_query(query):
            billing_context = await self._fetch_recent_billing_context(account_ids)
            return await self._build_explanation_response(query, billing_context)

        # Extract intent using LLM-based classification (with fallback)
        intent = await self.extract_optimization_intent_async(query)

        logger.debug(
            "Optimization intent extracted",
            categories=[str(c) for c in intent.get("categories", [])],
            services=intent.get("services", []),
            llm_confidence=intent.get("llm_confidence", "N/A (keyword fallback)")
        )

        # Get relevant opportunities
        opportunities = await self.get_opportunities_for_query(intent, account_ids)

        # Get stats if no specific opportunities found
        stats = None
        if not opportunities:
            try:
                stats = self.opp_service.get_stats()
            except Exception:
                pass

        # Detect strategy mode and fetch billing context for fallback
        strategy_mode = self._detect_strategy_mode(query)
        billing_context = None
        if not opportunities:
            billing_context = await self._fetch_recent_billing_context(account_ids)

        # Format response
        response = self.format_opportunities_response(
            opportunities, intent, stats,
            billing_context=billing_context,
            strategy_mode=strategy_mode,
        )

        logger.info(
            "Optimization query processed",
            opportunities_count=len(opportunities),
            total_savings=response.get("metadata", {}).get("total_monthly_savings", 0)
        )

        return response


# Factory function
def get_optimization_agent(organization_id: Optional[UUID] = None) -> OptimizationAgent:
    """Get optimization agent instance"""
    return OptimizationAgent(organization_id=organization_id)
