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
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
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

logger = structlog.get_logger(__name__)
settings = get_settings()


# Security: Maximum query length for LLM classification
# Prevents potential abuse and reduces token costs
MAX_QUERY_LENGTH_FOR_LLM = 2000  # characters

# LLM prompt for optimization intent classification
OPTIMIZATION_INTENT_PROMPT = """You are an expert at classifying FinOps (cloud cost management) queries.

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
        stats: Optional[Dict[str, Any]] = None
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

        # Format response
        response = self.format_opportunities_response(opportunities, intent, stats)

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
