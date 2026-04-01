"""
Storage Lifecycle Optimization Signals Service

Detects S3 and EBS storage waste that compounds silently over time.

Signals fetched:
- ec2:DescribeVolumes          → unattached EBS volumes (State=available)
- ec2:DescribeSnapshots        → orphaned/aged snapshots
- ec2:DescribeImages           → deregistered AMIs with retained snapshots
- s3:ListBuckets + CloudWatch  → S3 bucket sizes per storage class
- s3:GetBucketLifecycleConfig  → buckets missing lifecycle policies
- ec2 volume types             → gp2 volumes that could migrate to gp3 (~20% cheaper)

IAM permissions required:
  ec2:DescribeVolumes
  ec2:DescribeSnapshots
  ec2:DescribeImages
  s3:ListAllMyBuckets
  s3:GetBucketLocation
  s3:GetBucketLifecycleConfiguration
  cloudwatch:GetMetricData
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
EBS_IDLE_MIN_DAYS = 7          # Unattached volume older than this → idle
SNAPSHOT_AGE_DAYS = 90         # Snapshot older than this → candidate for cleanup
SNAPSHOT_MIN_SIZE_GB = 10      # Only flag snapshots larger than this
GP2_VOLUME_MIN_GB = 50         # Only flag gp2→gp3 above this size (smaller savings not worth noise)
S3_NO_LIFECYCLE_MIN_GB = 1.0   # Only flag buckets larger than this (GiB) that lack lifecycle policy

# EBS pricing per GB-month (us-east-1)
EBS_PRICE_GP2_PER_GB = 0.10
EBS_PRICE_GP3_PER_GB = 0.08
EBS_PRICE_IO1_PER_GB = 0.125
EBS_PRICE_SC1_PER_GB = 0.025
EBS_PRICE_SNAPSHOT_PER_GB = 0.05

# S3 pricing per GB-month
S3_PRICE_STANDARD_PER_GB = 0.023
S3_PRICE_IA_PER_GB = 0.0125
S3_PRICE_GLACIER_PER_GB = 0.004


class StorageOptimizationSignalsService:
    """
    Detects S3 and EBS storage lifecycle waste.
    Works at all AWS Support tiers.
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
        self._ec2_client = None
        self._s3_client = None
        self._cw_client = None

    @property
    def ec2_client(self):
        if self._ec2_client is None:
            self._ec2_client = self._session.client(AwsService.EC2)
        return self._ec2_client

    @property
    def s3_client(self):
        if self._s3_client is None:
            self._s3_client = self._session.client(AwsService.S3)
        return self._s3_client

    @property
    def cw_client(self):
        if self._cw_client is None:
            self._cw_client = self._session.client(AwsService.CLOUDWATCH)
        return self._cw_client

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def fetch_unattached_ebs_signals(self) -> List[Dict[str, Any]]:
        """
        Detect EBS volumes in 'available' state (not attached to any instance).
        Volumes older than EBS_IDLE_MIN_DAYS are flagged.
        """
        opportunities: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        try:
            paginator = self.ec2_client.get_paginator("describe_volumes")
            for page in paginator.paginate(
                Filters=[{"Name": "status", "Values": ["available"]}]
            ):
                for vol in page.get("Volumes", []):
                    create_time = vol.get("CreateTime")
                    if create_time is None:
                        continue

                    age_days = (now - create_time).days
                    if age_days < EBS_IDLE_MIN_DAYS:
                        continue

                    vol_id = vol.get("VolumeId", "")
                    vol_type = vol.get("VolumeType", "gp2")
                    size_gb = vol.get("Size", 0)
                    az = vol.get("AvailabilityZone", self.region)
                    name = self._get_tag(vol.get("Tags", []), "Name") or vol_id

                    monthly_cost = self._ebs_monthly_cost(vol_type, size_gb)

                    opp = self._make_unattached_ebs_opportunity(
                        vol_id=vol_id,
                        name=name,
                        vol_type=vol_type,
                        size_gb=size_gb,
                        az=az,
                        age_days=age_days,
                        monthly_cost=monthly_cost,
                    )
                    opportunities.append(opp)

            logger.info(f"Unattached EBS scan: {len(opportunities)} volumes found")

        except ClientError as e:
            logger.error(f"EBS DescribeVolumes error: {e}")
        except Exception as e:
            logger.error(f"Error fetching unattached EBS signals: {e}")

        return opportunities

    async def fetch_orphaned_snapshot_signals(self) -> List[Dict[str, Any]]:
        """
        Detect old, large EBS snapshots that are no longer linked to active AMIs.
        """
        opportunities: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        try:
            # Get snapshots owned by this account
            paginator = self.ec2_client.get_paginator("describe_snapshots")
            all_snapshots = []
            for page in paginator.paginate(OwnerIds=["self"]):
                all_snapshots.extend(page.get("Snapshots", []))

            # Build set of snapshot IDs used by active AMIs
            active_ami_snapshots = self._get_active_ami_snapshot_ids()

            for snap in all_snapshots:
                snap_id = snap.get("SnapshotId", "")
                start_time = snap.get("StartTime")
                size_gb = snap.get("VolumeSize", 0)
                description = snap.get("Description", "")
                name = self._get_tag(snap.get("Tags"), "Name") or snap_id

                if start_time is None or size_gb < SNAPSHOT_MIN_SIZE_GB:
                    continue

                age_days = (now - start_time).days
                if age_days < SNAPSHOT_AGE_DAYS:
                    continue

                # Skip if still referenced by an active AMI
                if snap_id in active_ami_snapshots:
                    continue

                monthly_cost = round(size_gb * EBS_PRICE_SNAPSHOT_PER_GB, 2)

                opp = self._make_orphaned_snapshot_opportunity(
                    snap_id=snap_id,
                    name=name,
                    size_gb=size_gb,
                    age_days=age_days,
                    monthly_cost=monthly_cost,
                    description=description,
                )
                opportunities.append(opp)

            logger.info(
                f"Orphaned snapshot scan: {len(all_snapshots)} total, "
                f"{len(opportunities)} orphaned/aged snapshots found"
            )

        except ClientError as e:
            logger.error(f"EBS DescribeSnapshots error: {e}")
        except Exception as e:
            logger.error(f"Error fetching orphaned snapshot signals: {e}")

        return opportunities

    async def fetch_gp2_to_gp3_signals(self) -> List[Dict[str, Any]]:
        """
        Detect gp2 EBS volumes that should be migrated to gp3.
        gp3 is 20% cheaper and offers higher baseline throughput/IOPS.
        Zero-downtime migration for most workloads.
        """
        opportunities: List[Dict[str, Any]] = []

        try:
            paginator = self.ec2_client.get_paginator("describe_volumes")
            for page in paginator.paginate(
                Filters=[
                    {"Name": "volume-type", "Values": ["gp2"]},
                    {"Name": "status", "Values": ["in-use", "available"]},
                ]
            ):
                for vol in page.get("Volumes", []):
                    size_gb = vol.get("Size", 0)
                    if size_gb < GP2_VOLUME_MIN_GB:
                        continue

                    vol_id = vol.get("VolumeId", "")
                    az = vol.get("AvailabilityZone", self.region)
                    name = self._get_tag(vol.get("Tags", []), "Name") or vol_id
                    iops = vol.get("Iops", 0)  # gp2 auto-provisioned IOPS

                    current_cost = round(size_gb * EBS_PRICE_GP2_PER_GB, 2)
                    projected_cost = round(size_gb * EBS_PRICE_GP3_PER_GB, 2)
                    savings = round(current_cost - projected_cost, 2)

                    if savings <= 0:
                        continue

                    opp = self._make_gp2_to_gp3_opportunity(
                        vol_id=vol_id,
                        name=name,
                        size_gb=size_gb,
                        az=az,
                        current_cost=current_cost,
                        projected_cost=projected_cost,
                        savings=savings,
                        current_iops=iops,
                    )
                    opportunities.append(opp)

            logger.info(f"gp2→gp3 scan: {len(opportunities)} volumes found")

        except ClientError as e:
            logger.error(f"EBS DescribeVolumes (gp2) error: {e}")
        except Exception as e:
            logger.error(f"Error fetching gp2→gp3 signals: {e}")

        return opportunities

    async def fetch_s3_lifecycle_signals(self) -> List[Dict[str, Any]]:
        """
        Detect S3 buckets without lifecycle policies that contain significant data.
        Uses CloudWatch S3 BucketSizeBytes metric for size estimation.
        """
        opportunities: List[Dict[str, Any]] = []

        try:
            buckets_response = self.s3_client.list_buckets()
            buckets = buckets_response.get("Buckets", [])

            if not buckets:
                return opportunities

            logger.info(f"Checking lifecycle policies for {len(buckets)} S3 buckets")

            # Get CloudWatch size metrics for all buckets in a batch
            bucket_sizes = self._get_s3_bucket_sizes([b["Name"] for b in buckets])

            for bucket in buckets:
                bucket_name = bucket.get("Name", "")
                size_gb = bucket_sizes.get(bucket_name, 0.0)

                if size_gb < S3_NO_LIFECYCLE_MIN_GB:
                    continue

                has_lifecycle = self._bucket_has_lifecycle_policy(bucket_name)
                if has_lifecycle:
                    continue

                monthly_cost = round(size_gb * S3_PRICE_STANDARD_PER_GB, 2)
                # Conservative savings estimate: 30% of data could move to IA
                potential_savings = round(size_gb * 0.30 * (S3_PRICE_STANDARD_PER_GB - S3_PRICE_IA_PER_GB), 2)

                if potential_savings < 1.0:
                    continue

                opp = self._make_s3_lifecycle_opportunity(
                    bucket_name=bucket_name,
                    size_gb=size_gb,
                    monthly_cost=monthly_cost,
                    potential_savings=potential_savings,
                )
                opportunities.append(opp)

            logger.info(f"S3 lifecycle scan: {len(opportunities)} buckets without lifecycle policies")

        except ClientError as e:
            logger.error(f"S3 bucket scan error: {e}")
        except Exception as e:
            logger.error(f"Error fetching S3 lifecycle signals: {e}")

        return opportunities

    async def fetch_all_storage_signals(self) -> List[Dict[str, Any]]:
        """Fetch all storage optimization signals."""
        all_signals: List[Dict[str, Any]] = []

        fetchers = [
            ("Unattached EBS", self.fetch_unattached_ebs_signals),
            ("Orphaned Snapshots", self.fetch_orphaned_snapshot_signals),
            ("gp2→gp3 Migration", self.fetch_gp2_to_gp3_signals),
            ("S3 Lifecycle", self.fetch_s3_lifecycle_signals),
        ]

        for label, fetch_fn in fetchers:
            try:
                signals = await fetch_fn()
                all_signals.extend(signals)
                logger.info(f"Storage {label}: {len(signals)} signals")
            except Exception as e:
                logger.error(f"Storage {label} fetch failed: {e}")

        return all_signals

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _get_active_ami_snapshot_ids(self) -> set:
        """
        Return the set of snapshot IDs referenced by currently registered AMIs.
        """
        snap_ids = set()
        try:
            paginator = self.ec2_client.get_paginator("describe_images")
            for page in paginator.paginate(Owners=["self"]):
                for image in page.get("Images", []):
                    for bdm in image.get("BlockDeviceMappings", []):
                        ebs = bdm.get("Ebs", {})
                        if ebs and ebs.get("SnapshotId"):
                            snap_ids.add(ebs["SnapshotId"])
        except ClientError as e:
            logger.warning(f"Could not fetch AMI snapshot IDs: {e}")
        return snap_ids

    def _get_s3_bucket_sizes(self, bucket_names: List[str]) -> Dict[str, float]:
        """
        Use CloudWatch to get standardStorage size for each bucket.
        Returns {bucket_name: size_gb} dict.
        """
        result: Dict[str, float] = {}
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=2)

        BATCH = 100
        for offset in range(0, len(bucket_names), BATCH):
            batch = bucket_names[offset: offset + BATCH]
            queries = [
                {
                    "Id": f"sz_{i}",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/S3",
                            "MetricName": "BucketSizeBytes",
                            "Dimensions": [
                                {"Name": "BucketName", "Value": name},
                                {"Name": "StorageType", "Value": "StandardStorage"},
                            ],
                        },
                        "Period": 86400,
                        "Stat": "Average",
                    },
                    "ReturnData": True,
                }
                for i, name in enumerate(batch)
            ]

            try:
                response = self.cw_client.get_metric_data(
                    MetricDataQueries=queries,
                    StartTime=start_time,
                    EndTime=end_time,
                )
                for i, mdr in enumerate(response.get("MetricDataResults", [])):
                    values = mdr.get("Values", [])
                    if values and offset + i < len(bucket_names):
                        bucket_name = bucket_names[offset + i]
                        size_bytes = max(values)
                        result[bucket_name] = size_bytes / (1024 ** 3)  # bytes → GiB
            except ClientError as e:
                logger.warning(f"S3 CloudWatch size batch error: {e}")

        return result

    def _bucket_has_lifecycle_policy(self, bucket_name: str) -> bool:
        """Return True if a bucket has at least one lifecycle rule."""
        try:
            response = self.s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
            rules = response.get("Rules", [])
            return len(rules) > 0
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchLifecycleConfiguration":
                return False
            # Other errors (permissions, etc.) — assume lifecycle might exist
            logger.debug(f"Could not check lifecycle for {bucket_name}: {e}")
            return True

    def _ebs_monthly_cost(self, vol_type: str, size_gb: int) -> float:
        """Estimate monthly EBS cost."""
        prices = {
            "gp2": EBS_PRICE_GP2_PER_GB,
            "gp3": EBS_PRICE_GP3_PER_GB,
            "io1": EBS_PRICE_IO1_PER_GB,
            "io2": EBS_PRICE_IO1_PER_GB,
            "sc1": EBS_PRICE_SC1_PER_GB,
            "st1": 0.045,
            "standard": 0.05,
        }
        return round(size_gb * prices.get(vol_type, EBS_PRICE_GP2_PER_GB), 2)

    # ------------------------------------------------------------------
    # Opportunity builders
    # ------------------------------------------------------------------

    def _make_unattached_ebs_opportunity(
        self,
        vol_id: str,
        name: str,
        vol_type: str,
        size_gb: int,
        az: str,
        age_days: int,
        monthly_cost: float,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        region = az[:-1] if az else self.region  # strip AZ suffix (e.g. us-east-1a → us-east-1)
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Unattached EBS Volume: {name} ({size_gb} GB {vol_type})",
            "description": (
                f"EBS volume {vol_id} ({size_gb} GB, {vol_type}) in {az} has been unattached "
                f"for {age_days} days. Unattached volumes still incur storage charges "
                f"(~${monthly_cost}/month). Snapshot and delete if no longer needed."
            ),
            "category": "storage_optimization",
            "source": "cloudwatch_analysis",
            "source_id": f"ebs-unattached-{vol_id}",
            "service": "EBS",
            "resource_id": vol_id,
            "resource_name": name,
            "resource_type": f"EBS {vol_type}",
            "region": region,
            "estimated_monthly_savings": monthly_cost,
            "estimated_annual_savings": monthly_cost * 12,
            "current_monthly_cost": monthly_cost,
            "projected_monthly_cost": 0.0,
            "effort_level": "low",
            "risk_level": "low",
            "confidence_score": 0.95,
            "implementation_steps": [
                {"step": 1, "action": "Verify volume is not intentionally detached (e.g. for data transfer)"},
                {"step": 2, "action": "Create a final EBS snapshot as backup"},
                {"step": 3, "action": "Delete the unattached volume via Console or CLI"},
                {"step": 4, "action": "After 30 days, delete the snapshot if data is confirmed unneeded"},
            ],
            "evidence": {
                "volume_type": vol_type,
                "size_gb": size_gb,
                "age_days": age_days,
                "availability_zone": az,
                "state": "available",
            },
            "api_trace": {
                "api": "ec2:DescribeVolumes",
                "filter": "status=available",
                "timestamp": now,
            },
            "cur_validation_sql": (
                "SELECT line_item_resource_id, SUM(line_item_unblended_cost) AS cost\n"
                "FROM cost_and_usage_report\n"
                f"WHERE line_item_resource_id = '{vol_id}'\n"
                "  AND line_item_product_code = 'AmazonEC2'\n"
                "  AND line_item_usage_start_date >= DATE_ADD('day', -30, CURRENT_DATE)\n"
                "GROUP BY 1;"
            ),
            "deep_link": (
                f"https://{region}.console.aws.amazon.com/ec2/v2/home"
                f"?region={region}#VolumeDetails:volumeId={vol_id}"
            ),
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_orphaned_snapshot_opportunity(
        self,
        snap_id: str,
        name: str,
        size_gb: int,
        age_days: int,
        monthly_cost: float,
        description: str,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Orphaned EBS Snapshot: {name} ({size_gb} GB, {age_days} days old)",
            "description": (
                f"EBS snapshot {snap_id} ({size_gb} GB) is {age_days} days old and is not "
                f"referenced by any currently registered AMI. "
                f"{'Description: ' + description[:100] + '. ' if description else ''}"
                f"It costs ~${monthly_cost}/month. Delete if no longer needed for recovery."
            ),
            "category": "storage_optimization",
            "source": "cloudwatch_analysis",
            "source_id": f"ebs-snapshot-orphan-{snap_id}",
            "service": "EBS",
            "resource_id": snap_id,
            "resource_name": name,
            "resource_type": "EBS Snapshot",
            "region": self.region,
            "estimated_monthly_savings": monthly_cost,
            "estimated_annual_savings": monthly_cost * 12,
            "current_monthly_cost": monthly_cost,
            "projected_monthly_cost": 0.0,
            "effort_level": "low",
            "risk_level": "low",
            "confidence_score": 0.85,
            "implementation_steps": [
                {"step": 1, "action": "Confirm the snapshot is not referenced by any AMI or used for restore"},
                {"step": 2, "action": "Check snapshot tags/description for retention requirements"},
                {"step": 3, "action": "Delete the snapshot via Console or CLI if confirmed unnecessary"},
            ],
            "evidence": {
                "size_gb": size_gb,
                "age_days": age_days,
                "description": description[:200] if description else None,
                "age_threshold_days": SNAPSHOT_AGE_DAYS,
            },
            "api_trace": {
                "api": "ec2:DescribeSnapshots",
                "filter": "owner=self",
                "timestamp": now,
            },
            "deep_link": (
                f"https://{self.region}.console.aws.amazon.com/ec2/v2/home"
                f"?region={self.region}#Snapshots:snapshotId={snap_id}"
            ),
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_gp2_to_gp3_opportunity(
        self,
        vol_id: str,
        name: str,
        size_gb: int,
        az: str,
        current_cost: float,
        projected_cost: float,
        savings: float,
        current_iops: int,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        region = az[:-1] if az else self.region
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Migrate gp2→gp3: {name} ({size_gb} GB) — Save ${savings:.0f}/month",
            "description": (
                f"EBS volume {vol_id} ({size_gb} GB, gp2) can be migrated to gp3 with zero downtime. "
                f"gp3 is 20% cheaper (${EBS_PRICE_GP2_PER_GB}/GB vs ${EBS_PRICE_GP3_PER_GB}/GB) "
                f"and provides 3,000 IOPS and 125 MB/s throughput as baseline at no extra cost "
                f"(gp2 provides {current_iops} IOPS baseline). "
                f"Estimated savings: ${savings:.2f}/month (${savings * 12:.0f}/year)."
            ),
            "category": "storage_optimization",
            "source": "cloudwatch_analysis",
            "source_id": f"ebs-gp2-to-gp3-{vol_id}",
            "service": "EBS",
            "resource_id": vol_id,
            "resource_name": name,
            "resource_type": "EBS gp2",
            "region": region,
            "estimated_monthly_savings": savings,
            "estimated_annual_savings": round(savings * 12, 2),
            "current_monthly_cost": current_cost,
            "projected_monthly_cost": projected_cost,
            "effort_level": "low",
            "risk_level": "low",
            "confidence_score": 0.98,
            "implementation_steps": [
                {"step": 1, "action": "No application downtime required — live modification"},
                {"step": 2, "action": "Run: aws ec2 modify-volume --volume-id " + vol_id + " --volume-type gp3"},
                {"step": 3, "action": "Monitor volume state until it shows 'optimizing' then 'completed'"},
                {"step": 4, "action": "Verify application performance is unchanged (IOPS and throughput)"},
            ],
            "evidence": {
                "current_type": "gp2",
                "target_type": "gp3",
                "size_gb": size_gb,
                "current_iops": current_iops,
                "gp3_baseline_iops": 3000,
                "price_reduction_pct": 20,
            },
            "api_trace": {
                "api": "ec2:DescribeVolumes",
                "filter": "volume-type=gp2",
                "timestamp": now,
            },
            "cur_validation_sql": (
                "SELECT line_item_resource_id, product_volume_api_name,\n"
                "       SUM(line_item_unblended_cost) AS monthly_cost\n"
                "FROM cost_and_usage_report\n"
                f"WHERE line_item_resource_id = '{vol_id}'\n"
                "  AND product_volume_api_name = 'gp2'\n"
                "  AND line_item_usage_start_date >= DATE_ADD('day', -30, CURRENT_DATE)\n"
                "GROUP BY 1, 2;"
            ),
            "deep_link": (
                f"https://{region}.console.aws.amazon.com/ec2/v2/home"
                f"?region={region}#VolumeDetails:volumeId={vol_id}"
            ),
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_s3_lifecycle_opportunity(
        self,
        bucket_name: str,
        size_gb: float,
        monthly_cost: float,
        potential_savings: float,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"S3 Bucket Missing Lifecycle Policy: {bucket_name} ({size_gb:.1f} GB)",
            "description": (
                f"S3 bucket '{bucket_name}' contains {size_gb:.1f} GiB of data "
                f"(~${monthly_cost:.0f}/month at Standard rates) but has no lifecycle policy. "
                f"Without automatic tiering, all data stays in S3 Standard indefinitely. "
                f"Adding a lifecycle rule to transition objects > 30 days to S3 Standard-IA "
                f"could save ~${potential_savings:.0f}/month (${potential_savings * 12:.0f}/year)."
            ),
            "category": "storage_optimization",
            "source": "cloudwatch_analysis",
            "source_id": f"s3-no-lifecycle-{bucket_name}",
            "service": "S3",
            "resource_id": bucket_name,
            "resource_name": bucket_name,
            "resource_type": "S3 Bucket",
            "region": self.region,
            "estimated_monthly_savings": potential_savings,
            "estimated_annual_savings": round(potential_savings * 12, 2),
            "current_monthly_cost": monthly_cost,
            "projected_monthly_cost": round(monthly_cost - potential_savings, 2),
            "effort_level": "low",
            "risk_level": "low",
            "confidence_score": 0.75,
            "implementation_steps": [
                {"step": 1, "action": f"Open S3 bucket '{bucket_name}' → Management → Lifecycle rules"},
                {"step": 2, "action": "Create a rule: transition objects to Standard-IA after 30 days"},
                {"step": 3, "action": "Add a second transition to Glacier Instant Retrieval after 90 days"},
                {"step": 4, "action": "Optionally add expiration for objects older than 365 days if appropriate"},
                {"step": 5, "action": "Monitor S3 Storage Lens for actual storage class distribution"},
            ],
            "evidence": {
                "size_gb": round(size_gb, 2),
                "has_lifecycle_policy": False,
                "standard_price_per_gb": S3_PRICE_STANDARD_PER_GB,
                "ia_price_per_gb": S3_PRICE_IA_PER_GB,
            },
            "api_trace": {
                "api": "s3:GetBucketLifecycleConfiguration + cloudwatch:GetMetricData",
                "timestamp": now,
            },
            "cur_validation_sql": (
                "SELECT line_item_resource_id, product_bucket_name,\n"
                "       SUM(line_item_unblended_cost) AS monthly_cost\n"
                "FROM cost_and_usage_report\n"
                f"WHERE line_item_resource_id LIKE '%{bucket_name}%'\n"
                "  AND line_item_product_code = 'AmazonS3'\n"
                "  AND line_item_usage_start_date >= DATE_ADD('day', -30, CURRENT_DATE)\n"
                "GROUP BY 1, 2;"
            ),
            "deep_link": f"https://s3.console.aws.amazon.com/s3/management/{bucket_name}/lifecycle",
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _get_tag(tags: Optional[List[Dict[str, str]]], key: str) -> Optional[str]:
        if not tags:
            return None
        for t in tags:
            if t.get("Key") == key:
                return t.get("Value")
        return None
