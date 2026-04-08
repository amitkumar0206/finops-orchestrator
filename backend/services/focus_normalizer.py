"""FOCUS-aligned normalization helpers for multi-cloud ingestion."""

from __future__ import annotations

from datetime import date
from typing import Any, List, Optional, Tuple, cast

import pandas as pd

from backend.models.data_sources import DataSourceProvider, NormalizedCostRecord


class FocusNormalizer:
    """Converts provider-native billing exports into a unified FOCUS-like schema."""

    _ALIASES = {
        DataSourceProvider.AZURE_EXPORT: {
            "cost": ["CostInBillingCurrency", "Cost", "PreTaxCost"],
            "currency": ["BillingCurrencyCode", "Currency"],
            "service": ["MeterCategory", "ServiceName", "ConsumedService"],
            "account": ["SubscriptionId", "BillingAccountId"],
            "region": ["ResourceLocation", "Region"],
            "usage_quantity": ["Quantity"],
            "usage_unit": ["UnitOfMeasure"],
            "usage_start": ["UsageDate", "Date"],
        },
        DataSourceProvider.GCP_BILLING: {
            "cost": ["cost", "Cost"],
            "currency": ["currency", "Currency"],
            "service": ["service.description", "service", "Service Description"],
            "account": ["project.id", "project_id", "project.name"],
            "region": ["location.region", "location", "region"],
            "usage_quantity": ["usage.amount", "usage_amount"],
            "usage_unit": ["usage.unit", "usage_unit"],
            "usage_start": ["usage_start_time", "usage_start"],
        },
        DataSourceProvider.GENERIC_COST: {
            "cost": ["cost", "amount", "total_cost"],
            "currency": ["currency", "billing_currency"],
            "service": ["service", "service_name", "product"],
            "account": ["account_id", "project_id", "subscription_id"],
            "region": ["region", "location"],
            "usage_quantity": ["usage", "usage_quantity"],
            "usage_unit": ["unit", "usage_unit"],
            "usage_start": ["usage_start", "date", "usage_date"],
        },
    }

    def normalize(
        self,
        provider: DataSourceProvider,
        df: pd.DataFrame,
    ) -> Tuple[List[NormalizedCostRecord], List[str]]:
        if provider == DataSourceProvider.AWS_CUR:
            return self._normalize_aws(df)
        if provider == DataSourceProvider.AZURE_EXPORT:
            return self._normalize_generic(provider, df)
        if provider == DataSourceProvider.GCP_BILLING:
            return self._normalize_generic(provider, df)
        return self._normalize_generic(DataSourceProvider.GENERIC_COST, df)

    def _normalize_aws(self, df: pd.DataFrame) -> Tuple[List[NormalizedCostRecord], List[str]]:
        errors: List[str] = []
        required = [
            "line_item_usage_start_date",
            "line_item_unblended_cost",
            "line_item_product_code",
        ]
        missing = [c for c in required if c not in df.columns]
        if missing:
            return [], [f"Missing required AWS CUR columns: {', '.join(missing)}"]

        work = df.copy()
        work["_usage_start"] = pd.to_datetime(work["line_item_usage_start_date"], errors="coerce", utc=True)
        work["_cost"] = pd.to_numeric(work["line_item_unblended_cost"], errors="coerce").fillna(0.0)
        work["_service"] = work["line_item_product_code"].fillna("Unknown")
        work["_account"] = self._series_or_default(work, "line_item_usage_account_id", "")
        work["_region"] = self._series_or_default(work, "product_region", "")
        work["_quantity"] = pd.to_numeric(
            self._series_or_default(work, "line_item_usage_amount", 0.0), errors="coerce"
        ).fillna(0.0)
        work["_unit"] = self._series_or_default(work, "pricing_unit", "")

        bad_dates = int(work["_usage_start"].isna().sum())
        if bad_dates:
            errors.append(f"{bad_dates} rows have invalid usage start dates")

        mask = work["_usage_start"].notna().to_numpy()
        work = work[mask]
        if work.empty:
            return [], errors or ["No valid rows after date validation"]

        work["_partition_month"] = work["_usage_start"].apply(
            lambda ts: date(int(getattr(ts, "year")), int(getattr(ts, "month")), 1)
        )

        grouped = (
            work.groupby(["_partition_month", "_service", "_account", "_region"], dropna=False)
            .agg(cost_amount=("_cost", "sum"), usage_quantity=("_quantity", "sum"), record_count=("_cost", "count"))
            .reset_index()
        )

        out: List[NormalizedCostRecord] = []
        for _, row in grouped.iterrows():
            month = row["_partition_month"]
            out.append(
                NormalizedCostRecord(
                    provider_type=DataSourceProvider.AWS_CUR,
                    billing_period_start=month,
                    billing_period_end=month,
                    partition_month=month,
                    account_or_project_id=self._str_or_none(row["_account"]),
                    service_name=str(row["_service"]),
                    region=self._str_or_none(row["_region"]),
                    usage_quantity=float(row["usage_quantity"]),
                    usage_unit=None,
                    cost_amount=float(row["cost_amount"]),
                    currency="USD",
                    tags={"aggregated_record_count": int(row["record_count"])},
                )
            )
        return out, errors

    def _normalize_generic(
        self,
        provider: DataSourceProvider,
        df: pd.DataFrame,
    ) -> Tuple[List[NormalizedCostRecord], List[str]]:
        aliases = self._ALIASES[provider]
        errors: List[str] = []

        def pick(name: str, default: Optional[Any] = None):
            for c in aliases[name]:
                if c in df.columns:
                    return df[c]
            return default

        cost_col = pick("cost")
        svc_col = pick("service")
        date_col = pick("usage_start")

        if cost_col is None:
            return [], ["Missing required cost column"]
        if svc_col is None:
            return [], ["Missing required service column"]
        if date_col is None:
            return [], ["Missing required usage/date column"]

        currency_col = pick("currency", "USD")
        account_col = pick("account", "")
        region_col = pick("region", "")
        usage_col = pick("usage_quantity", 0.0)
        unit_col = pick("usage_unit", "")

        work = pd.DataFrame({
            "_cost": pd.to_numeric(cost_col, errors="coerce").fillna(0.0),
            "_service": svc_col.fillna("Unknown").astype(str),
            "_usage_start": pd.to_datetime(date_col, errors="coerce", utc=True),
            "_currency": self._force_series(currency_col, len(df), "USD"),
            "_account": self._force_series(account_col, len(df), ""),
            "_region": self._force_series(region_col, len(df), ""),
            "_quantity": pd.to_numeric(self._force_series(usage_col, len(df), 0.0), errors="coerce").fillna(0.0),
            "_unit": self._force_series(unit_col, len(df), ""),
        })

        bad_dates = int(work["_usage_start"].isna().sum())
        if bad_dates:
            errors.append(f"{bad_dates} rows have invalid usage dates")

        mask = work["_usage_start"].notna().to_numpy()
        work = work[mask]
        if work.empty:
            return [], errors or ["No valid rows after date validation"]

        work["_partition_month"] = work["_usage_start"].apply(
            lambda ts: date(int(getattr(ts, "year")), int(getattr(ts, "month")), 1)
        )
        grouped = (
            work.groupby(["_partition_month", "_service", "_account", "_region", "_currency", "_unit"], dropna=False)
            .agg(cost_amount=("_cost", "sum"), usage_quantity=("_quantity", "sum"), record_count=("_cost", "count"))
            .reset_index()
        )

        out: List[NormalizedCostRecord] = []
        for _, row in grouped.iterrows():
            month: date = row["_partition_month"]
            out.append(
                NormalizedCostRecord(
                    provider_type=provider,
                    billing_period_start=month,
                    billing_period_end=month,
                    partition_month=month,
                    account_or_project_id=self._str_or_none(row["_account"]),
                    service_name=str(row["_service"]),
                    region=self._str_or_none(row["_region"]),
                    usage_quantity=float(row["usage_quantity"]),
                    usage_unit=self._str_or_none(row["_unit"]),
                    cost_amount=float(row["cost_amount"]),
                    currency=self._str_or_none(row["_currency"]) or "USD",
                    tags={"aggregated_record_count": int(row["record_count"])},
                )
            )
        return out, errors

    @staticmethod
    def _str_or_none(v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @staticmethod
    def _series_or_default(df: pd.DataFrame, column: str, default: Any) -> pd.Series:
        if column in df.columns:
            return df[column].fillna(default)
        return pd.Series([default] * len(df), index=df.index)

    @staticmethod
    def _force_series(value: Any, length: int, default: Any) -> pd.Series:
        if isinstance(value, pd.Series):
            return cast(pd.Series, value.fillna(default))
        return pd.Series([value if value is not None else default] * length)
