"""Intent Type Definitions

DEPRECATED: Intent classification is now handled by unified_query_processor.
This file only contains the IntentType enum for backward compatibility.
"""


class IntentType:
    """Intent types for cost analysis queries."""
    COST_BREAKDOWN = "COST_BREAKDOWN"
    TOP_N_RANKING = "TOP_N_RANKING"
    ANOMALY_ANALYSIS = "ANOMALY_ANALYSIS"
    COST_TREND = "COST_TREND"
    UTILIZATION = "UTILIZATION"
    OPTIMIZATION = "OPTIMIZATION"
    GOVERNANCE = "GOVERNANCE"
    DATA_METADATA = "DATA_METADATA"
    COMPARATIVE = "COMPARATIVE"
    OTHER = "OTHER"
