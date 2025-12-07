"""Repair Layer for UPS JSON

Validates and attempts one-shot self-repair of malformed LLM JSON output.
Usage:
  repaired_str = repair_json(raw_str, prompt)
If repair fails, returns original string.
"""
from __future__ import annotations
import json
import structlog
from typing import Optional
from backend.services.llm_service import llm_service

logger = structlog.get_logger(__name__)

REPAIR_SYSTEM_PROMPT = "You are a strict JSON repair assistant. Output ONLY valid JSON, no commentary."  # noqa: E501

async def repair_json(raw: str, original_prompt: str) -> str:
    try:
        json.loads(raw)
        return raw  # already valid
    except Exception:
        pass
    # Attempt repair by asking model to fix
    repair_prompt = f"Fix the following invalid JSON so it matches the original schema and intent. Return ONLY JSON.\n===\n{raw}\n==="
    try:
        repaired = await llm_service.call_llm(prompt=repair_prompt, system_prompt=REPAIR_SYSTEM_PROMPT)
        cleaned = repaired.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join([ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")])
        json.loads(cleaned)  # validate
        logger.info("JSON repair successful")
        return cleaned
    except Exception as e:
        logger.warning("JSON repair failed", error=str(e))
        return raw
