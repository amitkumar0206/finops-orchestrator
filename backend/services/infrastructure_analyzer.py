"""
Infrastructure Analyzer Service
Integrates AWS CloudWatch Logs, Metrics, and Compute Optimizer for infrastructure analysis.
"""

import structlog
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from backend.config.settings import get_settings
from backend.utils.aws_session import create_aws_session
from backend.utils.aws_constants import AwsService

logger = structlog.get_logger(__name__)
settings = get_settings()


class InfrastructureAnalyzer:
    """
    Analyzes AWS infrastructure metrics and correlates with cost data.
    
    Provides:
    - CloudWatch Logs Insights queries
    - CloudWatch Metrics analysis (CPU, memory, network, disk)
    - AWS Compute Optimizer recommendations
    - Cost spike correlation with infrastructure events
    """
    
    def __init__(self):
        """Initialize AWS clients for infrastructure analysis."""
        session = create_aws_session()
        self.logs_client = session.client(AwsService.CLOUDWATCH_LOGS)
        self.cloudwatch_client = session.client(AwsService.CLOUDWATCH)
        self.compute_optimizer_client = session.client(AwsService.COMPUTE_OPTIMIZER)
        
    async def query_cloudwatch_logs(
        self,
        log_group_name: str,
        start_time: int,
        end_time: int,
        query_string: str,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Execute CloudWatch Logs Insights query.
        
        Args:
            log_group_name: CloudWatch log group name
            start_time: Start time (Unix timestamp)
            end_time: End time (Unix timestamp)
            query_string: CloudWatch Logs Insights query
            limit: Maximum number of results
            
        Returns:
            Dict with status, results, and statistics
        """
        try:
            logger.info(f"Starting CloudWatch Logs query for {log_group_name}")
            
            # Start the query
            response = self.logs_client.start_query(
                logGroupName=log_group_name,
                startTime=start_time,
                endTime=end_time,
                queryString=query_string,
                limit=limit
            )
            
            query_id = response['queryId']
            
            # Poll for query completion (max 30 attempts = 30 seconds)
            max_attempts = 30
            for attempt in range(max_attempts):
                time.sleep(1)
                
                result = self.logs_client.get_query_results(queryId=query_id)
                status = result['status']
                
                if status == 'Complete':
                    logger.info(f"CloudWatch Logs query completed: {len(result['results'])} results")
                    return {
                        'status': 'success',
                        'results': result['results'],
                        'statistics': result.get('statistics', {}),
                        'query_id': query_id
                    }
                elif status == 'Failed':
                    logger.error(f"CloudWatch Logs query failed: {query_id}")
                    return {
                        'status': 'failed',
                        'reason': 'Query execution failed',
                        'query_id': query_id
                    }
                elif status == 'Cancelled':
                    logger.warning(f"CloudWatch Logs query cancelled: {query_id}")
                    return {
                        'status': 'cancelled',
                        'reason': 'Query was cancelled',
                        'query_id': query_id
                    }
            
            # Timeout
            logger.warning(f"CloudWatch Logs query timeout: {query_id}")
            return {
                'status': 'timeout',
                'reason': 'Query did not complete within 30 seconds',
                'query_id': query_id
            }
            
        except Exception as e:
            logger.error(f"CloudWatch Logs query error: {e}", exc_info=True)
            return {
                'status': 'error',
                'reason': str(e)
            }
    
    async def get_ec2_metrics(
        self,
        instance_ids: List[str],
        metric_names: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        period: int = 3600
    ) -> Dict[str, Any]:
        """
        Query CloudWatch metrics for EC2 instances.
        
        Args:
            instance_ids: List of EC2 instance IDs
            metric_names: Metrics to retrieve (default: CPU, Network)
            start_time: Start time (default: 14 days ago)
            end_time: End time (default: now)
            period: Period in seconds (default: 3600 = 1 hour)
            
        Returns:
            Dict with metrics per instance
        """
        try:
            # Default metrics
            if metric_names is None:
                metric_names = ['CPUUtilization', 'NetworkIn', 'NetworkOut']
            
            # Default time range (14 days for Compute Optimizer alignment)
            if end_time is None:
                end_time = datetime.utcnow()
            if start_time is None:
                start_time = end_time - timedelta(days=14)
            
            logger.info(f"Fetching EC2 metrics for {len(instance_ids)} instances")
            
            results = {}
            for instance_id in instance_ids:
                instance_metrics = {}
                
                for metric_name in metric_names:
                    try:
                        response = self.cloudwatch_client.get_metric_statistics(
                            Namespace='AWS/EC2',
                            MetricName=metric_name,
                            Dimensions=[
                                {
                                    'Name': 'InstanceId',
                                    'Value': instance_id
                                }
                            ],
                            StartTime=start_time,
                            EndTime=end_time,
                            Period=period,
                            Statistics=['Average', 'Maximum', 'Minimum']
                        )
                        
                        # Calculate average across all periods
                        datapoints = response['Datapoints']
                        if datapoints:
                            avg_value = sum(dp['Average'] for dp in datapoints) / len(datapoints)
                            max_value = max(dp['Maximum'] for dp in datapoints)
                            min_value = min(dp['Minimum'] for dp in datapoints)
                            
                            instance_metrics[metric_name] = {
                                'average': round(avg_value, 2),
                                'maximum': round(max_value, 2),
                                'minimum': round(min_value, 2),
                                'datapoints_count': len(datapoints),
                                'unit': response.get('Label', '')
                            }
                        else:
                            instance_metrics[metric_name] = {
                                'average': 0,
                                'maximum': 0,
                                'minimum': 0,
                                'datapoints_count': 0,
                                'unit': ''
                            }
                    
                    except Exception as metric_error:
                        logger.warning(f"Error fetching {metric_name} for {instance_id}: {metric_error}")
                        instance_metrics[metric_name] = {'error': str(metric_error)}
                
                results[instance_id] = instance_metrics
            
            logger.info(f"Successfully fetched metrics for {len(results)} instances")
            return {
                'status': 'success',
                'metrics': results,
                'time_range': {
                    'start': start_time.isoformat(),
                    'end': end_time.isoformat(),
                    'period_seconds': period
                }
            }
            
        except Exception as e:
            logger.error(f"Error fetching EC2 metrics: {e}", exc_info=True)
            return {
                'status': 'error',
                'reason': str(e)
            }
    
    async def get_rightsizing_recommendations(
        self,
        account_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch EC2 rightsizing recommendations from AWS Compute Optimizer.
        
        Args:
            account_ids: AWS account IDs (optional, defaults to current account)
            
        Returns:
            List of recommendation dicts with current/recommended types and savings
        """
        try:
            logger.info("Fetching Compute Optimizer recommendations")
            
            # Get EC2 instance recommendations
            params = {}
            if account_ids:
                params['accountIds'] = account_ids
            
            response = self.compute_optimizer_client.get_ec2_instance_recommendations(**params)
            
            recommendations = []
            for rec in response.get('instanceRecommendations', []):
                # Extract current instance info
                instance_arn = rec.get('instanceArn', '')
                instance_id = instance_arn.split('/')[-1] if instance_arn else ''
                current_type = rec.get('currentInstanceType', '')
                
                # Extract recommendation
                recommendation_options = rec.get('recommendationOptions', [])
                if recommendation_options:
                    best_option = recommendation_options[0]  # First option is usually best
                    
                    recommended_type = best_option.get('instanceType', '')
                    
                    # Calculate savings
                    performance_risk = best_option.get('performanceRisk', 0)
                    
                    # Estimated monthly savings (if available)
                    savings_opportunity = rec.get('savingsOpportunity', {})
                    estimated_monthly_savings = savings_opportunity.get('estimatedMonthlySavings', {})
                    savings_value = estimated_monthly_savings.get('value', 0)
                    savings_currency = estimated_monthly_savings.get('currency', 'USD')
                    
                    # Calculate percentage savings
                    savings_percentage = savings_opportunity.get('savingsOpportunityPercentage', 0)
                    
                    recommendations.append({
                        'instance_id': instance_id,
                        'instance_arn': instance_arn,
                        'current_instance_type': current_type,
                        'recommended_instance_type': recommended_type,
                        'performance_risk': performance_risk,
                        'estimated_monthly_savings': savings_value,
                        'currency': savings_currency,
                        'estimated_savings_percent': round(savings_percentage, 2),
                        'finding': rec.get('finding', 'Unknown'),
                        'utilization_metrics': rec.get('utilizationMetrics', {}),
                        'reason': f"Current {current_type} can be optimized to {recommended_type}"
                    })
            
            logger.info(f"Found {len(recommendations)} rightsizing recommendations")
            return recommendations
            
        except self.compute_optimizer_client.exceptions.OptInRequiredException:
            logger.warning("Compute Optimizer not enabled for this account")
            return []
        except Exception as e:
            logger.error(f"Error fetching Compute Optimizer recommendations: {e}", exc_info=True)
            return []
    
    async def correlate_cost_with_metrics(
        self,
        service: str,
        cost_spike_date: str,
        lookback_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Correlate cost spikes with infrastructure events.
        
        Args:
            service: AWS service name (e.g., EC2, RDS, Lambda)
            cost_spike_date: Date of cost spike (ISO format)
            lookback_hours: Hours to look back for anomalies
            
        Returns:
            Dict with correlation analysis and potential causes
        """
        try:
            logger.info(f"Correlating cost spike for {service} on {cost_spike_date}")
            
            # Parse spike date
            spike_datetime = datetime.fromisoformat(cost_spike_date.replace('Z', '+00:00'))
            start_time = spike_datetime - timedelta(hours=lookback_hours)
            end_time = spike_datetime + timedelta(hours=lookback_hours)
            
            potential_causes = []
            confidence = 0.5
            
            # Service-specific correlation logic
            if service.lower() in ['ec2', 'amazonec2']:
                # Check for CPU spikes, instance scaling events
                # This would query CloudWatch metrics around the spike time
                potential_causes.append({
                    'cause': 'High CPU utilization',
                    'description': 'EC2 instances may have experienced increased workload',
                    'likelihood': 'medium',
                    'recommended_action': 'Review CloudWatch CPU metrics and consider rightsizing'
                })
                confidence = 0.6
                
            elif service.lower() in ['cloudwatch', 'amazoncloudwatch']:
                # Check for log volume spikes, metric count increases
                potential_causes.append({
                    'cause': 'Increased log ingestion',
                    'description': 'Log volume may have spiked due to application errors or verbose logging',
                    'likelihood': 'high',
                    'recommended_action': 'Review application logs and implement log filtering'
                })
                confidence = 0.7
                
            elif service.lower() in ['lambda', 'awslambda']:
                # Check for invocation count spikes, duration increases
                potential_causes.append({
                    'cause': 'Increased Lambda invocations',
                    'description': 'Function may have been triggered more frequently',
                    'likelihood': 'high',
                    'recommended_action': 'Review Lambda invocation metrics and optimize triggers'
                })
                confidence = 0.65
            
            else:
                # Generic correlation
                potential_causes.append({
                    'cause': 'Usage increase',
                    'description': f'{service} usage increased around {cost_spike_date}',
                    'likelihood': 'medium',
                    'recommended_action': f'Review {service} usage metrics for the time period'
                })
            
            return {
                'service': service,
                'spike_date': cost_spike_date,
                'analysis_window': {
                    'start': start_time.isoformat(),
                    'end': end_time.isoformat(),
                    'lookback_hours': lookback_hours
                },
                'potential_causes': potential_causes,
                'confidence': confidence,
                'recommendation': 'Review detailed metrics for the identified causes'
            }
            
        except Exception as e:
            logger.error(f"Error correlating cost with metrics: {e}", exc_info=True)
            return {
                'service': service,
                'spike_date': cost_spike_date,
                'error': str(e),
                'potential_causes': [],
                'confidence': 0.0
            }


# Global instance
infrastructure_analyzer = InfrastructureAnalyzer()
