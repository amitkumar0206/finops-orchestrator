from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
import uuid


@dataclass
class TimeRange:
    start_date: str
    end_date: str
    description: Optional[str] = None
    explicit: bool = False
    source: Optional[str] = None


@dataclass
class QuerySpec:
    intent: str  # e.g., COST_BREAKDOWN, TOP_N_RANKING, COST_TREND, COMPARATIVE
    time_range: Union[TimeRange, Dict[str, Any]]
    dimensions: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    services: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    accounts: List[str] = field(default_factory=list)
    arn: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    query_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        """Convert time_range dict to TimeRange object if needed."""
        if isinstance(self.time_range, dict):
            self.time_range = TimeRange(
                start_date=self.time_range.get("start_date", ""),
                end_date=self.time_range.get("end_date", ""),
                description=self.time_range.get("description"),
                explicit=self.time_range.get("explicit", False),
                source=self.time_range.get("source")
            )

    @property
    def spec_version(self) -> str:
        return "v1"

    def has_dimension(self, name: str) -> bool:
        return name in (self.dimensions or [])

    def to_log_context(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "spec_version": self.spec_version,
            "intent": self.intent,
            "dimensions": self.dimensions,
            "services": self.services,
            "regions": self.regions,
            "accounts": self.accounts,
            "arn": self.arn,
            "start_date": self.time_range.start_date,
            "end_date": self.time_range.end_date,
        }
