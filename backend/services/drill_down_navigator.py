"""
Drill-Down Navigator Service
Provides OLAP-style dimensional navigation for cost analysis.
"""

import structlog
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

logger = structlog.get_logger(__name__)


class DrillDownNavigator:
    """
    OLAP-style drill-down navigation for multi-dimensional cost analysis.
    
    Features:
    - Dimensional hierarchy definition per service
    - Drill-down path tracking
    - Breadcrumb trail generation
    - Dynamic query generation for each drill level
    """
    
    def __init__(self):
        """Initialize drill-down navigator with service hierarchies."""
        self.dimension_hierarchies = self._build_dimension_hierarchies()
    
    def _build_dimension_hierarchies(self) -> Dict[str, List[str]]:
        """
        Define dimensional hierarchies for each AWS service.
        
        Returns:
            Dict mapping service names to their drill-down dimension lists
        """
        return {
            'CloudWatch': [
                'service',           # Level 0: Service level
                'usage_type',        # Level 1: DataProcessing-Bytes, PutLogEvents, GetMetricData, etc.
                'operation',         # Level 2: API operations
                'region'             # Level 3: Regional breakdown
            ],
            'EC2': [
                'service',           # Level 0: Service level
                'instance_type',     # Level 1: m5.large, c5.xlarge, etc.
                'instance_family',   # Level 2: m5, c5, r5, t3, etc.
                'platform',          # Level 3: Linux, Windows, etc.
                'region'             # Level 4: Regional breakdown
            ],
            'S3': [
                'service',           # Level 0: Service level
                'storage_class',     # Level 1: Standard, IA, Glacier, etc.
                'operation',         # Level 2: PUT, GET, DELETE, etc.
                'region'             # Level 3: Regional breakdown
            ],
            'Lambda': [
                'service',           # Level 0: Service level
                'function_name',     # Level 1: Specific functions
                'memory_size',       # Level 2: Memory configuration
                'region'             # Level 3: Regional breakdown
            ],
            'RDS': [
                'service',           # Level 0: Service level
                'database_engine',   # Level 1: MySQL, PostgreSQL, etc.
                'instance_type',     # Level 2: db.t3.micro, db.m5.large, etc.
                'region'             # Level 3: Regional breakdown
            ],
            'Default': [
                'service',           # Level 0: Service level
                'usage_type',        # Level 1: Usage type
                'operation',         # Level 2: Operation/API call
                'region'             # Level 3: Regional breakdown
            ]
        }
    
    def get_drill_options(
        self,
        current_level: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get available drill-down options from current aggregation level.
        
        Args:
            current_level: Dict with current drill state:
                {
                    'service': 'CloudWatch',
                    'drill_depth': 0,
                    'current_dimension': 'service',
                    'filters': {}
                }
        
        Returns:
            List of drill option dicts with dimension, description, and granularity
        """
        service = current_level.get('service', 'Default')
        drill_depth = current_level.get('drill_depth', 0)
        
        # Get hierarchy for this service
        hierarchy = self.dimension_hierarchies.get(service, self.dimension_hierarchies['Default'])
        
        # Get available next dimensions
        drill_options = []
        
        if drill_depth < len(hierarchy) - 1:
            next_dimension = hierarchy[drill_depth + 1]
            
            # Build drill option based on dimension
            option = {
                'dimension': next_dimension,
                'drill_into': self._get_dimension_display_name(next_dimension),
                'expected_granularity': self._get_granularity_description(next_dimension, service),
                'drill_depth': drill_depth + 1
            }
            drill_options.append(option)
        
        # Also offer alternative dimensions at same level
        alternative_dims = self._get_alternative_dimensions(service, drill_depth)
        for alt_dim in alternative_dims:
            drill_options.append({
                'dimension': alt_dim,
                'drill_into': self._get_dimension_display_name(alt_dim),
                'expected_granularity': self._get_granularity_description(alt_dim, service),
                'drill_depth': drill_depth + 1,
                'is_alternative': True
            })
        
        return drill_options
    
    def _get_dimension_display_name(self, dimension: str) -> str:
        """Convert dimension key to human-readable name."""
        display_names = {
            'service': 'Service',
            'cost_category': 'Cost Category',
            'usage_type': 'Usage Type',
            'region': 'Region',
            'instance_type': 'Instance Type',
            'instance_family': 'Instance Family',
            'platform': 'Platform',
            'storage_class': 'Storage Class',
            'operation': 'Operation',
            'function_name': 'Function Name',
            'memory_size': 'Memory Size',
            'database_engine': 'Database Engine',
            'account': 'Account',
            'cost_center': 'Cost Center'
        }
        return display_names.get(dimension, dimension.replace('_', ' ').title())
    
    def _get_granularity_description(self, dimension: str, service: str) -> str:
        """Get description of what drilling into this dimension reveals."""
        descriptions = {
            'CloudWatch': {
                'usage_type': 'Detailed usage types (DataProcessing-Bytes, PutLogEvents, GetMetricData, etc.)',
                'operation': 'API operations (PutLogEvents, GetMetricStatistics, etc.)',
                'region': 'Regional cost distribution'
            },
            'EC2': {
                'instance_type': 'Cost by instance type (m5.large, c5.xlarge, etc.)',
                'instance_family': 'Cost by instance family (m5, c5, r5, t3, etc.)',
                'platform': 'Cost by platform (Linux, Windows, RHEL)',
                'region': 'Regional cost distribution'
            },
            'S3': {
                'storage_class': 'Cost by storage class (Standard, IA, Glacier)',
                'operation': 'Cost by operation (PUT, GET, DELETE, LIST)',
                'region': 'Regional cost distribution'
            },
            'Lambda': {
                'function_name': 'Cost per Lambda function',
                'memory_size': 'Cost by memory configuration',
                'region': 'Regional cost distribution'
            },
            'RDS': {
                'database_engine': 'Cost by engine (MySQL, PostgreSQL, Aurora)',
                'instance_type': 'Cost by instance type',
                'region': 'Regional cost distribution'
            }
        }
        
        service_descriptions = descriptions.get(service, {})
        return service_descriptions.get(dimension, f'Breakdown by {self._get_dimension_display_name(dimension)}')
    
    def _get_alternative_dimensions(self, service: str, current_depth: int) -> List[str]:
        """Get alternative drill-down dimensions at current level."""
        # Common alternative dimensions
        alternatives = {
            1: ['account', 'region', 'usage_type'],
            2: ['region', 'operation'],
            3: ['account']
        }
        
        current_hierarchy = self.dimension_hierarchies.get(service, self.dimension_hierarchies['Default'])
        current_dims = set(current_hierarchy[:current_depth + 1])
        
        # Return alternatives not already in path
        return [dim for dim in alternatives.get(current_depth, []) if dim not in current_dims]
    
    def execute_drill_down(
        self,
        current_aggregation: Dict[str, Any],
        drill_dimension: str
    ) -> Dict[str, Any]:
        """
        Execute drill-down to next level of dimension hierarchy.
        
        Args:
            current_aggregation: Current drill state with filters and context
            drill_dimension: Dimension to drill into
        
        Returns:
            Dict with:
                - aggregation_data: Placeholder for actual Athena query results
                - drill_path: Updated drill path
                - next_drill_options: Available next drill-downs
                - query_metadata: Information about the drill-down query
        """
        service = current_aggregation.get('service', 'Default')
        current_filters = current_aggregation.get('filters', {})
        drill_depth = current_aggregation.get('drill_depth', 0)
        drill_path = current_aggregation.get('drill_path', [])
        
        # Add dimension to drill path
        new_drill_path = drill_path + [drill_dimension]
        new_depth = drill_depth + 1
        
        # Build new aggregation state
        new_state = {
            'service': service,
            'drill_depth': new_depth,
            'current_dimension': drill_dimension,
            'drill_path': new_drill_path,
            'filters': current_filters.copy()
        }
        
        # Generate query structure (actual Athena query would be built elsewhere)
        query_structure = {
            'group_by': drill_dimension,
            'filters': current_filters,
            'aggregations': ['SUM(line_item_unblended_cost) as total_cost'],
            'order_by': 'total_cost DESC'
        }
        
        # Get next drill options
        next_options = self.get_drill_options(new_state)
        
        return {
            'drill_state': new_state,
            'query_structure': query_structure,
            'next_drill_options': next_options,
            'breadcrumb_trail': self.build_breadcrumb_trail(new_drill_path),
            'query_metadata': {
                'dimension': drill_dimension,
                'depth': new_depth,
                'granularity': self._get_granularity_description(drill_dimension, service)
            }
        }
    
    def navigate_drill_path(
        self,
        start_path: List[str],
        target_path: List[str]
    ) -> Dict[str, Any]:
        """
        Navigate from one drill level to another (back up or different branch).
        
        Args:
            start_path: Current drill path
            target_path: Desired drill path
        
        Returns:
            Dict with navigation result and new state
        """
        # Find common prefix
        common_prefix = []
        for i in range(min(len(start_path), len(target_path))):
            if start_path[i] == target_path[i]:
                common_prefix.append(start_path[i])
            else:
                break
        
        # Determine navigation type
        if len(target_path) < len(start_path):
            navigation_type = 'roll_up'
            levels_changed = len(start_path) - len(target_path)
        elif len(target_path) > len(start_path):
            navigation_type = 'drill_down'
            levels_changed = len(target_path) - len(start_path)
        else:
            navigation_type = 'pivot'
            levels_changed = len(start_path) - len(common_prefix)
        
        return {
            'navigation_type': navigation_type,
            'levels_changed': levels_changed,
            'new_path': target_path,
            'common_prefix': common_prefix,
            'action_description': self._get_navigation_description(navigation_type, start_path, target_path)
        }
    
    def _get_navigation_description(
        self,
        navigation_type: str,
        start_path: List[str],
        target_path: List[str]
    ) -> str:
        """Generate human-readable description of navigation action."""
        if navigation_type == 'roll_up':
            return f"Rolling up from {' → '.join(start_path)} to {' → '.join(target_path)}"
        elif navigation_type == 'drill_down':
            new_dims = target_path[len(start_path):]
            return f"Drilling down into {' → '.join(new_dims)}"
        else:
            return f"Pivoting from {start_path[-1]} to {target_path[-1]}"
    
    def build_breadcrumb_trail(self, drill_history: List[str]) -> str:
        """
        Create user-friendly breadcrumb trail from drill history.
        
        Args:
            drill_history: List of dimensions in drill path
        
        Returns:
            Breadcrumb string (e.g., "Services > CloudWatch > Logs > us-east-1")
        """
        if not drill_history:
            return "All Services"
        
        breadcrumbs = [self._get_dimension_display_name(dim) for dim in drill_history]
        return " > ".join(breadcrumbs)
    
    def get_dimension_hierarchy(self, service: str) -> Dict[str, Any]:
        """
        Get hierarchical dimension structure for a service.
        
        Args:
            service: AWS service name
        
        Returns:
            Dict with hierarchy levels and descriptions
        """
        hierarchy = self.dimension_hierarchies.get(service, self.dimension_hierarchies['Default'])
        
        return {
            'service': service,
            'levels': [
                {
                    'level': i,
                    'dimension': dim,
                    'display_name': self._get_dimension_display_name(dim),
                    'description': self._get_granularity_description(dim, service)
                }
                for i, dim in enumerate(hierarchy)
            ],
            'max_depth': len(hierarchy)
        }
    
    def suggest_drill_path(
        self,
        service: str,
        user_query: str
    ) -> Dict[str, Any]:
        """
        Suggest appropriate drill path based on user query intent.
        
        Args:
            service: AWS service name
            user_query: User's natural language query
        
        Returns:
            Dict with suggested drill path and reasoning
        """
        query_lower = user_query.lower()
        
        # Detect drill intent from query
        if 'region' in query_lower or 'regional' in query_lower:
            suggested_dimension = 'region'
            reasoning = "User requested regional breakdown"
        elif 'account' in query_lower:
            suggested_dimension = 'account'
            reasoning = "User requested account-level breakdown"
        elif service == 'CloudWatch':
            if 'log' in query_lower or 'operation' in query_lower or 'api' in query_lower:
                suggested_dimension = 'operation'
                reasoning = "CloudWatch API operation analysis"
            else:
                suggested_dimension = 'usage_type'
                reasoning = "Detailed CloudWatch usage type breakdown (Logs, Metrics, Alarms, etc.)"
        elif service == 'EC2':
            if 'instance type' in query_lower or 'instance' in query_lower:
                suggested_dimension = 'instance_type'
                reasoning = "EC2 instance type analysis"
            else:
                suggested_dimension = 'instance_family'
                reasoning = "EC2 instance family comparison"
        elif service == 'S3':
            if 'storage class' in query_lower or 'tier' in query_lower:
                suggested_dimension = 'storage_class'
                reasoning = "S3 storage class analysis"
            else:
                suggested_dimension = 'operation'
                reasoning = "S3 operation cost breakdown"
        else:
            suggested_dimension = 'usage_type'
            reasoning = "Default usage type breakdown"
        
        return {
            'suggested_dimension': suggested_dimension,
            'display_name': self._get_dimension_display_name(suggested_dimension),
            'reasoning': reasoning,
            'full_hierarchy': self.get_dimension_hierarchy(service)
        }


# Global instance
drill_down_navigator = DrillDownNavigator()
