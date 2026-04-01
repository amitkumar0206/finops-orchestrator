"""IaC Workbench API endpoints for file analysis, chat, and final template generation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend.config.settings import get_settings
from backend.services.demo_identity_store import get_demo_identity_store, estimate_text_tokens
from backend.services.iac_analysis_service import iac_analysis_service
from backend.services.request_context import RequestContext, get_context_from_request

router = APIRouter(prefix="/iac", tags=["IaC Workbench"])
settings = get_settings()


def get_request_context(request: Request) -> RequestContext:
    context = get_context_from_request(request)
    if context is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return context


class IacAnalyzeResponse(BaseModel):
    analysis_id: str
    filename: str
    format: str
    summary: str
    explanation: str
    pros: List[str]
    cons: List[str]
    cost_analysis: List[Dict[str, Any]]
    improvements: List[str]
    improved_content: str
    file_count: int = 1
    files: List[Dict[str, Any]] = Field(default_factory=list)
    cross_file_analysis: Optional[Dict[str, Any]] = None


class IacChatRequest(BaseModel):
    analysis_id: str
    message: str = Field(min_length=1, max_length=4000)


class IacChatResponse(BaseModel):
    analysis_id: str
    message: str


class IacGenerateRequest(BaseModel):
    analysis_id: str
    goals: Optional[str] = Field(default=None, max_length=4000)


class IacGenerateResponse(BaseModel):
    analysis_id: str
    improved_content: str
    improvements: List[str]


@router.post("/analyze", response_model=IacAnalyzeResponse)
async def analyze_iac_file(
    files: List[UploadFile] = File(...),
    context: RequestContext = Depends(get_request_context),
):
    """Analyze one or more uploaded IaC files and create analysis sessions."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    decoded_files: List[tuple[str, str]] = []
    for file in files:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")

        try:
            content_bytes = await file.read()
        except Exception as err:
            raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {err}") from err

        if len(content_bytes) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"File too large ({file.filename}). Max file size is 2MB.")

        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError as err:
            raise HTTPException(status_code=400, detail=f"File must be valid UTF-8 text ({file.filename})") from err

        decoded_files.append((file.filename, content))

    try:
        result = await iac_analysis_service.analyze_files(
            files=decoded_files,
            owner_user_id=str(context.user_id),
            owner_org_id=str(context.organization_id) if context.organization_id else None,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"IaC analysis failed: {err}") from err

    primary = result["primary"]
    records = result["records"]

    if settings.config_demo_auth_enabled:
        token_estimate = sum(estimate_text_tokens(content) for _, content in decoded_files)
        await get_demo_identity_store().record_feature_usage(
            str(context.user_id),
            feature="analyze",
            tokens_used=token_estimate,
            details={
                "file_count": len(decoded_files),
                "filenames": [filename for filename, _ in decoded_files],
            },
        )

    return IacAnalyzeResponse(
        analysis_id=primary.analysis_id,
        filename=primary.filename,
        format=primary.format,
        summary=primary.summary,
        explanation=primary.explanation,
        pros=primary.pros,
        cons=primary.cons,
        cost_analysis=primary.cost_analysis,
        improvements=primary.improvements,
        improved_content=primary.improved_content,
        file_count=int(result.get("file_count", len(records))),
        files=[
            {
                "analysis_id": record.analysis_id,
                "filename": record.filename,
                "format": record.format,
                "summary": record.summary,
                "explanation": record.explanation,
                "pros": record.pros,
                "cons": record.cons,
                "cost_analysis": record.cost_analysis,
                "improvements": record.improvements,
                "improved_content": record.improved_content,
            }
            for record in records
        ],
        cross_file_analysis=result.get("cross_file_analysis"),
    )


@router.post("/chat", response_model=IacChatResponse)
async def chat_about_iac(
    payload: IacChatRequest,
    context: RequestContext = Depends(get_request_context),
):
    """Ask follow-up questions about a previously analyzed IaC file."""
    try:
        reply = await iac_analysis_service.chat_about_template(
            analysis_id=payload.analysis_id,
            question=payload.message,
            user_id=str(context.user_id),
            org_id=str(context.organization_id) if context.organization_id else None,
        )
        if settings.config_demo_auth_enabled:
            await get_demo_identity_store().record_feature_usage(
                str(context.user_id),
                feature="analyze",
                tokens_used=estimate_text_tokens(payload.message) + estimate_text_tokens(reply),
                details={
                    "analysis_id": payload.analysis_id,
                    "mode": "follow_up_chat",
                },
            )
        return IacChatResponse(analysis_id=payload.analysis_id, message=reply)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"IaC chat failed: {err}") from err


@router.post("/generate", response_model=IacGenerateResponse)
async def generate_final_iac(
    payload: IacGenerateRequest,
    context: RequestContext = Depends(get_request_context),
):
    """Generate a final optimized template revision from analysis + goals."""
    try:
        record = await iac_analysis_service.generate_final_version(
            analysis_id=payload.analysis_id,
            goals=payload.goals,
            user_id=str(context.user_id),
            org_id=str(context.organization_id) if context.organization_id else None,
        )
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"IaC generation failed: {err}") from err

    if settings.config_demo_auth_enabled:
        await get_demo_identity_store().record_feature_usage(
            str(context.user_id),
            feature="analyze",
            tokens_used=estimate_text_tokens(payload.goals or "") + estimate_text_tokens(record.improved_content),
            details={
                "analysis_id": payload.analysis_id,
                "mode": "optimized_revision",
            },
        )

    return IacGenerateResponse(
        analysis_id=record.analysis_id,
        improved_content=record.improved_content,
        improvements=record.improvements,
    )


@router.get("/{analysis_id}/download")
async def download_iac_version(
    analysis_id: str,
    version: str = "improved",
    context: RequestContext = Depends(get_request_context),
):
    """Download original or improved template for a given analysis."""
    try:
        record = iac_analysis_service.assert_owner_access(
            analysis_id,
            user_id=str(context.user_id),
            org_id=str(context.organization_id) if context.organization_id else None,
        )
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err

    selected_version = version.lower().strip()
    if selected_version not in {"improved", "original"}:
        raise HTTPException(status_code=400, detail="version must be 'improved' or 'original'")

    content = record.improved_content if selected_version == "improved" else record.original_content
    base = record.filename.rsplit(".", 1)[0]
    extension = record.filename.rsplit(".", 1)[1] if "." in record.filename else "txt"
    out_filename = f"{base}.{selected_version}.{extension}"

    return PlainTextResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{out_filename}"'},
    )
