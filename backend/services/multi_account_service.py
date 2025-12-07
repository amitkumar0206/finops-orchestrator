"""
Multi-Account Cost Management Service
Handles cross-account access, cost aggregation, and account management
"""

from typing import List, Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError
import structlog
from datetime import datetime

from backend.services.database import DatabaseService

logger = structlog.get_logger(__name__)


class MultiAccountService:
    """Service for managing multiple AWS accounts"""
    
    def __init__(self):
        self.db = DatabaseService()
        self.sts_client = boto3.client('sts')
    
    async def register_account(
        self,
        account_id: str,
        account_name: str,
        role_arn: str,
        created_by: str,
        account_email: Optional[str] = None,
        environment: Optional[str] = None,
        business_unit: Optional[str] = None,
        cost_center: Optional[str] = None,
        external_id: Optional[str] = None,
        cur_database: Optional[str] = None,
        cur_table: Optional[str] = None,
        region: str = 'us-east-1'
    ) -> Dict[str, Any]:
        """Register a new AWS account for cost tracking"""
        
        # Validate account access
        validation_result = await self._validate_account_access(
            role_arn, external_id, account_id
        )
        
        if not validation_result['success']:
            raise ValueError(f"Account validation failed: {validation_result['error']}")
        
        query = """
            INSERT INTO aws_accounts (
                account_id, account_name, account_email, environment,
                business_unit, cost_center, role_arn, external_id,
                cur_database, cur_table, region, status, created_by,
                last_validated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW()
            )
            RETURNING id, account_id, account_name, status
        """
        
        result = await self.db.execute(
            query,
            account_id, account_name, account_email, environment,
            business_unit, cost_center, role_arn, external_id,
            cur_database, cur_table, region, 'ACTIVE', created_by
        )
        
        logger.info(
            "account_registered",
            account_id=account_id,
            account_name=account_name,
            business_unit=business_unit
        )
        
        return result
    
    async def _validate_account_access(
        self,
        role_arn: str,
        external_id: Optional[str],
        account_id: str
    ) -> Dict[str, Any]:
        """Validate that we can assume the role in the target account"""
        
        try:
            assume_role_params = {
                'RoleArn': role_arn,
                'RoleSessionName': 'FinOps-Validation',
                'DurationSeconds': 900
            }
            
            if external_id:
                assume_role_params['ExternalId'] = external_id
            
            response = self.sts_client.assume_role(**assume_role_params)
            
            # Verify the account ID matches
            assumed_account_id = response['AssumedRoleUser']['Arn'].split(':')[4]
            if assumed_account_id != account_id:
                return {
                    'success': False,
                    'error': f"Account ID mismatch: expected {account_id}, got {assumed_account_id}"
                }
            
            logger.info(
                "account_validation_successful",
                account_id=account_id,
                role_arn=role_arn
            )
            
            return {'success': True, 'credentials': response['Credentials']}
            
        except ClientError as e:
            logger.error(
                "account_validation_failed",
                account_id=account_id,
                role_arn=role_arn,
                error=str(e)
            )
            return {'success': False, 'error': str(e)}
    
    async def get_account_credentials(self, account_id: str) -> Dict[str, Any]:
        """Get temporary credentials for an account"""
        
        query = """
            SELECT role_arn, external_id, status
            FROM aws_accounts
            WHERE account_id = $1
        """
        account = await self.db.fetch_one(query, account_id)
        
        if not account:
            raise ValueError(f"Account {account_id} not found")
        
        if account['status'] != 'ACTIVE':
            raise ValueError(f"Account {account_id} is not active")
        
        validation = await self._validate_account_access(
            account['role_arn'],
            account['external_id'],
            account_id
        )
        
        if not validation['success']:
            # Update account status to ERROR
            await self._update_account_status(account_id, 'ERROR', validation['error'])
            raise ValueError(f"Failed to assume role: {validation['error']}")
        
        return validation['credentials']
    
    async def get_athena_client_for_account(self, account_id: str):
        """Get an Athena client for a specific account"""
        
        credentials = await self.get_account_credentials(account_id)
        
        return boto3.client(
            'athena',
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
    
    async def aggregate_costs_across_accounts(
        self,
        account_ids: Optional[List[str]],
        start_date: str,
        end_date: str,
        group_by: str = 'account'
    ) -> Dict[str, Any]:
        """Aggregate costs across multiple accounts"""
        
        # Get all active accounts if no specific IDs provided
        if not account_ids:
            query = "SELECT account_id FROM aws_accounts WHERE status = 'ACTIVE'"
            accounts = await self.db.fetch_all(query)
            account_ids = [acc['account_id'] for acc in accounts]
        
        logger.info(
            "aggregating_costs",
            account_count=len(account_ids),
            start_date=start_date,
            end_date=end_date
        )
        
        aggregated_results = []
        
        for account_id in account_ids:
            try:
                # Get cost data for this account
                cost_data = await self._query_account_costs(
                    account_id, start_date, end_date, group_by
                )
                aggregated_results.extend(cost_data)
            except Exception as e:
                logger.error(
                    "account_cost_query_failed",
                    account_id=account_id,
                    error=str(e)
                )
        
        # Aggregate results
        return self._aggregate_cost_data(aggregated_results, group_by)
    
    async def _query_account_costs(
        self,
        account_id: str,
        start_date: str,
        end_date: str,
        group_by: str
    ) -> List[Dict[str, Any]]:
        """Query costs for a specific account"""
        
        # Get account configuration
        query = "SELECT cur_database, cur_table FROM aws_accounts WHERE account_id = $1"
        account = await self.db.fetch_one(query, account_id)
        
        if not account or not account['cur_database']:
            logger.warning("account_missing_cur_config", account_id=account_id)
            return []
        
        # Get Athena client for this account
        athena_client = await self.get_athena_client_for_account(account_id)
        
        # Build query based on group_by
        athena_query = self._build_aggregation_query(
            account['cur_database'],
            account['cur_table'],
            start_date,
            end_date,
            group_by,
            account_id
        )
        
        # Execute query (simplified - would use actual Athena executor)
        # results = await athena_executor.execute_query(athena_query, athena_client)
        
        return []  # Placeholder
    
    def _build_aggregation_query(
        self,
        database: str,
        table: str,
        start_date: str,
        end_date: str,
        group_by: str,
        account_id: str
    ) -> str:
        """Build Athena query for cost aggregation"""
        
        group_clause = {
            'account': f"'{account_id}' as account_id",
            'service': "line_item_product_code as service",
            'region': "product_region as region",
            'account_service': f"'{account_id}' as account_id, line_item_product_code as service"
        }.get(group_by, f"'{account_id}' as account_id")
        
        return f"""
            SELECT
                {group_clause},
                SUM(line_item_unblended_cost) as total_cost,
                DATE_FORMAT(line_item_usage_start_date, '%Y-%m-%d') as usage_date
            FROM {database}.{table}
            WHERE line_item_usage_start_date >= DATE '{start_date}'
            AND line_item_usage_start_date < DATE '{end_date}'
            GROUP BY {group_clause.split(' as ')[0]}, DATE_FORMAT(line_item_usage_start_date, '%Y-%m-%d')
            ORDER BY usage_date, total_cost DESC
        """
    
    def _aggregate_cost_data(
        self,
        results: List[Dict[str, Any]],
        group_by: str
    ) -> Dict[str, Any]:
        """Aggregate cost data from multiple accounts"""
        
        # Group and sum costs
        aggregated = {}
        total_cost = 0
        
        for row in results:
            key = row.get(group_by, 'unknown')
            if key not in aggregated:
                aggregated[key] = {'cost': 0, 'details': []}
            
            aggregated[key]['cost'] += row.get('total_cost', 0)
            aggregated[key]['details'].append(row)
            total_cost += row.get('total_cost', 0)
        
        return {
            'total_cost': total_cost,
            'breakdown': aggregated,
            'account_count': len(set(r.get('account_id') for r in results))
        }
    
    async def _update_account_status(
        self,
        account_id: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """Update account status"""
        query = """
            UPDATE aws_accounts
            SET status = $1,
                validation_error = $2,
                updated_at = NOW()
            WHERE account_id = $3
        """
        await self.db.execute(query, status, error_message, account_id)
    
    async def grant_account_access(
        self,
        account_id: str,
        user_email: str,
        access_level: str,
        granted_by: str,
        expires_at: Optional[datetime] = None
    ):
        """Grant user access to an account"""
        
        query = """
            SELECT id FROM aws_accounts WHERE account_id = $1
        """
        account = await self.db.fetch_one(query, account_id)
        
        if not account:
            raise ValueError(f"Account {account_id} not found")
        
        query = """
            INSERT INTO account_permissions (
                account_id, user_email, access_level, granted_by, expires_at
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (account_id, user_email)
            DO UPDATE SET
                access_level = $3,
                granted_by = $4,
                expires_at = $5,
                granted_at = NOW()
        """
        
        await self.db.execute(
            query,
            account['id'],
            user_email,
            access_level,
            granted_by,
            expires_at
        )
        
        logger.info(
            "account_access_granted",
            account_id=account_id,
            user_email=user_email,
            access_level=access_level
        )
    
    async def list_user_accounts(
        self,
        user_email: str,
        include_all: bool = False
    ) -> List[Dict[str, Any]]:
        """List accounts accessible to a user"""
        
        if include_all:
            # Admin can see all accounts
            query = """
                SELECT account_id, account_name, environment, business_unit, status
                FROM aws_accounts
                WHERE status != 'INACTIVE'
                ORDER BY account_name
            """
            return await self.db.fetch_all(query)
        
        # Normal users see only permitted accounts
        query = """
            SELECT a.account_id, a.account_name, a.environment, a.business_unit,
                   a.status, p.access_level
            FROM aws_accounts a
            JOIN account_permissions p ON a.id = p.account_id
            WHERE p.user_email = $1
            AND (p.expires_at IS NULL OR p.expires_at > NOW())
            AND a.status = 'ACTIVE'
            ORDER BY a.account_name
        """
        return await self.db.fetch_all(query, user_email)


# Service instance
multi_account_service = MultiAccountService()
