"""
FinOps Module - Core business logic for cost intelligence platform
"""

from backend.finops.time_range import (
    parse_time_range,
    merge_time_range,
    TimeRange,
    TimeRangeResult,
    Granularity
)

__all__ = [
    'parse_time_range',
    'merge_time_range',
    'TimeRange',
    'TimeRangeResult',
    'Granularity'
]
