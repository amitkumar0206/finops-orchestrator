"""
RI & Savings Plans Coverage Analysis Service

Detects gaps between what you're spending and what's covered by commitments,
and flags underutilized or expiring reservations.

Signals fetched:
- GetReservationCoverage     → which usage hours are NOT covered by RIs
- GetReservationUtilization  → which purchased RIs are going unused
- GetReservationPurchaseRecommendation  → what to buy next
- GetSavingsPlansCoverage    → eligible spend not under a Savings Plan
- GetSavingsPlansUtilization → how much of purchased SPs is consumed
- GetSavingsPlansPurchaseRecommendation → what commitment to add
- ec2:DescribeReservedInstances → expiring RI notifications (< 90 days)

IAM permissions required:
  ce:GetReservationCoverage
  ce:GetReservationUtilization
  ce:GetReservationPurchaseRecommendation
  ce:GetSavingsPlansCoverage
  ce:GetSavingsPlansUtilization
  ce:GetSavingsPlansPurchaseRecommendation
  ec2:DescribeReservedInstances
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import structlog
from botocore.exceptions import ClientError

from backend.config.settings import get_settings
from backend.utils.aws_constants import AwsService
from backend.utils.aws_session import create_aws_session

logger = structlog.get_logger(__name__)
settings = get_settings()

# Thresholds
RI_COVERAGE_MIN_PCT = 60.0        # below → recommend purchase
RI_UTILIZATION_MIN_PCT = 50.0     # below → investigate underused RIs
SP_COVERAGE_MIN_PCT = 60.0        # below → recommend SP purchase
SP_UTILIZATION_MIN_PCT = 80.0     # below → reduce SP commitment
RI_EXPIRY_WARNING_DAYS = 90       # notify this many days before expiry
LOOKBACK_DAYS = 30


class RISavingsPlansSignalsService:
    """
    Cost Explorer-based analysis for Reserved Instance and Savings Plans
    coverage, utilization, and purchase recommendations.
    """

    def __init__(
        self,
        region: str = None,
        account_id: str = None,
        organization_id: Optional[UUID] = None,
    ):
        self.region = region or settings.aws_region
        self.account_id = account_id
        self.organization_id = organization_id
        self._session = create_aws_session(region_name=self.region)
        self._ce_client = None
        self._ec2_client = None

    @property
    def ce_client(self):
        if self._ce_client is None:
            # Cost Explorer is a global API endpoint
            ce_session = create_aws_session(region_name="us-east-1")
            self._ce_client = ce_session.client(AwsService.COST_EXPLORER)
        return self._ce_client

    @property
    def ec2_client(self):
        if self._ec2_client is None:
            self._ec2_client = self._session.client(AwsService.EC2)
        return self._ec2_client

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def fetch_ri_coverage_signals(self) -> List[Dict[str, Any]]:
        """
        Detect low RI coverage gaps per service/region.
        Returns an opportunity for each service+region where coverage < 60%.
        """
        opportunities: List[Dict[str, Any]] = []
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=LOOKBACK_DAYS)

        try:
            response = self.ce_client.get_reservation_coverage(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d"),
                },
                GroupBy=[
                    {"Type": "DIMENSION", "Key": "SERVICE"},
                    {"Type": "DIMENSION", "Key": "REGION"},
                ],
                Granularity="MONTHLY",
            )

            for group in response.get("Total", {}).get("Groups", []):
                self._process_ri_coverage_group(group, opportunities)

            # Also check Top-level total coverage
            total = response.get("Total", {}).get("CoverageHours", {})
            if total:
                coverage_pct = float(total.get("CoverageHoursPercentage", 100))
                if coverage_pct < RI_COVERAGE_MIN_PCT:
                    opp = self._make_ri_coverage_opportunity(
                        service="ALL_SERVICES",
                        region=self.region,
                        coverage_pct=coverage_pct,
                        on_demand_hours=float(total.get("OnDemandHours", 0)),
                        monthly_on_demand_cost=None,
                    )
                    opportunities.append(opp)

            logger.info(f"RI coverage scan: {len(opportunities)} gaps found")

        except ClientError as e:
            logger.error(f"CE GetReservationCoverage error: {e}")
        except Exception as e:
            logger.error(f"Error fetching RI coverage: {e}")

        return opportunities

    async def fetch_ri_utilization_signals(self) -> List[Dict[str, Any]]:
        """
        Detect underutilized Reserved Instances (purchased but not fully used).
        """
        opportunities: List[Dict[str, Any]] = []
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=LOOKBACK_DAYS)

        try:
            response = self.ce_client.get_reservation_utilization(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d"),
                },
                GroupBy=[{"Type": "DIMENSION", "Key": "SUBSCRIPTION_ID"}],
                Granularity="MONTHLY",
            )

            for group in response.get("UtilizationsByTime", []):
                for group_item in group.get("Groups", []):
                    util_data = group_item.get("Utilization", {})
                    util_pct = float(util_data.get("UtilizationPercentage", 100))

                    if util_pct >= RI_UTILIZATION_MIN_PCT:
                        continue

                    subscription_id = group_item.get("Attributes", {}).get("subscriptionId", "")
                    unused_cost = float(util_data.get("UnusedRecurringFee", 0))
                    unused_hours = float(util_data.get("UnusedHours", 0))

                    if unused_cost <= 0:
                        continue

                    opp = self._make_ri_utilization_opportunity(
                        subscription_id=subscription_id,
                        util_pct=util_pct,
                        unused_cost=unused_cost,
                        unused_hours=unused_hours,
                        lookback_days=LOOKBACK_DAYS,
                    )
                    opportunities.append(opp)

            logger.info(f"RI utilization scan: {len(opportunities)} underutilized RIs found")

        except ClientError as e:
            logger.error(f"CE GetReservationUtilization error: {e}")
        except Exception as e:
            logger.error(f"Error fetching RI utilization: {e}")

        return opportunities

    async def fetch_ri_purchase_recommendation_signals(self) -> List[Dict[str, Any]]:
        """
        Fetch Cost Explorer RI purchase recommendations for EC2, RDS, ElastiCache, etc.
        """
        opportunities: List[Dict[str, Any]] = []

        services = [
            ("AmazonEC2", "EC2"),
            ("AmazonRDS", "RDS"),
            ("AmazonElastiCache", "ElastiCache"),
            ("AmazonRedshift", "Redshift"),
        ]

        for ce_service, display_name in services:
            try:
                response = self.ce_client.get_reservation_purchase_recommendation(
                    Service=ce_service,
                    LookbackPeriodInDays="THIRTY_DAYS",
                    TermInYears="ONE_YEAR",
                    PaymentOption="NO_UPFRONT",
                )
                recs = response.get("Recommendations", [])
                for rec in recs:
                    summary = rec.get("RecommendationSummary", {})
                    est_savings = float(summary.get("TotalEstimatedMonthlySavingsAmount", 0))
                    if est_savings <= 0:
                        continue
                    opp = self._make_ri_purchase_opportunity(
                        rec=rec,
                        service=display_name,
                        est_monthly_savings=est_savings,
                    )
                    opportunities.append(opp)

            except ClientError as e:
                if "OptInRequired" in str(e):
                    logger.warning(f"RI purchase recommendations require opt-in for {ce_service}")
                else:
                    logger.warning(f"CE RI purchase recommendation error for {ce_service}: {e}")

        logger.info(f"RI purchase recommendations: {len(opportunities)} found")
        return opportunities

    async def fetch_savings_plans_coverage_signals(self) -> List[Dict[str, Any]]:
        """
        Detect compute and EC2 spend not covered by Savings Plans.
        """
        opportunities: List[Dict[str, Any]] = []
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=LOOKBACK_DAYS)

        try:
            response = self.ce_client.get_savings_plans_coverage(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d"),
                },
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
                Granularity="MONTHLY",
            )

            for time_result in response.get("SavingsPlansCoverages", []):
                for group in time_result.get("Groups", []):
                    coverage = group.get("Coverage", {})
                    coverage_pct = float(coverage.get("CoveragePercentage", 100))

                    if coverage_pct >= SP_COVERAGE_MIN_PCT:
                        continue

                    service = group.get("Attributes", {}).get("SERVICE", "Unknown")
                    on_demand_cost = float(coverage.get("OnDemandCost", 0))

                    if on_demand_cost < 50:  # Skip tiny amounts
                        continue

                    potential_savings = on_demand_cost * 0.35  # ~35% average SP discount
                    opp = self._make_sp_coverage_opportunity(
                        service=service,
                        coverage_pct=coverage_pct,
                        on_demand_cost=on_demand_cost,
                        potential_savings=potential_savings,
                    )
                    opportunities.append(opp)

            logger.info(f"Savings Plans coverage scan: {len(opportunities)} gaps found")

        except ClientError as e:
            logger.error(f"CE GetSavingsPlansCoverage error: {e}")
        except Exception as e:
            logger.error(f"Error fetching SP coverage: {e}")

        return opportunities

    async def fetch_savings_plans_utilization_signals(self) -> List[Dict[str, Any]]:
        """
        Detect Savings Plans with low utilization (paying for commitment not being consumed).
        """
        opportunities: List[Dict[str, Any]] = []
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=LOOKBACK_DAYS)

        try:
            response = self.ce_client.get_savings_plans_utilization(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d"),
                },
                Granularity="MONTHLY",
            )

            total = response.get("Total", {}).get("Utilization", {})
            util_pct = float(total.get("UtilizationPercentage", 100))
            unused_commitment = float(total.get("UnusedCommitment", 0))

            if util_pct < SP_UTILIZATION_MIN_PCT and unused_commitment > 0:
                opp = self._make_sp_utilization_opportunity(
                    util_pct=util_pct,
                    unused_commitment=unused_commitment,
                    lookback_days=LOOKBACK_DAYS,
                )
                opportunities.append(opp)

            logger.info(f"Savings Plans utilization scan: {len(opportunities)} issues found")

        except ClientError as e:
            logger.error(f"CE GetSavingsPlansUtilization error: {e}")
        except Exception as e:
            logger.error(f"Error fetching SP utilization: {e}")

        return opportunities

    async def fetch_savings_plans_purchase_recommendation_signals(self) -> List[Dict[str, Any]]:
        """
        Fetch Cost Explorer Savings Plans purchase recommendations.
        """
        opportunities: List[Dict[str, Any]] = []

        for sp_type in ["COMPUTE_SP", "EC2_INSTANCE_SP"]:
            try:
                response = self.ce_client.get_savings_plans_purchase_recommendation(
                    SavingsPlansType=sp_type,
                    TermInYears="ONE_YEAR",
                    PaymentOption="NO_UPFRONT",
                    LookbackPeriodInDays="THIRTY_DAYS",
                )
                summary = response.get("SavingsPlansPurchaseRecommendationSummary", {})
                est_savings = float(summary.get("EstimatedMonthlySavingsAmount", 0))

                if est_savings <= 0:
                    continue

                hourly_commitment = float(
                    summary.get("HourlyCommitmentToPurchase", 0)
                )
                opp = self._make_sp_purchase_opportunity(
                    sp_type=sp_type,
                    est_monthly_savings=est_savings,
                    hourly_commitment=hourly_commitment,
                )
                opportunities.append(opp)

            except ClientError as e:
                logger.warning(f"CE SP purchase recommendation error ({sp_type}): {e}")

        logger.info(f"SP purchase recommendations: {len(opportunities)} found")
        return opportunities

    async def fetch_expiring_ri_signals(self) -> List[Dict[str, Any]]:
        """
        Detect Reserved Instances expiring within 90 days via ec2:DescribeReservedInstances.
        """
        opportunities: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        warning_cutoff = now + timedelta(days=RI_EXPIRY_WARNING_DAYS)

        try:
            response = self.ec2_client.describe_reserved_instances(
                Filters=[{"Name": "state", "Values": ["active"]}]
            )

            for ri in response.get("ReservedInstances", []):
                end_time = ri.get("End")
                if end_time is None:
                    continue

                # AWS returns timezone-aware datetime
                if end_time > warning_cutoff:
                    continue

                days_until_expiry = max(0, (end_time - now).days)
                instance_type = ri.get("InstanceType", "")
                count = ri.get("InstanceCount", 1)
                monthly_cost = (ri.get("FixedPrice", 0) or 0) / 12

                opp = self._make_ri_expiry_opportunity(
                    ri_id=ri.get("ReservedInstancesId", ""),
                    instance_type=instance_type,
                    count=count,
                    days_until_expiry=days_until_expiry,
                    end_time=end_time,
                    monthly_cost=monthly_cost,
                )
                opportunities.append(opp)

            logger.info(f"Expiring RI scan: {len(opportunities)} RIs expiring within 90 days")

        except ClientError as e:
            logger.error(f"EC2 DescribeReservedInstances error: {e}")
        except Exception as e:
            logger.error(f"Error fetching expiring RIs: {e}")

        return opportunities

    async def fetch_all_ri_sp_signals(self) -> List[Dict[str, Any]]:
        """Fetch all RI and Savings Plans optimization signals."""
        all_signals: List[Dict[str, Any]] = []

        fetchers = [
            ("RI Coverage", self.fetch_ri_coverage_signals),
            ("RI Utilization", self.fetch_ri_utilization_signals),
            ("RI Purchase Recommendations", self.fetch_ri_purchase_recommendation_signals),
            ("SP Coverage", self.fetch_savings_plans_coverage_signals),
            ("SP Utilization", self.fetch_savings_plans_utilization_signals),
            ("SP Purchase Recommendations", self.fetch_savings_plans_purchase_recommendation_signals),
            ("Expiring RIs", self.fetch_expiring_ri_signals),
        ]

        for label, fetch_fn in fetchers:
            try:
                signals = await fetch_fn()
                all_signals.extend(signals)
                logger.info(f"RI/SP {label}: {len(signals)} signals")
            except Exception as e:
                logger.error(f"RI/SP {label} fetch failed: {e}")

        return all_signals

    # ------------------------------------------------------------------
    # RI coverage group processing
    # ------------------------------------------------------------------

    def _process_ri_coverage_group(
        self, group: Dict[str, Any], opportunities: List[Dict[str, Any]]
    ) -> None:
        """Process a single RI coverage group and append opportunity if needed."""
        try:
            coverage_data = group.get("Metrics", {}).get("CoverageHours", {})
            coverage_pct = float(coverage_data.get("CoverageHoursPercentage", 100))

            if coverage_pct >= RI_COVERAGE_MIN_PCT:
                return

            keys = group.get("Keys", [])
            service = keys[0] if len(keys) > 0 else "Unknown"
            region = keys[1] if len(keys) > 1 else self.region

            on_demand_hours = float(coverage_data.get("OnDemandHours", 0))
            if on_demand_hours < 100:  # Skip tiny usage
                return

            opp = self._make_ri_coverage_opportunity(
                service=service,
                region=region,
                coverage_pct=coverage_pct,
                on_demand_hours=on_demand_hours,
                monthly_on_demand_cost=None,
            )
            opportunities.append(opp)
        except Exception as e:
            logger.warning(f"Error processing RI coverage group: {e}")

    # ------------------------------------------------------------------
    # Opportunity builders
    # ------------------------------------------------------------------

    def _make_ri_coverage_opportunity(
        self,
        service: str,
        region: str,
        coverage_pct: float,
        on_demand_hours: float,
        monthly_on_demand_cost: Optional[float],
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        gap_pct = 100 - coverage_pct
        # Rough savings: uncovered on-demand hours * average EC2 rate * 40% RI discount
        est_savings = on_demand_hours * 0.10 * 0.40 if on_demand_hours else 0

        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Low RI Coverage: {service} in {region} ({coverage_pct:.0f}% covered)",
            "description": (
                f"Only {coverage_pct:.1f}% of {service} usage hours in {region} are covered "
                f"by Reserved Instances. The remaining {gap_pct:.1f}% ({on_demand_hours:.0f} hours) "
                f"are billed at on-demand rates. Purchasing RIs for steady-state workloads can "
                f"save 30–60% on compute costs."
            ),
            "category": "reserved_instances",
            "source": "cost_explorer",
            "source_id": f"ce-ri-coverage-{service}-{region}".lower().replace(" ", "-"),
            "service": service,
            "region": region,
            "resource_id": None,
            "estimated_monthly_savings": round(est_savings, 2),
            "estimated_annual_savings": round(est_savings * 12, 2),
            "effort_level": "medium",
            "risk_level": "low",
            "confidence_score": 0.80,
            "implementation_steps": [
                {"step": 1, "action": f"Review {service} usage patterns in Cost Explorer"},
                {"step": 2, "action": "Identify stable, long-running workloads suitable for RIs"},
                {"step": 3, "action": "Start with 1-year No Upfront RIs to minimize commitment risk"},
                {"step": 4, "action": f"Purchase RIs covering ~{min(70, coverage_pct + 20):.0f}% of usage"},
                {"step": 5, "action": "Monitor coverage weekly and adjust over 3 months"},
            ],
            "evidence": {
                "coverage_pct": coverage_pct,
                "on_demand_hours": on_demand_hours,
                "lookback_period_days": LOOKBACK_DAYS,
                "target_coverage_pct": RI_COVERAGE_MIN_PCT,
            },
            "api_trace": {
                "api": "ce:GetReservationCoverage",
                "timestamp": now,
            },
            "deep_link": "https://console.aws.amazon.com/cost-management/home#/ri/coverage",
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_ri_utilization_opportunity(
        self,
        subscription_id: str,
        util_pct: float,
        unused_cost: float,
        unused_hours: float,
        lookback_days: int,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Underutilized RI: {subscription_id} ({util_pct:.0f}% utilized)",
            "description": (
                f"Reserved Instance {subscription_id} is only {util_pct:.1f}% utilized "
                f"over the last {lookback_days} days. You are paying for "
                f"{unused_hours:.0f} unused hours (${unused_cost:.0f}/month wasted). "
                f"Consider selling on the RI Marketplace or modifying the scope."
            ),
            "category": "reserved_instances",
            "source": "cost_explorer",
            "source_id": f"ce-ri-util-{subscription_id}",
            "service": "EC2",
            "resource_id": subscription_id,
            "estimated_monthly_savings": round(unused_cost, 2),
            "estimated_annual_savings": round(unused_cost * 12, 2),
            "current_monthly_cost": round(unused_cost, 2),
            "projected_monthly_cost": 0.0,
            "effort_level": "medium",
            "risk_level": "low",
            "confidence_score": 0.85,
            "implementation_steps": [
                {"step": 1, "action": "Review which instances are using this RI scope"},
                {"step": 2, "action": "Check if the RI can be modified to a different instance size"},
                {"step": 3, "action": "If modification not possible, list on AWS Reserved Instance Marketplace"},
                {"step": 4, "action": "Adjust future RI purchases to better match actual usage"},
            ],
            "evidence": {
                "utilization_pct": util_pct,
                "unused_hours": unused_hours,
                "unused_cost": unused_cost,
                "lookback_period_days": lookback_days,
            },
            "api_trace": {
                "api": "ce:GetReservationUtilization",
                "timestamp": now,
            },
            "deep_link": "https://console.aws.amazon.com/cost-management/home#/ri/utilization",
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_ri_purchase_opportunity(
        self,
        rec: Dict[str, Any],
        service: str,
        est_monthly_savings: float,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        summary = rec.get("RecommendationSummary", {})
        number_recs = len(rec.get("RecommendationDetails", []))

        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Purchase {service} Reserved Instances to Save ${est_monthly_savings:.0f}/month",
            "description": (
                f"Cost Explorer recommends purchasing {number_recs} {service} Reserved Instance(s) "
                f"based on 30 days of usage history. Estimated savings: "
                f"${est_monthly_savings:.0f}/month (${est_monthly_savings * 12:.0f}/year) "
                f"with 1-year No Upfront terms."
            ),
            "category": "reserved_instances",
            "source": "cost_explorer",
            "source_id": f"ce-ri-purchase-{service}-{hash(str(summary)) % 100000}".lower(),
            "service": service,
            "estimated_monthly_savings": round(est_monthly_savings, 2),
            "estimated_annual_savings": round(est_monthly_savings * 12, 2),
            "effort_level": "medium",
            "risk_level": "low",
            "confidence_score": 0.82,
            "implementation_steps": [
                {"step": 1, "action": "Review Cost Explorer RI recommendation details"},
                {"step": 2, "action": "Confirm workloads are stable and long-running"},
                {"step": 3, "action": "Start with 1-year No Upfront to test commitment"},
                {"step": 4, "action": "Purchase via AWS Console → Savings & Commitments"},
                {"step": 5, "action": "Monitor coverage ratio over the following month"},
            ],
            "evidence": {
                "recommendation_count": number_recs,
                "lookback_period_days": LOOKBACK_DAYS,
                "term": "ONE_YEAR",
                "payment_option": "NO_UPFRONT",
            },
            "api_trace": {
                "api": "ce:GetReservationPurchaseRecommendation",
                "service": service,
                "timestamp": now,
            },
            "deep_link": "https://console.aws.amazon.com/cost-management/home#/ri/purchase-recommendations",
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_sp_coverage_opportunity(
        self,
        service: str,
        coverage_pct: float,
        on_demand_cost: float,
        potential_savings: float,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        gap_pct = 100 - coverage_pct
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Low Savings Plan Coverage: {service} ({coverage_pct:.0f}% covered)",
            "description": (
                f"Only {coverage_pct:.1f}% of {service} eligible spend is covered by "
                f"Savings Plans. The uncovered {gap_pct:.1f}% is billed at on-demand rates "
                f"(${on_demand_cost:.0f}/month). Adding a Compute Savings Plan could save "
                f"~${potential_savings:.0f}/month with no instance type constraints."
            ),
            "category": "savings_plans",
            "source": "cost_explorer",
            "source_id": f"ce-sp-coverage-{service}".lower().replace(" ", "-"),
            "service": service,
            "estimated_monthly_savings": round(potential_savings, 2),
            "estimated_annual_savings": round(potential_savings * 12, 2),
            "effort_level": "medium",
            "risk_level": "low",
            "confidence_score": 0.80,
            "implementation_steps": [
                {"step": 1, "action": "Review SP coverage in Cost Explorer → Savings Plans → Coverage"},
                {"step": 2, "action": "Use Cost Explorer SP purchase recommendation to size commitment"},
                {"step": 3, "action": "Start with Compute SP for maximum flexibility across instance types"},
                {"step": 4, "action": "Purchase 1-year No Upfront for lowest risk commitment"},
                {"step": 5, "action": "Re-evaluate coverage monthly for first 3 months"},
            ],
            "evidence": {
                "coverage_pct": coverage_pct,
                "on_demand_cost": on_demand_cost,
                "lookback_period_days": LOOKBACK_DAYS,
            },
            "api_trace": {
                "api": "ce:GetSavingsPlansCoverage",
                "timestamp": now,
            },
            "deep_link": "https://console.aws.amazon.com/cost-management/home#/savings-plans/coverage",
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_sp_utilization_opportunity(
        self,
        util_pct: float,
        unused_commitment: float,
        lookback_days: int,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Savings Plan Underutilized ({util_pct:.0f}% used, ${unused_commitment:.0f}/mo wasted)",
            "description": (
                f"Your Savings Plans are only {util_pct:.1f}% utilized. "
                f"${unused_commitment:.0f}/month of committed spend is going unused. "
                f"Reduce your commitment on renewal to match actual consumption."
            ),
            "category": "savings_plans",
            "source": "cost_explorer",
            "source_id": "ce-sp-utilization-low",
            "service": "EC2",
            "estimated_monthly_savings": round(unused_commitment, 2),
            "estimated_annual_savings": round(unused_commitment * 12, 2),
            "current_monthly_cost": round(unused_commitment, 2),
            "projected_monthly_cost": 0.0,
            "effort_level": "medium",
            "risk_level": "low",
            "confidence_score": 0.85,
            "implementation_steps": [
                {"step": 1, "action": "In Cost Explorer, review SP utilization details"},
                {"step": 2, "action": "Identify which SP types have the most unused commitment"},
                {"step": 3, "action": "Note renewal/expiration date for current SPs"},
                {"step": 4, "action": "On renewal, reduce hourly commitment by the unused amount"},
                {"step": 5, "action": "Consider Compute SP for more flexible coverage"},
            ],
            "evidence": {
                "utilization_pct": util_pct,
                "unused_commitment": unused_commitment,
                "lookback_period_days": lookback_days,
            },
            "api_trace": {
                "api": "ce:GetSavingsPlansUtilization",
                "timestamp": now,
            },
            "deep_link": "https://console.aws.amazon.com/cost-management/home#/savings-plans/utilization",
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_sp_purchase_opportunity(
        self,
        sp_type: str,
        est_monthly_savings: float,
        hourly_commitment: float,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        sp_label = "Compute Savings Plan" if sp_type == "COMPUTE_SP" else "EC2 Instance Savings Plan"
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Purchase {sp_label} to Save ${est_monthly_savings:.0f}/month",
            "description": (
                f"Cost Explorer recommends adding a {sp_label} with an hourly commitment "
                f"of ${hourly_commitment:.2f}/hour (${hourly_commitment * 24 * 30:.0f}/month). "
                f"Estimated savings: ${est_monthly_savings:.0f}/month "
                f"(${est_monthly_savings * 12:.0f}/year) over 1 year."
            ),
            "category": "savings_plans",
            "source": "cost_explorer",
            "source_id": f"ce-sp-purchase-{sp_type.lower()}",
            "service": "EC2",
            "estimated_monthly_savings": round(est_monthly_savings, 2),
            "estimated_annual_savings": round(est_monthly_savings * 12, 2),
            "effort_level": "medium",
            "risk_level": "low",
            "confidence_score": 0.82,
            "implementation_steps": [
                {"step": 1, "action": "Review recommendation in Cost Explorer → Savings Plans → Recommendations"},
                {"step": 2, "action": f"Select '{sp_label}' with 1-year, No Upfront payment"},
                {"step": 3, "action": f"Set hourly commitment to ${hourly_commitment:.2f}"},
                {"step": 4, "action": "Purchase and monitor coverage ratio over the next 30 days"},
            ],
            "evidence": {
                "sp_type": sp_type,
                "hourly_commitment": hourly_commitment,
                "lookback_period_days": LOOKBACK_DAYS,
            },
            "api_trace": {
                "api": "ce:GetSavingsPlansPurchaseRecommendation",
                "sp_type": sp_type,
                "timestamp": now,
            },
            "deep_link": "https://console.aws.amazon.com/cost-management/home#/savings-plans/recommendations",
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_ri_expiry_opportunity(
        self,
        ri_id: str,
        instance_type: str,
        count: int,
        days_until_expiry: int,
        end_time: datetime,
        monthly_cost: float,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        urgency = "URGENT" if days_until_expiry < 30 else "ACTION NEEDED"
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"[{urgency}] RI Expiring in {days_until_expiry} days: {instance_type} x{count}",
            "description": (
                f"Reserved Instance {ri_id} ({instance_type} x{count}) expires on "
                f"{end_time.strftime('%Y-%m-%d')} ({days_until_expiry} days from now). "
                f"After expiry, these instances will revert to on-demand pricing. "
                f"Renew or repurchase to maintain the discount."
            ),
            "category": "reserved_instances",
            "source": "cost_explorer",
            "source_id": f"ec2-ri-expiry-{ri_id}",
            "service": "EC2",
            "resource_id": ri_id,
            "estimated_monthly_savings": round(monthly_cost * 0.40, 2),  # ~40% discount forfeited
            "estimated_annual_savings": round(monthly_cost * 0.40 * 12, 2),
            "effort_level": "low",
            "risk_level": "medium",
            "confidence_score": 1.0,  # Deterministic — expiry date is factual
            "implementation_steps": [
                {"step": 1, "action": "Confirm workload still requires this instance type and count"},
                {"step": 2, "action": "Decide: renew RI, switch to Savings Plan, or let expire"},
                {"step": 3, "action": "Purchase replacement RI or SP before expiry date"},
            ],
            "evidence": {
                "ri_id": ri_id,
                "instance_type": instance_type,
                "count": count,
                "expiry_date": end_time.strftime("%Y-%m-%d"),
                "days_until_expiry": days_until_expiry,
            },
            "api_trace": {
                "api": "ec2:DescribeReservedInstances",
                "timestamp": now,
            },
            "deep_link": (
                f"https://{self.region}.console.aws.amazon.com/ec2/v2/home"
                f"?region={self.region}#ReservedInstances:"
            ),
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }
