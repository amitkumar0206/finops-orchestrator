"""
Pydantic models for Opportunities API

Defines request/response schemas for:
- Opportunity CRUD operations
- Filtering and sorting
- Status management
- Export functionality
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Literal
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class OpportunityStatus(str, Enum):
    """Status of an optimization opportunity"""
    OPEN = "open"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    DISMISSED = "dismissed"
    EXPIRED = "expired"
    INVALID = "invalid"


class OpportunitySource(str, Enum):
    """Source of the optimization signal"""
    COST_EXPLORER = "cost_explorer"
    TRUSTED_ADVISOR = "trusted_advisor"
    COMPUTE_OPTIMIZER = "compute_optimizer"
    CUR_ANALYSIS = "cur_analysis"
    CUSTOM = "custom"
    MANUAL = "manual"


class OpportunityCategory(str, Enum):
    """Category of optimization"""
    RIGHTSIZING = "rightsizing"
    IDLE_RESOURCES = "idle_resources"
    RESERVED_INSTANCES = "reserved_instances"
    SAVINGS_PLANS = "savings_plans"
    STORAGE_OPTIMIZATION = "storage_optimization"
    DATA_TRANSFER = "data_transfer"
    LICENSING = "licensing"
    ARCHITECTURE = "architecture"
    SCHEDULING = "scheduling"
    SPOT_INSTANCES = "spot_instances"
    OTHER = "other"


class EffortLevel(str, Enum):
    """Implementation effort level"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(str, Enum):
    """Implementation risk level"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImplementationStep(BaseModel):
    """Single implementation step"""
    step: int = Field(..., ge=1, description="Step number")
    action: str = Field(..., min_length=1, description="Action to perform")
    notes: Optional[str] = Field(None, description="Additional notes")


class AffectedResource(BaseModel):
    """Details of an affected resource"""
    resource_id: str = Field(..., description="AWS resource ID/ARN")
    resource_type: Optional[str] = Field(None, description="Resource type")
    resource_name: Optional[str] = Field(None, description="Human-readable name")
    region: Optional[str] = Field(None, description="AWS region")
    monthly_cost: Optional[float] = Field(None, ge=0, description="Current monthly cost")


class Evidence(BaseModel):
    """Evidence supporting the opportunity"""
    api_trace: Optional[Dict[str, Any]] = Field(None, description="API call trace")
    cur_validation_sql: Optional[str] = Field(None, description="CUR validation SQL query")
    utilization_metrics: Optional[Dict[str, Any]] = Field(None, description="Utilization data")
    lookback_period_days: Optional[int] = Field(None, ge=1, description="Analysis lookback period")
    additional_data: Optional[Dict[str, Any]] = Field(None, description="Additional evidence")


# Request Models

class OpportunityCreate(BaseModel):
    """Request model for creating an opportunity manually"""
    account_id: str = Field(..., min_length=12, max_length=12, description="AWS account ID")
    title: str = Field(..., min_length=1, max_length=500, description="Opportunity title")
    description: str = Field(..., min_length=1, description="Detailed description")
    category: OpportunityCategory = Field(default=OpportunityCategory.OTHER)
    source: OpportunitySource = Field(default=OpportunitySource.MANUAL)
    service: str = Field(..., min_length=1, max_length=100, description="AWS service")
    resource_id: Optional[str] = Field(None, max_length=512, description="Resource ID/ARN")
    resource_name: Optional[str] = Field(None, max_length=255, description="Resource name")
    resource_type: Optional[str] = Field(None, max_length=100, description="Resource type")
    region: Optional[str] = Field(None, max_length=50, description="AWS region")
    estimated_monthly_savings: Optional[float] = Field(None, ge=0, description="Monthly savings estimate")
    current_monthly_cost: Optional[float] = Field(None, ge=0, description="Current monthly cost")
    effort_level: Optional[EffortLevel] = Field(None, description="Implementation effort")
    risk_level: Optional[RiskLevel] = Field(None, description="Implementation risk")
    implementation_steps: Optional[List[ImplementationStep]] = Field(None, description="Steps to implement")
    tags: Optional[List[str]] = Field(None, description="Tags for categorization")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class OpportunityUpdate(BaseModel):
    """Request model for updating an opportunity"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = Field(None, min_length=1)
    category: Optional[OpportunityCategory] = None
    effort_level: Optional[EffortLevel] = None
    risk_level: Optional[RiskLevel] = None
    implementation_steps: Optional[List[ImplementationStep]] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class OpportunityStatusUpdate(BaseModel):
    """Request model for updating opportunity status"""
    status: OpportunityStatus = Field(..., description="New status")
    reason: Optional[str] = Field(None, max_length=1000, description="Reason for status change")


class OpportunityFilter(BaseModel):
    """Filter parameters for listing opportunities"""
    account_ids: Optional[List[str]] = Field(None, description="Filter by AWS account IDs")
    statuses: Optional[List[OpportunityStatus]] = Field(None, description="Filter by status")
    categories: Optional[List[OpportunityCategory]] = Field(None, description="Filter by category")
    sources: Optional[List[OpportunitySource]] = Field(None, description="Filter by source")
    services: Optional[List[str]] = Field(None, description="Filter by AWS service")
    regions: Optional[List[str]] = Field(None, description="Filter by region")
    min_savings: Optional[float] = Field(None, ge=0, description="Minimum monthly savings")
    max_savings: Optional[float] = Field(None, ge=0, description="Maximum monthly savings")
    effort_levels: Optional[List[EffortLevel]] = Field(None, description="Filter by effort level")
    risk_levels: Optional[List[RiskLevel]] = Field(None, description="Filter by risk level")
    tags: Optional[List[str]] = Field(None, description="Filter by tags (any match)")
    search: Optional[str] = Field(None, max_length=500, description="Full-text search query")
    first_detected_after: Optional[datetime] = Field(None, description="Filter by detection date")
    first_detected_before: Optional[datetime] = Field(None, description="Filter by detection date")


class OpportunitySort(str, Enum):
    """Sort options for opportunities"""
    SAVINGS_DESC = "savings_desc"
    SAVINGS_ASC = "savings_asc"
    PRIORITY_DESC = "priority_desc"
    PRIORITY_ASC = "priority_asc"
    FIRST_DETECTED_DESC = "first_detected_desc"
    FIRST_DETECTED_ASC = "first_detected_asc"
    LAST_SEEN_DESC = "last_seen_desc"
    STATUS = "status"
    SERVICE = "service"


class OpportunityListRequest(BaseModel):
    """Request model for listing opportunities with pagination"""
    filter: Optional[OpportunityFilter] = Field(None, description="Filter criteria")
    sort: OpportunitySort = Field(default=OpportunitySort.SAVINGS_DESC, description="Sort order")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class OpportunityExportRequest(BaseModel):
    """Request model for exporting opportunities"""
    filter: Optional[OpportunityFilter] = Field(None, description="Filter criteria")
    format: Literal["csv", "json", "excel"] = Field(default="csv", description="Export format")
    include_evidence: bool = Field(default=False, description="Include detailed evidence")
    include_steps: bool = Field(default=True, description="Include implementation steps")


# Response Models

class OpportunityBase(BaseModel):
    """Base opportunity fields for responses"""
    id: UUID
    account_id: str
    organization_id: Optional[UUID] = None
    created_by_user_id: Optional[UUID] = None  # User who created this opportunity
    title: str
    description: str
    category: OpportunityCategory
    source: OpportunitySource
    source_id: Optional[str] = None
    service: str
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None
    resource_type: Optional[str] = None
    region: Optional[str] = None

    # Savings
    estimated_monthly_savings: Optional[float] = None
    estimated_annual_savings: Optional[float] = None
    savings_percentage: Optional[float] = None
    current_monthly_cost: Optional[float] = None
    projected_monthly_cost: Optional[float] = None
    savings_currency: str = "USD"

    # Implementation
    effort_level: Optional[str] = None
    risk_level: Optional[str] = None

    # Status
    status: OpportunityStatus
    status_reason: Optional[str] = None
    status_changed_by: Optional[str] = None
    status_changed_at: Optional[datetime] = None

    # Priority
    priority_score: Optional[int] = None
    confidence_score: Optional[float] = None
    tags: Optional[List[str]] = None

    # Timestamps
    first_detected_at: datetime
    last_seen_at: datetime
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Links
    deep_link: Optional[str] = None

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }
    }


class OpportunitySummary(BaseModel):
    """Compact opportunity summary for list views"""
    id: UUID
    title: str
    service: str
    category: OpportunityCategory
    status: OpportunityStatus
    estimated_monthly_savings: Optional[float] = None
    priority_score: Optional[int] = None
    effort_level: Optional[str] = None
    risk_level: Optional[str] = None
    resource_id: Optional[str] = None
    region: Optional[str] = None
    first_detected_at: datetime
    last_seen_at: datetime

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }
    }


class OpportunityDetail(OpportunityBase):
    """Full opportunity details including evidence"""
    affected_resources: Optional[List[AffectedResource]] = None
    implementation_steps: Optional[List[ImplementationStep]] = None
    prerequisites: Optional[List[str]] = None
    evidence: Optional[Evidence] = None
    api_trace: Optional[Dict[str, Any]] = None
    cur_validation_sql: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    raw_signal: Optional[Dict[str, Any]] = None


class OpportunityListResponse(BaseModel):
    """Paginated list of opportunities"""
    items: List[OpportunitySummary]
    total: int = Field(..., ge=0, description="Total matching items")
    page: int = Field(..., ge=1, description="Current page")
    page_size: int = Field(..., ge=1, description="Items per page")
    total_pages: int = Field(..., ge=0, description="Total pages")
    has_next: bool = Field(..., description="Has more pages")
    has_prev: bool = Field(..., description="Has previous pages")

    # Aggregations
    total_monthly_savings: Optional[float] = Field(None, description="Sum of savings for filtered items")
    status_counts: Optional[Dict[str, int]] = Field(None, description="Count by status")
    category_counts: Optional[Dict[str, int]] = Field(None, description="Count by category")
    service_counts: Optional[Dict[str, int]] = Field(None, description="Count by service")


class OpportunitiesStats(BaseModel):
    """Statistics summary for opportunities dashboard"""
    total_opportunities: int = Field(..., ge=0)
    open_opportunities: int = Field(..., ge=0)
    total_potential_monthly_savings: float = Field(..., ge=0)
    total_potential_annual_savings: float = Field(..., ge=0)
    implemented_savings_monthly: float = Field(..., ge=0)
    implemented_savings_annual: float = Field(..., ge=0)
    by_status: Dict[str, int]
    by_category: Dict[str, int]
    by_service: Dict[str, int]
    by_source: Dict[str, int]
    by_effort_level: Dict[str, int]
    top_opportunities: List[OpportunitySummary]


class OpportunityIngestResult(BaseModel):
    """Result of ingesting opportunities from AWS signals"""
    total_signals: int = Field(..., ge=0, description="Total signals received")
    new_opportunities: int = Field(..., ge=0, description="New opportunities created")
    updated_opportunities: int = Field(..., ge=0, description="Existing opportunities updated")
    skipped: int = Field(..., ge=0, description="Signals skipped (duplicates, etc.)")
    errors: int = Field(..., ge=0, description="Errors during processing")
    error_details: Optional[List[str]] = Field(None, description="Error messages")
    ingested_at: datetime


class BulkStatusUpdateRequest(BaseModel):
    """Request to update status of multiple opportunities"""
    opportunity_ids: List[UUID] = Field(..., min_length=1, max_length=100)
    status: OpportunityStatus
    reason: Optional[str] = Field(None, max_length=1000)


class BulkStatusUpdateResponse(BaseModel):
    """Response from bulk status update"""
    updated: int
    failed: int
    errors: Optional[List[Dict[str, str]]] = None
