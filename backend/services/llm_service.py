"""
LLM Service using AWS Bedrock for secure internal AI processing.
Supports multiple models including Amazon Nova, Meta Llama, and Mistral families.
Enhanced with FinOps expertise and rich text formatting.
"""

import asyncio
import json
import structlog
from typing import Dict, List, Optional, Any, Tuple
from botocore.exceptions import ClientError, BotoCoreError

from backend.utils.aws_session import create_aws_session
from backend.utils.aws_constants import AwsService

try:
    from ..config.settings import get_settings
except ImportError:
    from config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


# FinOps Expert System Prompt
FINOPS_EXPERT_SYSTEM_PROMPT = """You are an expert FinOps (Financial Operations) consultant with decades of experience managing cloud infrastructure costs across AWS, Azure, and GCP. You specialize in AWS cost optimization and financial management for enterprise-scale deployments. Your role is to help DAZN engineers and managers understand, analyze, and optimize their AWS infrastructure costs with the depth and precision of a seasoned cloud economist.

Your expertise includes:
- Deep knowledge of AWS service pricing models, billing dimensions, and cost allocation
- Understanding of complex cost breakdowns (e.g., CloudWatch by API operations, EC2 by instance type/region/usage type)
- Experience with multi-million dollar cloud budgets and optimization strategies
- Ability to drill down from high-level service costs to granular resource-level details
- Knowledge of AWS Cost and Usage Report (CUR) dimensions and hierarchies

Your communication style:
- Talk like a seasoned FinOps professional with deep AWS expertise
- Use precise financial and technical terminology
- Present data with clear, actionable insights
- Format responses with markdown for readability (bold, italics, headers, lists, tables)
- Always provide context and explanations, not just raw numbers
- Suggest follow-up analyses and next steps
- Be proactive in identifying optimization opportunities

When analyzing costs:
- Always interpret the data, don't just repeat numbers
- Highlight cost drivers and trends
- Explain why costs might be high or increasing
- Provide industry context and benchmarks when relevant
- Suggest specific, actionable optimization strategies
- Quantify potential savings where possible

Handling hierarchical cost breakdowns (IMPORTANT):
When users ask to "breakdown" or "drill down" into a specific service:
1. **First breakdown request** (e.g., "breakdown CloudWatch costs"):
   - Provide a CHART/GRAPH showing the next level of detail
   - For CloudWatch: break down by usage types (Logs, Metrics, Alarms, Events, etc.)
   - For EC2: break down by instance types, regions, or usage types
   - For S3: break down by storage classes, data transfer, requests
   - Always visualize this breakdown as a chart for clarity

2. **Second breakdown request** (e.g., "breakdown CloudWatch Logs further"):
   - Provide another CHART/GRAPH with even more granular details
   - For CloudWatch Logs: break down by API operations (PutLogEvents, GetLogEvents, etc.)
   - For EC2 instances: break down by specific instance families or purchase options
   - Continue drilling down as long as data dimensions exist

3. **Explanation request** (e.g., "how did you calculate this?" or "explain the breakdown"):
   - Switch to TEXT/TABLE format (NO chart)
   - Explain the cost calculation methodology
   - Show the dimensions used (line_item_usage_type, product_code, operation, etc.)
   - Provide a table showing the hierarchy of breakdowns applied
   - Clarify any aggregations or filters

Example conversation flow:
- User: "What are my top 5 most expensive services?" → CHART with top 5 services
- User: "Breakdown CloudWatch costs" → CHART breaking CloudWatch by usage types (Logs, Metrics, etc.)
- User: "Breakdown CloudWatch Logs" → CHART breaking Logs by API operations (PutLogEvents, etc.)
- User: "How did you calculate this?" → TABLE/TEXT explaining CUR dimensions and calculation logic

Response formatting guidelines:
- Use **bold** for key metrics, service names, and important insights
- Use *italics* for emphasis and clarifications
- Create bullet points for lists of services, recommendations, or insights
- Use numbered lists for sequential steps or prioritized recommendations
- Format currency as **$X,XXX.XX** with bold
- Use headers (##, ###) to structure complex responses
- Create tables for comparative data when helpful
- Add visual separators (---) for distinct sections

Always be helpful, insightful, and professional. Your goal is to empower users to make informed decisions about their AWS spending with the depth of analysis they need."""


class BedrockLLMService:
    """Service for interacting with AWS Bedrock LLM models."""
    
    def __init__(self):
        """Initialize Bedrock client and model configuration."""
        self.settings = settings
        self.region = self.settings.aws_region
        self.model_id = self.settings.bedrock_model_id
        self.initialized = False
        self.initialization_error = None
        self.model_kwargs: Dict[str, Any] = {}
        self.use_converse_api: bool = True
        
        try:
            session = create_aws_session(region_name=self.region)
            self.bedrock_client = session.client(AwsService.BEDROCK_RUNTIME)
            self.model_kwargs = self._get_model_kwargs(self.model_id)
            self.use_converse_api = self._should_use_converse_api(self.model_id)
            self.initialized = True
            logger.info(
                "Bedrock LLM service initialized",
                model_id=self.model_id,
                use_converse_api=self.use_converse_api
            )
        except Exception as e:
            self.initialized = False
            self.initialization_error = str(e)
            logger.error(f"Failed to initialize Bedrock client: {e}")
            logger.warning("LLM service will use fallback responses due to initialization failure")
    
    def _should_use_converse_api(self, model_id: str) -> bool:
        """
        Determine if a model should use the Converse API.
        
        The Converse API is required for:
        - Amazon Nova 2.0 models (us.amazon.nova-*)
        - Anthropic Claude 3+ models (anthropic.claude-3-*)
        - Most newer Bedrock models
        
        Args:
            model_id: The Bedrock model ID
            
        Returns:
            True if model should use Converse API, False for legacy InvokeModel API
        """
        converse_api_models = [
            "us.amazon.nova",        # Nova 2.0 models
            "anthropic.claude-3",    # Claude 3 and newer
            "meta.llama3",           # Llama 3 models
            "mistral.mistral-large", # Newer Mistral models
        ]
        
        # Check if model ID starts with any known Converse API model prefix
        for prefix in converse_api_models:
            if model_id.startswith(prefix):
                return True
        
        # Default to Converse API for unknown models (safer for newer models)
        # This will auto-fallback to legacy API if Converse fails
        return True
    
    def _get_model_kwargs(self, model_id: str) -> Dict[str, Any]:
        """
        Get model-specific kwargs for different Bedrock model families.
        
        Args:
            model_id: The Bedrock model ID
            
        Returns:
            Dictionary of model-specific parameters
        """
        # Amazon Nova 2.0 models require specific inference configuration
        if model_id.startswith("us.amazon.nova"):
            return {
                "temperature": self.settings.temperature,
                "top_p": 0.9,
                "max_tokens": self.settings.max_tokens,
            }
        # Meta Llama models
        elif model_id.startswith("meta.llama"):
            return {
                "max_gen_len": self.settings.max_tokens,
                "temperature": self.settings.temperature,
                "top_p": 0.9,
            }
        # Mistral models
        elif model_id.startswith("mistral."):
            return {
                "max_tokens": self.settings.max_tokens,
                "temperature": self.settings.temperature,
                "top_p": 0.9,
            }
        # Cohere models
        elif model_id.startswith("cohere."):
            return {
                "max_tokens": self.settings.max_tokens,
                "temperature": self.settings.temperature,
                "p": 0.9,
            }
        # Default (works for most models including Anthropic Claude)
        else:
            return {
                "max_tokens": self.settings.max_tokens,
                "temperature": self.settings.temperature,
                "top_p": 0.9,
            }

    def _convert_to_bedrock_messages(
        self,
        messages: List[Dict[str, str]],
        context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Normalize internal message format into Bedrock-compatible structure."""
        bedrock_messages: List[Dict[str, Any]] = []
        context_prefix = ""

        def _coerce_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            try:
                return json.dumps(value, ensure_ascii=False, default=str)
            except TypeError:
                return str(value)

        # If context is provided, prepend it to the first user message instead of using system role
        # because Amazon Nova doesn't support system messages in Converse API
        if context:
            try:
                context_str = json.dumps(context, indent=2, default=str)
            except TypeError:
                context_str = str(context)
            context_prefix = f"Additional context:\n{context_str}\n\n"

        first_user_message = True
        for message in messages:
            role = message.get("role", "user").lower()
            # Skip system messages as they're not supported by Nova Converse API
            if role == "system":
                continue
            if role not in {"user", "assistant"}:
                role = "user"
            content = _coerce_text(message.get("content", ""))
            if not content:
                continue
            
            # Prepend context to first user message
            if first_user_message and role == "user" and context_prefix:
                content = context_prefix + content
                first_user_message = False
            
            bedrock_messages.append({
                "role": role,
                "content": [{"text": content}]
            })

        return bedrock_messages

    def _build_inference_config(self) -> Dict[str, Any]:
        """Build inference configuration suitable for Bedrock Converse API."""
        config: Dict[str, Any] = {}

        max_tokens = self.model_kwargs.get("max_tokens", self.settings.max_tokens)
        if max_tokens:
            config["maxTokens"] = int(max_tokens)

        temperature = self.model_kwargs.get("temperature", self.settings.temperature)
        if temperature is not None:
            config["temperature"] = float(temperature)

        top_p = self.model_kwargs.get("top_p") or self.model_kwargs.get("p")
        if top_p is not None:
            config["topP"] = float(top_p)

        stop_sequences = self.model_kwargs.get("stop_sequences") or self.model_kwargs.get("stopWords")
        if stop_sequences:
            config["stopSequences"] = stop_sequences

        return config

    def _extract_text_from_converse(self, response: Dict[str, Any]) -> str:
        """Extract textual content from Bedrock Converse response."""
        if not response:
            return ""

        output = response.get("output") or {}
        message = output.get("message") or {}
        content = message.get("content") or []

        text_chunks = []
        for part in content:
            if isinstance(part, dict):
                if part.get("text"):
                    text_chunks.append(part["text"])
                elif "toolUse" in part:
                    tool_use = part["toolUse"]
                    if isinstance(tool_use, dict) and "input" in tool_use:
                        text_chunks.append(json.dumps(tool_use["input"]))
        return "\n".join(chunk for chunk in text_chunks if chunk).strip()

    def _extract_text_from_invoke(self, response: Dict[str, Any]) -> str:
        """Extract text output from legacy InvokeModel response."""
        if not response:
            return ""

        body = response.get("body")
        if not body:
            return ""

        try:
            if hasattr(body, "read"):
                payload = body.read()
            else:
                payload = body
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            data = json.loads(payload)
        except Exception as err:
            logger.error(f"Failed to parse Bedrock invoke_model response: {err}")
            return ""

        if isinstance(data, dict):
            if "outputText" in data:
                return data["outputText"].strip()
            if "results" in data and data["results"]:
                texts = []
                for result in data["results"]:
                    text_val = result.get("outputText") or result.get("text")
                    if text_val:
                        texts.append(text_val)
                if texts:
                    return "\n".join(texts).strip()
            if "output" in data and isinstance(data["output"], dict):
                output = data["output"]
                if "message" in output:
                    message = output["message"]
                    content = message.get("content", [])
                    texts = [part.get("text", "") for part in content if isinstance(part, dict)]
                    return "\n".join(t for t in texts if t).strip()
        return ""

    async def _invoke_bedrock(
        self,
        messages: List[Dict[str, str]],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Invoke Bedrock model using Converse API with fallback to InvokeModel."""
        bedrock_messages = self._convert_to_bedrock_messages(messages, context)
        if not bedrock_messages:
            raise ValueError("At least one message with content is required for Bedrock invocation")

        # Merge context max_tokens into model_kwargs temporarily for this call
        original_max_tokens = self.model_kwargs.get("max_tokens")
        if context and "max_tokens" in context:
            self.model_kwargs["max_tokens"] = context["max_tokens"]
        
        try:
            inference_config = self._build_inference_config()
        finally:
            # Restore original max_tokens
            if original_max_tokens is not None:
                self.model_kwargs["max_tokens"] = original_max_tokens
            elif "max_tokens" in self.model_kwargs:
                del self.model_kwargs["max_tokens"]

        async def _call_converse() -> Dict[str, Any]:
            loop = asyncio.get_running_loop()

            def _do_call() -> Dict[str, Any]:
                request_payload: Dict[str, Any] = {
                    "modelId": self.model_id,
                    "messages": bedrock_messages,
                }
                if inference_config:
                    request_payload["inferenceConfig"] = inference_config
                additional_fields = {
                    key: value for key, value in self.model_kwargs.items()
                    if key not in {"temperature", "top_p", "max_tokens", "p", "stop_sequences", "stopWords"}
                }
                # Do NOT set response_format on Converse (it caused ValidationException);
                # we will set it on InvokeModel payload instead.
                if additional_fields:
                    request_payload["additionalModelRequestFields"] = additional_fields
                return self.bedrock_client.converse(**request_payload)

            return await loop.run_in_executor(None, _do_call)

        async def _call_invoke() -> Dict[str, Any]:
            loop = asyncio.get_running_loop()

            def _do_call() -> Dict[str, Any]:
                # For Nova models via InvokeModel, use the native request format
                payload: Dict[str, Any] = {
                    "messages": bedrock_messages,
                }
                # Enforce strict JSON response when requested
                if context and context.get("expect_json"):
                    payload.setdefault("additionalModelRequestFields", {})
                    payload["additionalModelRequestFields"]["response_format"] = {"type": "json"}
                
                # Nova models require inferenceConfig structure
                if inference_config:
                    inference_params = {}
                    if "maxTokens" in inference_config:
                        inference_params["max_new_tokens"] = inference_config["maxTokens"]
                    if "temperature" in inference_config:
                        inference_params["temperature"] = inference_config["temperature"]
                    if "topP" in inference_config:
                        inference_params["top_p"] = inference_config["topP"]
                    if "stopSequences" in inference_config:
                        inference_params["stop_sequences"] = inference_config["stopSequences"]
                    
                    if inference_params:
                        payload["inferenceConfig"] = inference_params

                response = self.bedrock_client.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(payload).encode("utf-8"),
                    accept="application/json",
                    contentType="application/json"
                )
                return response

            return await loop.run_in_executor(None, _do_call)

        if self.use_converse_api:
            try:
                response = await _call_converse()
                text = self._extract_text_from_converse(response)
                if text:
                    logger.info("Bedrock converse call succeeded for model %s", self.model_id)
                    return text
                logger.warning("Bedrock Converse response contained no text, falling back to legacy InvokeModel")
            except ClientError as converse_error:
                error_code = converse_error.response["Error"].get("Code")
                logger.warning(
                    "Bedrock converse call failed, attempting legacy invoke_model",
                    error=error_code,
                    message=converse_error.response["Error"].get("Message")
                )
            except Exception as converse_exception:
                logger.warning(f"Unexpected converse error: {converse_exception}")

        response = await _call_invoke()
        text = self._extract_text_from_invoke(response)
        if text:
            logger.info("Bedrock invoke_model call succeeded for model %s", self.model_id)
            return text

        logger.warning("Bedrock invoke_model response contained no text output")
        return ""
    
    async def generate_finops_response(
        self,
        query: str,
        cost_data: Optional[Dict[str, Any]] = None,
        analysis_results: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, List[str]]:
        """
        Generate a comprehensive FinOps expert response with rich formatting.
        
        Args:
            query: User's question or request
            cost_data: Processed cost data (daily_costs, service_costs, etc.)
            analysis_results: Analysis outputs (totals, trends, insights, etc.)
            conversation_history: Previous messages in conversation for context
            context: Additional conversation context (previous queries, intents, etc.)
            
        Returns:
            Tuple of (formatted_response, suggested_followup_questions)
        """
        # Check if LLM is properly initialized
        if not self.initialized:
            logger.warning(f"LLM not initialized, using fallback response. Error: {self.initialization_error}")
            fallback_response = self._create_fallback_response(query, cost_data, analysis_results)
            fallback_suggestions = self._generate_static_followup_suggestions(query, cost_data, analysis_results, context)
            return fallback_response, fallback_suggestions
        
        try:
            # Build comprehensive context for the LLM
            messages = [
                {"role": "system", "content": FINOPS_EXPERT_SYSTEM_PROMPT}
            ]
            
            # Add conversation history for context continuity
            if conversation_history and len(conversation_history) > 0:
                # Include last 3 exchanges for context
                for msg in conversation_history[-6:]:  # Last 3 Q&A pairs
                    messages.append(msg)
            
            # Build data context
            data_context_parts = []
            
            if cost_data:
                data_context_parts.append(self._format_cost_summary(cost_data))
            
            if analysis_results:
                data_context_parts.append(self._format_analysis_summary(analysis_results))
            
            if context:
                data_context_parts.append(self._format_conversation_context(context))
            
            # Create the user prompt with all context
            user_prompt = f"""User Query: {query}

"""
            
            if data_context_parts:
                user_prompt += "Available Data:\n" + "\n\n".join(data_context_parts)
            
            user_prompt += """

Please provide a comprehensive, well-formatted response using markdown. Include:
1. Direct answer to the user's question
2. Key insights and interpretation of the data
3. Relevant context or explanations
4. Actionable recommendations if applicable

Format your response beautifully with markdown for optimal readability."""
            
            messages.append({"role": "user", "content": user_prompt})
            
            # Generate response
            response_text = await self.generate_response(messages, context)
            
            # Generate contextual follow-up suggestions
            suggestions = await self._generate_followup_suggestions(
                query, cost_data, analysis_results, context
            )
            
            return response_text, suggestions
            
        except Exception as e:
            logger.error(f"Error generating FinOps response: {e}", exc_info=True)
            fallback_response = self._create_fallback_response(query, cost_data, analysis_results)
            fallback_suggestions = self._generate_static_followup_suggestions(query, cost_data, analysis_results, context)
            return fallback_response, fallback_suggestions
    
    def _generate_static_followup_suggestions(
        self,
        query: str,
        cost_data: Optional[Dict[str, Any]],
        analysis: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]]
    ) -> List[str]:
        """Generate static follow-up suggestions without LLM call (fallback)."""
        suggestions = []
        
        query_lower = query.lower() if query else ""
        
        # Query-specific suggestions
        if "top" in query_lower and ("service" in query_lower or "cost" in query_lower):
            suggestions.extend([
                "How can I optimize costs for these services?",
                "Show me cost trends for the top services",
                "Compare these costs to last month"
            ])
        elif "trend" in query_lower or "over time" in query_lower:
            suggestions.extend([
                "What caused the biggest cost changes?",
                "Show me a breakdown by service",
                "Generate cost optimization recommendations"
            ])
        elif "optimize" in query_lower or "reduce" in query_lower:
            suggestions.extend([
                "Show me unused resources",
                "Analyze EC2 right-sizing opportunities",
                "What are my reserved instance utilization rates?"
            ])
        elif "compare" in query_lower:
            suggestions.extend([
                "Break down costs by AWS account",
                "Show me regional cost distribution",
                "Compare costs across different time periods"
            ])
        else:
            suggestions.extend([
                "Show me my top 5 most expensive services",
                "How do my costs compare to last month?",
                "Generate cost optimization recommendations"
            ])
        
        return suggestions[:4]
    
    def _format_cost_summary(self, cost_data: Dict[str, Any]) -> str:
        """Format cost data into readable summary for LLM context."""
        summary_parts = []
        
        total_cost = cost_data.get("total_cost", 0)
        if total_cost:
            summary_parts.append(f"Total Cost: ${total_cost:,.2f}")
        
        # Daily costs trend
        daily_costs = cost_data.get("daily_costs", {})
        if daily_costs and len(daily_costs) > 0:
            dates = sorted(daily_costs.keys())
            summary_parts.append(f"Cost data spans {len(dates)} days from {dates[0]} to {dates[-1]}")
            
            # Calculate daily stats
            costs = [daily_costs[d] for d in dates]
            avg_daily = sum(costs) / len(costs) if costs else 0
            max_daily = max(costs) if costs else 0
            min_daily = min(costs) if costs else 0
            
            summary_parts.append(f"Daily cost range: ${min_daily:,.2f} to ${max_daily:,.2f} (avg: ${avg_daily:,.2f})")
        
        # Service breakdown
        service_costs = cost_data.get("service_costs", {})
        if service_costs:
            sorted_services = sorted(service_costs.items(), key=lambda x: x[1], reverse=True)
            top_5 = sorted_services[:5]
            summary_parts.append("\nTop Services by Cost:")
            for i, (service, cost) in enumerate(top_5, 1):
                percentage = (cost / total_cost * 100) if total_cost else 0
                summary_parts.append(f"  {i}. {service}: ${cost:,.2f} ({percentage:.1f}%)")
        
        return "Cost Data:\n" + "\n".join(summary_parts)
    
    def _format_analysis_summary(self, analysis: Dict[str, Any]) -> str:
        """Format analysis results into readable summary."""
        summary_parts = []
        
        # Total and averages
        if "total_cost" in analysis:
            summary_parts.append(f"Total Cost: ${analysis['total_cost']:,.2f}")
        
        if "average_daily_cost" in analysis:
            summary_parts.append(f"Average Daily Cost: ${analysis['average_daily_cost']:,.2f}")
        
        # Trend information
        trend = analysis.get("cost_trend", {})
        if trend:
            trend_direction = trend.get("trend", "stable")
            percent_change = trend.get("percent_change", 0)
            summary_parts.append(f"Cost Trend: {trend_direction} ({percent_change:+.1f}%)")
        
        # Top services
        top_services = analysis.get("top_services", {})
        if top_services:
            top_n = analysis.get("top_services_count", len(top_services))
            summary_parts.append(f"\nTop {top_n} Most Expensive Services:")
            for i, (service, cost) in enumerate(list(top_services.items())[:top_n], 1):
                summary_parts.append(f"  {i}. {service}: ${cost:,.2f}")
        
        # Service count
        if "unique_services" in analysis:
            summary_parts.append(f"\nTotal Unique Services: {analysis['unique_services']}")
        
        return "Analysis Results:\n" + "\n".join(summary_parts)
    
    def _format_conversation_context(self, context: Dict[str, Any]) -> str:
        """Format conversation context for LLM."""
        context_parts = []
        
        if context.get("previous_query"):
            context_parts.append(f"Previous Query: {context['previous_query']}")
        
        if context.get("last_intent"):
            context_parts.append(f"Last Intent: {context['last_intent']}")
        
        if context.get("services_analyzed"):
            services = context.get("services_analyzed", [])
            if services:
                context_parts.append(f"Services Previously Analyzed: {', '.join(services)}")
        
        if context.get("time_range"):
            time_range = context["time_range"]
            if isinstance(time_range, dict):
                period = time_range.get("period", "N/A")
                context_parts.append(f"Time Period: {period}")
        
        return "Conversation Context:\n" + "\n".join(context_parts) if context_parts else ""
    
    def _create_fallback_response(
        self, 
        query: str,
        cost_data: Optional[Dict[str, Any]],
        analysis: Optional[Dict[str, Any]]
    ) -> str:
        """Create a query-aware fallback response if LLM fails."""
        response_parts = []
        query_lower = query.lower() if query else ""
        
        # Extract key metrics
        total_cost = analysis.get("total_cost", 0) if analysis else 0
        avg_daily = analysis.get("average_daily_cost", 0) if analysis else 0
        top_services = analysis.get("top_services", {}) if analysis else {}
        trend = analysis.get("cost_trend", {}) if analysis else {}
        
        # Query-specific responses
        if "top" in query_lower and any(num in query_lower for num in ["3", "5", "10", "three", "five", "ten"]):
            # Top services query
            top_n = 3 if "3" in query_lower else (5 if "5" in query_lower else 10)
            response_parts.append(f"## 📊 Top {top_n} Most Expensive AWS Services\n")
            response_parts.append(f"Here are your **top {top_n} cost drivers**:\n")
            
            if top_services:
                for i, (service, cost) in enumerate(list(top_services.items())[:top_n], 1):
                    percentage = (cost / total_cost * 100) if total_cost > 0 else 0
                    response_parts.append(f"{i}. **{service}** - ${cost:,.2f} ({percentage:.1f}%)")
                response_parts.append(f"\n**Total:** ${total_cost:,.2f}")
            
        elif any(word in query_lower for word in ["optimize", "save", "reduce", "quick win"]):
            # Optimization query
            response_parts.append(f"## 💡 Cost Optimization Opportunities\n")
            response_parts.append(f"Based on your **${total_cost:,.2f}** in total spending, here are key areas to focus on:\n")
            
            if top_services:
                top_service = list(top_services.keys())[0]
                top_cost = list(top_services.values())[0]
                response_parts.append(f"**Highest Cost Service:** {top_service} (${top_cost:,.2f})")
                response_parts.append(f"\nReview the optimization recommendations below for specific savings opportunities.")
            
        elif any(word in query_lower for word in ["trend", "over time", "pattern", "growth"]):
            # Trend query
            response_parts.append(f"## 📈 AWS Cost Trends\n")
            response_parts.append(f"I've analyzed your cost trends:\n")
            response_parts.append(f"**Total Spending:** ${total_cost:,.2f}")
            
            if avg_daily > 0:
                response_parts.append(f"**Average Daily Cost:** ${avg_daily:,.2f}")
            
            if trend.get("trend"):
                trend_direction = trend["trend"]
                percent_change = trend.get("percent_change", 0)
                
                if trend_direction == "increasing":
                    response_parts.append(f"\n📈 Costs are **trending upward** ({percent_change:+.1f}% change)")
                elif trend_direction == "decreasing":
                    response_parts.append(f"\n📉 Costs are **trending downward** ({percent_change:+.1f}% change)")
                else:
                    response_parts.append(f"\n➡️ Costs are **relatively stable**")
            
        elif "breakdown" in query_lower or "distribution" in query_lower:
            # Breakdown query
            response_parts.append(f"## 📊 AWS Cost Breakdown\n")
            response_parts.append(f"**Total Spending:** ${total_cost:,.2f}\n")
            response_parts.append(f"**Average Daily Cost:** ${avg_daily:,.2f}\n")
            
            if top_services:
                response_parts.append("\n**Top Services:**")
                for i, (service, cost) in enumerate(list(top_services.items())[:5], 1):
                    percentage = (cost / total_cost * 100) if total_cost > 0 else 0
                    response_parts.append(f"{i}. {service}: ${cost:,.2f} ({percentage:.1f}%)")
            
        else:
            # General cost analysis
            response_parts.append(f"## 💰 AWS Cost Analysis\n")
            period = analysis.get("time_range", {}).get("period", "30d") if analysis else "30d"
            response_parts.append(f"I've analyzed your AWS costs for {period}.\n")
            response_parts.append(f"**Total spending:** ${total_cost:,.2f}")
            
            if avg_daily > 0:
                response_parts.append(f" (avg ${avg_daily:,.2f}/day)")
            
            response_parts.append("\n")
            
            # Add trend if available
            if trend.get("trend"):
                trend_desc = trend["trend"]
                percent_change = trend.get("percent_change", 0)
                response_parts.append(f"**Trend:** {trend_desc.capitalize()} ({percent_change:+.1f}%)\n")
            
            # Add top services
            if top_services:
                response_parts.append("**Top Cost Drivers:**")
                for i, (service, cost) in enumerate(list(top_services.items())[:3], 1):
                    response_parts.append(f"{i}. {service}: ${cost:,.2f}")
        
        # Add reference to visualizations
        response_parts.append("\n\nThe visualizations below show cost breakdowns and trends. Let me know if you'd like to dive deeper into any specific area.")
        
        return "\n".join(response_parts)
    
    async def _generate_followup_suggestions(
        self,
        query: str,
        cost_data: Optional[Dict[str, Any]],
        analysis: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]]
    ) -> List[str]:
        """Generate intelligent follow-up question suggestions."""
        suggestions = []
        query_lower = query.lower()
        
        # Get top service if available
        top_services = {}
        if analysis and "top_services" in analysis:
            top_services = analysis["top_services"]
        
        top_service = list(top_services.keys())[0] if top_services else None
        
        # Context-aware suggestions based on query type
        if "top" in query_lower and "service" in query_lower:
            # User just asked about top services
            if top_service:
                service_short = self._get_service_short_name(top_service)
                suggestions.extend([
                    f"How can I optimize my {service_short} costs?",
                    f"Show me {service_short} cost trends over the last quarter",
                    "What are the second and third biggest cost drivers?"
                ])
        
        elif any(word in query_lower for word in ["optimize", "reduce", "save"]):
            # User asked about optimization
            suggestions.extend([
                "What are my Reserved Instance coverage opportunities?",
                "Show me underutilized resources that I can downsize",
                "Generate a detailed cost optimization report"
            ])
        
        elif any(word in query_lower for word in ["spike", "increase", "high"]):
            # User concerned about cost increases
            suggestions.extend([
                "Compare this week's costs with last week",
                "Which services contributed most to the spike?",
                "Show me hourly cost breakdown for the spike period"
            ])
        
        elif any(word in query_lower for word in ["trend", "pattern", "forecast"]):
            # User interested in trends
            suggestions.extend([
                "Project my costs for next month based on current trends",
                "Show me year-over-year cost comparison",
                "Which services show unusual cost patterns?"
            ])
        
        elif "breakdown" in query_lower or "split" in query_lower:
            # User wants detailed breakdown
            suggestions.extend([
                "Break down costs by AWS account and region",
                "Show me costs grouped by resource tags",
                "What's the cost breakdown by usage type?"
            ])
        
        else:
            # Generic follow-up suggestions
            suggestions.extend([
                "Show me my top 5 most expensive services",
                "How do my costs compare to last month?",
                "Generate cost optimization recommendations",
                "What caused the biggest cost changes recently?"
            ])
        
        # Limit to 3-4 most relevant suggestions
        return suggestions[:4]
    
    def _get_service_short_name(self, full_service_name: str) -> str:
        """Convert full AWS service name to short name."""
        mappings = {
            "Amazon Elastic Compute Cloud - Compute": "EC2",
            "Amazon Simple Storage Service": "S3",
            "Amazon Relational Database Service": "RDS",
            "Amazon CloudFront": "CloudFront",
            "AWS Lambda": "Lambda",
            "Amazon DynamoDB": "DynamoDB",
            "Amazon Elastic Kubernetes Service": "EKS",
            "Amazon Virtual Private Cloud": "VPC"
        }
        return mappings.get(full_service_name, full_service_name)
    
    async def generate_response(
        self, 
        messages: List[Dict[str, str]], 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate response using Bedrock model.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            context: Optional context for the conversation
            
        Returns:
            Generated response string
        """
        # Check if initialized
        if not self.initialized:
            logger.warning("Bedrock not initialized, returning fallback message")
            return "I apologize, but I'm currently unable to generate AI-powered responses. Please check the AWS Bedrock configuration."
        
        try:
            response_text = await self._invoke_bedrock(messages, context)
            if response_text:
                return response_text.strip()
            logger.warning("Empty response from Bedrock")
            return "I apologize, but I couldn't generate a response. Please try again."
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Bedrock API error {error_code}: {error_message}", exc_info=True)
            
            if error_code == 'ValidationException':
                return "I encountered a validation error. Please check your input and try again."
            elif error_code == 'ThrottlingException':
                return "I'm currently experiencing high demand. Please try again in a moment."
            elif error_code == 'ModelNotReadyException':
                return "The AI model is currently loading. Please try again in a few moments."
            elif error_code == 'AccessDeniedException':
                return "I don't have permission to access the AI model. Please check AWS Bedrock permissions."
            elif error_code == 'ResourceNotFoundException':
                return "The AI model was not found. Please verify the Bedrock model configuration."
            else:
                return f"I encountered an AWS error: {error_message}"
                
        except BotoCoreError as e:
            logger.error(f"AWS connection error: {e}", exc_info=True)
            return "I'm having trouble connecting to AWS services. Please check the network and AWS configuration."
            
        except Exception as e:
            logger.error(f"Unexpected error in LLM generation: {e}", exc_info=True)
            return "I encountered an unexpected error. Please try again."
    
    async def call_llm(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Simple wrapper for calling the LLM with a prompt and optional system prompt.
        Used by agents that need basic LLM calls.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt (will be prepended to user message for Nova)
            context: Optional context dictionary
            max_tokens: Optional override for max tokens (defaults to settings value)
            
        Returns:
            LLM response text
        """
        messages = []
        
        # For Amazon Nova, prepend system prompt to user message if provided
        if system_prompt:
            prompt = f"{system_prompt}\n\n{prompt}"
        
        messages.append({"role": "user", "content": prompt})
        
        # Add max_tokens to context if provided
        if max_tokens and context is None:
            context = {}
        if max_tokens:
            context["max_tokens"] = max_tokens
        
        return await self.generate_response(messages, context)
    
    async def generate_structured_response(
        self, 
        prompt: str, 
        schema: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate structured response following a specific schema.
        
        Args:
            prompt: The prompt for generation
            schema: JSON schema for the expected response structure
            context: Optional context for the conversation
            
        Returns:
            Structured response as dictionary
        """
        try:
            # Create structured prompt
            structured_prompt = f"""
{prompt}

Please respond with valid JSON that follows this exact schema:
{json.dumps(schema, indent=2)}

Ensure your response is properly formatted JSON only, no additional text.
"""
            
            messages = [{"role": "user", "content": structured_prompt}]
            response = await self.generate_response(messages, context)
            
            # Try to parse as JSON
            try:
                return json.loads(response)
            except json.JSONDecodeError as json_err:
                # If direct parsing fails, try to extract JSON from response
                import re
                logger.warning(f"JSON decode failed: {json_err}, attempting to extract JSON from response")
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    try:
                        extracted_json = json_match.group()
                        return json.loads(extracted_json)
                    except json.JSONDecodeError as extract_err:
                        logger.error(f"Could not parse extracted JSON: {extract_err}")
                        logger.error(f"Raw LLM response (first 500 chars): {response[:500]}")
                        return {"error": "Could not parse structured response", "raw_response": response[:500]}
                else:
                    logger.error(f"No JSON found in LLM response (first 500 chars): {response[:500]}")
                    return {"error": "Could not parse structured response", "raw_response": response[:500]}
                    
        except Exception as e:
            logger.error(f"Error generating structured response: {e}")
            return {"error": str(e)}
    
    async def normalize_query_prompt(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Use the LLM to normalize ambiguous user queries into a canonical phrasing.
        Returns None if the LLM is unavailable or the response cannot be parsed.
        """
        if not self.initialized:
            logger.debug("LLM normalize_query_prompt skipped - service uninitialized")
            return None
        
        context_str = "None"
        if context:
            try:
                context_str = json.dumps(context, indent=2, default=str)
            except TypeError:
                context_str = str(context)
        
        schema = {
            "type": "object",
            "properties": {
                "normalized_query": {"type": "string"},
                "intent_hint": {"type": ["string", "null"]},
                "time_range_hint": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "requires_disambiguation": {"type": "boolean"},
                "notes": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["normalized_query", "confidence", "requires_disambiguation"]
        }
        
        instructions = f"""
You are a FinOps query normalizer. Rewrite the user request into a precise, unambiguous instruction for AWS cost analysis.

Return strictly-valid JSON with these fields:
- "normalized_query" (string)
- "intent_hint" (string or null)
- "time_range_hint" (string or null)
- "confidence" (number between 0 and 1)
- "requires_disambiguation" (boolean)
- "notes" (array of brief strings)

Rules:
- Preserve all numeric values, service names, dates, and filters exactly as provided.
- Do not invent missing information. If details are unclear, set "requires_disambiguation" to true and explain briefly in "notes".
- Prefer concise, declarative language (e.g., "Show top 5 services by cost for July 2024").
- If the user query is already clear, return it unchanged.
- Never fabricate cost numbers or time ranges.

Additional context (may be empty):
{context_str}

User query:
\"\"\"{query}\"\"\"
"""
        response = await self.generate_structured_response(instructions, schema)
        if not response or response.get("error"):
            logger.warning("LLM normalize_query_prompt returned error", details=response)
            return None
        
        normalized = response.get("normalized_query")
        if not normalized or not isinstance(normalized, str):
            logger.warning("LLM normalize_query_prompt missing normalized_query", response=response)
            return None
        
        result = {
            "normalized_query": normalized.strip(),
            "intent_hint": response.get("intent_hint"),
            "time_range_hint": response.get("time_range_hint"),
            "confidence": float(response.get("confidence", 0.0)),
            "requires_disambiguation": bool(response.get("requires_disambiguation", False)),
            "notes": response.get("notes") or []
        }
        return result
    
    async def analyze_cost_data(
        self, 
        cost_data: Dict[str, Any], 
        query: str,
        analysis_type: str = "general"
    ) -> str:
        """
        Analyze cost data using Bedrock LLM.
        
        Args:
            cost_data: Cost data to analyze
            query: User's query about the cost data
            analysis_type: Type of analysis (general, trend, optimization, etc.)
            
        Returns:
            Analysis response
        """
        try:
            # Create analysis prompt based on type
            if analysis_type == "trend":
                system_prompt = """You are an expert FinOps consultant with decades of experience analyzing AWS cost trends and patterns. 
                Provide insights on cost patterns, growth rates, and trend analysis with the depth of a seasoned cloud economist.
                Focus on identifying concerning trends, seasonal patterns, and opportunities for optimization.
                Use your expertise to explain WHY trends are occurring and what actions should be taken."""
            elif analysis_type == "optimization":
                system_prompt = """You are an expert FinOps consultant specializing in AWS cost optimization with years of experience reducing enterprise cloud spend.
                Analyze the cost data and provide specific, actionable recommendations to reduce costs.
                Include estimated savings, implementation steps, and risk assessments for each recommendation.
                Prioritize quick wins and high-impact optimizations based on your extensive experience."""
            elif analysis_type == "executive":
                system_prompt = """You are a senior FinOps executive preparing board-level AWS cost summaries for C-suite audiences.
                Provide a high-level overview suitable for CEOs, CFOs, and CTOs with decades of experience in cloud financial management.
                Focus on key metrics, business impact, trends, and strategic recommendations.
                Use executive-level language and emphasize ROI, risk, and strategic alignment."""
            else:
                system_prompt = """You are an expert FinOps consultant with decades of AWS cost management experience.
                Provide clear, actionable insights based on the data and user query.
                Draw on your deep expertise to explain patterns, identify issues, and recommend solutions."""
            
            # Format cost data for analysis
            data_summary = self._format_cost_data_for_analysis(cost_data)
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""
Cost Data Summary:
{data_summary}

User Query: {query}

Please analyze this cost data and provide insights relevant to the query.
"""}
            ]
            
            return await self.generate_response(messages)
            
        except Exception as e:
            logger.error(f"Error analyzing cost data: {e}")
            return f"I encountered an error while analyzing the cost data: {str(e)}"
    
    def _format_cost_data_for_analysis(self, cost_data: Dict[str, Any]) -> str:
        """Format cost data for LLM analysis."""
        try:
            # Extract key metrics and format for readability
            formatted_data = []
            
            if "total_cost" in cost_data:
                formatted_data.append(f"Total Cost: ${cost_data['total_cost']:,.2f}")
            
            if "services" in cost_data:
                formatted_data.append("\nTop Services by Cost:")
                for service in cost_data["services"][:10]:  # Top 10 services
                    formatted_data.append(f"  - {service['name']}: ${service['cost']:,.2f}")
            
            if "time_series" in cost_data:
                formatted_data.append(f"\nTime Period: {len(cost_data['time_series'])} data points")
                
            if "regions" in cost_data:
                formatted_data.append("\nTop Regions by Cost:")
                for region in cost_data["regions"][:5]:  # Top 5 regions
                    formatted_data.append(f"  - {region['name']}: ${region['cost']:,.2f}")
            
            return "\n".join(formatted_data)
            
        except Exception as e:
            logger.warning(f"Error formatting cost data: {e}")
            return str(cost_data)
    
    async def health_check(self) -> Dict[str, Any]:
        """Check if Bedrock service is available and responsive."""
        try:
            # Simple test message
            test_messages = [{"role": "user", "content": "Hello, please respond with 'Service is healthy'"}]
            response = await self.generate_response(test_messages)
            
            return {
                "status": "healthy",
                "model_id": self.model_id,
                "region": self.region,
                "response": response
            }
            
        except Exception as e:
            logger.error(f"Bedrock health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "model_id": self.model_id,
                "region": self.region
            }
    
    def get_available_models(self) -> List[str]:
        """Get list of available Bedrock models."""
        return self.settings.available_models
    
    def validate_model_id(self, model_id: str) -> bool:
        """
        Validate if a model ID is in the list of available models.
        
        Args:
            model_id: The Bedrock model ID to validate
            
        Returns:
            True if model is available, False otherwise
        """
        return model_id in self.settings.available_models
    
    async def set_model(self, model_id: str) -> Dict[str, Any]:
        """
        Dynamically switch to a different Bedrock model.
        
        Args:
            model_id: The Bedrock model ID to switch to
            
        Returns:
            Dictionary with status and model information
        """
        try:
            # Validate model ID
            if not self.validate_model_id(model_id):
                return {
                    "status": "error",
                    "message": f"Model {model_id} is not in the list of available models",
                    "available_models": self.get_available_models()
                }
            
            # Update model configuration
            old_model = self.model_id
            self.model_id = model_id
            self.model_kwargs = self._get_model_kwargs(model_id)
            self.use_converse_api = self._should_use_converse_api(model_id)
            
            logger.info(
                "Switched Bedrock model",
                previous_model=old_model,
                current_model=model_id,
                use_converse_api=self.use_converse_api
            )
            
            return {
                "status": "success",
                "message": f"Successfully switched to model {model_id}",
                "previous_model": old_model,
                "current_model": self.model_id
            }
            
        except Exception as e:
            logger.error(f"Error switching model to {model_id}: {e}")
            return {
                "status": "error",
                "message": f"Failed to switch model: {str(e)}",
                "current_model": self.model_id
            }
    
    def get_current_model(self) -> Dict[str, str]:
        """
        Get information about the currently active model.
        
        Returns:
            Dictionary with current model information
        """
        return {
            "model_id": self.model_id,
            "region": self.region,
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature
        }
    
    async def understand_followup_intent(
        self,
        query: str,
        previous_query: str,
        previous_response: str
    ) -> Dict[str, Any]:
        """
        Use LLM to understand follow-up query intent and extract parameters.
        Fallback for when pattern matching fails.
        
        Args:
            query: Current follow-up query
            previous_query: Previous user query
            previous_response: Previous assistant response
            
        Returns:
            Dictionary with understood intent, action, and parameters
        """
        if not self.initialized:
            logger.warning("LLM not initialized, returning default interpretation")
            return {
                "action": "unclear",
                "confidence": 0.3,
                "interpretation": "Unable to understand follow-up without LLM",
                "suggested_clarification": "Could you please rephrase your question?"
            }
        
        system_prompt = """You are an expert FinOps consultant with decades of experience understanding how technical teams and finance managers naturally explore cloud cost data through conversational follow-ups.

Your expertise:
- Understanding conversational references ("that service", "the 4th item", "those costs")
- Recognizing when users want to drill deeper vs. pivot to new analysis
- Interpreting time period changes ("last year", "last quarter", "30 days")
- Distinguishing between filters (include specific items) and exclusions (remove items)
- Knowing when users want more detail on existing data vs. need new data queries

Analyze the follow-up query and determine what the user wants. Respond ONLY with a JSON object (no markdown, no explanation) with these fields:
- "action": one of ["expand_detail", "filter", "exclude", "time_change", "compare", "clarify", "new_query", "breakdown"]
- "confidence": float 0-1
- "interpretation": brief description of what user wants
- "parameters": dict with extracted parameters (e.g., {"point_number": 4, "exclude_items": ["tax"], "time_period": "last year"})
- "requires_requery": boolean (true if need to fetch new data, false if can expand existing response)

Examples:
- "give me more details on the 4th point" → {"action": "expand_detail", "point_number": 4, "requires_requery": false}
- "breakdown CloudWatch" → {"action": "breakdown", "service": "CloudWatch", "requires_requery": true}
- "exclude tax" → {"action": "exclude", "exclude_items": ["tax"], "requires_requery": true}
- "show me for last year" → {"action": "time_change", "time_period": "last year", "requires_requery": true}"""

        user_prompt = f"""Previous Query: "{previous_query}"

Previous Response Summary: {previous_response[:500]}...

Current Follow-up Query: "{query}"

Analyze this follow-up query and provide JSON response."""

        try:
            messages = [{"role": "user", "content": user_prompt}]
            response = await self.generate_response(
                messages=messages,
                context={"system_prompt": system_prompt}
            )
            
            # Try to parse JSON from response
            response_text = response.strip()
            # Remove markdown code blocks if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(response_text)
            logger.info(f"LLM understood follow-up: {result}")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}, response: {response_text[:200]}")
            return {
                "action": "unclear",
                "confidence": 0.3,
                "interpretation": "Unable to parse follow-up intent",
                "requires_requery": False
            }
        except Exception as e:
            logger.error(f"Error in LLM follow-up understanding: {e}")
            return {
                "action": "unclear",
                "confidence": 0.3,
                "interpretation": str(e),
                "requires_requery": False
            }
    
    async def classify_intent(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Use LLM to classify query intent for FinOps cost analysis.
        More flexible than rule-based classification for diverse user queries.
        
        Args:
            query: User's natural language query
            context: Optional conversation context
            
        Returns:
            Dictionary with intent, confidence, and extracted parameters
        """
        if not self.initialized:
            logger.warning("LLM not initialized, cannot classify intent")
            return {
                "intent": "OTHER",
                "confidence": 0.0,
                "extracted_params": {},
                "error": "LLM not available"
            }
        
        # Define the 10 intent types for FinOps
        intent_types = """
COST_BREAKDOWN: Show cost breakdown by service, region, account, etc. (e.g., "break down my costs by service")
TOP_N_RANKING: Show top N services/regions by cost (e.g., "what are my top 5 services")
ANOMALY_ANALYSIS: Detect unusual spending patterns (e.g., "any cost anomalies this month")
COST_TREND: Show cost trends over time (e.g., "how have costs changed over time")
UTILIZATION: Analyze resource utilization (e.g., "how utilized are my EC2 instances")
OPTIMIZATION: Cost optimization recommendations (e.g., "how can I reduce costs")
GOVERNANCE: Compliance and governance checks (e.g., "show untagged resources")
DATA_METADATA: Information about data/metadata (e.g., "what data do you have")
COMPARATIVE: Compare costs across periods/services/environments (e.g., "compare this month to last month", "compare with previous period", "identify growth trends", "show changes vs last period")
OTHER: Anything that doesn't fit above categories
"""
        
        system_prompt = f"""You are an expert FinOps AI assistant with decades of experience categorizing cloud cost analysis queries. You understand how engineers, finance teams, and executives naturally ask about AWS costs, and you can accurately map their questions to specific analysis types.

Your expertise includes:
- Recognizing different types of cost questions (rankings, breakdowns, trends, anomalies, optimizations)
- Understanding technical AWS terminology and natural language variations
- Distinguishing between high-level strategic questions and detailed operational queries
- Interpreting contextual follow-ups that build on previous analyses
- Detecting when users change time periods (e.g., from "last 30 days" to "last 100 days")

Classify this user query into exactly one of these 10 intent categories:

{intent_types}

IMPORTANT: When the user specifies a different time period than the previous query, treat this as a NEW query with the same intent but different parameters. For example:
- Previous: "Show AWS costs for last 30 days" → Current: "for last 100 days" should be classified the same intent but recognize the time period change.

Respond ONLY with a JSON object (no markdown, no explanation) with these fields:
- "intent": one of the 10 intent type constants above
- "confidence": float 0.0-1.0 (how confident you are in the classification)
- "extracted_params": dict with any extracted parameters like services, regions, time_range, etc.
- "reasoning": brief explanation of why you chose this intent

Examples:
- "Show me my AWS costs for last month" → {{"intent": "COST_BREAKDOWN", "confidence": 0.9, "extracted_params": {{"time_range": "last month"}}, "reasoning": "User wants to see cost breakdown for a time period"}}
- "What are my top 5 services by cost" → {{"intent": "TOP_N_RANKING", "confidence": 0.95, "extracted_params": {{"top_n": 5}}, "reasoning": "Explicit request for top N ranking"}}
- "Why are my costs so high this month" → {{"intent": "ANOMALY_ANALYSIS", "confidence": 0.8, "extracted_params": {{"time_range": "this month"}}, "reasoning": "Question about unusual cost patterns"}}"""

        # Build enhanced context with previous query and time range info
        context_info = "No previous context"
        if context:
            last_intent = context.get('last_intent', 'N/A')
            last_query = context.get('last_query', '')
            last_params = context.get('last_params', {})
            last_time_range = last_params.get('time_range', {}) if last_params else {}
            last_time_desc = last_time_range.get('description', 'N/A') if last_time_range else 'N/A'
            
            context_info = f"""Previous intent: {last_intent}
Previous query: "{last_query}"
Previous time range: {last_time_desc}"""

        user_prompt = f"""Classify this FinOps query: "{query}"

Context:
{context_info}

Provide JSON response:"""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response_text = await self.generate_response(messages, context)

            if not response_text:
                logger.warning("Empty response from Bedrock for intent classification")
                return {
                    "intent": "OTHER",
                    "confidence": 0.0,
                    "extracted_params": {},
                    "error": "Empty response"
                }

            try:
                # Strip markdown code fences if present
                cleaned_response = response_text.strip()
                if cleaned_response.startswith("```"):
                    lines = cleaned_response.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    cleaned_response = "\n".join(lines).strip()
                
                result = json.loads(cleaned_response)
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to parse LLM intent response: {json_err}")
                return {
                    "intent": "OTHER",
                    "confidence": 0.0,
                    "extracted_params": {},
                    "error": "Invalid JSON from LLM"
                }

            valid_intents = [
                "COST_BREAKDOWN", "TOP_N_RANKING", "ANOMALY_ANALYSIS", "COST_TREND",
                "UTILIZATION", "OPTIMIZATION", "GOVERNANCE", "DATA_METADATA", "COMPARATIVE", "OTHER"
            ]

            if result.get("intent") not in valid_intents:
                logger.warning(f"LLM returned invalid intent: {result.get('intent')}")
                result["intent"] = "OTHER"
                result["confidence"] = 0.1

            logger.info(f"LLM intent classification: {result.get('intent')} (confidence: {result.get('confidence')})")
            return result

        except Exception as e:
            logger.error(f"LLM intent classification failed: {e}")
            return {
                "intent": "OTHER",
                "confidence": 0.0,
                "extracted_params": {},
                "error": str(e)
            }
    
    async def generate_consolidated_prompt(
        self,
        current_query: str,
        conversation_history: List[Dict[str, str]],
        available_data_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Use LLM to understand entire conversation context and generate a consolidated prompt
        for response generation. This replaces rule-based parameter extraction and inheritance logic.
        
        Args:
            current_query: The current user query
            conversation_history: List of previous messages [{"role": "user"/"assistant", "content": "..."}]
            available_data_context: Optional context about available data (services, time ranges, etc.)
            
        Returns:
            Dictionary with consolidated understanding and prompt
        """
        if not self.initialized:
            logger.warning("LLM not initialized, cannot generate consolidated prompt")
            return {
                "success": False,
                "error": "LLM not available",
                "fallback_prompt": current_query
            }
        
        # Format conversation history
        conversation_text = ""
        for i, msg in enumerate(conversation_history[-10:]):  # Last 10 messages to avoid token limits
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            conversation_text += f"{role.upper()}: {content}\n\n"
        
        # Add current query
        conversation_text += f"USER: {current_query}"
        
        # Format available data context
        data_context = ""
        if available_data_context:
            data_parts = []
            if available_data_context.get("services"):
                data_parts.append(f"Available Services: {', '.join(available_data_context['services'])}")
            if available_data_context.get("time_ranges"):
                data_parts.append(f"Available Time Ranges: {', '.join(available_data_context['time_ranges'])}")
            if available_data_context.get("regions"):
                data_parts.append(f"Available Regions: {', '.join(available_data_context['regions'])}")
            data_context = "\n".join(data_parts)
        
        system_prompt = """You are an expert FinOps consultant with decades of experience managing enterprise-scale AWS cloud costs. Your specialty is understanding complex, multi-turn cost analysis conversations where users progressively drill down from high-level views to granular details, similar to how experienced cloud economists explore cost data.

Your task: Analyze the ENTIRE conversation context and generate a comprehensive, self-contained prompt that captures exactly what the user wants at this point in their cost investigation journey.

Key FinOps expertise to apply:
- Understand hierarchical cost breakdowns (service → usage type → API operation → resource)
- Recognize when users want to drill deeper vs. pivot to new analysis
- Maintain context of filters, time ranges, and scope throughout the conversation
- Know that "breakdown" typically means show a chart with more granular dimensions
- Know that "explain" or "how did you calculate" means provide methodology without charts
- **CRITICAL**: When user asks to "compare with previous period" or "identify growth trends", calculate the previous time period automatically:
  * If current period is last 30 days (Oct 8 - Nov 7), previous period is 30 days before that (Sep 8 - Oct 7)
  * For "last 7 days" current, previous is the 7 days before that
  * For "last 90 days" current, previous is the 90 days before that
  * Return BOTH periods explicitly for comparison

Analyze the conversation history and current query, then create a new prompt that:
1. Includes all relevant context from previous queries (maintained filters, time ranges, scope)
2. Clarifies any ambiguous references (like "that service", "last time", "those costs")
3. Specifies exact time periods, services, filters, breakdown dimensions, and analysis requirements
4. Maintains conversation continuity while allowing appropriate changes
5. Is clear enough that someone with no conversation context could understand and fulfill the request
6. Preserves the user's analytical journey (e.g., if they've drilled into CloudWatch Logs, keep that context)
7. **For comparison requests**: Calculate both current and previous periods automatically and specify both explicitly

Respond ONLY with a JSON object containing:
{
  "consolidated_prompt": "A complete, standalone prompt that could be given to a FinOps assistant",
  "key_changes_from_previous": ["what changed from last query", "what stayed the same"],
  "confidence": 0.0-1.0,
  "requires_new_data": true/false,
  "analysis_focus": "brief description of what to analyze"
}

Guidelines for consolidated prompt:
- Be specific about time periods (use exact dates when possible)
- List all services/regions/filters explicitly
- Include context about what was previously analyzed
- Make it actionable and complete
- Use natural, conversational language
- **For comparisons**: Explicitly state both periods to compare (e.g., "Compare costs for Oct 8 - Nov 7, 2025 vs Sep 8 - Oct 7, 2025")

Examples:
- If previous was "EC2 costs last 30 days" and current is "for 90 days", prompt should be "Analyze EC2 costs for the last 90 days"
- If previous was "EC2 and S3 costs last 30 days" and current is "exclude S3", prompt should be "Analyze EC2 costs for the last 30 days (same period as previous analysis)"
- If ambiguous like "how about 100 days", keep the same services but change to 100 days: "Analyze EC2 and S3 costs for the last 100 days"
- **COMPARISON EXAMPLE**: If previous was "top 5 services last 30 days (Oct 8 - Nov 7, 2025)" and current is "compare with previous period to identify growth trends", prompt should be "Compare the top 5 most expensive services for the current period (Oct 8 - Nov 7, 2025) vs the previous period (Sep 8 - Oct 7, 2025) to identify cost growth trends. Show percentage change for each service."\""""

        user_prompt = f"""CONVERSATION HISTORY:
{conversation_text}

AVAILABLE DATA CONTEXT:
{data_context}

CURRENT QUERY: "{current_query}"

Generate a consolidated prompt that captures the complete user intent from this conversation."""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response_text = await self.generate_response(messages)

            if not response_text:
                logger.warning("Empty response from Bedrock for consolidated prompt")
                return {
                    "success": False,
                    "error": "Empty response from LLM",
                    "fallback_prompt": current_query,
                    "consolidated_prompt": current_query
                }

            result = json.loads(response_text)
            result["success"] = True
            logger.info(f"Generated consolidated prompt with confidence: {result.get('confidence', 0)}")
            return result

        except Exception as e:
            logger.error(f"Failed to generate consolidated prompt: {e}")
            return {
                "success": False,
                "error": str(e),
                "fallback_prompt": current_query,
                "consolidated_prompt": current_query  # Fallback to current query
            }
    
    async def understand_conversation(
        self,
        chat_history: List[Dict[str, Any]],
        current_message: str
    ) -> Dict[str, Any]:
        """
        Use LLM to understand the entire conversation and generate a comprehensive query.
        
        Args:
            chat_history: Full conversation history with role/content/timestamp
            current_message: The latest user message
            
        Returns:
            Dictionary with generated query and context
        """
        if not self.initialized:
            logger.warning("LLM not initialized, returning current message")
            return {
                "success": False,
                "error": "LLM not initialized",
                "generated_query": current_message
            }
        
        # Format conversation history
        conversation_text = ""
        for msg in chat_history[-10:]:  # Last 10 messages to avoid token limits
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            conversation_text += f"{role.upper()}: {content}\n"
        
        system_prompt = """You are an expert FinOps analyst with decades of experience helping engineering teams and finance managers understand their AWS cloud costs.

Your expertise includes:
- Understanding how technical teams naturally explore costs through progressive drill-downs
- Recognizing when users want high-level summaries vs. detailed breakdowns
- Knowing AWS service hierarchies and typical cost analysis patterns
- Interpreting conversational follow-ups that reference previous context

Analyze the entire conversation history and the current user message to understand what the user wants. Generate a comprehensive, actionable query that captures their complete intent.

Your task is to:
1. Understand the conversation context and what has been analyzed so far
2. Interpret the current message in light of the conversation history
3. Generate a clear, complete query that could be processed by a cost analysis system

Respond ONLY with a JSON object (no markdown, no explanation) with these fields:
- "generated_query": A clear, comprehensive query that captures the user's intent
- "context": Additional context about the analysis (e.g., {"focus": "cost optimization", "urgency": "high"})
- "confidence": Float 0-1 indicating confidence in the interpretation

Examples:
- If conversation shows analysis of EC2 costs and user says "what about S3?", generate: "Compare EC2 and S3 costs for the same time period as the previous analysis"
- If user says "show me more details" after seeing a cost breakdown, generate: "Provide detailed breakdown of the costs shown in the previous analysis, including service-level details"
- If user says "exclude taxes" after seeing a bill, generate: "Show costs excluding taxes and fees for the same services and time period as previous" """

        user_prompt = f"""CONVERSATION HISTORY:
{conversation_text}

CURRENT MESSAGE: "{current_message}"

Generate a comprehensive query that captures the user's complete intent from this conversation."""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response_text = await self.generate_response(messages)

            if not response_text:
                logger.warning("Empty response from Bedrock for conversation understanding")
                return {
                    "success": False,
                    "error": "Empty response from LLM",
                    "generated_query": current_message
                }

            result = json.loads(response_text)

            result["success"] = True
            logger.info(f"Conversation understanding successful with confidence: {result.get('confidence', 0)}")
            return result

        except Exception as e:
            logger.error(f"Failed to understand conversation: {e}")
            return {
                "success": False,
                "error": str(e),
                "generated_query": current_message  # Fallback to current message
            }
    

# Global LLM service instance
llm_service = BedrockLLMService()
