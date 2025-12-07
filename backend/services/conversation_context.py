"""
Conversation Context Manager - Manages conversation state and follow-up handling
Implements context retention for multi-turn conversations

NOTE: This is the legacy in-memory/SQLAlchemy-based context manager. 
For new development, use services/conversation_manager.py (PostgreSQL/psycopg2-based).
This module is retained for compatibility with existing tests and legacy code paths.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json
import re
import structlog

from utils.date_parser import date_parser
from backend.services.database import DatabaseService
from backend.models.database_models import Conversation
from backend.services.column_constants import CHARGE_TYPE_SYNONYMS
from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# Import LLM query refiner for intelligent follow-up handling
try:
    from services.llm_query_refiner import llm_query_refiner
    LLM_REFINER_AVAILABLE = True
except ImportError:
    LLM_REFINER_AVAILABLE = False
    logger.warning("LLM query refiner not available, using rule-based fallback")


class ConversationContext:
    """
    Manages conversation context for follow-up query handling.
    Stores: last_intent, last_params, last_query, conversation_history
    """
    
    def __init__(self, conversation_id: str):
        """
        Initialize conversation context.
        
        Args:
            conversation_id: Unique conversation identifier
        """
        self.conversation_id = conversation_id
        self.created_at = datetime.utcnow()
        self.last_updated = datetime.utcnow()
        
        # Context state
        self.last_intent: Optional[str] = None
        self.last_params: Dict[str, Any] = {}
        self.last_query: str = ""
        self.last_results_count: int = 0
        self.last_total_cost: Optional[float] = None
        self.last_services_in_results: List[str] = []  # Track services from last results
        
        # Conversation history
        self.conversation_history: List[Dict[str, str]] = []
        
        # Accumulated context (for follow-ups)
        self.accumulated_filters: Dict[str, Any] = {
            "services": [],
            "regions": [],
            "accounts": [],
            "tags": {},
            "excluded_services": []
        }
        
        # Scope retention
        self.last_time_range: Optional[Dict[str, Any]] = None
        self.last_dimensions: List[str] = []
        
        # Track chart aggregation for "Others" drill-down
        self.last_shown_top_items: List[str] = []  # Items shown in chart
        self.last_hidden_items: List[Dict[str, Any]] = []  # Items aggregated into "Others"
        self.last_chart_aggregated: bool = False
    
    def update(
        self,
        query: str,
        intent: str,
        extracted_params: Dict[str, Any],
        results_count: int = 0,
        total_cost: Optional[float] = None,
        services_in_results: Optional[List[str]] = None
    ):
        """
        Update context with new query information.
        
        Args:
            query: User query
            intent: Classified intent
            extracted_params: Extracted parameters
            results_count: Number of results returned
            total_cost: Sum of primary cost metric from results (if available)
            services_in_results: List of services present in the results
        """
        self.last_updated = datetime.utcnow()
        self.last_query = query
        self.last_intent = intent
        self.last_params = extracted_params.copy()
        self.last_results_count = results_count
        if total_cost is not None:
            try:
                self.last_total_cost = float(total_cost)
            except (TypeError, ValueError):
                logger.warning("Invalid total_cost passed to context.update", total_cost=total_cost)
        
        # Store services from results for LLM-based matching
        if services_in_results:
            self.last_services_in_results = services_in_results
        
        # Update accumulated filters
        self._merge_filters(extracted_params)
        
        # Update scope retention
        if extracted_params.get("time_range"):
            self.last_time_range = extracted_params["time_range"]
        
        if extracted_params.get("dimensions"):
            self.last_dimensions = extracted_params["dimensions"]
        
        logger.info(
            "Context updated",
            conversation_id=self.conversation_id,
            intent=intent,
            query_preview=query[:50]
        )
    
    def _merge_filters(self, new_params: Dict[str, Any]):
        """Merge new parameters into accumulated filters"""
        # Add new services
        if new_params.get("services"):
            for service in new_params["services"]:
                if service not in self.accumulated_filters["services"]:
                    self.accumulated_filters["services"].append(service)
        
        # Add new regions
        if new_params.get("regions"):
            for region in new_params["regions"]:
                if region not in self.accumulated_filters["regions"]:
                    self.accumulated_filters["regions"].append(region)
        
        # Add new accounts
        if new_params.get("accounts"):
            for account in new_params["accounts"]:
                if account not in self.accumulated_filters["accounts"]:
                    self.accumulated_filters["accounts"].append(account)
        
        # Merge tags
        if new_params.get("tags"):
            self.accumulated_filters["tags"].update(new_params["tags"])
    
    def apply_follow_up_refinement(
        self,
        query: str,
        new_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply follow-up refinements to existing context.
        Handles: exclude, include, drill down, same period, etc.
        
        Args:
            query: Follow-up query
            new_params: Newly extracted parameters
            
            Returns:
            Merged parameters for follow-up query
        """
        query_lower = query.lower()
        refined_params = self.last_params.copy()
        
        # Re-extract time range from query if not already in new_params (for follow-ups)
        if "time_range" not in new_params:
            try:
                from utils.date_parser import date_parser
                start_date, end_date, metadata = date_parser.parse_time_range(query)
                new_params["time_range"] = {
                    "start_date": start_date,
                    "end_date": end_date,
                    "period": metadata.get("period_type", "default"),
                    "description": metadata.get("description", "Last 30 days"),
                    "source": "followup_extraction",
                    "metadata": metadata
                }
                logger.info(f"Re-extracted time range from follow-up query: {new_params['time_range']['description']}")
            except Exception as e:
                logger.debug(f"Could not extract time range from follow-up query: {e}")
        
        logger.info(
            "FOLLOW-UP REFINEMENT START",
            query=query,
            last_params_services=self.last_params.get("services"),
            new_params_services=new_params.get("services"),
            new_params_keys=list(new_params.keys())
        )
        
        # Track which parameters were explicitly handled
        handled_params = set()
        
        # Handle exclusions
        if "exclude" in query_lower:
            # Check if excluding tax/fees/credits (line item types)
            if any(term in query_lower for term in ["tax", "taxes", "fee", "fees", "credit", "credits", "support", "refund"]):
                refined_params["exclude_line_item_types"] = []
                # Use CHARGE_TYPE_SYNONYMS to map user terms to canonical CUR values
                for user_term, canonical_type in CHARGE_TYPE_SYNONYMS.items():
                    if user_term in query_lower:
                        if canonical_type not in refined_params["exclude_line_item_types"]:
                            refined_params["exclude_line_item_types"].append(canonical_type)
                
                # Special case: "support" might refer to AWS Support service, not Support charge type
                if "support" in query_lower:
                    refined_params.setdefault("exclude_services", []).append("AWSSupport")
                
                logger.info(f"Excluding line item types: {refined_params.get('exclude_line_item_types', [])}")
                handled_params.add("exclude_line_item_types")
            else:
                # Excluding services
                services_to_exclude = new_params.get("services", [])
                if services_to_exclude:
                    refined_params["exclude_services"] = services_to_exclude
                    logger.info(f"Excluding services: {services_to_exclude}")
                    handled_params.add("services")
        
        # Handle inclusions (addition to existing)
        elif "include" in query_lower or "add" in query_lower:
            if new_params.get("services"):
                existing = refined_params.get("services", [])
                refined_params["services"] = existing + new_params["services"]
                handled_params.add("services")
        
        # Handle "only" or "just" (replacement)
        elif "only" in query_lower or "just" in query_lower:
            if new_params.get("services"):
                refined_params["services"] = new_params["services"]
                handled_params.add("services")
            if new_params.get("regions"):
                refined_params["regions"] = new_params["regions"]
                handled_params.add("regions")
        
        # Handle drilldown
        elif "drill" in query_lower or "zoom" in query_lower or "break" in query_lower or "breakdown" in query_lower:
            # Drill down usually adds a dimension but KEEPS existing filters
            if new_params.get("dimensions"):
                refined_params["dimensions"] = new_params["dimensions"]
                handled_params.add("dimensions")
            if new_params.get("services"):
                # Only update services if explicitly mentioned
                refined_params["services"] = new_params["services"]
                handled_params.add("services")
            # Otherwise keep existing service filter from last_params
        
        # DEFAULT: If query mentions services/regions without specific keywords, treat as FILTER/REPLACEMENT
        # E.g., "filter by lambda", "show me lambda costs"
        else:
            if new_params.get("services"):
                refined_params["services"] = new_params["services"]
                handled_params.add("services")
                logger.info(f"Replacing services filter with: {new_params['services']}")
            if new_params.get("regions"):
                refined_params["regions"] = new_params["regions"]
                handled_params.add("regions")
                logger.info(f"Replacing regions filter with: {new_params['regions']}")
            # IMPORTANT: If NO services mentioned in new query but services exist from previous query,
            # this likely means user is only changing time range, so preserve the services
            # (Don't treat as removal, treat as implicit preservation)
        
        # Handle "same period" or inherited timeframe
        new_time_range = new_params.get("time_range")
        new_time_range_source = (new_time_range or {}).get("source")
        # FIXED: Consider "explicit" source (from date_parser) and "followup_extraction" as explicit
        explicit_new_time_range = bool(new_time_range) and new_time_range_source in {"explicit", "followup_extraction"}
        
        # For follow-ups, decide whether to inherit or allow new time range
        should_inherit_time_range = False
        
        # DIAGNOSTIC LOGGING for follow-up time range handling
        logger.info(
            "FOLLOW-UP TIME RANGE DECISION",
            query=query[:80],
            new_time_range_present=bool(new_time_range),
            new_time_range_source=new_time_range_source,
            explicit_new_time_range=explicit_new_time_range,
            new_time_range_description=new_time_range.get("description") if new_time_range else None
        )
        
        if "same" in query_lower and "period" in query_lower:
            # Explicitly keep last time range
            should_inherit_time_range = True
            logger.info("INHERITING: 'same period' phrase detected")
        elif not new_time_range:
            # No time range mentioned at all - inherit from previous query
            should_inherit_time_range = True
            logger.info("INHERITING: No time range in follow-up")
        elif "how about" in query_lower or "what about" in query_lower:
            # Ambiguous queries - inherit to avoid confusion
            should_inherit_time_range = True
            logger.info("INHERITING: Ambiguous phrase detected")
        elif explicit_new_time_range:
            # Clear time range change - allow override
            should_inherit_time_range = False
            logger.info(f"NOT INHERITING: Explicit new time range detected: {new_time_range.get('description', 'N/A')}")
        else:
            # Implicit or default time range - inherit
            should_inherit_time_range = True
            logger.info("INHERITING: Implicit/default time range")
        
        if should_inherit_time_range:
            if self.last_time_range:
                # Inherit previous period
                logger.info(f"INHERITING TIME RANGE: {self.last_time_range.get('description')}")
                inherited_range = self.last_time_range.copy()
                inherited_range["source"] = "inherited_followup"
                if "metadata" in inherited_range:
                    inherited_range["metadata"] = inherited_range["metadata"].copy()
                    inherited_range["metadata"]["source"] = "inherited_followup"
                refined_params["time_range"] = inherited_range
                refined_params["start_date"] = self.last_time_range.get("start_date")
                refined_params["end_date"] = self.last_time_range.get("end_date")
                handled_params.add("time_range")
                logger.info("Inherited time range from previous query")
        elif new_time_range:
            # Use the new time range
            refined_params["time_range"] = new_time_range
            refined_params["start_date"] = new_time_range.get("start_date")
            refined_params["end_date"] = new_time_range.get("end_date")
            handled_params.add("time_range")
            logger.info(f"Using new time range: {new_time_range.get('description', 'N/A')}")
            
            # CRITICAL FIX: When time range changes but no services mentioned in new query,
            # preserve services from previous query (context preservation)
            if "services" not in handled_params and not new_params.get("services"):
                if self.last_params.get("services"):
                    refined_params["services"] = self.last_params.get("services", [])
                    logger.info(f"PRESERVING services from previous query (time changed, no services mentioned): {refined_params['services']}")
        
        # Merge any remaining new explicit parameters that weren't handled above
        for key, value in new_params.items():
            if value and key not in handled_params:
                refined_params[key] = value

        # Align requested services with canonical names observed in previous results
        if refined_params.get("services"):
            aligned_services = self._align_services_to_results(refined_params["services"])
            refined_params["services"] = aligned_services
        
        logger.info(
            "FOLLOW-UP REFINEMENT COMPLETE",
            final_services=refined_params.get("services"),
            final_dimensions=refined_params.get("dimensions"),
            handled_params=list(handled_params)
        )
        
        return refined_params
    
    def _align_services_to_results(self, services: List[str]) -> List[str]:
        """Map user-specified services to canonical names from previous results to avoid CUR mismatches."""
        if not services or not self.last_services_in_results:
            return services
        
        normalized_catalog = {
            self._normalize_service_token(service): service
            for service in self.last_services_in_results
            if service
        }
        
        aligned: List[str] = []
        for requested in services:
            normalized_requested = self._normalize_service_token(requested)
            matched = normalized_catalog.get(normalized_requested)
            
            if not matched and normalized_requested:
                for candidate_key, candidate_value in normalized_catalog.items():
                    if (
                        normalized_requested in candidate_key
                        or candidate_key in normalized_requested
                    ):
                        matched = candidate_value
                        break
            
            if matched:
                if matched != requested:
                    logger.info(
                        "Aligned follow-up service name to canonical result",
                        requested=requested,
                        aligned=matched
                    )
                aligned.append(matched)
            else:
                aligned.append(requested)
        
        return aligned
    
    @staticmethod
    def _normalize_service_token(name: Optional[str]) -> str:
        """Normalize service names for comparison (strip non-alphanumerics, lowercase)."""
        if not name:
            return ""
        return re.sub(r"[^a-z0-9]", "", name.lower())
    
    async def apply_llm_follow_up_refinement(
        self,
        query: str,
        new_params: Dict[str, Any],
        available_services: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Use LLM to intelligently refine follow-up queries.
        Handles misspellings, variations, and context better than rule-based approach.
        
        Args:
            query: Follow-up query
            new_params: Newly extracted parameters
            available_services: List of services from previous results (for matching)
            
        Returns:
            Merged parameters for follow-up query
        """
        
        if not LLM_REFINER_AVAILABLE:
            logger.warning("LLM refiner not available, falling back to rule-based refinement")
            return self.apply_follow_up_refinement(query, new_params)
        
        try:
            # Get LLM's interpretation of the follow-up query
            llm_refined = await llm_query_refiner.refine_follow_up_query(
                current_query=query,
                conversation_history=self.conversation_history,
                available_services=available_services or [],
                last_params=self.last_params
            )
            
            logger.info(
                "LLM refinement result",
                query=query,
                inherit_time_range=llm_refined.get('inherit_time_range'),
                services=llm_refined.get('services'),
                operation=llm_refined.get('service_operation'),
                context_switch=llm_refined.get('context_switch'),
                reasoning=llm_refined.get('reasoning')
            )
            
            # Check if LLM returned all nulls (failed to understand) - fall back to rule-based
            if all(v is None for k, v in llm_refined.items() if k not in ['reasoning', 'context_switch']):
                logger.warning("LLM returned all nulls, falling back to rule-based refinement")
                return self.apply_follow_up_refinement(query, new_params)
            
            # Check if this is a context switch (new analysis)
            if llm_refined.get('context_switch'):
                logger.info("LLM detected context switch - starting fresh analysis")
                # Don't inherit anything, start fresh with new params
                refined_params = {}
                
                # Apply time range if specified
                if llm_refined.get('time_range'):
                    refined_params["time_range"] = llm_refined['time_range']
                    refined_params["start_date"] = llm_refined['time_range'].get("start_date")
                    refined_params["end_date"] = llm_refined['time_range'].get("end_date")
                elif llm_refined.get('inherit_time_range') and self.last_time_range:
                    # Even with context switch, may inherit time range
                    inherited_range = self.last_time_range.copy()
                    inherited_range["source"] = "llm_inherited"
                    refined_params["time_range"] = inherited_range
                    refined_params["start_date"] = self.last_time_range.get("start_date")
                    refined_params["end_date"] = self.last_time_range.get("end_date")
                
                # Apply new services if specified
                if llm_refined.get('services'):
                    refined_params["services"] = llm_refined['services']
                
                # Merge other new params
                for key, value in new_params.items():
                    if value and key not in ['services', 'time_range', 'start_date', 'end_date']:
                        refined_params[key] = value
                
                return refined_params
            
            refined_params = self.last_params.copy()
            
            # CRITICAL FIX: Check if new_params has explicit time range BEFORE applying LLM inheritance
            new_time_range_from_params = new_params.get('time_range')
            new_time_source = (new_time_range_from_params or {}).get('source')
            has_explicit_new_time = new_time_range_from_params and new_time_source not in {'default', 'implicit_followup'}
            
            # Apply time range inheritance based on LLM decision
            if llm_refined.get('inherit_time_range') and self.last_time_range and not has_explicit_new_time:
                inherited_range = self.last_time_range.copy()
                inherited_range["source"] = "llm_inherited"
                refined_params["time_range"] = inherited_range
                refined_params["start_date"] = self.last_time_range.get("start_date")
                refined_params["end_date"] = self.last_time_range.get("end_date")
                logger.info(f"LLM: Inheriting time range - {self.last_time_range.get('description')}")
            elif llm_refined.get('time_range'):
                # Use new time range from LLM
                refined_params["time_range"] = llm_refined['time_range']
                refined_params["start_date"] = llm_refined['time_range'].get("start_date")
                refined_params["end_date"] = llm_refined['time_range'].get("end_date")
                logger.info(f"LLM: Using new time range - {llm_refined['time_range'].get('description')}")
            elif has_explicit_new_time:
                # Use explicit time range from new_params (when LLM didn't provide one)
                refined_params["time_range"] = new_time_range_from_params
                refined_params["start_date"] = new_time_range_from_params.get("start_date")
                refined_params["end_date"] = new_time_range_from_params.get("end_date")
                logger.info(f"LLM: Using explicit time range from params - {new_time_range_from_params.get('description')}")
            
            # Apply service filters based on LLM decision
            services = llm_refined.get('services')
            service_operation = llm_refined.get('service_operation')
            
            if service_operation == 'clear':
                # Clear all service filters - start fresh
                refined_params.pop("services", None)
                refined_params.pop("exclude_services", None)
                logger.info("LLM: Clearing all service filters (new analysis context)")
            elif services:
                if service_operation == 'replace':
                    # Replace with new services
                    refined_params["services"] = services
                    logger.info(f"LLM: Replacing services with {services}")
                elif service_operation == 'add':
                    # Add to existing services
                    existing = refined_params.get("services", [])
                    refined_params["services"] = list(set(existing + services))
                    logger.info(f"LLM: Adding services {services} to existing {existing}")
                elif service_operation == 'remove':
                    # Remove from existing services
                    existing = refined_params.get("services", [])
                    refined_params["services"] = [s for s in existing if s not in services]
                    logger.info(f"LLM: Removing services {services}, keeping {refined_params['services']}")
                elif service_operation == 'inherit':
                    # Inherit/preserve services from previous query (time range changed but keep filters)
                    refined_params["services"] = services
                    logger.info(f"LLM: Inheriting/preserving services {services} (time range changed)")
                else:
                    # No operation specified but services provided - treat as replace
                    refined_params["services"] = services
                    logger.info(f"LLM: Setting services to {services}")
            elif service_operation == 'inherit' and self.last_params.get("services"):
                # Time range changed but no services mentioned - inherit previous services
                refined_params["services"] = self.last_params.get("services", [])
                logger.info(f"LLM: Inheriting services from previous query (time changed, no services mentioned): {refined_params['services']}")
            
            # Merge any other parameters from new_params that LLM didn't handle
            for key, value in new_params.items():
                if value and key not in ['services', 'time_range', 'start_date', 'end_date']:
                    refined_params[key] = value
            
            return refined_params
            
        except Exception as e:
            logger.error(f"LLM refinement failed, falling back to rule-based: {e}", exc_info=True)
            return self.apply_follow_up_refinement(query, new_params)
    
    def add_message(self, role: str, content: str):
        """
        Add message to conversation history.
        
        Args:
            role: Message role (user/assistant)
            content: Message content
        """
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Keep last 20 messages (10 exchanges)
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
    
    def get_conversation_summary(self) -> str:
        """Get brief summary of conversation for LLM context"""
        if not self.conversation_history:
            return "New conversation"
        
        summary_parts = []
        
        # Last query
        if self.last_query:
            summary_parts.append(f"Previous query: {self.last_query}")
        
        # Current scope
        if self.last_time_range:
            period = self.last_time_range.get("period", "custom")
            summary_parts.append(f"Time scope: {period}")
        
        if self.accumulated_filters.get("services"):
            summary_parts.append(f"Services in scope: {', '.join(self.accumulated_filters['services'][:3])}")
        
        return " | ".join(summary_parts)
    
    def is_expired(self, max_age_minutes: int = 60) -> bool:
        """Check if context is expired"""
        age = datetime.utcnow() - self.last_updated
        return age > timedelta(minutes=max_age_minutes)
    
    def to_dict(self) -> Dict[str, Any]:
        """Export context to dictionary"""
        return {
            "conversation_id": self.conversation_id,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "last_intent": self.last_intent,
            "last_params": self.last_params,
            "last_query": self.last_query,
            "last_results_count": self.last_results_count,
            "last_total_cost": self.last_total_cost,
            "accumulated_filters": self.accumulated_filters,
            "last_time_range": self.last_time_range,
            "conversation_history": self.conversation_history
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationContext':
        """Create context from dictionary"""
        context = cls(data["conversation_id"])
        context.created_at = datetime.fromisoformat(data["created_at"])
        context.last_updated = datetime.fromisoformat(data["last_updated"])
        context.last_intent = data.get("last_intent")
        context.last_params = data.get("last_params", {})
        context.last_query = data.get("last_query", "")
        context.last_results_count = data.get("last_results_count", 0)
        context.last_total_cost = data.get("last_total_cost")
        context.accumulated_filters = data.get("accumulated_filters", {})
        context.last_time_range = data.get("last_time_range")
        context.conversation_history = data.get("conversation_history", [])
        return context


class ConversationContextManager:
    """
    Manages multiple conversation contexts with persistent PostgreSQL storage.
    Replaces in-memory storage for production AWS deployment.
    """
    
    def __init__(self):
        """Initialize context manager with database service"""
        self.db_service = None
        self._initialized = False
        logger.info("Conversation Context Manager initialized (database-backed)")
    
    async def _ensure_initialized(self):
        """Ensure database service is initialized and tables exist"""
        if not self._initialized:
            try:
                self.db_service = DatabaseService()
                await self.db_service.initialize()
                logger.info("Database service initialized successfully")
                
                # Create tables if they don't exist
                try:
                    from models.database_models import Base
                    logger.info("Imported Base successfully")
                    
                    async with self.db_service.engine.begin() as conn:
                        logger.info("Starting table creation")
                        await conn.run_sync(Base.metadata.create_all)
                        logger.info("Database tables created/verified")
                    
                except Exception as e:
                    logger.error(f"Failed to create tables: {e}", exc_info=True)
                    raise
                
                self._initialized = True
                logger.info("Database service initialized for conversation context manager")
                
            except Exception as e:
                logger.error(f"Failed to initialize database service: {e}", exc_info=True)
                raise
    
    async def get_or_create_context(self, conversation_id: str) -> ConversationContext:
        """
        Get existing context or create new one.
        
        Args:
            conversation_id: Conversation identifier
            
        Returns:
            ConversationContext instance
        """
        await self._ensure_initialized()
        
        try:
            session = await self.db_service.get_session()
            async with session:
                # Try to load existing conversation
                db_conversation = await session.get(Conversation, conversation_id)
                
                if db_conversation:
                    context = ConversationContext.from_dict(db_conversation.context_data)
                    
                    # Check if expired
                    if context.is_expired():
                        logger.info(f"Context expired, creating new one: {conversation_id}")
                        context = ConversationContext(conversation_id)
                        # Save new context
                        await self._save_context(session, context)
                    else:
                        logger.info(f"Loaded existing context: {conversation_id}")
                else:
                    context = ConversationContext(conversation_id)
                    await self._save_context(session, context)
                    logger.info(f"Created new conversation context: {conversation_id}")
                
                return context
                
        except Exception as e:
            logger.error(f"Error loading/creating context {conversation_id}: {e}", exc_info=True)
            # Fallback to in-memory context if database fails
            return ConversationContext(conversation_id)
    
    async def _save_context(self, session, context: ConversationContext):
        """Save context to database"""
        context_data = context.to_dict()
        
        db_conversation = Conversation(
            id=context.conversation_id,
            context_data=context_data,
            created_at=context.created_at,
            updated_at=context.last_updated
        )
        
        # Upsert operation
        await session.merge(db_conversation)
        await session.commit()
    
    async def update_context(
        self,
        conversation_id: str,
        query: str,
        intent: str,
        extracted_params: Dict[str, Any],
        results_count: int = 0,
        total_cost: Optional[float] = None,
        services_in_results: Optional[List[str]] = None
    ):
        """Update conversation context"""
        context = await self.get_or_create_context(conversation_id)
        context.update(query, intent, extracted_params, results_count, total_cost, services_in_results)
        
        # Save updated context
        await self._ensure_initialized()
        try:
            session = await self.db_service.get_session()
            async with session:
                await self._save_context(session, context)
                logger.info(f"Updated and saved context: {conversation_id}")
        except Exception as e:
            logger.error(f"Error saving updated context {conversation_id}: {e}", exc_info=True)
    
    async def add_message(self, conversation_id: str, role: str, content: str):
        """Add message to conversation history"""
        context = await self.get_or_create_context(conversation_id)
        context.add_message(role, content)
        
        # Save updated context
        await self._ensure_initialized()
        try:
            session = await self.db_service.get_session()
            async with session:
                await self._save_context(session, context)
        except Exception as e:
            logger.error(f"Error saving message to context {conversation_id}: {e}", exc_info=True)
    
    async def get_context(self, conversation_id: str) -> Optional[ConversationContext]:
        """Get existing context"""
        await self._ensure_initialized()
        
        try:
            session = await self.db_service.get_session()
            async with session:
                db_conversation = await session.get(Conversation, conversation_id)
                if db_conversation:
                    context = ConversationContext.from_dict(db_conversation.context_data)
                    # Check if expired
                    if not context.is_expired():
                        return context
                return None
        except Exception as e:
            logger.error(f"Error loading context {conversation_id}: {e}", exc_info=True)
            return None
    
    async def cleanup_expired(self, max_age_minutes: int = 60):
        """Remove expired contexts from database"""
        await self._ensure_initialized()
        
        try:
            cutoff_time = datetime.utcnow() - timedelta(minutes=max_age_minutes)
            
            session = await self.db_service.get_session()
            async with session:
                # Delete expired conversations
                result = await session.execute(
                    "DELETE FROM conversations WHERE updated_at < :cutoff",
                    {"cutoff": cutoff_time}
                )
                deleted_count = result.rowcount
                
                await session.commit()
                
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} expired contexts from database")
                    
        except Exception as e:
            logger.error(f"Error cleaning up expired contexts: {e}", exc_info=True)
    
    async def export_context(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Export context to dictionary"""
        context = await self.get_context(conversation_id)
        return context.to_dict() if context else None
    
    async def import_context(self, data: Dict[str, Any]):
        """Import context from dictionary"""
        context = ConversationContext.from_dict(data)
        
        await self._ensure_initialized()
        try:
            session = await self.db_service.get_session()
            async with session:
                await self._save_context(session, context)
                logger.info(f"Imported context: {context.conversation_id}")
        except Exception as e:
            logger.error(f"Error importing context {context.conversation_id}: {e}", exc_info=True)
    
    async def close(self):
        """Close database connections"""
        if self.db_service:
            await self.db_service.close()
            self._initialized = False


# Global context manager instance
context_manager = ConversationContextManager()
