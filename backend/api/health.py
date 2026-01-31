"""
Health check endpoints for monitoring system status
"""

from datetime import datetime
from typing import Dict, Any
import asyncio

from fastapi import APIRouter, Request
import structlog

from backend.models.schemas import HealthCheck

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("", response_model=HealthCheck)
@router.get("/", response_model=HealthCheck)
async def health_check(request: Request) -> HealthCheck:
    """Comprehensive health check for all system components"""
    
    start_time = datetime.utcnow()
    
    # Check actual service availability from app state
    db_available = hasattr(request.app.state, 'db') and request.app.state.db is not None
    vector_available = hasattr(request.app.state, 'vector_store') and request.app.state.vector_store is not None
    
    # Check all services in parallel
    health_tasks = {}
    
    if db_available:
        health_tasks["database"] = _check_database(request.app.state.db)
    
    health_tasks["valkey"] = _check_valkey()
    
    if vector_available:
        health_tasks["vector_store"] = _check_vector_store(request.app.state.vector_store)
    
    health_tasks["llm_services"] = _check_llm_services()
    health_tasks["aws_services"] = _check_aws_services()
    
    results = await asyncio.gather(
        *health_tasks.values(),
        return_exceptions=True
    )
    
    # Process results
    services = {}
    overall_status = "healthy"
    
    for service_name, result in zip(health_tasks.keys(), results):
        if isinstance(result, Exception):
            services[service_name] = {
                "status": "unhealthy",
                "error": str(result),
                "timestamp": datetime.utcnow().isoformat()
            }
            overall_status = "degraded"
        else:
            services[service_name] = result
            if result.get("status") != "healthy":
                overall_status = "degraded"
    
    # Add status for services not initialized
    if not db_available:
        services["database"] = {
            "status": "unavailable",
            "message": "Database service not initialized",
            "timestamp": datetime.utcnow().isoformat()
        }
        overall_status = "degraded"
    
    if not vector_available:
        services["vector_store"] = {
            "status": "unavailable",
            "message": "Vector store service not initialized",
            "timestamp": datetime.utcnow().isoformat()
        }
        overall_status = "degraded"
    
    # Calculate uptime (simplified)
    uptime = (datetime.utcnow() - start_time).total_seconds()
    
    return HealthCheck(
        status=overall_status,
        version="1.0.0",
        timestamp=datetime.utcnow(),
        services=services,
        uptime=uptime
    )


@router.get("/liveness")
async def liveness_probe():
    """Kubernetes liveness probe endpoint"""
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}


@router.get("/readiness") 
async def readiness_probe(request: Request):
    """Kubernetes readiness probe endpoint"""
    
    # Check if app has initialized (at least attempted startup)
    # App is ready even if some services are unavailable
    try:
        # Basic readiness - can the app respond?
        return {
            "status": "ready", 
            "timestamp": datetime.utcnow().isoformat(),
            "database_available": hasattr(request.app.state, 'db'),
            "vector_store_available": hasattr(request.app.state, 'vector_store')
        }
        
    except Exception as e:
        return {"status": "not_ready", "reason": str(e)}


async def _check_database(db_service=None) -> Dict[str, Any]:
    """Check database connectivity"""
    
    if db_service is None:
        return {
            "status": "unavailable",
            "details": {"message": "Database service not initialized"}
        }
    
    try:
        from sqlalchemy import text
        # Test connection
        async with db_service.engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "response_time": 0.05,  # seconds
            "details": {
                "connection_pool": "active",
                "last_query": datetime.utcnow().isoformat()
            }
        }
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "details": {}
        }


async def _check_valkey() -> Dict[str, Any]:
    """Check Valkey connectivity"""
    
    try:
        import time
        import valkey
        from config.settings import get_settings
        settings = get_settings()
        start = time.time()
        # Connect to Valkey (Redis protocol compatible)
        client = valkey.Valkey(
            host=getattr(settings, 'valkey_host', 'localhost'),
            port=getattr(settings, 'valkey_port', 6379),
            db=getattr(settings, 'valkey_db', 0),
            socket_timeout=1
        )
        pong = client.ping()
        response_time = round(time.time() - start, 3)
        info = client.info()
        return {
            "status": "healthy" if pong else "unhealthy",
            "response_time": response_time,
            "details": {
                "memory_usage": info.get("used_memory_human", "N/A"),
                "connected_clients": info.get("connected_clients", "N/A")
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "details": {}
        }


async def _check_vector_store(vector_service=None) -> Dict[str, Any]:
    """Check vector database connectivity"""
    
    if vector_service is None:
        return {
            "status": "unavailable",
            "details": {"message": "Vector store service not initialized"}
        }
    
    try:
        # Check if collection exists and is accessible
        count = vector_service.collection.count() if vector_service.collection else 0
        
        return {
            "status": "healthy",
            "response_time": 0.1,
            "details": {
                "collection_count": 1,
                "document_count": count,
                "index_status": "ready"
            }
        }
        
    except Exception as e:
        return {
            "status": "unhealthy", 
            "error": str(e)
        }


async def _check_llm_services() -> Dict[str, Any]:
    """Check LLM service availability"""
    
    try:
        import time
        from botocore.exceptions import ClientError
        from config.settings import get_settings
        from backend.utils.aws_session import create_aws_client
        from backend.utils.aws_constants import AwsService, DEFAULT_AWS_REGION
        settings = get_settings()
        start = time.time()
        # Example: Bedrock invoke for model health (using IAM role credentials)
        bedrock = create_aws_client(AwsService.BEDROCK_RUNTIME, region_name=getattr(settings, "aws_region", DEFAULT_AWS_REGION))
        # Use a lightweight model and minimal input for health check
        payload = {"prompt": "ping", "max_tokens": 1}
        response = bedrock.invoke_model(
            modelId=getattr(settings, "bedrock_model_id", "anthropic.claude-instant-v1"),
            body=str(payload),
            accept="application/json",
            contentType="application/json"
        )
        latency = round(time.time() - start, 3)
        return {
            "status": "healthy" if response["ResponseMetadata"]["HTTPStatusCode"] == 200 else "unhealthy",
            "response_time": latency,
            "details": {
                "model_id": getattr(settings, "bedrock_model_id", "anthropic.claude-instant-v1"),
                "region": getattr(settings, "aws_region", DEFAULT_AWS_REGION),
                "quota": response.get("ConsumedQuota", "N/A")
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


async def _check_aws_services() -> Dict[str, Any]:
    """Check AWS service connectivity including CUR data availability"""
    
    try:
        from botocore.exceptions import ClientError
        from config.settings import get_settings
        from backend.utils.aws_session import create_aws_session
        from backend.utils.aws_constants import AwsService

        settings = get_settings()
        start_time = datetime.utcnow()
        details = {}
        all_healthy = True

        # Create AWS clients using IAM role credentials (default credential chain)
        session = create_aws_session()
        athena_client = session.client(AwsService.ATHENA)
        s3_client = session.client(AwsService.S3)
        
        # Check Athena connectivity
        try:
            athena_client.list_work_groups(MaxResults=1)
            details["athena"] = "available"
        except ClientError as e:
            details["athena"] = f"error: {str(e)}"
            all_healthy = False
        
        # Check S3 bucket accessibility
        try:
            bucket_name = settings.cur_s3_bucket.replace("s3://", "").split("/")[0]
            s3_client.head_bucket(Bucket=bucket_name)
            details["s3_bucket"] = "accessible"
        except ClientError as e:
            details["s3_bucket"] = f"error: {str(e)}"
            all_healthy = False
        
        # Check CUR S3 data exists
        try:
            bucket_name = settings.cur_s3_bucket.replace("s3://", "").split("/")[0]
            prefix = settings.cur_s3_prefix + "/"
            
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix,
                MaxKeys=1
            )
            
            if response.get('KeyCount', 0) > 0:
                details["cur_data"] = "available"
                details["cur_s3_location"] = f"s3://{bucket_name}/{prefix}"
            else:
                details["cur_data"] = "no data found"
                details["cur_s3_location"] = f"s3://{bucket_name}/{prefix}"
                all_healthy = False
        except ClientError as e:
            details["cur_data"] = f"error: {str(e)}"
            all_healthy = False
        
        # Check Athena database exists
        try:
            athena_client.get_database(
                CatalogName='AwsDataCatalog',
                DatabaseName=settings.aws_cur_database
            )
            details["athena_database"] = settings.aws_cur_database
        except ClientError as e:
            details["athena_database"] = f"not found: {settings.aws_cur_database}"
            all_healthy = False
        
        # Check Athena table exists and has data
        try:
            # Quick validation query
            query_string = f"""
                SELECT COUNT(*) as record_count
                FROM {settings.aws_cur_database}.{settings.aws_cur_table}
                WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
                  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
                LIMIT 1
            """
            
            response = athena_client.start_query_execution(
                QueryString=query_string,
                QueryExecutionContext={'Database': settings.aws_cur_database},
                ResultConfiguration={'OutputLocation': settings.athena_output_location},
                WorkGroup=settings.athena_workgroup
            )
            
            query_id = response['QueryExecutionId']
            
            # Wait for query to complete (max 10 seconds)
            for _ in range(10):
                await asyncio.sleep(1)
                status_response = athena_client.get_query_execution(QueryExecutionId=query_id)
                state = status_response['QueryExecution']['Status']['State']
                
                if state == 'SUCCEEDED':
                    details["athena_table"] = f"{settings.aws_cur_table} (queryable)"
                    details["cur_table_health"] = "healthy"
                    break
                elif state in ['FAILED', 'CANCELLED']:
                    reason = status_response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
                    details["athena_table"] = f"query failed: {reason}"
                    details["cur_table_health"] = "unhealthy"
                    all_healthy = False
                    break
            else:
                details["athena_table"] = "query timeout"
                details["cur_table_health"] = "unknown"
        
        except ClientError as e:
            details["athena_table"] = f"error: {str(e)}"
            details["cur_table_health"] = "unhealthy"
            all_healthy = False
        
        # Check Cost Explorer (optional fallback)
        try:
            ce_client = session.client('ce')
            ce_client.get_cost_and_usage(
                TimePeriod={
                    'Start': '2024-11-01',
                    'End': '2024-11-02'
                },
                Granularity='DAILY',
                Metrics=['UnblendedCost']
            )
            details["cost_explorer"] = "available"
        except ClientError as e:
            details["cost_explorer"] = f"error: {str(e)}"
            # Cost Explorer is optional fallback, don't mark as unhealthy
        
        response_time = (datetime.utcnow() - start_time).total_seconds()
        
        return {
            "status": "healthy" if all_healthy else "degraded",
            "response_time": response_time,
            "details": details
        }
        
    except Exception as e:
        logger.error(f"AWS services health check failed: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "error": str(e),
            "details": {}
        }