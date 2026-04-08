from __future__ import annotations

from typing import Dict, Any
import io

import pandas as pd


class GenericCostConnector:
    """Parses generic cost CSV feeds with minimal column assumptions."""

    provider = "generic_cost"

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        # Generic advisory uploads do not require credentials.
        return {"valid": True, "required": []}

    def load_dataframe(self, content: bytes, filename: str, max_rows: int) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(content), low_memory=False, nrows=max_rows)
        return df.rename(columns={c: c.strip() for c in df.columns})
