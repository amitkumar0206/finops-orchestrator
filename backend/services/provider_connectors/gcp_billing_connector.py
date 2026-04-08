from __future__ import annotations

from typing import Dict, Any
import io

import pandas as pd


class GCPBillingConnector:
    """Parses GCP billing export CSV content."""

    provider = "gcp_billing"

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        required = ["project_id", "dataset"]
        missing = [k for k in required if not credentials.get(k)]
        return {
            "valid": not missing,
            "required": required,
            "missing": missing,
        }

    def load_dataframe(self, content: bytes, filename: str, max_rows: int) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(content), low_memory=False, nrows=max_rows)
        return df.rename(columns={c: c.strip() for c in df.columns})
