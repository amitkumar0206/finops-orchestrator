from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from datetime import datetime

class UserQueryAnalysis(BaseModel):
    """Structured intent classification output"""
    intent: Literal[
        "cost_analysis", "anomaly_detection", "optimization", 
        "forecasting", "budget_tracking", "resource_analysis",
        "trend_analysis", "comparative_analysis", "drill_down", "general_inquiry"
    ]
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in classification")
    entities: dict[str, List[str]] = Field(default_factory=dict, description="Extracted AWS entities")
    time_range: Optional[str] = None
    requires_history: bool = Field(description="Does query reference previous conversation?")
    ambiguous_references: List[str] = Field(default_factory=list)

class FinOpsQueryPlan(BaseModel):
    """Athena query specification"""
    data_sources: List[Literal["athena_cur", "cloudwatch_metrics", "vector_db"]]
    athena_query: Optional[str] = None
    filters: dict = Field(default_factory=dict)
    aggregations: List[str] = Field(default_factory=list)
    time_range_start: datetime
    time_range_end: datetime
    visualization_type: Optional[Literal["time_series", "bar", "pie", "table"]] = None

class ConversationalResponse(BaseModel):
    """Final structured response"""
    answer: str
    data_summary: dict = Field(default_factory=dict)
    insights: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    chart_specs: Optional[dict] = None
    follow_up_suggestions: List[str] = Field(default_factory=list)
