"""Prometheus metrics for service resolution pipeline."""
from prometheus_client import Counter

resolution_counter = Counter(
    "service_resolution_events_total",
    "Count of service resolution events by method",
    labelnames=["method"],
)
