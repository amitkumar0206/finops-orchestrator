"""
Saved Views API endpoints
Manages saved views for multi-tenant account scoping.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
import structlog

from backend.services.saved_views_service import saved_views_service
from backend.services.audit_log_service import audit_log_service
from backend.services.request_context import require_context, RequestContext

router = APIRouter()
logger = structlog.get_logger(__name__)


# Request/Response Models
class CreateSavedViewRequest(BaseModel):
    """Request model for creating a saved view"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    account_ids: List[UUID] = Field(..., min_items=1)
    default_time_range: Optional[dict] = None
    filters: Optional[dict] = None
    is_default: bool = False
    is_personal: bool = False
    shared_with_users: Optional[List[UUID]] = None
    shared_with_roles: Optional[List[UUID]] = None
    expires_at: Optional[datetime] = None


class UpdateSavedViewRequest(BaseModel):
    """Request model for updating a saved view"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    account_ids: Optional[List[UUID]] = None
    default_time_range: Optional[dict] = None
    filters: Optional[dict] = None
    is_default: Optional[bool] = None
    shared_with_users: Optional[List[UUID]] = None
    shared_with_roles: Optional[List[UUID]] = None
    expires_at: Optional[datetime] = None


class SavedViewResponse(BaseModel):
    """Response model for saved view"""
    id: str
    name: str
    description: Optional[str]
    account_ids: List[str]
    account_count: int
    default_time_range: Optional[dict]
    filters: Optional[dict]
    is_default: bool
    is_personal: bool
    expires_at: Optional[str]
    created_at: Optional[str]
    created_by: Optional[str]
    created_by_email: Optional[str]


async def get_request_context(request: Request) -> RequestContext:
    """Dependency to get request context"""
    return require_context(request)


@router.post("/views", response_model=SavedViewResponse)
async def create_saved_view(
    payload: CreateSavedViewRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Create a new saved view"""
    try:
        result = await saved_views_service.create_saved_view(
            context=context,
            name=payload.name,
            account_ids=payload.account_ids,
            description=payload.description,
            default_time_range=payload.default_time_range,
            filters=payload.filters,
            is_default=payload.is_default,
            is_personal=payload.is_personal,
            shared_with_users=payload.shared_with_users,
            shared_with_roles=payload.shared_with_roles,
            expires_at=payload.expires_at,
        )

        # Audit log
        await audit_log_service.log_saved_view_created(
            context=context,
            view_id=UUID(result['id']),
            view_name=payload.name,
            account_count=len(payload.account_ids),
            request=request
        )

        return SavedViewResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("failed_to_create_saved_view", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create saved view")


@router.get("/views", response_model=List[SavedViewResponse])
async def list_saved_views(
    request: Request,
    include_personal: bool = True,
    include_shared: bool = True,
    context: RequestContext = Depends(get_request_context)
):
    """List all saved views accessible by the user"""
    try:
        views = await saved_views_service.list_saved_views(
            context=context,
            include_personal=include_personal,
            include_shared=include_shared,
        )
        return [SavedViewResponse(**v) for v in views]

    except Exception as e:
        logger.error("failed_to_list_saved_views", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list saved views")


@router.get("/views/active")
async def get_active_view(
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Get the user's currently active view"""
    try:
        view = await saved_views_service.get_active_view(context=context)
        if view:
            return SavedViewResponse(**view)
        return {"active_view": None, "message": "No active view set"}

    except Exception as e:
        logger.error("failed_to_get_active_view", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get active view")


@router.put("/views/active/{view_id}")
async def set_active_view(
    view_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Set the user's active view"""
    try:
        # Get old view for audit
        old_view = await saved_views_service.get_active_view(context=context)
        old_view_id = UUID(old_view['id']) if old_view else None

        # Set new view
        await saved_views_service.set_active_view(context=context, view_id=view_id)

        # Get new view details
        new_view = await saved_views_service.get_saved_view(context=context, view_id=view_id)

        # Audit log
        await audit_log_service.log_active_view_changed(
            context=context,
            old_view_id=old_view_id,
            new_view_id=view_id,
            new_view_name=new_view['name'] if new_view else None,
            request=request
        )

        return {"success": True, "active_view": SavedViewResponse(**new_view) if new_view else None}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("failed_to_set_active_view", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to set active view")


@router.delete("/views/active")
async def clear_active_view(
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Clear the user's active view (use org default)"""
    try:
        # Get old view for audit
        old_view = await saved_views_service.get_active_view(context=context)
        old_view_id = UUID(old_view['id']) if old_view else None

        await saved_views_service.set_active_view(context=context, view_id=None)

        # Audit log
        await audit_log_service.log_active_view_changed(
            context=context,
            old_view_id=old_view_id,
            new_view_id=None,
            new_view_name=None,
            request=request
        )

        return {"success": True, "message": "Active view cleared"}

    except Exception as e:
        logger.error("failed_to_clear_active_view", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear active view")


@router.get("/views/{view_id}", response_model=SavedViewResponse)
async def get_saved_view(
    view_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Get a specific saved view by ID"""
    try:
        view = await saved_views_service.get_saved_view(context=context, view_id=view_id)
        if not view:
            raise HTTPException(status_code=404, detail="Saved view not found")
        return SavedViewResponse(**view)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("failed_to_get_saved_view", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get saved view")


@router.put("/views/{view_id}", response_model=SavedViewResponse)
async def update_saved_view(
    view_id: UUID,
    payload: UpdateSavedViewRequest,
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Update an existing saved view"""
    try:
        # Get changes for audit
        changes = {k: v for k, v in payload.dict().items() if v is not None}

        result = await saved_views_service.update_saved_view(
            context=context,
            view_id=view_id,
            **changes
        )

        # Audit log
        await audit_log_service.log_saved_view_updated(
            context=context,
            view_id=view_id,
            view_name=result.get('name', 'Unknown'),
            changes=changes,
            request=request
        )

        return SavedViewResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("failed_to_update_saved_view", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update saved view")


@router.delete("/views/{view_id}")
async def delete_saved_view(
    view_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_request_context)
):
    """Delete a saved view"""
    try:
        # Get view name for audit
        view = await saved_views_service.get_saved_view(context=context, view_id=view_id)
        if not view:
            raise HTTPException(status_code=404, detail="Saved view not found")

        await saved_views_service.delete_saved_view(context=context, view_id=view_id)

        # Audit log
        await audit_log_service.log_saved_view_deleted(
            context=context,
            view_id=view_id,
            view_name=view['name'],
            request=request
        )

        return {"success": True, "deleted_id": str(view_id)}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("failed_to_delete_saved_view", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete saved view")
