"""
Pydantic models for API request/response schemas and data validation
"""

from datetime import datetime, date
from typing import Any, Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class MessageRole(str, Enum):
    """Chat message roles"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChartType(str, Enum):
    """Supported chart types for visualizations"""
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    AREA = "area"
    SCATTER = "scatter"
    DONUT = "donut"
    TREEMAP = "treemap"


class TimeRange(str, Enum):
    """Predefined time ranges for cost analysis"""
    LAST_7_DAYS = "7d"
    LAST_30_DAYS = "30d"
    LAST_90_DAYS = "90d"
    LAST_6_MONTHS = "6m"
    LAST_12_MONTHS = "12m"
    YEAR_TO_DATE = "ytd"
    CUSTOM = "custom"


class AgentType(str, Enum):
    """Types of agents in the system"""
    ORCHESTRATOR = "orchestrator"
    COST_DATA_PROCESSOR = "cost_data_processor"
    EXTERNAL_INTELLIGENCE = "external_intelligence"
    QUERY_INTELLIGENCE = "query_intelligence"
    REPORT_GENERATOR = "report_generator"
    RECOMMENDATION_ENGINE = "recommendation_engine"


# Request Models
class ChatMessage(BaseModel):
    """Chat message model"""
    role: MessageRole
    content: str
    timestamp: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }


class ChatRequest(BaseModel):
    """Chat request payload"""
    message: str = Field(..., min_length=1, max_length=4000, description="User message")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for context")
    chat_history: Optional[List[Dict[str, Any]]] = Field(None, description="Full conversation history")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    include_reasoning: bool = Field(default=False, description="Include AI reasoning in response")
    
    @field_validator('message')
    @classmethod
    def validate_message(cls, v):
        if not v.strip():
            raise ValueError('Message cannot be empty or whitespace only')
        return v.strip()


class CostAnalysisRequest(BaseModel):
    """Cost analysis request parameters"""
    time_range: TimeRange = Field(default=TimeRange.LAST_30_DAYS)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    services: Optional[List[str]] = Field(None, description="AWS services to analyze")
    accounts: Optional[List[str]] = Field(None, description="AWS account IDs")
    regions: Optional[List[str]] = Field(None, description="AWS regions")
    tags: Optional[Dict[str, str]] = Field(None, description="Resource tags filter")
    granularity: Literal["DAILY", "MONTHLY", "HOURLY"] = Field(default="DAILY")
    group_by: Optional[List[str]] = Field(None, description="Group results by dimensions")

    @field_validator('end_date')
    @classmethod
    def validate_date_range(cls, v, values):
        if v and 'start_date' in values.data and values.data['start_date']:
            if v < values.data['start_date']:
                raise ValueError('end_date must be after start_date')
        return v


class ReportRequest(BaseModel):
    """Report generation request"""
    report_type: Literal["executive", "detailed", "trend", "anomaly"] = Field(default="executive")
    time_range: TimeRange = Field(default=TimeRange.LAST_30_DAYS)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    format: Literal["pdf", "excel", "json"] = Field(default="pdf")
    include_charts: bool = Field(default=True)
    filters: Optional[Dict[str, Any]] = None


# Response Models
class ChartData(BaseModel):
    """Chart data structure for Chart.js and Plotly formats"""
    type: str  # Changed from ChartType enum to str for flexibility
    title: str
    data: Union[List[Dict[str, Any]], Dict[str, Any]]  # Support both list (Plotly) and dict (Chart.js)
    config: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class Insight(BaseModel):
    """Cost insight or recommendation"""
    type: Literal["saving", "alert", "trend", "anomaly", "recommendation"]
    title: str
    description: str
    impact: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None


class ActionItem(BaseModel):
    """Actionable recommendation"""
    id: str
    title: str
    description: str
    category: str
    priority: Literal["low", "medium", "high", "critical"]
    estimated_savings: Optional[float] = None
    effort_level: Literal["low", "medium", "high"]
    implementation_time: Optional[str] = None
    dependencies: Optional[List[str]] = None


class AgentResponse(BaseModel):
    """Individual agent response"""
    agent_type: AgentType
    status: Literal["success", "error", "partial"]
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """Chat response payload"""
    message: str
    conversation_id: str
    charts: Optional[List[ChartData]] = None
    insights: Optional[List[Insight]] = None
    action_items: Optional[List[ActionItem]] = None
    suggestions: Optional[List[str]] = None
    agent_responses: Optional[List[AgentResponse]] = None
    reasoning: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    user_intent: Optional[str] = None
    athena_query: Optional[str] = None  # SQL query executed for cost data retrieval
    # Structured response fields
    summary: Optional[str] = None  # Concise summary of findings
    structuredInsights: Optional[List[Dict[str, Any]]] = None  # Structured insights with category/description
    recommendations: Optional[List[Dict[str, Any]]] = None  # Structured recommendations
    results: Optional[List[Dict[str, Any]]] = None  # Data table results
    metadata: Optional[Dict[str, Any]] = None  # Query metadata (time_period, scope, filters, etc.)
    execution_time: float
    timestamp: datetime

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }


class CostData(BaseModel):
    """Cost data point"""
    date: date
    service: str
    account_id: Optional[str] = None
    region: Optional[str] = None
    cost: float
    usage_quantity: Optional[float] = None
    usage_unit: Optional[str] = None
    tags: Optional[Dict[str, str]] = None

    model_config = {
        "json_encoders": {
            date: lambda v: v.isoformat()
        }
    }


class CostAnalysisResponse(BaseModel):
    """Cost analysis response"""
    summary: Dict[str, Any]
    data: List[CostData]
    charts: List[ChartData]
    insights: List[Insight]
    time_range: Dict[str, Any]
    total_cost: float
    cost_change: Optional[Dict[str, float]] = None


class HealthCheck(BaseModel):
    """Health check response"""
    status: Literal["healthy", "unhealthy", "degraded"]
    version: str
    timestamp: datetime
    services: Dict[str, Dict[str, Any]]
    uptime: float

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }


class ErrorResponse(BaseModel):
    """Error response model"""
    detail: str
    error_code: Optional[str] = None
    timestamp: datetime
    trace_id: Optional[str] = None

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }


# Database Models
class ConversationModel(BaseModel):
    """Conversation database model"""
    id: str
    user_id: Optional[str] = None
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessage] = []
    metadata: Optional[Dict[str, Any]] = None

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }


class QueryModel(BaseModel):
    """Query tracking model"""
    id: str
    conversation_id: Optional[str] = None
    query: str
    response: str
    execution_time: float
    agents_used: List[AgentType]
    success: bool
    error: Optional[str] = None
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }