"""
CUR CSV Analyzer (Advisory Mode)

Mines an *uploaded* AWS Cost and Usage Report export (CSV / CSV.GZ) for the
same waste, anomaly and commitment-coverage signals that Connected Mode
extracts via Athena + Cost Explorer. This is the file-based half of
Feature 2 (CUR / Billing Export Deep Analysis) — it lets clients who cannot
or will not grant live AWS API access still receive actionable findings.

Every detector returns a list of opportunity dicts in the *exact* shape
consumed by ``OpportunitiesService.ingest_signals()`` (see
``ri_savings_plans_signals.py`` for the canonical example), so Advisory-Mode
findings flow into the same multi-tenant Opportunities dashboard as live
signals, tagged ``source=cur_analysis``.

The analyzer is deliberately dependency-light (pandas only — already in
requirements) and never touches AWS, so it also runs when
``DATABASE_ENABLED=false`` / demo deployments.
"""

from __future__ import annotations

import gzip
import io
import re
from datetime import datetime, timezone
from typing import Any, BinaryIO, Dict, List, Optional, Union
from uuid import UUID, uuid4

import pandas as pd
import structlog

from backend.config.settings import get_settings
from backend.models.opportunities import OpportunityCategory, OpportunitySource

logger = structlog.get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------
# AWS exports CUR with several naming conventions depending on whether the
# table was created by Glue, Data Exports (CUR 2.0), or downloaded directly
# from the Billing console. We map every variant to a single canonical
# snake_case name so detectors below can be written once.

_NORMALISED_COLUMN_ALIASES: Dict[str, str] = {
    # identity / line-item core
    "lineitem/usagestartdate": "line_item_usage_start_date",
    "lineitem/lineitemtype": "line_item_line_item_type",
    "lineitem/usagetype": "line_item_usage_type",
    "lineitem/productcode": "line_item_product_code",
    "lineitem/unblendedcost": "line_item_unblended_cost",
    "lineitem/blendedcost": "line_item_blended_cost",
    "lineitem/usageamount": "line_item_usage_amount",
    "lineitem/resourceid": "line_item_resource_id",
    "lineitem/usageaccountid": "line_item_usage_account_id",
    # product
    "product/region": "product_region",
    "product/regioncode": "product_region",
    "product/instancetype": "product_instance_type",
    "product/servicecode": "product_servicecode",
    # pricing
    "pricing/term": "pricing_term",
    # reservation (12-column family — we only need the cost-bearing ones)
    "reservation/reservationarn": "reservation_reservation_a_r_n",
    "reservation/unusedamortizedupfrontfeeforbillingperiod": "reservation_unused_amortized_upfront_fee_for_billing_period",
    "reservation/unusedrecurringfee": "reservation_unused_recurring_fee",
    "reservation/unusedquantity": "reservation_unused_quantity",
    "reservation/amortizedupfrontfeeforbillingperiod": "reservation_amortized_upfront_fee_for_billing_period",
    "reservation/recurringfeeforusage": "reservation_recurring_fee_for_usage",
    # savings plan (8-column family)
    "savingsplan/savingsplanarn": "savings_plan_savings_plan_a_r_n",
    "savingsplan/totalcommitmenttodate": "savings_plan_total_commitment_to_date",
    "savingsplan/usedcommitment": "savings_plan_used_commitment",
    "savingsplan/savingsplaneffectivecost": "savings_plan_savings_plan_effective_cost",
}

_NUMERIC_COLUMNS = (
    "line_item_unblended_cost",
    "line_item_blended_cost",
    "line_item_usage_amount",
    "reservation_unused_amortized_upfront_fee_for_billing_period",
    "reservation_unused_recurring_fee",
    "reservation_unused_quantity",
    "reservation_amortized_upfront_fee_for_billing_period",
    "reservation_recurring_fee_for_usage",
    "savings_plan_total_commitment_to_date",
    "savings_plan_used_commitment",
    "savings_plan_savings_plan_effective_cost",
)

# Minimum columns required for any analysis at all.
_REQUIRED_COLUMNS = (
    "line_item_line_item_type",
    "line_item_unblended_cost",
)


def _canonicalise(col: str) -> str:
    """Normalise a CUR column header to canonical snake_case."""
    raw = col.strip()
    # Already-canonical Glue-style snake_case (line_item_*, product_*, ...)
    if "/" not in raw and raw == raw.lower() and " " not in raw:
        return raw
    lowered = raw.lower()
    if lowered in _NORMALISED_COLUMN_ALIASES:
        return _NORMALISED_COLUMN_ALIASES[lowered]
    # Generic fallback: lineItem/UsageStartDate -> line_item_usage_start_date
    parts = re.split(r"[\/]", raw)
    snake_parts: List[str] = []
    for part in parts:
        # split camelCase / PascalCase
        s = re.sub(r"(?<!^)(?=[A-Z])", "_", part).lower()
        s = re.sub(r"[^a-z0-9_]+", "_", s)
        snake_parts.append(s)
    return "_".join(p for p in snake_parts if p)


class CURCSVAnalyzer:
    """
    Pandas-based CUR pattern miner for uploaded CSV exports.

    All thresholds are read from :class:`Settings` so they are configurable
    per deployment / per tenant via environment variables, matching the
    SaaS-configurability requirement.
    """

    def __init__(
        self,
        account_id: Optional[str] = None,
        organization_id: Optional[UUID] = None,
    ):
        self.account_id = account_id
        self.organization_id = organization_id
        # Per-tenant configurable thresholds (env-driven, see settings.py)
        self.min_idle_cost = settings.cur_mining_min_idle_cost_usd
        self.min_data_transfer_cost = settings.cur_mining_min_data_transfer_usd
        self.min_ri_unused_cost = settings.cur_mining_min_ri_unused_usd
        self.min_sp_unused_cost = settings.cur_mining_min_sp_unused_usd
        self.steady_state_hours_per_day = settings.cur_mining_steady_state_hours_per_day
        self.min_steady_state_cost = settings.cur_mining_min_steady_state_cost_usd
        self.scheduling_off_hours_share = settings.cur_mining_scheduling_off_hours_share
        self.max_findings_per_detector = settings.cur_mining_max_findings_per_detector

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @staticmethod
    def load_dataframe(
        source: Union[bytes, BinaryIO, str, pd.DataFrame],
        filename: Optional[str] = None,
        max_rows: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Read a CUR export into a normalised DataFrame.

        Accepts raw bytes (from ``UploadFile.read()``), a file-like object,
        a filesystem path, or an already-built DataFrame (used by tests).
        Transparently decompresses ``.gz`` payloads.
        """
        if isinstance(source, pd.DataFrame):
            df = source.copy()
        else:
            buf: BinaryIO
            if isinstance(source, (bytes, bytearray)):
                data = bytes(source)
                if (filename and filename.lower().endswith(".gz")) or data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                buf = io.BytesIO(data)
            elif isinstance(source, str):
                # Filesystem path — let pandas handle compression by extension.
                df = pd.read_csv(source, low_memory=False, nrows=max_rows)
                return CURCSVAnalyzer._normalise_dataframe(df)
            else:
                buf = source  # already a file-like
            df = pd.read_csv(buf, low_memory=False, nrows=max_rows)

        return CURCSVAnalyzer._normalise_dataframe(df)

    @staticmethod
    def _normalise_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        df = df.rename(columns={c: _canonicalise(c) for c in df.columns})
        missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(
                "Uploaded file does not look like an AWS CUR export — "
                f"missing required column(s): {', '.join(missing)}"
            )
        for col in _NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        if "line_item_usage_start_date" in df.columns:
            df["line_item_usage_start_date"] = pd.to_datetime(
                df["line_item_usage_start_date"], errors="coerce", utc=True
            )
        return df

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Run every detector against the supplied (already normalised)
        DataFrame and return both the raw opportunity list and a summary
        suitable for the API response body.
        """
        if "line_item_usage_account_id" in df.columns and not self.account_id:
            accounts = df["line_item_usage_account_id"].dropna().astype(str).unique()
            if len(accounts) == 1:
                self.account_id = accounts[0]

        period_start, period_end, days = self._derive_period(df)

        opportunities: List[Dict[str, Any]] = []
        detector_counts: Dict[str, int] = {}

        for label, fn in (
            ("usage_type_cost_drivers", self._detect_usage_type_cost_drivers),
            ("ri_unused_hours", self._detect_ri_unused_hours),
            ("sp_unused_commitment", self._detect_sp_unused_commitment),
            ("cross_region_data_transfer", self._detect_cross_region_data_transfer),
            ("idle_resources", self._detect_idle_resources),
            ("on_demand_steady_state_db", self._detect_on_demand_steady_state_db),
            ("scheduling_candidates", self._detect_scheduling_candidates),
        ):
            try:
                found = fn(df, days)
                detector_counts[label] = len(found)
                opportunities.extend(found)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("CUR CSV detector failed", detector=label, error=str(exc))
                detector_counts[label] = 0

        total_cost = float(
            df.loc[
                df["line_item_line_item_type"].isin(
                    ["Usage", "DiscountedUsage", "SavingsPlanCoveredUsage"]
                ),
                "line_item_unblended_cost",
            ].sum()
        )

        return {
            "opportunities": opportunities,
            "summary": {
                "rows_analyzed": int(len(df)),
                "period_start": period_start,
                "period_end": period_end,
                "period_days": days,
                "total_unblended_cost_usd": round(total_cost, 2),
                "total_opportunities": len(opportunities),
                "estimated_monthly_savings_usd": round(
                    sum(o.get("estimated_monthly_savings") or 0.0 for o in opportunities), 2
                ),
                "by_detector": detector_counts,
            },
        }

    # ------------------------------------------------------------------
    # Detectors — each mirrors a CURPatternMiningTemplates query
    # ------------------------------------------------------------------

    def _detect_usage_type_cost_drivers(self, df: pd.DataFrame, days: int) -> List[Dict[str, Any]]:
        """Single ARCHITECTURE-category opportunity summarising the top cost-driver families."""
        if "line_item_usage_type" not in df.columns:
            return []
        usage = df[df["line_item_line_item_type"].isin(
            ["Usage", "DiscountedUsage", "SavingsPlanCoveredUsage"]
        )].copy()
        if usage.empty:
            return []

        def family(ut: str) -> str:
            ut = str(ut)
            if "BoxUsage" in ut:
                return "Compute (BoxUsage)"
            if "DataTransfer" in ut:
                return "Data Transfer"
            if "EBS:Volume" in ut:
                return "EBS Volumes"
            if "EBS:Snapshot" in ut:
                return "EBS Snapshots"
            if "NatGateway" in ut:
                return "NAT Gateway"
            if "LoadBalancer" in ut:
                return "Load Balancer"
            if "Storage" in ut:
                return "Storage"
            return "Other"

        usage["usage_family"] = usage["line_item_usage_type"].map(family)
        grouped = (
            usage.groupby("usage_family")["line_item_unblended_cost"].sum().sort_values(ascending=False)
        )
        total = float(grouped.sum()) or 1.0
        breakdown = [
            {
                "usage_family": fam,
                "cost_usd": round(float(cost), 2),
                "share_pct": round(float(cost) * 100.0 / total, 1),
            }
            for fam, cost in grouped.head(8).items()
        ]
        top = breakdown[0]
        return [
            self._opportunity(
                title=f"Top cost driver: {top['usage_family']} ({top['share_pct']:.0f}% of spend)",
                description=(
                    f"{top['usage_family']} accounts for {top['share_pct']:.1f}% "
                    f"(${top['cost_usd']:.2f}) of the analysed CUR window. Use this "
                    "breakdown to prioritise which optimisation lever to pull first."
                ),
                category=OpportunityCategory.ARCHITECTURE,
                service=top["usage_family"],
                region=None,
                resource_id=None,
                monthly_savings=0.0,
                current_monthly_cost=self._monthly(top["cost_usd"], days),
                effort="low",
                risk="low",
                confidence=0.95,
                evidence={"cost_driver_breakdown": breakdown, "lookback_period_days": days},
                source_id="cur-csv-cost-drivers",
                steps=[
                    {"step": 1, "action": "Review the cost-driver families below"},
                    {"step": 2, "action": "Open the matching detector findings for the top family"},
                ],
            )
        ]

    def _detect_ri_unused_hours(self, df: pd.DataFrame, days: int) -> List[Dict[str, Any]]:
        cols = (
            "reservation_reservation_a_r_n",
            "reservation_unused_amortized_upfront_fee_for_billing_period",
            "reservation_unused_recurring_fee",
        )
        if not all(c in df.columns for c in cols):
            return []
        ri = df[df["line_item_line_item_type"] == "RIFee"].copy()
        if ri.empty:
            return []
        ri["unused_cost"] = (
            ri["reservation_unused_amortized_upfront_fee_for_billing_period"]
            + ri["reservation_unused_recurring_fee"]
        )
        if "reservation_unused_quantity" in ri.columns:
            ri["unused_hours"] = ri["reservation_unused_quantity"]
        else:
            ri["unused_hours"] = 0.0
        grouped = (
            ri.groupby(
                [
                    "reservation_reservation_a_r_n",
                    ri.get("line_item_product_code", pd.Series(index=ri.index, dtype=str)).fillna(""),
                    ri.get("product_region", pd.Series(index=ri.index, dtype=str)).fillna(""),
                ]
            )[["unused_cost", "unused_hours"]]
            .sum()
            .reset_index()
        )
        grouped.columns = ["reservation_arn", "service", "region", "unused_cost", "unused_hours"]
        grouped = grouped[grouped["unused_cost"] > self.min_ri_unused_cost].sort_values(
            "unused_cost", ascending=False
        )

        out: List[Dict[str, Any]] = []
        for _, row in grouped.head(self.max_findings_per_detector).iterrows():
            monthly_waste = self._monthly(float(row["unused_cost"]), days)
            out.append(
                self._opportunity(
                    title=f"Unused Reserved Instance capacity (${monthly_waste:.0f}/mo wasted)",
                    description=(
                        f"Reservation {row['reservation_arn']} recorded "
                        f"${float(row['unused_cost']):.2f} of unused amortised + recurring fees "
                        f"({float(row['unused_hours']):.0f} unused hours) in the uploaded CUR window. "
                        "Modify the reservation scope, sell on the RI Marketplace, or shift "
                        "matching workloads onto it."
                    ),
                    category=OpportunityCategory.RESERVED_INSTANCES,
                    service=str(row["service"]) or "EC2",
                    region=str(row["region"]) or None,
                    resource_id=str(row["reservation_arn"]),
                    monthly_savings=monthly_waste,
                    current_monthly_cost=monthly_waste,
                    effort="medium",
                    risk="low",
                    confidence=0.85,
                    evidence={
                        "unused_cost_usd": round(float(row["unused_cost"]), 2),
                        "unused_hours": round(float(row["unused_hours"]), 1),
                        "lookback_period_days": days,
                    },
                    source_id=f"cur-csv-ri-unused-{abs(hash(row['reservation_arn'])) % 100000}",
                    steps=[
                        {"step": 1, "action": "Open RI utilisation in Cost Explorer for this ARN"},
                        {"step": 2, "action": "Modify size/scope or list on RI Marketplace"},
                        {"step": 3, "action": "Right-size future RI purchases to match steady-state"},
                    ],
                )
            )
        return out

    def _detect_sp_unused_commitment(self, df: pd.DataFrame, days: int) -> List[Dict[str, Any]]:
        cols = (
            "savings_plan_savings_plan_a_r_n",
            "savings_plan_total_commitment_to_date",
            "savings_plan_used_commitment",
        )
        if not all(c in df.columns for c in cols):
            return []
        sp = df[df["line_item_line_item_type"] == "SavingsPlanRecurringFee"].copy()
        if sp.empty:
            return []
        sp["unused"] = (
            sp["savings_plan_total_commitment_to_date"] - sp["savings_plan_used_commitment"]
        ).clip(lower=0)
        grouped = (
            sp.groupby(
                [
                    "savings_plan_savings_plan_a_r_n",
                    sp.get("product_region", pd.Series(index=sp.index, dtype=str)).fillna(""),
                ]
            )[["unused", "savings_plan_total_commitment_to_date", "savings_plan_used_commitment"]]
            .sum()
            .reset_index()
        )
        grouped.columns = ["sp_arn", "region", "unused", "committed", "used"]
        grouped = grouped[grouped["unused"] > self.min_sp_unused_cost].sort_values(
            "unused", ascending=False
        )

        out: List[Dict[str, Any]] = []
        for _, row in grouped.head(self.max_findings_per_detector).iterrows():
            committed = float(row["committed"]) or 1.0
            util_pct = max(0.0, min(100.0, float(row["used"]) * 100.0 / committed))
            monthly_waste = self._monthly(float(row["unused"]), days)
            out.append(
                self._opportunity(
                    title=f"Savings Plan under-utilised ({util_pct:.0f}% used, ${monthly_waste:.0f}/mo wasted)",
                    description=(
                        f"Savings Plan {row['sp_arn']} has ${float(row['unused']):.2f} of committed "
                        f"spend that was not consumed in the uploaded window "
                        f"({util_pct:.1f}% utilisation). Shift eligible compute onto this plan or "
                        "reduce the next commitment."
                    ),
                    category=OpportunityCategory.SAVINGS_PLANS,
                    service="Compute Savings Plan",
                    region=str(row["region"]) or None,
                    resource_id=str(row["sp_arn"]),
                    monthly_savings=monthly_waste,
                    current_monthly_cost=monthly_waste,
                    effort="medium",
                    risk="low",
                    confidence=0.85,
                    evidence={
                        "unused_commitment_usd": round(float(row["unused"]), 2),
                        "committed_usd": round(float(row["committed"]), 2),
                        "used_usd": round(float(row["used"]), 2),
                        "utilization_pct": round(util_pct, 1),
                        "lookback_period_days": days,
                    },
                    source_id=f"cur-csv-sp-unused-{abs(hash(row['sp_arn'])) % 100000}",
                    steps=[
                        {"step": 1, "action": "Confirm SP utilisation in Cost Explorer"},
                        {"step": 2, "action": "Migrate on-demand compute into SP-eligible families"},
                        {"step": 3, "action": "Right-size next SP commitment to actual baseline"},
                    ],
                )
            )
        return out

    def _detect_cross_region_data_transfer(self, df: pd.DataFrame, days: int) -> List[Dict[str, Any]]:
        if "line_item_usage_type" not in df.columns:
            return []
        mask = df["line_item_line_item_type"].eq("Usage") & df["line_item_usage_type"].astype(
            str
        ).str.contains("InterRegion|AWS-Out-Bytes|DataTransfer-Regional", regex=True, na=False)
        dt = df[mask]
        if dt.empty:
            return []
        region_col = "product_region" if "product_region" in dt.columns else None
        group_cols = [c for c in (region_col, "line_item_product_code") if c]
        grouped = (
            dt.groupby(group_cols)["line_item_unblended_cost"].sum().reset_index()
            if group_cols
            else pd.DataFrame({"line_item_unblended_cost": [dt["line_item_unblended_cost"].sum()]})
        )
        grouped = grouped[grouped["line_item_unblended_cost"] > self.min_data_transfer_cost].sort_values(
            "line_item_unblended_cost", ascending=False
        )

        out: List[Dict[str, Any]] = []
        for _, row in grouped.head(self.max_findings_per_detector).iterrows():
            cost = float(row["line_item_unblended_cost"])
            monthly_cost = self._monthly(cost, days)
            region = str(row[region_col]) if region_col else None
            service = str(row.get("line_item_product_code", "AWSDataTransfer"))
            out.append(
                self._opportunity(
                    title=f"High cross-region data transfer in {region or 'multiple regions'} (${monthly_cost:.0f}/mo)",
                    description=(
                        f"${cost:.2f} of inter-region / regional data-transfer charges from "
                        f"{service} in {region or 'this account'}. Co-locate producers and "
                        "consumers in the same region, or replace cross-region traffic with "
                        "VPC Peering / PrivateLink to cut transfer charges by up to 100%."
                    ),
                    category=OpportunityCategory.DATA_TRANSFER,
                    service=service,
                    region=region,
                    resource_id=None,
                    monthly_savings=round(monthly_cost * 0.5, 2),
                    current_monthly_cost=monthly_cost,
                    effort="high",
                    risk="medium",
                    confidence=0.7,
                    evidence={
                        "transfer_cost_usd": round(cost, 2),
                        "lookback_period_days": days,
                    },
                    source_id=f"cur-csv-dt-{(region or 'all').lower()}-{service.lower()}",
                    steps=[
                        {"step": 1, "action": "Identify producer/consumer pair driving the transfer"},
                        {"step": 2, "action": "Evaluate co-locating in a single region"},
                        {"step": 3, "action": "If co-location is impossible, price PrivateLink / S3 CRR"},
                    ],
                )
            )
        return out

    def _detect_idle_resources(self, df: pd.DataFrame, days: int) -> List[Dict[str, Any]]:
        needed = ("line_item_resource_id", "line_item_usage_amount")
        if not all(c in df.columns for c in needed):
            return []
        usage = df[
            df["line_item_line_item_type"].eq("Usage")
            & df["line_item_resource_id"].astype(str).str.len().gt(0)
        ]
        if usage.empty:
            return []
        agg = (
            usage.groupby(
                [
                    "line_item_resource_id",
                    usage.get("line_item_product_code", pd.Series(index=usage.index, dtype=str)).fillna(""),
                    usage.get("product_region", pd.Series(index=usage.index, dtype=str)).fillna(""),
                ]
            )
            .agg(
                cost_usd=("line_item_unblended_cost", "sum"),
                usage_amount=("line_item_usage_amount", "sum"),
            )
            .reset_index()
        )
        agg.columns = ["resource_id", "service", "region", "cost_usd", "usage_amount"]
        idle = agg[(agg["usage_amount"] == 0) & (agg["cost_usd"] > self.min_idle_cost)].sort_values(
            "cost_usd", ascending=False
        )

        out: List[Dict[str, Any]] = []
        for _, row in idle.head(self.max_findings_per_detector).iterrows():
            monthly = self._monthly(float(row["cost_usd"]), days)
            out.append(
                self._opportunity(
                    title=f"Idle resource costing ${monthly:.0f}/mo: {row['resource_id']}",
                    description=(
                        f"Resource {row['resource_id']} ({row['service']}) incurred "
                        f"${float(row['cost_usd']):.2f} in the uploaded window with zero recorded "
                        "usage. It is likely orphaned or permanently idle and can be terminated."
                    ),
                    category=OpportunityCategory.IDLE_RESOURCES,
                    service=str(row["service"]) or "Unknown",
                    region=str(row["region"]) or None,
                    resource_id=str(row["resource_id"]),
                    monthly_savings=monthly,
                    current_monthly_cost=monthly,
                    effort="low",
                    risk="low",
                    confidence=0.75,
                    evidence={
                        "cost_usd": round(float(row["cost_usd"]), 2),
                        "usage_amount": 0.0,
                        "lookback_period_days": days,
                    },
                    source_id=f"cur-csv-idle-{abs(hash(row['resource_id'])) % 100000}",
                    steps=[
                        {"step": 1, "action": "Confirm the resource is unused (CloudWatch / owner)"},
                        {"step": 2, "action": "Snapshot if stateful, then terminate / release"},
                    ],
                )
            )
        return out

    def _detect_on_demand_steady_state_db(self, df: pd.DataFrame, days: int) -> List[Dict[str, Any]]:
        needed = ("line_item_resource_id", "line_item_usage_amount", "line_item_product_code")
        if not all(c in df.columns for c in needed):
            return []
        db = df[
            df["line_item_line_item_type"].eq("Usage")
            & df["line_item_product_code"].isin(["AmazonRDS", "AmazonElastiCache", "AmazonRedshift"])
            & df.get("line_item_usage_type", pd.Series(index=df.index, dtype=str))
            .astype(str)
            .str.contains("InstanceUsage", na=False)
        ].copy()
        if db.empty:
            return []
        # On-demand only: pricing_term blank/OnDemand AND no reservation ARN.
        if "pricing_term" in db.columns:
            db = db[db["pricing_term"].fillna("").isin(["", "OnDemand"])]
        if "reservation_reservation_a_r_n" in db.columns:
            db = db[db["reservation_reservation_a_r_n"].fillna("") == ""]
        if db.empty:
            return []

        if "line_item_usage_start_date" in db.columns:
            db["__day"] = db["line_item_usage_start_date"].dt.date
            day_count = db.groupby("line_item_resource_id")["__day"].nunique()
        else:
            day_count = None

        agg = (
            db.groupby(
                [
                    "line_item_resource_id",
                    db.get("product_instance_type", pd.Series(index=db.index, dtype=str)).fillna(""),
                    db.get("product_region", pd.Series(index=db.index, dtype=str)).fillna(""),
                    "line_item_product_code",
                ]
            )
            .agg(
                run_hours=("line_item_usage_amount", "sum"),
                cost_usd=("line_item_unblended_cost", "sum"),
            )
            .reset_index()
        )
        agg.columns = ["resource_id", "instance_type", "region", "service", "run_hours", "cost_usd"]
        agg["active_days"] = (
            agg["resource_id"].map(day_count) if day_count is not None else float(max(days, 1))
        )
        agg["active_days"] = agg["active_days"].fillna(float(max(days, 1))).clip(lower=1)
        agg["avg_hours_per_day"] = agg["run_hours"] / agg["active_days"]
        steady = agg[
            (agg["avg_hours_per_day"] >= self.steady_state_hours_per_day)
            & (agg["cost_usd"] >= self.min_steady_state_cost)
        ].sort_values("cost_usd", ascending=False)

        out: List[Dict[str, Any]] = []
        for _, row in steady.head(self.max_findings_per_detector).iterrows():
            monthly_cost = self._monthly(float(row["cost_usd"]), days)
            est_savings = round(monthly_cost * 0.40, 2)  # 1-yr No-Upfront RI ≈ 40 %
            out.append(
                self._opportunity(
                    title=(
                        f"Reserve {row['service']} {row['instance_type'] or 'instance'} "
                        f"running {row['avg_hours_per_day']:.0f} h/day on-demand"
                    ),
                    description=(
                        f"{row['resource_id']} ran {float(row['run_hours']):.0f} hours over "
                        f"{int(row['active_days'])} days (~{float(row['avg_hours_per_day']):.1f} h/day) "
                        f"entirely on-demand at ${monthly_cost:.0f}/mo. A 1-year No-Upfront Reserved "
                        f"Instance would save roughly ${est_savings:.0f}/mo (~40%)."
                    ),
                    category=OpportunityCategory.RESERVED_INSTANCES,
                    service=str(row["service"]),
                    region=str(row["region"]) or None,
                    resource_id=str(row["resource_id"]),
                    resource_type=str(row["instance_type"]) or None,
                    monthly_savings=est_savings,
                    current_monthly_cost=monthly_cost,
                    effort="medium",
                    risk="low",
                    confidence=0.8,
                    evidence={
                        "run_hours": round(float(row["run_hours"]), 1),
                        "active_days": int(row["active_days"]),
                        "avg_hours_per_day": round(float(row["avg_hours_per_day"]), 1),
                        "lookback_period_days": days,
                    },
                    source_id=f"cur-csv-ri-candidate-{abs(hash(row['resource_id'])) % 100000}",
                    steps=[
                        {"step": 1, "action": "Confirm workload will run ≥ 1 year"},
                        {"step": 2, "action": "Purchase 1-yr No-Upfront RI for this instance class"},
                        {"step": 3, "action": "Re-evaluate after 30 days for 3-yr upgrade"},
                    ],
                )
            )
        return out

    def _detect_scheduling_candidates(self, df: pd.DataFrame, days: int) -> List[Dict[str, Any]]:
        if "line_item_usage_start_date" not in df.columns or "line_item_usage_type" not in df.columns:
            return []
        compute = df[
            df["line_item_line_item_type"].eq("Usage")
            & df["line_item_usage_type"].astype(str).str.contains("BoxUsage", na=False)
            & df["line_item_usage_start_date"].notna()
        ].copy()
        if compute.empty:
            return []
        compute["__hour"] = compute["line_item_usage_start_date"].dt.hour
        # Off-hours = 20:00–07:59 UTC. A "flat" profile (off-hours share ~ 50%)
        # on workloads that *should* be batch is the scheduling signal.
        off_mask = (compute["__hour"] >= 20) | (compute["__hour"] < 8)
        by_service = compute.groupby(
            compute.get("line_item_product_code", pd.Series(index=compute.index, dtype=str)).fillna("Unknown")
        )
        out: List[Dict[str, Any]] = []
        for service, grp in by_service:
            total = float(grp["line_item_unblended_cost"].sum())
            if total <= self.min_idle_cost:
                continue
            off = float(grp.loc[off_mask.loc[grp.index], "line_item_unblended_cost"].sum())
            share = off / total if total else 0.0
            if share < self.scheduling_off_hours_share:
                continue
            monthly = self._monthly(total, days)
            est_savings = round(monthly * share * 0.7, 2)  # assume 70% of off-hours can be stopped
            out.append(
                self._opportunity(
                    title=f"{service} compute runs 24×7 — schedule off-hours stop (~${est_savings:.0f}/mo)",
                    description=(
                        f"{service} BoxUsage cost is {share * 100:.0f}% concentrated in off-hours "
                        f"(20:00–07:59 UTC), totalling ${monthly:.0f}/mo. If this is a non-production "
                        "or batch workload, an Instance Scheduler stop/start policy can recover most "
                        "of the off-hours spend."
                    ),
                    category=OpportunityCategory.SCHEDULING,
                    service=str(service),
                    region=None,
                    resource_id=None,
                    monthly_savings=est_savings,
                    current_monthly_cost=monthly,
                    effort="medium",
                    risk="medium",
                    confidence=0.6,
                    evidence={
                        "off_hours_cost_share": round(share, 3),
                        "monthly_compute_cost_usd": round(monthly, 2),
                        "lookback_period_days": days,
                    },
                    source_id=f"cur-csv-schedule-{str(service).lower()}",
                    steps=[
                        {"step": 1, "action": "Tag non-prod / batch instances for scheduling"},
                        {"step": 2, "action": "Deploy AWS Instance Scheduler with off-hours stop"},
                        {"step": 3, "action": "Validate no production workload is affected"},
                    ],
                )
            )
            if len(out) >= self.max_findings_per_detector:
                break
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_period(df: pd.DataFrame) -> tuple[Optional[str], Optional[str], int]:
        if "line_item_usage_start_date" in df.columns:
            ts = df["line_item_usage_start_date"].dropna()
            if not ts.empty:
                start = ts.min()
                end = ts.max()
                days = max(1, (end - start).days + 1)
                return start.date().isoformat(), end.date().isoformat(), days
        return None, None, 30

    @staticmethod
    def _monthly(cost_in_window: float, days: int) -> float:
        days = max(days, 1)
        return round(cost_in_window * 30.0 / days, 2)

    def _opportunity(
        self,
        *,
        title: str,
        description: str,
        category: OpportunityCategory,
        service: str,
        region: Optional[str],
        resource_id: Optional[str],
        monthly_savings: float,
        current_monthly_cost: Optional[float],
        effort: str,
        risk: str,
        confidence: float,
        evidence: Dict[str, Any],
        source_id: str,
        steps: List[Dict[str, Any]],
        resource_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": title,
            "description": description,
            "category": category.value,
            "source": OpportunitySource.CUR_ANALYSIS.value,
            "source_id": source_id,
            "service": service,
            "region": region,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "estimated_monthly_savings": round(float(monthly_savings), 2),
            "estimated_annual_savings": round(float(monthly_savings) * 12.0, 2),
            "current_monthly_cost": (
                round(float(current_monthly_cost), 2) if current_monthly_cost is not None else None
            ),
            "effort_level": effort,
            "risk_level": risk,
            "confidence_score": confidence,
            "implementation_steps": steps,
            "evidence": evidence,
            "api_trace": {"api": "advisory:cur-csv-upload", "timestamp": now},
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }
