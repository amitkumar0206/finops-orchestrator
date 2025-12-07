"""
Unified query result structure returned by all data sources.

This standardizes the response format across Athena, Cost Explorer, and any future data sources,
enabling loose coupling between data layer, business logic, and presentation layer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class ResultMetadata:
    """Metadata about query execution and data source."""
    
    data_source: str  # "athena", "cost_explorer", "cloudwatch"
    execution_time_ms: Optional[float] = None
    query_id: Optional[str] = None
    sql_query: Optional[str] = None
    
    # Fallback indicators
    arn_fallback: bool = False
    original_arn: Optional[str] = None
    cost_explorer_fallback: bool = False
    
    # Context for presentation layer
    breakdown_dimension: Optional[str] = None
    breakdown_dimension_label: Optional[str] = None
    top_service_breakdown: Optional[Dict[str, Any]] = None
    resource_type_explanation: Optional[str] = None
    
    # Additional context
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Ensure extra is a dict."""
        if self.extra is None:
            self.extra = {}


@dataclass
class QueryResult:
    """
    Unified result structure from any data source.
    
    This is the contract between the data layer and presentation layer.
    All data sources must return this format.
    """
    
    # Core data
    data: List[Dict[str, Any]]  # Table rows
    metadata: ResultMetadata
    
    # Computed totals
    total_cost: float = 0.0
    row_count: int = 0
    
    # Execution status
    is_empty: bool = False
    error: Optional[str] = None
    
    def __post_init__(self):
        """Auto-compute derived fields."""
        self.row_count = len(self.data)
        self.is_empty = self.row_count == 0
        
        # Auto-compute total_cost from data if not explicitly set
        if self.total_cost == 0 and self.data:
            cost_fields = ["cost_usd", "total_cost", "cost", "unblended_cost"]
            for row in self.data:
                for field in cost_fields:
                    if field in row and row[field] is not None:
                        try:
                            self.total_cost += float(row[field])
                            break  # Only count once per row
                        except (ValueError, TypeError):
                            pass
    
    @property
    def has_data(self) -> bool:
        """Convenience property for checking if result has data."""
        return not self.is_empty and self.error is None
    
    @property
    def succeeded(self) -> bool:
        """Query executed successfully (may or may not have data)."""
        return self.error is None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "data": self.data,
            "total_cost": self.total_cost,
            "row_count": self.row_count,
            "is_empty": self.is_empty,
            "error": self.error,
            "metadata": {
                "data_source": self.metadata.data_source,
                "execution_time_ms": self.metadata.execution_time_ms,
                "query_id": self.metadata.query_id,
                "sql_query": self.metadata.sql_query,
                "arn_fallback": self.metadata.arn_fallback,
                "original_arn": self.metadata.original_arn,
                "cost_explorer_fallback": self.metadata.cost_explorer_fallback,
                "breakdown_dimension": self.metadata.breakdown_dimension,
                "breakdown_dimension_label": self.metadata.breakdown_dimension_label,
                "top_service_breakdown": self.metadata.top_service_breakdown,
                "resource_type_explanation": self.metadata.resource_type_explanation,
                **self.metadata.extra
            }
        }
