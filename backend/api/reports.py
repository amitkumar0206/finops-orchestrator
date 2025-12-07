"""Reports API endpoints"""

from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/")
async def get_reports():
    """Get available reports"""
    return {"reports": [], "timestamp": datetime.utcnow().isoformat()}

@router.post("/generate")
async def generate_report():
    """Generate new report"""
    return {"report_id": "mock-123", "status": "generated"}