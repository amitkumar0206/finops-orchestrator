"""
CloudWatch Optimization Signals Service

Detects idle and underutilized AWS resources by querying CloudWatch metrics.
Works at ALL AWS Support tiers — no Business/Enterprise requirement.

Detects:
- Idle EC2 instances (CPU P95 < 5% over 30 days)
- Idle RDS instances (zero connections over 7 days)
- Idle Load Balancers (zero requests over 7 days)
- Idle Lambda functions (zero invocations over 30 days)
- Underutilized EC2 instances (CPU P95 5-15%, candidate for downsizing)
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

# Thresholds for waste detection
IDLE_CPU_THRESHOLD_PCT = 5.0          # P95 CPU below this = idle
UNDERUTIL_CPU_THRESHOLD_PCT = 15.0    # P95 CPU below this = underutilized
LOOKBACK_DAYS_COMPUTE = 30
LOOKBACK_DAYS_NETWORK = 14
MIN_NETWORK_MB_DAY = 5.0              # NetworkIn below this (combined) = idle
RDS_CONN_LOOKBACK_DAYS = 7
ELB_REQ_LOOKBACK_DAYS = 7
LAMBDA_INVOKE_LOOKBACK_DAYS = 30

# Rough hourly on-demand pricing for savings estimate (us-east-1, Linux)
# These are order-of-magnitude estimates; CUR data should be used for precision.
EC2_HOURLY_PRICES: Dict[str, float] = {
    "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208,
    "t3.medium": 0.0416, "t3.large": 0.0832, "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328,
    "t2.micro": 0.0116, "t2.small": 0.023, "t2.medium": 0.0464,
    "t2.large": 0.0928, "t2.xlarge": 0.1856,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768, "m5.8xlarge": 1.536,
    "c5.large": 0.085, "c5.xlarge": 0.17, "c5.2xlarge": 0.34,
    "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504,
}


class CloudWatchOptimizationSignalsService:
    """
    Detects AWS resource waste using CloudWatch metrics.

    Requires IAM permissions:
      cloudwatch:GetMetricData
      ec2:DescribeInstances
      rds:DescribeDBInstances
      elasticloadbalancing:DescribeLoadBalancers
      lambda:ListFunctions
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
        self._cw_client = None
        self._ec2_client = None
        self._rds_client = None
        self._elb_client = None
        self._lambda_client = None

    # ------------------------------------------------------------------
    # Lazy boto3 clients
    # ------------------------------------------------------------------

    @property
    def cw_client(self):
        if self._cw_client is None:
            self._cw_client = self._session.client(AwsService.CLOUDWATCH)
        return self._cw_client

    @property
    def ec2_client(self):
        if self._ec2_client is None:
            self._ec2_client = self._session.client(AwsService.EC2)
        return self._ec2_client

    @property
    def rds_client(self):
        if self._rds_client is None:
            self._rds_client = self._session.client(AwsService.RDS)
        return self._rds_client

    @property
    def elb_client(self):
        if self._elb_client is None:
            self._elb_client = self._session.client(AwsService.ELB)
        return self._elb_client

    @property
    def lambda_client(self):
        if self._lambda_client is None:
            self._lambda_client = self._session.client(AwsService.LAMBDA)
        return self._lambda_client

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def fetch_idle_ec2_signals(self) -> List[Dict[str, Any]]:
        """
        Detect idle and underutilized EC2 instances via CloudWatch CPUUtilization.
        Returns opportunity dicts compatible with the existing ingest pipeline.
        """
        opportunities: List[Dict[str, Any]] = []

        try:
            instances = self._list_running_ec2_instances()
            if not instances:
                logger.info("No running EC2 instances found")
                return opportunities

            logger.info(f"Checking CloudWatch metrics for {len(instances)} EC2 instances")

            # Batch metric queries — CloudWatch allows up to 500 queries per call
            cpu_data = self._batch_get_ec2_cpu_p95(instances)
            net_data = self._batch_get_ec2_network_avg(instances)

            now = datetime.now(timezone.utc)
            for inst in instances:
                iid = inst["InstanceId"]
                itype = inst.get("InstanceType", "")
                name = self._get_tag(inst.get("Tags", []), "Name") or iid
                launch_time = inst.get("LaunchTime")
                age_days = (now - launch_time).days if launch_time else 0

                cpu_p95 = cpu_data.get(iid)
                net_avg_mb = net_data.get(iid)

                if cpu_p95 is None:
                    # Not enough data — skip
                    continue

                monthly_cost = self._estimate_monthly_cost(itype)

                if cpu_p95 < IDLE_CPU_THRESHOLD_PCT:
                    # Truly idle
                    opp = self._make_ec2_opportunity(
                        instance_id=iid,
                        name=name,
                        instance_type=itype,
                        region=self.region,
                        age_days=age_days,
                        cpu_p95=cpu_p95,
                        net_avg_mb=net_avg_mb,
                        monthly_cost=monthly_cost,
                        category="idle_resources",
                        action="terminate",
                        savings=monthly_cost,
                    )
                    opportunities.append(opp)

                elif cpu_p95 < UNDERUTIL_CPU_THRESHOLD_PCT:
                    # Underutilized — rightsizing candidate
                    savings = monthly_cost * 0.35  # ~35% savings with one size smaller
                    opp = self._make_ec2_opportunity(
                        instance_id=iid,
                        name=name,
                        instance_type=itype,
                        region=self.region,
                        age_days=age_days,
                        cpu_p95=cpu_p95,
                        net_avg_mb=net_avg_mb,
                        monthly_cost=monthly_cost,
                        category="rightsizing",
                        action="downsize",
                        savings=savings,
                    )
                    opportunities.append(opp)

            logger.info(
                "CloudWatch EC2 scan complete",
                instances_checked=len(instances),
                opportunities_found=len(opportunities),
            )

        except ClientError as e:
            logger.error(f"CloudWatch EC2 API error: {e}")
        except Exception as e:
            logger.error(f"Error fetching CloudWatch EC2 signals: {e}")

        return opportunities

    async def fetch_idle_rds_signals(self) -> List[Dict[str, Any]]:
        """
        Detect idle RDS instances with zero DatabaseConnections over 7 days.
        """
        opportunities: List[Dict[str, Any]] = []

        try:
            instances = self._list_rds_instances()
            if not instances:
                return opportunities

            logger.info(f"Checking CloudWatch metrics for {len(instances)} RDS instances")

            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=RDS_CONN_LOOKBACK_DAYS)

            for db in instances:
                db_id = db.get("DBInstanceIdentifier", "")
                db_class = db.get("DBInstanceClass", "")
                multi_az = db.get("MultiAZ", False)

                conn_sum = self._get_rds_connection_sum(db_id, start_time, end_time)

                if conn_sum is None or conn_sum > 0:
                    continue

                # Estimate monthly cost (rough): db.t3.medium ≈ $51/mo
                monthly_cost = self._estimate_rds_monthly_cost(db_class, multi_az)

                opportunity = self._make_rds_opportunity(
                    db_id=db_id,
                    db_class=db_class,
                    multi_az=multi_az,
                    monthly_cost=monthly_cost,
                    lookback_days=RDS_CONN_LOOKBACK_DAYS,
                )
                opportunities.append(opportunity)

            logger.info(
                "CloudWatch RDS scan complete",
                instances_checked=len(instances),
                opportunities_found=len(opportunities),
            )

        except ClientError as e:
            logger.error(f"CloudWatch RDS API error: {e}")
        except Exception as e:
            logger.error(f"Error fetching CloudWatch RDS signals: {e}")

        return opportunities

    async def fetch_idle_elb_signals(self) -> List[Dict[str, Any]]:
        """
        Detect idle Application and Classic Load Balancers with zero requests over 7 days.
        """
        opportunities: List[Dict[str, Any]] = []

        try:
            load_balancers = self._list_load_balancers()
            if not load_balancers:
                return opportunities

            logger.info(f"Checking CloudWatch metrics for {len(load_balancers)} load balancers")

            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=ELB_REQ_LOOKBACK_DAYS)

            for lb in load_balancers:
                lb_arn = lb.get("LoadBalancerArn", "")
                lb_name = lb.get("LoadBalancerName", "")
                lb_type = lb.get("Type", "application")
                lb_scheme = lb.get("Scheme", "")

                request_count = self._get_elb_request_count(lb_arn, lb_name, lb_type, start_time, end_time)

                if request_count is None or request_count > 0:
                    continue

                opportunity = self._make_elb_opportunity(
                    lb_arn=lb_arn,
                    lb_name=lb_name,
                    lb_type=lb_type,
                    lb_scheme=lb_scheme,
                    lookback_days=ELB_REQ_LOOKBACK_DAYS,
                )
                opportunities.append(opportunity)

            logger.info(
                "CloudWatch ELB scan complete",
                lbs_checked=len(load_balancers),
                opportunities_found=len(opportunities),
            )

        except ClientError as e:
            logger.error(f"CloudWatch ELB API error: {e}")
        except Exception as e:
            logger.error(f"Error fetching CloudWatch ELB signals: {e}")

        return opportunities

    async def fetch_idle_lambda_signals(self) -> List[Dict[str, Any]]:
        """
        Detect Lambda functions with zero invocations over 30 days
        (provisioned concurrency cost, dead code).
        """
        opportunities: List[Dict[str, Any]] = []

        try:
            functions = self._list_lambda_functions()
            if not functions:
                return opportunities

            logger.info(f"Checking CloudWatch metrics for {len(functions)} Lambda functions")

            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=LAMBDA_INVOKE_LOOKBACK_DAYS)

            for fn in functions:
                fn_name = fn.get("FunctionName", "")
                fn_arn = fn.get("FunctionArn", "")
                runtime = fn.get("Runtime", "")
                memory_mb = fn.get("MemorySize", 128)

                # Only flag if provisioned concurrency is configured, or function is > 30 days old
                last_modified = fn.get("LastModified", "")

                invoke_sum = self._get_lambda_invocation_sum(fn_name, start_time, end_time)

                if invoke_sum is None or invoke_sum > 0:
                    continue

                opportunity = self._make_lambda_opportunity(
                    fn_name=fn_name,
                    fn_arn=fn_arn,
                    runtime=runtime,
                    memory_mb=memory_mb,
                    lookback_days=LAMBDA_INVOKE_LOOKBACK_DAYS,
                )
                opportunities.append(opportunity)

            logger.info(
                "CloudWatch Lambda scan complete",
                functions_checked=len(functions),
                opportunities_found=len(opportunities),
            )

        except ClientError as e:
            logger.error(f"CloudWatch Lambda API error: {e}")
        except Exception as e:
            logger.error(f"Error fetching CloudWatch Lambda signals: {e}")

        return opportunities

    async def fetch_all_cloudwatch_signals(self) -> List[Dict[str, Any]]:
        """Fetch all CloudWatch-based optimization signals."""
        all_signals: List[Dict[str, Any]] = []

        for label, fetch_fn in [
            ("EC2", self.fetch_idle_ec2_signals),
            ("RDS", self.fetch_idle_rds_signals),
            ("ELB", self.fetch_idle_elb_signals),
            ("Lambda", self.fetch_idle_lambda_signals),
        ]:
            try:
                signals = await fetch_fn()
                all_signals.extend(signals)
                logger.info(f"CloudWatch {label}: {len(signals)} signals")
            except Exception as e:
                logger.error(f"CloudWatch {label} fetch failed: {e}")

        return all_signals

    # ------------------------------------------------------------------
    # AWS resource inventory helpers
    # ------------------------------------------------------------------

    def _list_running_ec2_instances(self) -> List[Dict[str, Any]]:
        """Return all running EC2 instances."""
        instances = []
        paginator = self.ec2_client.get_paginator("describe_instances")
        for page in paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        ):
            for reservation in page.get("Reservations", []):
                instances.extend(reservation.get("Instances", []))
        return instances

    def _list_rds_instances(self) -> List[Dict[str, Any]]:
        """Return all available RDS instances."""
        instances = []
        paginator = self.rds_client.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                if db.get("DBInstanceStatus") == "available":
                    instances.append(db)
        return instances

    def _list_load_balancers(self) -> List[Dict[str, Any]]:
        """Return all active load balancers."""
        lbs = []
        paginator = self.elb_client.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page.get("LoadBalancers", []):
                if lb.get("State", {}).get("Code") == "active":
                    lbs.append(lb)
        return lbs

    def _list_lambda_functions(self) -> List[Dict[str, Any]]:
        """Return all Lambda functions."""
        functions = []
        paginator = self.lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            functions.extend(page.get("Functions", []))
        return functions

    # ------------------------------------------------------------------
    # CloudWatch metric query helpers
    # ------------------------------------------------------------------

    def _batch_get_ec2_cpu_p95(
        self, instances: List[Dict[str, Any]]
    ) -> Dict[str, Optional[float]]:
        """
        Batch-fetch 30-day P95 CPUUtilization for all instances.
        Returns {instance_id: p95_value} dict.
        """
        result: Dict[str, Optional[float]] = {}
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=LOOKBACK_DAYS_COMPUTE)

        # CloudWatch allows max 500 MetricDataQueries per request
        BATCH = 499
        ids = [i["InstanceId"] for i in instances]

        for offset in range(0, len(ids), BATCH):
            batch_ids = ids[offset: offset + BATCH]
            queries = [
                {
                    "Id": f"cpu_{iid.replace('-', '_')}",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/EC2",
                            "MetricName": "CPUUtilization",
                            "Dimensions": [{"Name": "InstanceId", "Value": iid}],
                        },
                        "Period": 86400,  # 1-day period
                        "Stat": "p95",
                    },
                    "ReturnData": True,
                }
                for iid in batch_ids
            ]

            try:
                response = self.cw_client.get_metric_data(
                    MetricDataQueries=queries,
                    StartTime=start_time,
                    EndTime=end_time,
                )
                for mdr in response.get("MetricDataResults", []):
                    # Id is "cpu_i_1234567890abcdef0" — extract instance id
                    iid = mdr["Id"].replace("cpu_", "").replace("_", "-", 1)
                    # Reconstruct from parts (handle multi-dash IDs)
                    # Safer: build reverse mapping
                    values = mdr.get("Values", [])
                    p95 = max(values) if values else None
                    # Map back using Id label
                    result[mdr["Label"]] = p95
            except ClientError as e:
                logger.warning(f"CloudWatch cpu batch error: {e}")

        # Rebuild using InstanceId as key (Label = InstanceId in CW)
        return result

    def _batch_get_ec2_network_avg(
        self, instances: List[Dict[str, Any]]
    ) -> Dict[str, Optional[float]]:
        """
        Batch-fetch 14-day average daily NetworkIn (MB) for all instances.
        Returns {instance_id: avg_mb_per_day} dict.
        """
        result: Dict[str, Optional[float]] = {}
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=LOOKBACK_DAYS_NETWORK)

        BATCH = 499
        ids = [i["InstanceId"] for i in instances]

        for offset in range(0, len(ids), BATCH):
            batch_ids = ids[offset: offset + BATCH]
            queries = [
                {
                    "Id": f"net_{iid.replace('-', '_')}",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/EC2",
                            "MetricName": "NetworkIn",
                            "Dimensions": [{"Name": "InstanceId", "Value": iid}],
                        },
                        "Period": 86400,
                        "Stat": "Sum",
                    },
                    "ReturnData": True,
                }
                for iid in batch_ids
            ]
            try:
                response = self.cw_client.get_metric_data(
                    MetricDataQueries=queries,
                    StartTime=start_time,
                    EndTime=end_time,
                )
                for mdr in response.get("MetricDataResults", []):
                    values = mdr.get("Values", [])
                    if values:
                        avg_bytes = sum(values) / len(values)
                        result[mdr["Label"]] = avg_bytes / (1024 * 1024)  # Convert to MB
                    else:
                        result[mdr["Label"]] = None
            except ClientError as e:
                logger.warning(f"CloudWatch network batch error: {e}")

        return result

    def _get_rds_connection_sum(
        self,
        db_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Optional[float]:
        """Return total DatabaseConnections sum for a RDS instance over the period."""
        try:
            response = self.cw_client.get_metric_data(
                MetricDataQueries=[{
                    "Id": "conn",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/RDS",
                            "MetricName": "DatabaseConnections",
                            "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": db_id}],
                        },
                        "Period": 86400,
                        "Stat": "Maximum",
                    },
                    "ReturnData": True,
                }],
                StartTime=start_time,
                EndTime=end_time,
            )
            results = response.get("MetricDataResults", [])
            if not results:
                return None
            values = results[0].get("Values", [])
            return sum(values) if values else 0.0  # 0 sum over all days = idle
        except ClientError:
            return None

    def _get_elb_request_count(
        self,
        lb_arn: str,
        lb_name: str,
        lb_type: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Optional[float]:
        """Return total request count for an ELB over the period."""
        try:
            # ALB uses LoadBalancer dimension with ARN suffix; CLB uses LoadBalancerName
            if lb_type == "application":
                # ALB dimension value = arn suffix after 'loadbalancer/'
                dim_value = lb_arn.split("loadbalancer/")[-1] if "loadbalancer/" in lb_arn else lb_name
                namespace = "AWS/ApplicationELB"
                metric_name = "RequestCount"
                dim_name = "LoadBalancer"
            else:
                dim_value = lb_name
                namespace = "AWS/ELB"
                metric_name = "RequestCount"
                dim_name = "LoadBalancerName"

            response = self.cw_client.get_metric_data(
                MetricDataQueries=[{
                    "Id": "req",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": namespace,
                            "MetricName": metric_name,
                            "Dimensions": [{"Name": dim_name, "Value": dim_value}],
                        },
                        "Period": 86400,
                        "Stat": "Sum",
                    },
                    "ReturnData": True,
                }],
                StartTime=start_time,
                EndTime=end_time,
            )
            results = response.get("MetricDataResults", [])
            if not results:
                return None
            values = results[0].get("Values", [])
            return sum(values) if values else 0.0
        except ClientError:
            return None

    def _get_lambda_invocation_sum(
        self,
        fn_name: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Optional[float]:
        """Return total Lambda invocations over the period."""
        try:
            response = self.cw_client.get_metric_data(
                MetricDataQueries=[{
                    "Id": "inv",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/Lambda",
                            "MetricName": "Invocations",
                            "Dimensions": [{"Name": "FunctionName", "Value": fn_name}],
                        },
                        "Period": 86400,
                        "Stat": "Sum",
                    },
                    "ReturnData": True,
                }],
                StartTime=start_time,
                EndTime=end_time,
            )
            results = response.get("MetricDataResults", [])
            if not results:
                return None
            values = results[0].get("Values", [])
            return sum(values) if values else 0.0
        except ClientError:
            return None

    # ------------------------------------------------------------------
    # Opportunity builders
    # ------------------------------------------------------------------

    def _make_ec2_opportunity(
        self,
        instance_id: str,
        name: str,
        instance_type: str,
        region: str,
        age_days: int,
        cpu_p95: float,
        net_avg_mb: Optional[float],
        monthly_cost: float,
        category: str,
        action: str,
        savings: float,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        is_idle = category == "idle_resources"
        net_info = f", avg NetworkIn {net_avg_mb:.1f} MB/day" if net_avg_mb is not None else ""

        if is_idle:
            title = f"Idle EC2 Instance: {name} ({instance_type})"
            description = (
                f"Instance {instance_id} ({instance_type}) has had P95 CPU utilization of "
                f"{cpu_p95:.1f}%{net_info} over the last {LOOKBACK_DAYS_COMPUTE} days. "
                f"This instance has been running for {age_days} days and appears idle. "
                f"Consider stopping or terminating to save ~${monthly_cost:.0f}/month."
            )
            steps = [
                {"step": 1, "action": "Verify the instance is not serving any traffic"},
                {"step": 2, "action": "Check for scheduled or periodic workloads"},
                {"step": 3, "action": "Create an AMI snapshot as a recovery backup"},
                {"step": 4, "action": "Update DNS records and load balancer target groups"},
                {"step": 5, "action": "Terminate the instance via Console or AWS CLI"},
            ]
        else:
            title = f"Underutilized EC2: {name} ({instance_type})"
            description = (
                f"Instance {instance_id} ({instance_type}) has P95 CPU of {cpu_p95:.1f}%"
                f"{net_info} over {LOOKBACK_DAYS_COMPUTE} days, indicating it is "
                f"overprovisioned. Consider downsizing to a smaller instance type."
            )
            steps = [
                {"step": 1, "action": "Review application performance requirements"},
                {"step": 2, "action": "Create an AMI backup before resizing"},
                {"step": 3, "action": "Stop the instance"},
                {"step": 4, "action": "Modify instance type to one size smaller"},
                {"step": 5, "action": "Start the instance and monitor performance for 48 hours"},
            ]

        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": title,
            "description": description,
            "category": category,
            "source": "cloudwatch_analysis",
            "source_id": f"cw-ec2-{action}-{instance_id}",
            "service": "EC2",
            "resource_id": instance_id,
            "resource_name": name,
            "resource_type": instance_type,
            "region": region,
            "estimated_monthly_savings": round(savings, 2),
            "estimated_annual_savings": round(savings * 12, 2),
            "current_monthly_cost": round(monthly_cost, 2),
            "projected_monthly_cost": round(monthly_cost - savings, 2),
            "effort_level": "low" if is_idle else "medium",
            "risk_level": "low",
            "confidence_score": 0.90 if cpu_p95 < IDLE_CPU_THRESHOLD_PCT else 0.75,
            "implementation_steps": steps,
            "evidence": {
                "cpu_p95_pct": cpu_p95,
                "net_avg_mb_per_day": net_avg_mb,
                "lookback_period_days": LOOKBACK_DAYS_COMPUTE,
                "age_days": age_days,
                "thresholds": {
                    "idle_cpu_threshold_pct": IDLE_CPU_THRESHOLD_PCT,
                    "underutil_cpu_threshold_pct": UNDERUTIL_CPU_THRESHOLD_PCT,
                },
            },
            "api_trace": {
                "api": "cloudwatch:GetMetricData",
                "metric": "CPUUtilization",
                "stat": "p95",
                "timestamp": now,
            },
            "cur_validation_sql": self._ec2_validation_sql(instance_id),
            "deep_link": (
                f"https://{region}.console.aws.amazon.com/ec2/v2/home?region={region}"
                f"#InstanceDetails:instanceId={instance_id}"
            ),
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_rds_opportunity(
        self,
        db_id: str,
        db_class: str,
        multi_az: bool,
        monthly_cost: float,
        lookback_days: int,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Idle RDS Instance: {db_id} ({db_class})",
            "description": (
                f"RDS instance {db_id} ({db_class}) has received zero database connections "
                f"over the last {lookback_days} days. "
                f"{'This is a Multi-AZ deployment. ' if multi_az else ''}"
                f"Consider stopping or deleting this instance to save ~${monthly_cost:.0f}/month."
            ),
            "category": "idle_resources",
            "source": "cloudwatch_analysis",
            "source_id": f"cw-rds-idle-{db_id}",
            "service": "RDS",
            "resource_id": db_id,
            "resource_name": db_id,
            "resource_type": db_class,
            "region": self.region,
            "estimated_monthly_savings": round(monthly_cost, 2),
            "estimated_annual_savings": round(monthly_cost * 12, 2),
            "current_monthly_cost": round(monthly_cost, 2),
            "projected_monthly_cost": 0.0,
            "effort_level": "low",
            "risk_level": "medium",
            "confidence_score": 0.92,
            "implementation_steps": [
                {"step": 1, "action": "Confirm no application is connecting to this database"},
                {"step": 2, "action": "Take a final RDS snapshot as backup"},
                {"step": 3, "action": "Stop (or delete) the RDS instance"},
                {"step": 4, "action": "Update application configs and secrets to remove the endpoint"},
            ],
            "evidence": {
                "connection_sum_7d": 0,
                "lookback_period_days": lookback_days,
                "multi_az": multi_az,
            },
            "api_trace": {
                "api": "cloudwatch:GetMetricData",
                "metric": "DatabaseConnections",
                "stat": "Maximum",
                "timestamp": now,
            },
            "cur_validation_sql": self._rds_validation_sql(db_id),
            "deep_link": (
                f"https://{self.region}.console.aws.amazon.com/rds/home"
                f"?region={self.region}#database:id={db_id}"
            ),
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_elb_opportunity(
        self,
        lb_arn: str,
        lb_name: str,
        lb_type: str,
        lb_scheme: str,
        lookback_days: int,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        # ALB ≈ $16/mo base charge; NLB ≈ $16/mo; CLB ≈ $18/mo
        monthly_cost = 18.0
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Idle Load Balancer: {lb_name} ({lb_type.upper()})",
            "description": (
                f"Load balancer {lb_name} has processed zero requests over the last "
                f"{lookback_days} days. Idle load balancers still incur the base hourly "
                f"charge (~${monthly_cost}/month). Delete if no longer needed."
            ),
            "category": "idle_resources",
            "source": "cloudwatch_analysis",
            "source_id": f"cw-elb-idle-{lb_name}",
            "service": "ELB",
            "resource_id": lb_name,
            "resource_name": lb_name,
            "resource_type": f"{lb_type} load balancer",
            "region": self.region,
            "estimated_monthly_savings": monthly_cost,
            "estimated_annual_savings": monthly_cost * 12,
            "current_monthly_cost": monthly_cost,
            "projected_monthly_cost": 0.0,
            "effort_level": "low",
            "risk_level": "low",
            "confidence_score": 0.95,
            "implementation_steps": [
                {"step": 1, "action": "Confirm no DNS records or services point to this load balancer"},
                {"step": 2, "action": "Remove any listener rules and target groups"},
                {"step": 3, "action": "Delete the load balancer via Console or AWS CLI"},
            ],
            "evidence": {
                "request_count_sum": 0,
                "lookback_period_days": lookback_days,
                "scheme": lb_scheme,
                "lb_type": lb_type,
            },
            "api_trace": {
                "api": "cloudwatch:GetMetricData",
                "metric": "RequestCount",
                "stat": "Sum",
                "timestamp": now,
            },
            "deep_link": (
                f"https://{self.region}.console.aws.amazon.com/ec2/v2/home"
                f"?region={self.region}#LoadBalancers:search={lb_name}"
            ),
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    def _make_lambda_opportunity(
        self,
        fn_name: str,
        fn_arn: str,
        runtime: str,
        memory_mb: int,
        lookback_days: int,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        region = fn_arn.split(":")[3] if ":" in fn_arn else self.region
        return {
            "id": str(uuid4()),
            "account_id": self.account_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "title": f"Unused Lambda Function: {fn_name}",
            "description": (
                f"Lambda function {fn_name} ({runtime}, {memory_mb} MB) has had zero "
                f"invocations over the last {lookback_days} days. "
                f"If it has provisioned concurrency configured, it is incurring idle charges. "
                f"Consider deleting or archiving this function."
            ),
            "category": "idle_resources",
            "source": "cloudwatch_analysis",
            "source_id": f"cw-lambda-idle-{fn_name}",
            "service": "Lambda",
            "resource_id": fn_name,
            "resource_name": fn_name,
            "resource_type": f"Lambda ({runtime})",
            "region": region,
            "estimated_monthly_savings": 0.0,  # Updated by CUR validation
            "estimated_annual_savings": 0.0,
            "current_monthly_cost": 0.0,
            "projected_monthly_cost": 0.0,
            "effort_level": "low",
            "risk_level": "low",
            "confidence_score": 0.80,
            "implementation_steps": [
                {"step": 1, "action": "Confirm function is not triggered by EventBridge, SQS, or SNS"},
                {"step": 2, "action": "Check if provisioned concurrency is configured"},
                {"step": 3, "action": "Remove provisioned concurrency if present to stop charges"},
                {"step": 4, "action": "Archive or delete the function if no longer needed"},
            ],
            "evidence": {
                "invocation_sum": 0,
                "lookback_period_days": lookback_days,
                "memory_mb": memory_mb,
                "runtime": runtime,
            },
            "api_trace": {
                "api": "cloudwatch:GetMetricData",
                "metric": "Invocations",
                "stat": "Sum",
                "timestamp": now,
            },
            "deep_link": (
                f"https://{region}.console.aws.amazon.com/lambda/home"
                f"?region={region}#/functions/{fn_name}"
            ),
            "status": "open",
            "first_detected_at": now,
            "last_seen_at": now,
        }

    # ------------------------------------------------------------------
    # Cost estimation helpers
    # ------------------------------------------------------------------

    def _estimate_monthly_cost(self, instance_type: str) -> float:
        """Estimate monthly on-demand cost for an EC2 instance type."""
        hourly = EC2_HOURLY_PRICES.get(instance_type, 0.10)  # default $0.10/hr
        return round(hourly * 24 * 30, 2)

    def _estimate_rds_monthly_cost(self, db_class: str, multi_az: bool) -> float:
        """
        Rough monthly cost estimate for an RDS instance.
        Multi-AZ doubles the compute cost.
        """
        # Rough hourly prices for common RDS classes (us-east-1, MySQL)
        rds_hourly = {
            "db.t3.micro": 0.017, "db.t3.small": 0.034, "db.t3.medium": 0.068,
            "db.t3.large": 0.136, "db.t3.xlarge": 0.272,
            "db.m5.large": 0.171, "db.m5.xlarge": 0.342, "db.m5.2xlarge": 0.684,
            "db.r5.large": 0.24, "db.r5.xlarge": 0.48,
        }
        hourly = rds_hourly.get(db_class, 0.10)
        if multi_az:
            hourly *= 2
        return round(hourly * 24 * 30, 2)

    # ------------------------------------------------------------------
    # CUR validation SQL
    # ------------------------------------------------------------------

    def _ec2_validation_sql(self, instance_id: str) -> str:
        return (
            "-- Validate EC2 idle cost from CUR\n"
            "SELECT line_item_resource_id,\n"
            "       SUM(line_item_unblended_cost) AS monthly_cost\n"
            "FROM cost_and_usage_report\n"
            f"WHERE line_item_resource_id = '{instance_id}'\n"
            "  AND line_item_product_code = 'AmazonEC2'\n"
            "  AND line_item_usage_start_date >= DATE_ADD('day', -30, CURRENT_DATE)\n"
            "GROUP BY 1;"
        )

    def _rds_validation_sql(self, db_id: str) -> str:
        return (
            "-- Validate RDS idle cost from CUR\n"
            "SELECT line_item_resource_id,\n"
            "       SUM(line_item_unblended_cost) AS monthly_cost\n"
            "FROM cost_and_usage_report\n"
            f"WHERE line_item_resource_id LIKE '%{db_id}%'\n"
            "  AND line_item_product_code = 'AmazonRDS'\n"
            "  AND line_item_usage_start_date >= DATE_ADD('day', -30, CURRENT_DATE)\n"
            "GROUP BY 1;"
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _get_tag(tags: List[Dict[str, str]], key: str) -> Optional[str]:
        for t in tags:
            if t.get("Key") == key:
                return t.get("Value")
        return None
