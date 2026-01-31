"""
AWS Optimization Signals Service

Ingests optimization signals from various AWS sources:
- Cost Explorer Recommendations
- Trusted Advisor Checks
- Compute Optimizer Recommendations
- Custom CUR Analysis

Converts signals to unified Opportunity format for storage and display.
"""

from botocore.exceptions import ClientError, BotoCoreError

from backend.utils.aws_session import create_aws_session
from backend.utils.aws_constants import AwsService, TRUSTED_ADVISOR_REGION
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
import json
import structlog

from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class AWSOptimizationSignalsService:
    """
    Service for ingesting and transforming AWS optimization signals.

    Supports multiple AWS APIs:
    - Cost Explorer: get_rightsizing_recommendation, get_savings_plans_purchase_recommendation
    - Trusted Advisor: describe_checks, describe_check_result
    - Compute Optimizer: get_ec2_instance_recommendations, get_lambda_function_recommendations
    """

    # Category mapping from AWS signal types
    CATEGORY_MAP = {
        # Cost Explorer
        'RightsizingRecommendation': 'rightsizing',
        'SavingsPlansPurchaseRecommendation': 'savings_plans',
        'ReservationPurchaseRecommendation': 'reserved_instances',

        # Trusted Advisor check categories
        'cost_optimizing': 'idle_resources',
        'Amazon EC2 Reserved Instance Lease Expiration': 'reserved_instances',
        'Low Utilization Amazon EC2 Instances': 'rightsizing',
        'Idle Load Balancers': 'idle_resources',
        'Unassociated Elastic IP Addresses': 'idle_resources',
        'Underutilized Amazon EBS Volumes': 'storage_optimization',
        'Amazon RDS Idle DB Instances': 'idle_resources',
        'Amazon EC2 Reserved Instance Optimization': 'reserved_instances',

        # Compute Optimizer
        'Underprovisioned': 'rightsizing',
        'Overprovisioned': 'rightsizing',
        'NotOptimized': 'rightsizing',
    }

    # Effort level mapping
    EFFORT_MAP = {
        'low': ['terminate', 'delete', 'release'],
        'medium': ['modify', 'resize', 'change'],
        'high': ['migrate', 'refactor', 'redesign']
    }

    def __init__(
        self,
        region: str = None,
        account_id: str = None,
        organization_id: Optional[UUID] = None
    ):
        """
        Initialize the AWS Optimization Signals service.

        Args:
            region: AWS region (defaults to settings)
            account_id: AWS account ID to scope operations
            organization_id: Organization ID for multi-tenant scoping
        """
        self.region = region or settings.aws_region
        self.account_id = account_id
        self.organization_id = organization_id

        # Initialize AWS clients
        self._session = create_aws_session(region_name=self.region)
        self._ce_client = None
        self._ta_client = None
        self._co_client = None
        self._support_client = None

    @property
    def ce_client(self):
        """Lazy initialization of Cost Explorer client"""
        if self._ce_client is None:
            self._ce_client = self._session.client(AwsService.COST_EXPLORER)
        return self._ce_client

    @property
    def support_client(self):
        """Lazy initialization of Support client for Trusted Advisor"""
        if self._support_client is None:
            # Trusted Advisor requires a specific region (see aws_constants)
            self._support_client = create_aws_session(region_name=TRUSTED_ADVISOR_REGION).client(AwsService.TRUSTED_ADVISOR)
        return self._support_client

    @property
    def co_client(self):
        """Lazy initialization of Compute Optimizer client"""
        if self._co_client is None:
            self._co_client = self._session.client(AwsService.COMPUTE_OPTIMIZER)
        return self._co_client

    def _determine_effort_level(self, description: str, action_type: str = None) -> str:
        """Determine effort level from description and action type"""
        desc_lower = description.lower()

        if action_type:
            action_lower = action_type.lower()
            for effort, keywords in self.EFFORT_MAP.items():
                if any(kw in action_lower for kw in keywords):
                    return effort

        # Check description for keywords
        for effort, keywords in self.EFFORT_MAP.items():
            if any(kw in desc_lower for kw in keywords):
                return effort

        return 'medium'  # Default

    def _generate_deep_link(
        self,
        service: str,
        resource_id: str,
        region: str = None
    ) -> str:
        """Generate AWS console deep link for a resource"""
        region = region or self.region

        deep_links = {
            'EC2': f"https://{region}.console.aws.amazon.com/ec2/v2/home?region={region}#InstanceDetails:instanceId={resource_id}",
            'RDS': f"https://{region}.console.aws.amazon.com/rds/home?region={region}#database:id={resource_id}",
            'EBS': f"https://{region}.console.aws.amazon.com/ec2/v2/home?region={region}#VolumeDetails:volumeId={resource_id}",
            'ELB': f"https://{region}.console.aws.amazon.com/ec2/v2/home?region={region}#LoadBalancers:",
            'Lambda': f"https://{region}.console.aws.amazon.com/lambda/home?region={region}#/functions/{resource_id}",
            'S3': f"https://s3.console.aws.amazon.com/s3/buckets/{resource_id}",
            'ElastiCache': f"https://{region}.console.aws.amazon.com/elasticache/home?region={region}#/redis/{resource_id}",
        }

        return deep_links.get(service, f"https://console.aws.amazon.com/")

    async def fetch_cost_explorer_recommendations(self) -> List[Dict[str, Any]]:
        """
        Fetch rightsizing recommendations from Cost Explorer.

        Returns:
            List of opportunity dictionaries
        """
        opportunities = []

        try:
            # Get rightsizing recommendations
            paginator = self.ce_client.get_paginator('get_rightsizing_recommendation')

            for page in paginator.paginate(
                Service='AmazonEC2',
                Configuration={
                    'RecommendationTarget': 'SAME_INSTANCE_FAMILY',
                    'BenefitsConsidered': True
                }
            ):
                for rec in page.get('RightsizingRecommendations', []):
                    opportunity = self._transform_rightsizing_recommendation(rec)
                    if opportunity:
                        opportunities.append(opportunity)

            logger.info(f"Fetched {len(opportunities)} Cost Explorer rightsizing recommendations")

        except ClientError as e:
            logger.error(f"Cost Explorer API error: {e}")
        except Exception as e:
            logger.error(f"Error fetching Cost Explorer recommendations: {e}")

        return opportunities

    def _transform_rightsizing_recommendation(
        self,
        rec: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Transform Cost Explorer rightsizing recommendation to Opportunity format"""
        try:
            current = rec.get('CurrentInstance', {})
            modification = rec.get('ModifyRecommendationDetail', {})
            terminate = rec.get('TerminateRecommendationDetail', {})

            resource_id = current.get('ResourceId', '')
            resource_type = current.get('InstanceType', '')

            # Determine action and savings
            if rec.get('RightsizingType') == 'Terminate':
                action = 'Terminate'
                target = None
                savings = Decimal(str(terminate.get('EstimatedMonthlySavings', 0)))
            else:
                target = modification.get('TargetInstances', [{}])[0]
                action = 'Modify'
                savings = Decimal(str(modification.get('EstimatedMonthlySavings', 0)))

            # Calculate confidence based on utilization data
            utilization = current.get('ResourceUtilization', {}).get('EC2ResourceUtilization', {})
            max_cpu = float(utilization.get('MaxCpuUtilizationPercentage', 50))
            confidence = min(1.0, (100 - max_cpu) / 100 + 0.3)  # Higher confidence for lower utilization

            return {
                'id': str(uuid4()),
                'account_id': rec.get('AccountId', self.account_id),
                'organization_id': str(self.organization_id) if self.organization_id else None,
                'title': f"Rightsize EC2 Instance: {resource_id}",
                'description': self._generate_rightsizing_description(rec, current, target),
                'category': 'rightsizing',
                'source': 'cost_explorer',
                'source_id': f"ce-rightsize-{resource_id}",
                'service': 'EC2',
                'resource_id': resource_id,
                'resource_name': current.get('Tags', {}).get('Name', resource_id),
                'resource_type': resource_type,
                'region': current.get('Region', self.region),
                'estimated_monthly_savings': float(savings),
                'estimated_annual_savings': float(savings * 12),
                'savings_percentage': float(current.get('MonthlySavings', {}).get('SavingsPercentage', 0)),
                'current_monthly_cost': float(current.get('MonthlyCost', 0)),
                'projected_monthly_cost': float(current.get('MonthlyCost', 0)) - float(savings),
                'effort_level': 'low' if action == 'Terminate' else 'medium',
                'risk_level': 'low' if action == 'Modify' else 'medium',
                'implementation_steps': self._generate_ec2_rightsize_steps(rec, action, target),
                'evidence': {
                    'utilization': utilization,
                    'recommendation_type': rec.get('RightsizingType'),
                    'lookback_period_days': 14
                },
                'api_trace': {
                    'api': 'ce:GetRightsizingRecommendation',
                    'service': 'AmazonEC2',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                },
                'cur_validation_sql': self._generate_ec2_validation_sql(resource_id),
                'deep_link': self._generate_deep_link('EC2', resource_id, current.get('Region')),
                'confidence_score': round(confidence, 2),
                'status': 'open',
                'first_detected_at': datetime.now(timezone.utc).isoformat(),
                'last_seen_at': datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning(f"Error transforming rightsizing recommendation: {e}")
            return None

    def _generate_rightsizing_description(
        self,
        rec: Dict,
        current: Dict,
        target: Optional[Dict]
    ) -> str:
        """Generate human-readable description for rightsizing recommendation"""
        current_type = current.get('InstanceType', 'unknown')
        utilization = current.get('ResourceUtilization', {}).get('EC2ResourceUtilization', {})
        cpu = utilization.get('MaxCpuUtilizationPercentage', 'N/A')

        if rec.get('RightsizingType') == 'Terminate':
            return (
                f"This EC2 instance ({current_type}) shows very low utilization "
                f"(max CPU: {cpu}%) and appears to be idle. Consider terminating "
                f"this instance to eliminate unnecessary costs."
            )
        else:
            target_type = target.get('InstanceType', 'smaller') if target else 'smaller'
            return (
                f"This EC2 instance ({current_type}) is overprovisioned based on "
                f"utilization metrics (max CPU: {cpu}%). Consider downsizing to "
                f"{target_type} to reduce costs while maintaining performance."
            )

    def _generate_ec2_rightsize_steps(
        self,
        rec: Dict,
        action: str,
        target: Optional[Dict]
    ) -> List[Dict[str, Any]]:
        """Generate implementation steps for EC2 rightsizing"""
        steps = []

        if action == 'Terminate':
            steps = [
                {"step": 1, "action": "Verify instance is not serving production traffic"},
                {"step": 2, "action": "Check for any dependent resources or services"},
                {"step": 3, "action": "Create AMI backup if needed for recovery"},
                {"step": 4, "action": "Update any references to this instance (DNS, load balancers)"},
                {"step": 5, "action": "Terminate the instance via AWS Console or CLI"}
            ]
        else:
            target_type = target.get('InstanceType', 'smaller') if target else 'smaller'
            steps = [
                {"step": 1, "action": f"Schedule maintenance window for instance modification"},
                {"step": 2, "action": "Create AMI backup of current instance"},
                {"step": 3, "action": "Stop the instance"},
                {"step": 4, "action": f"Modify instance type to {target_type}"},
                {"step": 5, "action": "Start the instance and validate application"},
                {"step": 6, "action": "Monitor for 24-48 hours to ensure stability"}
            ]

        return steps

    def _generate_ec2_validation_sql(self, resource_id: str) -> str:
        """Generate CUR validation SQL for EC2 instance"""
        return f"""
-- Validate EC2 rightsizing savings from CUR
SELECT
    line_item_resource_id,
    product_instance_type,
    SUM(line_item_unblended_cost) as current_cost,
    DATE_TRUNC('month', line_item_usage_start_date) as month
FROM cost_and_usage_report
WHERE line_item_resource_id = '{resource_id}'
    AND line_item_product_code = 'AmazonEC2'
    AND line_item_usage_start_date >= DATE_ADD('day', -30, CURRENT_DATE)
GROUP BY 1, 2, 4
ORDER BY month DESC;
        """.strip()

    async def fetch_trusted_advisor_recommendations(self) -> List[Dict[str, Any]]:
        """
        Fetch cost optimization checks from Trusted Advisor.

        Note: Requires Business or Enterprise Support plan.

        Returns:
            List of opportunity dictionaries
        """
        opportunities = []

        try:
            # Get cost optimization checks
            checks_response = self.support_client.describe_trusted_advisor_checks(
                language='en'
            )

            cost_checks = [
                check for check in checks_response.get('checks', [])
                if check.get('category') == 'cost_optimizing'
            ]

            for check in cost_checks:
                check_id = check.get('id')

                # Get check results
                result_response = self.support_client.describe_trusted_advisor_check_result(
                    checkId=check_id,
                    language='en'
                )

                result = result_response.get('result', {})

                # Process flagged resources
                for resource in result.get('flaggedResources', []):
                    opportunity = self._transform_trusted_advisor_resource(
                        check, resource
                    )
                    if opportunity:
                        opportunities.append(opportunity)

            logger.info(f"Fetched {len(opportunities)} Trusted Advisor recommendations")

        except ClientError as e:
            if 'SubscriptionRequiredException' in str(e):
                logger.warning("Trusted Advisor requires Business/Enterprise Support")
            else:
                logger.error(f"Trusted Advisor API error: {e}")
        except Exception as e:
            logger.error(f"Error fetching Trusted Advisor recommendations: {e}")

        return opportunities

    def _transform_trusted_advisor_resource(
        self,
        check: Dict[str, Any],
        resource: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Transform Trusted Advisor flagged resource to Opportunity format"""
        try:
            check_name = check.get('name', '')
            check_id = check.get('id', '')
            metadata = resource.get('metadata', [])

            # Parse metadata based on check type
            resource_info = self._parse_ta_metadata(check_name, metadata, check.get('metadata', []))

            # Determine category
            category = self.CATEGORY_MAP.get(check_name, 'other')

            # Extract savings if available
            savings = resource_info.get('estimated_savings', 0)

            return {
                'id': str(uuid4()),
                'account_id': self.account_id,
                'organization_id': str(self.organization_id) if self.organization_id else None,
                'title': f"{check_name}: {resource_info.get('resource_id', 'Unknown')}",
                'description': check.get('description', ''),
                'category': category,
                'source': 'trusted_advisor',
                'source_id': f"ta-{check_id}-{resource.get('resourceId', '')}",
                'service': resource_info.get('service', 'AWS'),
                'resource_id': resource_info.get('resource_id'),
                'resource_name': resource_info.get('resource_name'),
                'resource_type': resource_info.get('resource_type'),
                'region': resource_info.get('region', self.region),
                'estimated_monthly_savings': savings,
                'estimated_annual_savings': savings * 12 if savings else None,
                'effort_level': self._determine_effort_level(check.get('description', ''), check_name),
                'risk_level': resource_info.get('risk_level', 'medium'),
                'implementation_steps': [],
                'evidence': {
                    'check_name': check_name,
                    'check_id': check_id,
                    'status': resource.get('status'),
                    'metadata': dict(zip(check.get('metadata', []), metadata))
                },
                'api_trace': {
                    'api': 'support:DescribeTrustedAdvisorCheckResult',
                    'check_id': check_id,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                },
                'deep_link': self._generate_deep_link(
                    resource_info.get('service', 'AWS'),
                    resource_info.get('resource_id', ''),
                    resource_info.get('region')
                ),
                'confidence_score': 0.85,  # Trusted Advisor is generally reliable
                'status': 'open',
                'first_detected_at': datetime.now(timezone.utc).isoformat(),
                'last_seen_at': datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning(f"Error transforming Trusted Advisor resource: {e}")
            return None

    def _parse_ta_metadata(
        self,
        check_name: str,
        metadata: List[str],
        metadata_keys: List[str]
    ) -> Dict[str, Any]:
        """Parse Trusted Advisor metadata based on check type"""
        result = {}

        # Create key-value mapping
        meta_dict = dict(zip(metadata_keys, metadata)) if metadata_keys else {}

        # Common patterns
        result['region'] = meta_dict.get('Region', meta_dict.get('region', self.region))

        # Check-specific parsing
        if 'EC2' in check_name or 'Instance' in check_name:
            result['service'] = 'EC2'
            result['resource_id'] = meta_dict.get('Instance ID', meta_dict.get('Resource ID'))
            result['resource_type'] = meta_dict.get('Instance Type')

            # Try to extract savings
            if 'Estimated Monthly Savings' in meta_dict:
                try:
                    savings_str = meta_dict['Estimated Monthly Savings'].replace('$', '').replace(',', '')
                    result['estimated_savings'] = float(savings_str)
                except:
                    pass

        elif 'EBS' in check_name or 'Volume' in check_name:
            result['service'] = 'EBS'
            result['resource_id'] = meta_dict.get('Volume ID')
            result['resource_type'] = meta_dict.get('Volume Type')

        elif 'RDS' in check_name:
            result['service'] = 'RDS'
            result['resource_id'] = meta_dict.get('DB Instance', meta_dict.get('Resource ID'))
            result['resource_type'] = meta_dict.get('Instance Type')

        elif 'Load Balancer' in check_name or 'ELB' in check_name:
            result['service'] = 'ELB'
            result['resource_id'] = meta_dict.get('Load Balancer Name')

        elif 'Elastic IP' in check_name:
            result['service'] = 'VPC'
            result['resource_id'] = meta_dict.get('IP Address')

        else:
            result['service'] = 'AWS'
            result['resource_id'] = meta_dict.get('Resource ID', list(meta_dict.values())[0] if meta_dict else None)

        return result

    async def fetch_compute_optimizer_recommendations(self) -> List[Dict[str, Any]]:
        """
        Fetch recommendations from AWS Compute Optimizer.

        Returns:
            List of opportunity dictionaries
        """
        opportunities = []

        try:
            # Get EC2 instance recommendations
            ec2_response = self.co_client.get_ec2_instance_recommendations(
                maxResults=100
            )

            for rec in ec2_response.get('instanceRecommendations', []):
                opportunity = self._transform_compute_optimizer_ec2(rec)
                if opportunity:
                    opportunities.append(opportunity)

            # Get Lambda function recommendations
            try:
                lambda_response = self.co_client.get_lambda_function_recommendations(
                    maxResults=100
                )

                for rec in lambda_response.get('lambdaFunctionRecommendations', []):
                    opportunity = self._transform_compute_optimizer_lambda(rec)
                    if opportunity:
                        opportunities.append(opportunity)
            except ClientError:
                logger.debug("Lambda recommendations not available")

            logger.info(f"Fetched {len(opportunities)} Compute Optimizer recommendations")

        except ClientError as e:
            logger.error(f"Compute Optimizer API error: {e}")
        except Exception as e:
            logger.error(f"Error fetching Compute Optimizer recommendations: {e}")

        return opportunities

    def _transform_compute_optimizer_ec2(
        self,
        rec: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Transform Compute Optimizer EC2 recommendation to Opportunity format"""
        try:
            instance_arn = rec.get('instanceArn', '')
            instance_id = instance_arn.split('/')[-1] if '/' in instance_arn else instance_arn
            current_type = rec.get('currentInstanceType', '')
            finding = rec.get('finding', '')

            if finding not in ['Overprovisioned', 'NotOptimized']:
                return None  # Only process optimization opportunities

            # Get best recommendation option
            options = rec.get('recommendationOptions', [])
            if not options:
                return None

            best_option = options[0]
            target_type = best_option.get('instanceType', '')

            # Calculate savings
            current_cost = self._estimate_ec2_monthly_cost(current_type)
            projected_cost = self._estimate_ec2_monthly_cost(target_type)
            savings = current_cost - projected_cost

            if savings <= 0:
                return None

            # Get utilization metrics
            utilization = rec.get('utilizationMetrics', [])
            cpu_metric = next((m for m in utilization if m.get('name') == 'CPU'), {})

            return {
                'id': str(uuid4()),
                'account_id': rec.get('accountId', self.account_id),
                'organization_id': str(self.organization_id) if self.organization_id else None,
                'title': f"Rightsize EC2: {instance_id} ({current_type} → {target_type})",
                'description': (
                    f"Compute Optimizer has identified that instance {instance_id} "
                    f"is {finding.lower()}. Current type {current_type} can be "
                    f"downsized to {target_type} based on CPU utilization of "
                    f"{cpu_metric.get('value', 'N/A')}%."
                ),
                'category': 'rightsizing',
                'source': 'compute_optimizer',
                'source_id': f"co-ec2-{instance_id}",
                'service': 'EC2',
                'resource_id': instance_id,
                'resource_name': rec.get('instanceName', instance_id),
                'resource_type': current_type,
                'region': instance_arn.split(':')[3] if ':' in instance_arn else self.region,
                'estimated_monthly_savings': round(savings, 2),
                'estimated_annual_savings': round(savings * 12, 2),
                'savings_percentage': round((savings / current_cost) * 100, 1) if current_cost > 0 else 0,
                'current_monthly_cost': round(current_cost, 2),
                'projected_monthly_cost': round(projected_cost, 2),
                'effort_level': 'medium',
                'risk_level': 'low',
                'implementation_steps': [
                    {"step": 1, "action": "Review application performance requirements"},
                    {"step": 2, "action": "Schedule maintenance window"},
                    {"step": 3, "action": "Create AMI backup"},
                    {"step": 4, "action": f"Stop instance and change type to {target_type}"},
                    {"step": 5, "action": "Start instance and validate"},
                    {"step": 6, "action": "Monitor for 48 hours"}
                ],
                'evidence': {
                    'finding': finding,
                    'finding_reason_codes': rec.get('findingReasonCodes', []),
                    'utilization_metrics': utilization,
                    'recommendation_options': options[:3],  # Top 3 options
                    'lookback_period_seconds': rec.get('lookBackPeriodInDays', 14) * 86400
                },
                'api_trace': {
                    'api': 'compute-optimizer:GetEC2InstanceRecommendations',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                },
                'cur_validation_sql': self._generate_ec2_validation_sql(instance_id),
                'deep_link': self._generate_deep_link(
                    'EC2',
                    instance_id,
                    instance_arn.split(':')[3] if ':' in instance_arn else self.region
                ),
                'confidence_score': round(best_option.get('performanceRisk', 0.2), 2),
                'status': 'open',
                'first_detected_at': datetime.now(timezone.utc).isoformat(),
                'last_seen_at': datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning(f"Error transforming Compute Optimizer EC2 recommendation: {e}")
            return None

    def _transform_compute_optimizer_lambda(
        self,
        rec: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Transform Compute Optimizer Lambda recommendation to Opportunity format"""
        try:
            function_arn = rec.get('functionArn', '')
            function_name = function_arn.split(':')[-1] if ':' in function_arn else function_arn
            finding = rec.get('finding', '')

            if finding not in ['Overprovisioned', 'NotOptimized']:
                return None

            # Get memory recommendations
            options = rec.get('memorySizeRecommendationOptions', [])
            if not options:
                return None

            current_config = rec.get('currentMemorySize', 128)
            best_option = options[0]
            recommended_memory = best_option.get('memorySize', current_config)

            # Estimate savings (Lambda pricing is complex, using approximation)
            current_cost = self._estimate_lambda_monthly_cost(current_config, rec)
            projected_cost = self._estimate_lambda_monthly_cost(recommended_memory, rec)
            savings = current_cost - projected_cost

            if savings <= 0:
                return None

            return {
                'id': str(uuid4()),
                'account_id': rec.get('accountId', self.account_id),
                'organization_id': str(self.organization_id) if self.organization_id else None,
                'title': f"Optimize Lambda: {function_name} Memory",
                'description': (
                    f"Lambda function {function_name} is {finding.lower()} for memory. "
                    f"Current memory {current_config}MB can be adjusted to {recommended_memory}MB "
                    f"for optimal cost-performance balance."
                ),
                'category': 'rightsizing',
                'source': 'compute_optimizer',
                'source_id': f"co-lambda-{function_name}",
                'service': 'Lambda',
                'resource_id': function_arn,
                'resource_name': function_name,
                'resource_type': f'{current_config}MB',
                'region': function_arn.split(':')[3] if ':' in function_arn else self.region,
                'estimated_monthly_savings': round(savings, 2),
                'estimated_annual_savings': round(savings * 12, 2),
                'current_monthly_cost': round(current_cost, 2),
                'projected_monthly_cost': round(projected_cost, 2),
                'effort_level': 'low',
                'risk_level': 'low',
                'implementation_steps': [
                    {"step": 1, "action": "Review function performance requirements"},
                    {"step": 2, "action": f"Update function memory to {recommended_memory}MB"},
                    {"step": 3, "action": "Deploy and test in non-production"},
                    {"step": 4, "action": "Deploy to production"},
                    {"step": 5, "action": "Monitor invocation duration and errors"}
                ],
                'evidence': {
                    'finding': finding,
                    'current_memory_mb': current_config,
                    'recommended_memory_mb': recommended_memory,
                    'utilization_metrics': rec.get('utilizationMetrics', [])
                },
                'api_trace': {
                    'api': 'compute-optimizer:GetLambdaFunctionRecommendations',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                },
                'deep_link': self._generate_deep_link('Lambda', function_name),
                'confidence_score': 0.8,
                'status': 'open',
                'first_detected_at': datetime.now(timezone.utc).isoformat(),
                'last_seen_at': datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning(f"Error transforming Compute Optimizer Lambda recommendation: {e}")
            return None

    def _estimate_ec2_monthly_cost(self, instance_type: str) -> float:
        """Estimate monthly EC2 cost based on instance type (on-demand, us-east-1)"""
        # Approximate on-demand hourly rates (simplified)
        pricing = {
            't2.micro': 0.0116, 't2.small': 0.023, 't2.medium': 0.0464,
            't3.micro': 0.0104, 't3.small': 0.0208, 't3.medium': 0.0416,
            'm5.large': 0.096, 'm5.xlarge': 0.192, 'm5.2xlarge': 0.384,
            'm6i.large': 0.096, 'm6i.xlarge': 0.192, 'm6i.2xlarge': 0.384,
            'c5.large': 0.085, 'c5.xlarge': 0.17, 'c5.2xlarge': 0.34,
            'r5.large': 0.126, 'r5.xlarge': 0.252, 'r5.2xlarge': 0.504,
        }

        hourly_rate = pricing.get(instance_type, 0.1)  # Default to $0.10/hr
        return hourly_rate * 24 * 30  # Monthly estimate

    def _estimate_lambda_monthly_cost(self, memory_mb: int, rec: Dict) -> float:
        """Estimate monthly Lambda cost"""
        # Lambda pricing: $0.0000166667 per GB-second
        # Assume average invocations from metrics
        metrics = rec.get('utilizationMetrics', [])

        # Try to get invocation count and duration
        invocations = 100000  # Default assumption
        avg_duration_ms = 200  # Default

        for m in metrics:
            if m.get('name') == 'Invocations':
                invocations = float(m.get('value', 100000))
            elif m.get('name') == 'Duration':
                avg_duration_ms = float(m.get('value', 200))

        gb_seconds = (memory_mb / 1024) * (avg_duration_ms / 1000) * invocations
        return gb_seconds * 0.0000166667

    async def fetch_all_signals(self) -> List[Dict[str, Any]]:
        """
        Fetch optimization signals from all available sources.

        Returns:
            Combined list of all opportunities
        """
        all_opportunities = []

        # Fetch from each source
        sources = [
            ("Cost Explorer", self.fetch_cost_explorer_recommendations),
            ("Trusted Advisor", self.fetch_trusted_advisor_recommendations),
            ("Compute Optimizer", self.fetch_compute_optimizer_recommendations),
        ]

        for source_name, fetch_func in sources:
            try:
                opportunities = await fetch_func()
                all_opportunities.extend(opportunities)
                logger.info(f"Fetched {len(opportunities)} opportunities from {source_name}")
            except Exception as e:
                logger.error(f"Error fetching from {source_name}: {e}")

        logger.info(f"Total opportunities fetched: {len(all_opportunities)}")
        return all_opportunities

    def deduplicate_opportunities(
        self,
        opportunities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Remove duplicate opportunities based on resource_id and category.

        Keeps the opportunity with the highest confidence score.
        """
        seen = {}

        for opp in opportunities:
            key = (opp.get('resource_id'), opp.get('category'))

            if key not in seen:
                seen[key] = opp
            else:
                # Keep the one with higher confidence
                existing_confidence = seen[key].get('confidence_score', 0) or 0
                new_confidence = opp.get('confidence_score', 0) or 0

                if new_confidence > existing_confidence:
                    seen[key] = opp

        return list(seen.values())


# Singleton instance
_signals_service = None


def get_optimization_signals_service(
    region: str = None,
    account_id: str = None,
    organization_id: Optional[UUID] = None
) -> AWSOptimizationSignalsService:
    """Get or create the optimization signals service instance"""
    global _signals_service

    if _signals_service is None or (
        region != _signals_service.region or
        account_id != _signals_service.account_id
    ):
        _signals_service = AWSOptimizationSignalsService(
            region=region,
            account_id=account_id,
            organization_id=organization_id
        )

    return _signals_service
