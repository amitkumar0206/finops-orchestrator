from __future__ import annotations

from typing import Dict, Any

import pandas as pd

from backend.services.cur_csv_analyzer import CURCSVAnalyzer


class AWSCURConnector:
    """Loads AWS CUR exports and maps them to canonical intermediate columns."""

    provider = "aws_cur"

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        # Advisory mode uploads do not require live credentials.
        mode = str(credentials.get("mode") or "advisory_upload")
        return {
            "mode": mode,
            "valid": True,
            "required": [] if mode == "advisory_upload" else ["bucket", "prefix"],
        }

    def load_dataframe(self, content: bytes, filename: str, max_rows: int) -> pd.DataFrame:
        return CURCSVAnalyzer.load_dataframe(content, filename=filename, max_rows=max_rows)
