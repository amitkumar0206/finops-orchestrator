"""
DEPRECATED: EnhancedParameterExtractor is superseded by the UPS extractor.
Archived on 2025-11-19. This module is kept as a no-op for compatibility.
"""

from typing import Any, Dict, List, Optional

class EnhancedParameterExtractor:
    async def extract_parameters(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        current_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "intent": "OTHER",
            "confidence": 0.0,
            "parameters": {},
            "reasoning": "deprecated; use UPS extractor",
            "is_followup": False,
            "context_changes": {},
            "method": "deprecated",
        }


enhanced_parameter_extractor = EnhancedParameterExtractor()
