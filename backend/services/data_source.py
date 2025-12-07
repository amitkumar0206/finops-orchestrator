"""
Abstract data source interface for loose coupling between data layer and business logic.

All data sources (Athena, Cost Explorer, CloudWatch) implement this interface,
allowing the QueryOrchestrator to work with any data source without knowing implementation details.
"""
from abc import ABC, abstractmethod
from typing import Optional
from backend.services.query_spec import QuerySpec
from backend.services.query_result import QueryResult, ResultMetadata
import structlog

logger = structlog.get_logger(__name__)


class DataSource(ABC):
    """
    Abstract base class for all data sources.
    
    This defines the contract that all data sources must implement,
    enabling the orchestrator to work with any data source without coupling.
    """
    
    @abstractmethod
    async def fetch(self, spec: QuerySpec) -> QueryResult:
        """
        Execute a query and return standardized results.
        
        Args:
            spec: Standardized query specification
            
        Returns:
            QueryResult: Standardized result with data and metadata
            
        Raises:
            DataSourceError: If query execution fails critically
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Return the name of this data source (e.g., 'athena', 'cost_explorer')."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this data source is available."""
        pass


class DataSourceError(Exception):
    """Raised when a data source encounters a critical error."""
    
    def __init__(self, message: str, source: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.source = source
        self.original_error = original_error
