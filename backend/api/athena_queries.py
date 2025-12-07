"""
Athena Query API endpoints
Handles Athena SQL query generation, execution, and result export
"""

from typing import Optional
from datetime import datetime, timedelta, date

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
import structlog
import io

from services.athena_query_service import athena_service
from config.settings import get_settings

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()


class AthenaQueryRequest(BaseModel):
    """Request model for Athena query generation"""
    user_query: str = Field(..., description="Natural language query from user")
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    services: Optional[list[str]] = Field(None, description="AWS services to filter")
    execute_query: bool = Field(default=False, description="Execute query immediately")
    export_format: Optional[str] = Field(None, description="Export format: csv or json")


class AthenaQueryResponse(BaseModel):
    """Response model for Athena query"""
    sql_query: str
    description: str
    query_execution_id: Optional[str] = None
    status: Optional[str] = None
    results: Optional[list[dict]] = None
    row_count: Optional[int] = None
    error: Optional[str] = None


@router.post("/generate", response_model=AthenaQueryResponse)
async def generate_athena_query(request: AthenaQueryRequest):
    """
    Generate Athena SQL query based on user's natural language request
    Optionally execute the query and return results
    """
    
    logger.info(
        "Generating Athena query",
        user_query=request.user_query,
        execute=request.execute_query
    )
    
    try:
        # Parse time range
        if request.start_date and request.end_date:
            start_date = date.fromisoformat(request.start_date)
            end_date = date.fromisoformat(request.end_date)
        else:
            # Default to last 30 days
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
        
        time_range = {
            "start_date": start_date,
            "end_date": end_date
        }
        
        # Generate SQL query
        sql_query, description = await athena_service.generate_query_for_user_request(
            user_query=request.user_query,
            time_range=time_range,
            services=request.services
        )
        
        response_data = {
            "sql_query": sql_query,
            "description": description
        }
        
        # Execute query if requested
        if request.execute_query:
            execution_result = await athena_service.execute_query(sql_query)
            
            response_data.update({
                "query_execution_id": execution_result.get("query_execution_id"),
                "status": execution_result.get("status"),
                "results": execution_result.get("results"),
                "row_count": execution_result.get("row_count"),
                "error": execution_result.get("error")
            })
        
        return AthenaQueryResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Error generating Athena query: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate Athena query: {str(e)}"
        )


@router.get("/execute/{query_execution_id}")
async def get_query_results(query_execution_id: str):
    """Get results from a previously executed Athena query"""
    
    try:
        results = await athena_service._get_query_results(query_execution_id)
        
        return {
            "query_execution_id": query_execution_id,
            "results": results,
            "row_count": len(results)
        }
        
    except Exception as e:
        logger.error(f"Error getting query results: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get query results: {str(e)}"
        )


@router.post("/export/csv")
async def export_results_csv(request: AthenaQueryRequest):
    """
    Execute query and export results as CSV file
    """
    
    try:
        # Parse time range
        if request.start_date and request.end_date:
            start_date = date.fromisoformat(request.start_date)
            end_date = date.fromisoformat(request.end_date)
        else:
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
        
        time_range = {
            "start_date": start_date,
            "end_date": end_date
        }
        
        # Generate and execute query
        sql_query, description = await athena_service.generate_query_for_user_request(
            user_query=request.user_query,
            time_range=time_range,
            services=request.services
        )
        
        execution_result = await athena_service.execute_query(sql_query)
        
        if execution_result.get("status") != "success":
            raise HTTPException(
                status_code=500,
                detail=f"Query execution failed: {execution_result.get('error', 'Unknown error')}"
            )
        
        results = execution_result.get("results", [])
        
        # Export to CSV
        csv_content, filename = await athena_service.export_results_to_csv(results)
        
        # Return as downloadable file
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export results: {str(e)}"
        )


@router.post("/export/json")
async def export_results_json(request: AthenaQueryRequest):
    """
    Execute query and export results as JSON file
    """
    
    try:
        # Parse time range
        if request.start_date and request.end_date:
            start_date = date.fromisoformat(request.start_date)
            end_date = date.fromisoformat(request.end_date)
        else:
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
        
        time_range = {
            "start_date": start_date,
            "end_date": end_date
        }
        
        # Generate and execute query
        sql_query, description = await athena_service.generate_query_for_user_request(
            user_query=request.user_query,
            time_range=time_range,
            services=request.services
        )
        
        execution_result = await athena_service.execute_query(sql_query)
        
        if execution_result.get("status") != "success":
            raise HTTPException(
                status_code=500,
                detail=f"Query execution failed: {execution_result.get('error', 'Unknown error')}"
            )
        
        results = execution_result.get("results", [])
        
        # Export to JSON
        json_content, filename = await athena_service.export_results_to_json(results)
        
        # Return as downloadable file
        return Response(
            content=json_content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting to JSON: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export results: {str(e)}"
        )


@router.get("/sample-queries")
async def get_sample_queries():
    """Get sample Athena queries that users can try"""
    
    return {
        "samples": [
            {
                "title": "Top 10 Most Expensive Services",
                "query": "Show me my top 10 most expensive AWS services",
                "description": "Returns the top 10 services by total cost"
            },
            {
                "title": "Daily Cost Breakdown",
                "query": "Show me daily costs for EC2 and S3",
                "description": "Returns daily cost breakdown for specified services"
            },
            {
                "title": "Cost by Region",
                "query": "Show me costs broken down by AWS region",
                "description": "Returns cost distribution across AWS regions"
            },
            {
                "title": "Cost by Account",
                "query": "Show me costs by AWS account",
                "description": "Returns cost breakdown across different AWS accounts"
            },
            {
                "title": "Service Cost Details",
                "query": "Show me detailed breakdown of S3 costs",
                "description": "Returns detailed usage and cost information for a specific service"
            }
        ]
    }
