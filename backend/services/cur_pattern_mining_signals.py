"""
CUR Pattern-Mining Signals Service (Connected Mode)

Runs the :class:`CURPatternMiningTemplates` Athena queries against the
tenant's live CUR table and converts each result row into an opportunity
dict compatible with ``OpportunitiesService.ingest_signals()``. This is the
live-API half of Feature 2 (CUR / Billing Export Deep Analysis); the
file-based half is :mod:`backend.services.cur_csv_analyzer`.

It also closes the two Connected-Mode signal gaps that were not already
covered by ``ri_savings_plans_signals.py``:

* ``ce:GetAnomalies`` / ``ce:GetAnomalyMonitors`` — surface AWS-detected
  cost spikes as opportunities so the LLM can explain "what spiked and why".
* ``ce:GetCostAndUsage`` — current-month vs prior-3-month service trend, so
  large month-over-month increases become first-class findings.

IAM permissions required (read-only):
  athena:StartQueryExecution
  athena:GetQueryExecution
  athena:GetQueryResults
  s3:GetObject (Athena results bucket)
  glue:GetTable / glue:GetDatabase
  ce:GetAnomalies
  ce:GetAnomalyMonitors
  ce:GetCostAndUsage
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

import structlog
from botocore.exceptions import ClientError

from backend.config.settings import get_settings
from backend.models.opportunities import OpportunityCategory, OpportunitySource
from backend.services.athena_cur_templates import CURPatternMiningTemplates
from backend.services.athena_executor import EnhancedAthenaQueryExecutor
from backend.utils.aws_constants import AwsService
from backend.utils.aws_session import create_aws_session

logger = structlog.get_logger(__name__)
settings = get_settings()


class CURPatternMiningSignalsService:
    """
    Live CUR pattern miner. Mirrors the seven Advisory-Mode detectors in
    :class:`CURCSVAnalyzer` but executes against Athena, then layers on the
    Cost Explorer anomaly + service-trend signals that have no CUR-only
    equivalent.

    All thresholds come from :class:`Settings` so they are configurable per
    tenant deployment via environment variables.
    """

    def __init__(
        self,
        region: Optional[str] = None,
        account_id: Optional[str] = None,
        organization_id: Optional[UUID] = None,
        executor: Optional[EnhancedAthenaQueryExecutor] = None,
    ):
        self.region = region or settings.aws_region
        self.account_id = account_id
        self.organization_id = organization_id

        self.lookback_days = settings.cur_mining_lookback_days
        self.min_idle_cost = settings.cur_mining_min_idle_cost_usd
        self.min_data_transfer_cost = settings.cur_mining_min_data_transfer_usd
        self.min_ri_unused_cost = settings.cur_mining_min_ri_unused_usd
        self.min_sp_unused_cost = settings.cur_mining_min_sp_unused_usd
        self.steady_state_hours_per_day = settings.cur_mining_steady_state_hours_per_day
        self.min_steady_state_cost = settings.cur_mining_min_steady_state_cost_usd
        self.mom_increase_threshold_pct = settings.cur_mining_mom_increase_threshold_pct
        self.max_findings_per_detector = settings.cur_mining_max_findings_per_detector

        self.templates = CURPatternMiningTemplates(
            database=settings.aws_cur_database,
            table=settings.aws_cur_table,
        )
        # Re-use the project's polled Athena executor so retry / output-bucket
        # behaviour stays consistent with the chat pipeline.
        self._executor = executor or EnhancedAthenaQueryExecutor()

        self._session = create_aws_session(region_name=self.region)
        self._ce_client = None
        self._available_columns_cache: Optional[Set[str]] = None

    # ------------------------------------------------------------------
    # Lazy clients
    # ------------------------------------------------------------------

    @property
    def ce_client(self):
        if self._ce_client is None:
            ce_session = create_aws_session(region_name="us-east-1")
            self._ce_client = ce_session.client(AwsService.COST_EXPLORER)
        return self._ce_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def fetch_all_cur_signals(self) -> List[Dict[str, Any]]:
        """Run every detector; failures are logged and skipped, never raised."""
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=self.lookback_days)
        start_s, end_s = start.isoformat(), end.isoformat()

        signals: List[Dict[str, Any]] = []
        available_columns = await self._get_available_columns()
        athena_detectors = [
            (
                "ri_unused_hours",
                self._mine_ri_unused_hours,
                {
                    "reservation_reservation_a_r_n",
                    "reservation_unused_amortized_upfront_fee_for_billing_period",
                    "reservation_unused_recurring_fee",
                    "reservation_unused_quantity",
                },
            ),
            (
                "sp_unused_commitment",
                self._mine_sp_unused_commitment,
                {
                    "savings_plan_savings_plan_a_r_n",
                    "savings_plan_total_commitment_to_date",
                    "savings_plan_used_commitment",
                },
            ),
            ("cross_region_data_transfer", self._mine_cross_region_data_transfer, set()),
            ("idle_resources", self._mine_idle_resources, set()),
            (
                "on_demand_steady_state_db",
                self._mine_on_demand_steady_state_db,
                {"reservation_reservation_a_r_n"},
            ),
        ]
        for label, fn, required_columns in athena_detectors:
            if available_columns and required_columns:
                missing = sorted(required_columns - available_columns)
                if missing:
                    logger.info(
                        "CUR mining detector skipped due to missing schema columns",
                        detector=label,
                        missing_columns=missing,
                    )
                    continue
            try:
                found = await fn(start_s, end_s)
                signals.extend(found)
                logger.info("CUR mining detector complete", detector=label, count=len(found))
            except Exception as exc:
                logger.warning("CUR mining detector failed", detector=label, error=str(exc))

        for label, fn in (
            ("ce_anomalies", self.fetch_cost_anomaly_signals),
            ("ce_service_trend", self.fetch_service_cost_trend_signals),
        ):
            try:
                found = await fn()
                signals.extend(found)
                logger.info("CUR mining CE detector complete", detector=label, count=len(found))
            except Exception as exc:
                logger.warning("CUR mining CE detector failed", detector=label, error=str(exc))

        return signals

    # ------------------------------------------------------------------
    # Athena-backed detectors
    # ------------------------------------------------------------------

    async def _run(self, sql: str) -> List[Dict[str, Any]]:
        # ``_execute_athena_query`` already handles polling + error logging.
        return await self._executor._execute_athena_query(sql)

    async def _get_available_columns(self) -> Set[str]:
        if self._available_columns_cache is not None:
            return self._available_columns_cache

        database = settings.aws_cur_database.replace("'", "''")
        table = settings.aws_cur_table.replace("'", "''")
        sql = (
            "SELECT LOWER(column_name) AS column_name "
            "FROM information_schema.columns "
            f"WHERE table_schema = '{database}' AND table_name = '{table}'"
        )

        try:
            rows = await self._run(sql)
            discovered: Set[str] = set()
            for row in rows:
                name = str(row.get("column_name") or "").strip().lower()
                if name:
                    discovered.add(name)
            self._available_columns_cache = discovered
            if discovered:
                logger.info("Discovered CUR schema columns", count=len(discovered))
            return discovered
        except Exception as exc:
            logger.warning("Failed to discover CUR schema columns", error=str(exc))
            self._available_columns_cache = set()
            return self._available_columns_cache

    async def _mine_ri_unused_hours(self, start: str, end: str) -> List[Dict[str, Any]]:
        sql = self.templates.ri_unused_hours(start, end, min_unused_cost=self.min_ri_unused_cost)
        rows = await self._run(sql)
        out: List[Dict[str, Any]] = []
        for row in rows[: self.max_findings_per_detector]:
            unused = _f(row.get("unused_cost_usd"))
            monthly = _monthly(unused, self.lookback_days)
            out.append(
                self._opportunity(
                    title=f"Unused Reserved Instance capacity (${monthly:.0f}/mo wasted)",
                    description=(
                        f"Reservation {row.get('reservation_arn')} shows "
                        f"${unused:.2f} of unused amortised + recurring fees "
                        f"({_f(row.get('unused_hours')):.0f} unused hours) over the last "
                        f"{self.lookback_days} days. Modify scope, sell on the RI Marketplace, "
                        "or shift matching workloads onto it."
                    ),
                    category=OpportunityCategory.RESERVED_INSTANCES,
                    service=str(row.get("service") or "EC2"),
                    region=row.get("region"),
                    resource_id=row.get("reservation_arn"),
                    monthly_savings=monthly,
                    current_monthly_cost=monthly,
                    effort="medium",
                    risk="low",
                    confidence=0.85,
                    evidence={
                        "unused_cost_usd": round(unused, 2),
                        "unused_hours": round(_f(row.get("unused_hours")), 1),
                        "amortized_cost_usd": round(_f(row.get("amortized_cost_usd")), 2),
                        "lookback_period_days": self.lookback_days,
                    },
                    cur_validation_sql=sql,
                    source_id=f"cur-athena-ri-unused-{abs(hash(str(row.get('reservation_arn')))) % 100000}",
                    steps=[
                        {"step": 1, "action": "Open RI utilisation in Cost Explorer for this ARN"},
                        {"step": 2, "action": "Modify size/scope or list on RI Marketplace"},
                        {"step": 3, "action": "Right-size future RI purchases to match steady-state"},
                    ],
                    deep_link="https://console.aws.amazon.com/cost-management/home#/ri/utilization",
                )
            )
        return out

    async def _mine_sp_unused_commitment(self, start: str, end: str) -> List[Dict[str, Any]]:
        sql = self.templates.sp_unused_commitment(start, end, min_unused_cost=self.min_sp_unused_cost)
        rows = await self._run(sql)
        out: List[Dict[str, Any]] = []
        for row in rows[: self.max_findings_per_detector]:
            unused = _f(row.get("unused_commitment_usd"))
            committed = max(_f(row.get("committed_usd")), 0.01)
            util_pct = max(0.0, min(100.0, _f(row.get("used_usd")) * 100.0 / committed))
            monthly = _monthly(unused, self.lookback_days)
            out.append(
                self._opportunity(
                    title=f"Savings Plan under-utilised ({util_pct:.0f}% used, ${monthly:.0f}/mo wasted)",
                    description=(
                        f"Savings Plan {row.get('savings_plan_arn')} has ${unused:.2f} of "
                        f"committed spend not consumed in the last {self.lookback_days} days "
                        f"({util_pct:.1f}% utilisation). Migrate eligible compute onto the plan "
                        "or reduce the next commitment."
                    ),
                    category=OpportunityCategory.SAVINGS_PLANS,
                    service="Compute Savings Plan",
                    region=row.get("region"),
                    resource_id=row.get("savings_plan_arn"),
                    monthly_savings=monthly,
                    current_monthly_cost=monthly,
                    effort="medium",
                    risk="low",
                    confidence=0.85,
                    evidence={
                        "unused_commitment_usd": round(unused, 2),
                        "committed_usd": round(_f(row.get("committed_usd")), 2),
                        "used_usd": round(_f(row.get("used_usd")), 2),
                        "utilization_pct": round(util_pct, 1),
                        "lookback_period_days": self.lookback_days,
                    },
                    cur_validation_sql=sql,
                    source_id=f"cur-athena-sp-unused-{abs(hash(str(row.get('savings_plan_arn')))) % 100000}",
                    steps=[
                        {"step": 1, "action": "Confirm SP utilisation in Cost Explorer"},
                        {"step": 2, "action": "Migrate on-demand compute into SP-eligible families"},
                        {"step": 3, "action": "Right-size next SP commitment to actual baseline"},
                    ],
                    deep_link="https://console.aws.amazon.com/cost-management/home#/savings-plans/utilization",
                )
            )
        return out

    async def _mine_cross_region_data_transfer(self, start: str, end: str) -> List[Dict[str, Any]]:
        sql = self.templates.cross_region_data_transfer(start, end, min_cost=self.min_data_transfer_cost)
        rows = await self._run(sql)
        out: List[Dict[str, Any]] = []
        for row in rows[: self.max_findings_per_detector]:
            cost = _f(row.get("cost_usd"))
            monthly = _monthly(cost, self.lookback_days)
            region = row.get("region")
            service = str(row.get("service") or "AWSDataTransfer")
            out.append(
                self._opportunity(
                    title=f"High cross-region data transfer in {region or 'multiple regions'} (${monthly:.0f}/mo)",
                    description=(
                        f"${cost:.2f} of inter-region / regional data-transfer charges from "
                        f"{service} in {region or 'this account'} over {self.lookback_days} days. "
                        "Co-locate producers and consumers, or replace cross-region traffic with "
                        "VPC Peering / PrivateLink."
                    ),
                    category=OpportunityCategory.DATA_TRANSFER,
                    service=service,
                    region=region,
                    resource_id=None,
                    monthly_savings=round(monthly * 0.5, 2),
                    current_monthly_cost=monthly,
                    effort="high",
                    risk="medium",
                    confidence=0.7,
                    evidence={
                        "transfer_cost_usd": round(cost, 2),
                        "gb_transferred": round(_f(row.get("gb_transferred")), 2),
                        "lookback_period_days": self.lookback_days,
                    },
                    cur_validation_sql=sql,
                    source_id=f"cur-athena-dt-{(region or 'all').lower()}-{service.lower()}",
                    steps=[
                        {"step": 1, "action": "Identify producer/consumer pair driving the transfer"},
                        {"step": 2, "action": "Evaluate co-locating in a single region"},
                        {"step": 3, "action": "If co-location is impossible, price PrivateLink / S3 CRR"},
                    ],
                )
            )
        return out

    async def _mine_idle_resources(self, start: str, end: str) -> List[Dict[str, Any]]:
        sql = self.templates.idle_resources_with_cost(start, end, min_cost=self.min_idle_cost)
        rows = await self._run(sql)
        out: List[Dict[str, Any]] = []
        for row in rows[: self.max_findings_per_detector]:
            cost = _f(row.get("cost_usd"))
            monthly = _monthly(cost, self.lookback_days)
            out.append(
                self._opportunity(
                    title=f"Idle resource costing ${monthly:.0f}/mo: {row.get('resource_id')}",
                    description=(
                        f"Resource {row.get('resource_id')} ({row.get('service')}, "
                        f"{row.get('usage_type')}) incurred ${cost:.2f} with zero usage in the "
                        f"last {self.lookback_days} days. It is likely orphaned or permanently "
                        "idle and can be terminated."
                    ),
                    category=OpportunityCategory.IDLE_RESOURCES,
                    service=str(row.get("service") or "Unknown"),
                    region=row.get("region"),
                    resource_id=row.get("resource_id"),
                    monthly_savings=monthly,
                    current_monthly_cost=monthly,
                    effort="low",
                    risk="low",
                    confidence=0.75,
                    evidence={
                        "cost_usd": round(cost, 2),
                        "usage_amount": 0.0,
                        "usage_type": row.get("usage_type"),
                        "lookback_period_days": self.lookback_days,
                    },
                    cur_validation_sql=sql,
                    source_id=f"cur-athena-idle-{abs(hash(str(row.get('resource_id')))) % 100000}",
                    steps=[
                        {"step": 1, "action": "Confirm the resource is unused (CloudWatch / owner)"},
                        {"step": 2, "action": "Snapshot if stateful, then terminate / release"},
                    ],
                )
            )
        return out

    async def _mine_on_demand_steady_state_db(self, start: str, end: str) -> List[Dict[str, Any]]:
        sql = self.templates.on_demand_steady_state_db(
            start,
            end,
            min_run_hours_per_day=self.steady_state_hours_per_day,
            min_cost=self.min_steady_state_cost,
        )
        rows = await self._run(sql)
        out: List[Dict[str, Any]] = []
        for row in rows[: self.max_findings_per_detector]:
            monthly_cost = _monthly(_f(row.get("cost_usd")), self.lookback_days)
            est_savings = round(monthly_cost * 0.40, 2)
            instance_type = row.get("instance_type") or "instance"
            out.append(
                self._opportunity(
                    title=(
                        f"Reserve RDS/{instance_type} running "
                        f"{_f(row.get('avg_hours_per_day')):.0f} h/day on-demand"
                    ),
                    description=(
                        f"{row.get('resource_id')} ran {_f(row.get('run_hours')):.0f} hours over "
                        f"{int(_f(row.get('active_days')))} days entirely on-demand at "
                        f"${monthly_cost:.0f}/mo. A 1-year No-Upfront Reserved Instance would save "
                        f"~${est_savings:.0f}/mo (~40%)."
                    ),
                    category=OpportunityCategory.RESERVED_INSTANCES,
                    service="AmazonRDS",
                    region=row.get("region"),
                    resource_id=row.get("resource_id"),
                    resource_type=str(instance_type),
                    monthly_savings=est_savings,
                    current_monthly_cost=monthly_cost,
                    effort="medium",
                    risk="low",
                    confidence=0.8,
                    evidence={
                        "run_hours": round(_f(row.get("run_hours")), 1),
                        "active_days": int(_f(row.get("active_days"))),
                        "avg_hours_per_day": round(_f(row.get("avg_hours_per_day")), 1),
                        "lookback_period_days": self.lookback_days,
                    },
                    cur_validation_sql=sql,
                    source_id=f"cur-athena-ri-candidate-{abs(hash(str(row.get('resource_id')))) % 100000}",
                    steps=[
                        {"step": 1, "action": "Confirm workload will run ≥ 1 year"},
                        {"step": 2, "action": "Purchase 1-yr No-Upfront RI for this instance class"},
                        {"step": 3, "action": "Re-evaluate after 30 days for 3-yr upgrade"},
                    ],
                    deep_link="https://console.aws.amazon.com/cost-management/home#/ri/recommendations",
                )
            )
        return out

    # ------------------------------------------------------------------
    # Cost Explorer-backed detectors
    # ------------------------------------------------------------------

    async def fetch_cost_anomaly_signals(self) -> List[Dict[str, Any]]:
        """ce:GetAnomalies — surface AWS-detected cost spikes as opportunities."""
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=self.lookback_days)
        out: List[Dict[str, Any]] = []
        try:
            resp = self.ce_client.get_anomalies(
                DateInterval={"StartDate": start.isoformat(), "EndDate": end.isoformat()},
                MaxResults=self.max_findings_per_detector,
            )
            for anomaly in resp.get("Anomalies", []):
                impact = anomaly.get("Impact", {})
                total_impact = _f(impact.get("TotalImpact"))
                if total_impact <= 0:
                    continue
                root_causes = anomaly.get("RootCauses") or [{}]
                rc = root_causes[0]
                service = rc.get("Service") or "Unknown"
                region = rc.get("Region")
                out.append(
                    self._opportunity(
                        title=f"Cost anomaly in {service}: ${total_impact:.0f} above baseline",
                        description=(
                            f"AWS Cost Anomaly Detection flagged a ${total_impact:.2f} spike in "
                            f"{service} ({region or 'global'}) between "
                            f"{anomaly.get('AnomalyStartDate')} and {anomaly.get('AnomalyEndDate')}. "
                            f"Root cause: {rc.get('UsageType') or rc.get('LinkedAccountName') or 'see console'}."
                        ),
                        category=OpportunityCategory.OTHER,
                        service=service,
                        region=region,
                        resource_id=anomaly.get("AnomalyId"),
                        monthly_savings=total_impact,
                        current_monthly_cost=None,
                        effort="low",
                        risk="low",
                        confidence=min(1.0, _f(anomaly.get("AnomalyScore", {}).get("CurrentScore")) or 0.7),
                        evidence={
                            "anomaly_id": anomaly.get("AnomalyId"),
                            "anomaly_start": anomaly.get("AnomalyStartDate"),
                            "anomaly_end": anomaly.get("AnomalyEndDate"),
                            "total_impact_usd": round(total_impact, 2),
                            "root_causes": root_causes,
                        },
                        source_id=f"ce-anomaly-{anomaly.get('AnomalyId')}",
                        api_trace_api="ce:GetAnomalies",
                        steps=[
                            {"step": 1, "action": "Open the anomaly in Cost Explorer to confirm scope"},
                            {"step": 2, "action": "Identify the resource(s) responsible for the spike"},
                            {"step": 3, "action": "Add a budget alert or scale-in policy to cap recurrence"},
                        ],
                        deep_link="https://console.aws.amazon.com/cost-management/home#/anomaly-detection",
                    )
                )
        except ClientError as exc:
            logger.warning("ce:GetAnomalies failed", error=str(exc))
        return out

    async def fetch_service_cost_trend_signals(self) -> List[Dict[str, Any]]:
        """
        ce:GetCostAndUsage — current month vs trailing-3-month average per
        service. Services whose run-rate exceeds the trailing average by
        ``mom_increase_threshold_pct`` are surfaced.
        """
        today = datetime.now(timezone.utc).date()
        # Need 3 full prior months + current month-to-date.
        first_of_current = today.replace(day=1)
        start = (first_of_current - timedelta(days=1)).replace(day=1)
        for _ in range(2):
            start = (start - timedelta(days=1)).replace(day=1)

        out: List[Dict[str, Any]] = []
        try:
            resp = self.ce_client.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": today.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            results = resp.get("ResultsByTime", [])
            if len(results) < 2:
                return out

            current = results[-1]
            prior = results[:-1]
            days_in_current = max((today - first_of_current).days, 1)

            # Build trailing average per service
            trailing: Dict[str, float] = {}
            for month in prior:
                for grp in month.get("Groups", []):
                    svc = grp["Keys"][0]
                    amt = _f(grp["Metrics"]["UnblendedCost"]["Amount"])
                    trailing[svc] = trailing.get(svc, 0.0) + amt
            for svc in list(trailing):
                trailing[svc] /= max(len(prior), 1)

            for grp in current.get("Groups", []):
                svc = grp["Keys"][0]
                mtd = _f(grp["Metrics"]["UnblendedCost"]["Amount"])
                projected = mtd * 30.0 / days_in_current
                baseline = trailing.get(svc, 0.0)
                if baseline < 1.0:
                    continue
                increase_pct = (projected - baseline) * 100.0 / baseline
                if increase_pct < self.mom_increase_threshold_pct:
                    continue
                out.append(
                    self._opportunity(
                        title=f"{svc} trending {increase_pct:.0f}% above 3-month average",
                        description=(
                            f"{svc} is projected to cost ${projected:.0f} this month vs a "
                            f"${baseline:.0f} trailing-3-month average (+{increase_pct:.0f}%). "
                            "Investigate before month-end to avoid bill shock."
                        ),
                        category=OpportunityCategory.OTHER,
                        service=svc,
                        region=None,
                        resource_id=None,
                        monthly_savings=round(max(projected - baseline, 0.0), 2),
                        current_monthly_cost=round(projected, 2),
                        effort="low",
                        risk="low",
                        confidence=0.7,
                        evidence={
                            "projected_month_usd": round(projected, 2),
                            "trailing_3mo_avg_usd": round(baseline, 2),
                            "increase_pct": round(increase_pct, 1),
                        },
                        source_id=f"ce-trend-{svc.lower().replace(' ', '-')}",
                        api_trace_api="ce:GetCostAndUsage",
                        steps=[
                            {"step": 1, "action": f"Open Cost Explorer filtered to {svc}"},
                            {"step": 2, "action": "Group by Usage Type to find the driver"},
                            {"step": 3, "action": "Set a budget alert at the trailing average"},
                        ],
                        deep_link="https://console.aws.amazon.com/cost-management/home#/cost-explorer",
                    )
                )
                if len(out) >= self.max_findings_per_detector:
                    break
        except ClientError as exc:
            logger.warning("ce:GetCostAndUsage trend failed", error=str(exc))
        return out

    # ------------------------------------------------------------------
    # Opportunity builder
    # ------------------------------------------------------------------

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
        cur_validation_sql: Optional[str] = None,
        resource_type: Optional[str] = None,
        api_trace_api: str = "athena:StartQueryExecution",
        deep_link: Optional[str] = None,
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
            "cur_validation_sql": cur_validation_sql,
            "api_trace": {"api": api_trace_api, "timestamp": now},
            "deep_link": deep_link,
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _f(value: Any) -> float:
    """Best-effort float coercion for Athena/CE string-typed numerics."""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _monthly(cost_in_window: float, days: int) -> float:
    days = max(int(days), 1)
    return round(cost_in_window * 30.0 / days, 2)
