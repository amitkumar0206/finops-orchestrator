"""
LLM-based Query Refinement Service
Uses LLM to understand conversation context and generate structured filters
"""

from typing import Dict, List, Any, Optional
import json
import re
import structlog
from backend.services.llm_service import llm_service

logger = structlog.get_logger(__name__)


class LLMQueryRefiner:
    """
    Uses LLM to intelligently refine queries based on conversation context.
    Handles misspellings, variations, and contextual understanding.
    """
    
    def __init__(self):
        self.llm = llm_service
    
    async def refine_follow_up_query(
        self,
        current_query: str,
        conversation_history: List[Dict[str, str]],
        available_services: List[str],
        last_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Use LLM to understand follow-up query and generate refined parameters.
        
        Args:
            current_query: Current user query
            conversation_history: Previous conversation turns
            available_services: List of actual AWS service names from previous results
            last_params: Parameters from previous query
            
        Returns:
            Refined parameters dictionary
        """
        
        # Build conversation context
        context_lines = []
        for turn in conversation_history[-5:]:  # Last 5 turns
            context_lines.append(f"User: {turn.get('user', '')}")
            context_lines.append(f"Assistant: {turn.get('assistant', '')}")
        
        conversation_context = "\n".join(context_lines)
        
        # Build prompt for LLM
        prompt = f"""You are an expert FinOps consultant with decades of experience analyzing cloud infrastructure costs. You have deep expertise in understanding how engineers and finance teams naturally talk about AWS costs, and you excel at interpreting conversational follow-up queries in the context of ongoing cost analysis.

Your role: Understand the FULL CONVERSATION CONTEXT like a seasoned FinOps professional would.

CONVERSATION HISTORY:
{conversation_context}

CURRENT QUERY: "{current_query}"

PREVIOUS QUERY CONTEXT:
- Time Range: {last_params.get('time_range', {}).get('description', 'Not specified')}
- Services: {last_params.get('services', 'All services')}
- Regions: {last_params.get('regions', 'All regions')}
- Other Filters: {json.dumps({k: v for k, v in last_params.items() if k not in ['time_range', 'services', 'regions', 'start_date', 'end_date']}, indent=2) if last_params else '{}'}

AVAILABLE SERVICES FROM PREVIOUS RESULTS:
{json.dumps(available_services[:20], indent=2)}

YOUR TASK - Think Like an Experienced FinOps Professional:
Analyze the current query as a follow-up and determine what the user REALLY wants based on how FinOps teams naturally explore costs:

1. **Context Change Detection:**
   - Is the user asking about something COMPLETELY DIFFERENT? (Clear context switch)
   - Or refining/expanding the SAME analysis? (Context preservation/addition)

2. **Filter Management:**
   - PRESERVE: Time change only → Keep all filters ("for 100 days" after filtering for "ec2 and lambda")
   - ADD: Expanding scope → Add new filters to existing ("also include S3" or "add region us-east-1")
   - REPLACE: Narrowing/changing scope → Replace filters ("only ec2" or "switch to lambda instead")
   - REMOVE: Explicit removal → Remove specific filters ("exclude lambda" or "without S3")
   - CLEAR: New context → Start fresh (completely new topic/question)

3. **Human Understanding Examples:**
   - "for 100 days" after "ec2 and lambda" = PRESERVE services, change time
   - "only for S3" after "ec2 and lambda" = REPLACE services
   - "also for S3" after "ec2 and lambda" = ADD S3 to existing
   - "exclude lambda" after "ec2 and lambda" = REMOVE lambda, keep EC2
   - "what about RDS costs?" after "ec2 costs" = CLEAR context (new analysis)
   - "show me total cost" after "cost breakdown" = CLEAR context (different intent)

CRITICAL CONTEXT PRESERVATION RULE:
**When ONLY parameters like time/region change WITHOUT mentioning services, PRESERVE existing service filters!**
The user's mental model maintains filters unless explicitly changed.

SERVICE MATCHING RULES:
- "ec2" or "elastic compute" → "Amazon Elastic Compute Cloud - Compute"
- "s3" or "storage" → "Amazon Simple Storage Service"
- "lambda" → "AWS Lambda"
- "rds" or "database" → "Amazon Relational Database Service"
- Handle abbreviations, typos, and variations intelligently

Return ONLY a JSON object:
{{
  "inherit_time_range": true/false,
  "time_range": {{
    "start_date": "YYYY-MM-DD" or null,
    "end_date": "YYYY-MM-DD" or null,
    "description": "description" or null
  }},
  "services": ["exact service name"] or null,
  "service_operation": "replace" | "add" | "remove" | "inherit" | "clear" | null,
  "context_switch": true/false,  // Is this a completely new analysis?
  "reasoning": "Your human-like interpretation of what the user wants"
}}

CRITICAL: For "exclude tax", "exclude fees", etc., do NOT set services. These are line item exclusions, not service filters.
Set inherit_time_range=true and service_operation=null to preserve existing context.

DETAILED EXAMPLES (Format: Context → Query → Response):

Context: Previous filtered for "ec2 and lambda" for "30 days"
Query: "for last 100 days"
→ {{"inherit_time_range": false, "time_range": {{"description": "Last 100 days"}}, "services": ["Amazon Elastic Compute Cloud - Compute", "AWS Lambda"], "service_operation": "inherit", "context_switch": false, "reasoning": "User wants same services (EC2 + Lambda) but different time period (100 days)"}}

Context: Previous filtered for "ec2 and lambda"
Query: "only for S3"
→ {{"inherit_time_range": true, "services": ["Amazon Simple Storage Service"], "service_operation": "replace", "context_switch": false, "reasoning": "User explicitly wants to REPLACE services with only S3"}}

Context: Previous filtered for "ec2 and lambda"
Query: "also include S3"
→ {{"inherit_time_range": true, "services": ["Amazon Simple Storage Service"], "service_operation": "add", "context_switch": false, "reasoning": "User wants to ADD S3 to existing EC2 and Lambda filters"}}

Context: Previous filtered for "ec2 and lambda"
Query: "exclude lambda"
→ {{"inherit_time_range": true, "services": ["AWS Lambda"], "service_operation": "remove", "context_switch": false, "reasoning": "User wants to REMOVE Lambda, keeping only EC2"}}

Context: Previous query showed costs including Tax
Query: "exclude tax"
→ {{"inherit_time_range": true, "services": null, "service_operation": null, "context_switch": false, "reasoning": "User wants to exclude Tax line items from the results, preserving time range and other filters"}}

Context: Previous filtered for "ec2 and lambda"
Query: "what about RDS costs?"
→ {{"inherit_time_range": false, "services": ["Amazon Relational Database Service"], "service_operation": "clear", "context_switch": true, "reasoning": "Completely new question about RDS, clear previous context"}}

Context: Previous query was "cost breakdown by service"
Query: "show me total cost"
→ {{"inherit_time_range": true, "services": null, "service_operation": "clear", "context_switch": true, "reasoning": "Different type of query (total vs breakdown), clear filters"}}

Context: Previous had NO filters
Query: "for 200 days"
→ {{"inherit_time_range": false, "time_range": {{"description": "Last 200 days"}}, "services": null, "service_operation": null, "context_switch": false, "reasoning": "No previous filters to preserve, just changing time range"}}

Now analyze the CURRENT query with FULL CONVERSATION UNDERSTANDING and return the JSON:

IMPORTANT: Return ONLY the JSON object, no explanation, no markdown, no code blocks. Just raw JSON."""

        try:
            # Define expected schema for structured response
            schema = {
                "type": "object",
                "properties": {
                    "inherit_time_range": {"type": ["boolean", "null"]},
                    "time_range": {
                        "type": ["object", "null"],
                        "properties": {
                            "start_date": {"type": ["string", "null"]},
                            "end_date": {"type": ["string", "null"]},
                            "description": {"type": ["string", "null"]}
                        }
                    },
                    "services": {"type": ["array", "null"], "items": {"type": "string"}},
                    "service_operation": {"type": ["string", "null"], "enum": ["replace", "add", "remove", "inherit", "clear", None]},
                    "context_switch": {"type": ["boolean", "null"]},
                    "reasoning": {"type": "string"}
                },
                "required": ["inherit_time_range", "services", "service_operation", "context_switch", "reasoning"]
            }
            
            refined = await self.llm.generate_structured_response(
                prompt=prompt,
                schema=schema
            )
            
            # Check if error occurred
            if refined.get('error'):
                logger.warning(f"LLM structured response error: {refined.get('error')}")
                return {}
            
            logger.info(
                "LLM query refinement successful",
                current_query=current_query,
                refined_services=refined.get('services'),
                inherit_time_range=refined.get('inherit_time_range'),
                reasoning=refined.get('reasoning')
            )
            
            return refined
                
        except Exception as e:
            logger.error(f"LLM query refinement failed: {e}", exc_info=True)
            return {}
    
    async def match_services_intelligently(
        self,
        user_service_query: str,
        available_services: List[str]
    ) -> List[str]:
        """
        Use LLM to match user's service description to actual AWS service names.
        
        Args:
            user_service_query: User's description (e.g., "ec2", "compute", "lambda functions")
            available_services: List of actual AWS service names
            
        Returns:
            List of matched service names
        """
        
        prompt = f"""Match the user's service description to actual AWS service names.

USER QUERY: "{user_service_query}"

AVAILABLE AWS SERVICES:
{json.dumps(available_services, indent=2)}

MATCHING RULES:
- Match abbreviations (ec2 → Amazon Elastic Compute Cloud)
- Match partial names (compute → all compute services)
- Match categories (storage → S3, EBS, EFS, etc.)
- Handle typos and variations
- Be inclusive - if unsure, include related services

Return ONLY a JSON array of matched service names:
["service1", "service2", ...]

If no clear matches, return empty array: []"""

        try:
            response = await self.llm.generate_text(
                prompt=prompt,
                temperature=0.1,
                max_tokens=300
            )
            
            # Extract JSON array from response
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                matched_services = json.loads(json_match.group(0))
                logger.info(
                    "LLM service matching successful",
                    user_query=user_service_query,
                    matched_count=len(matched_services),
                    matches=matched_services
                )
                return matched_services
            else:
                logger.warning("No JSON array in LLM response", response=response)
                return []
                
        except Exception as e:
            logger.error(f"LLM service matching failed: {e}", exc_info=True)
            return []


# Global instance
llm_query_refiner = LLMQueryRefiner()
