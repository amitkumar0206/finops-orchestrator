"""IaC generation workflow endpoints for greenfield template generation."""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from backend.config.settings import get_settings
from backend.services.demo_identity_store import get_demo_identity_store, estimate_text_tokens
from backend.services.request_context import RequestContext, get_context_from_request
from backend.services.iac_blueprint_generator import iac_blueprint_generator_service

router = APIRouter(prefix="/iac-generate", tags=["IaC Generate"])
settings = get_settings()


def get_request_context(request: Request) -> RequestContext:
    context = get_context_from_request(request)
    if context is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return context


OutputFormat = Literal["terraform", "cloudformation"]


class GenerateFromTextRequest(BaseModel):
    requirements: str = Field(min_length=10, max_length=12000)
    output_format: OutputFormat = "terraform"
    region: str = Field(default="us-east-1", min_length=3, max_length=30)
    environment: str = Field(default="development", min_length=2, max_length=30)


class GenerateFromServicesRequest(BaseModel):
    services: List[str] = Field(min_length=1, max_length=30)
    output_format: OutputFormat = "terraform"
    region: str = Field(default="us-east-1", min_length=3, max_length=30)
    environment: str = Field(default="development", min_length=2, max_length=30)


class GenerateWorkflowResponse(BaseModel):
    mode: Literal["text", "services", "diagram"]
    summary: str
    assumptions: List[str]
    selected_services: List[str]
    output_format: OutputFormat
    generated_template: str
    alternate_template: str
    next_steps: List[str]
    diagram_notes: Optional[str] = None


@router.post("/start-from-text", response_model=GenerateWorkflowResponse)
async def start_from_text(
    payload: GenerateFromTextRequest,
    context: RequestContext = Depends(get_request_context),
):
    try:
        result = iac_blueprint_generator_service.generate_from_text(
            requirements=payload.requirements,
            output_format=payload.output_format,
            region=payload.region,
            environment=payload.environment,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Generation failed: {err}") from err

    if settings.config_demo_auth_enabled:
        await get_demo_identity_store().record_feature_usage(
            str(context.user_id),
            feature="generate",
            tokens_used=estimate_text_tokens(payload.requirements) + estimate_text_tokens(result.generated_template),
            details={
                "mode": "text",
                "output_format": payload.output_format,
            },
        )

    return GenerateWorkflowResponse(
        mode="text",
        summary=result.summary,
        assumptions=result.assumptions,
        selected_services=result.selected_services,
        output_format=payload.output_format,
        generated_template=result.generated_template,
        alternate_template=result.alternate_template,
        next_steps=result.next_steps,
    )


@router.post("/start-from-services", response_model=GenerateWorkflowResponse)
async def start_from_services(
    payload: GenerateFromServicesRequest,
    context: RequestContext = Depends(get_request_context),
):
    try:
        result = iac_blueprint_generator_service.generate_from_services(
            services=payload.services,
            output_format=payload.output_format,
            region=payload.region,
            environment=payload.environment,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Generation failed: {err}") from err

    if settings.config_demo_auth_enabled:
        await get_demo_identity_store().record_feature_usage(
            str(context.user_id),
            feature="generate",
            tokens_used=estimate_text_tokens(" ".join(payload.services)) + estimate_text_tokens(result.generated_template),
            details={
                "mode": "services",
                "output_format": payload.output_format,
                "service_count": len(payload.services),
            },
        )

    return GenerateWorkflowResponse(
        mode="services",
        summary=result.summary,
        assumptions=result.assumptions,
        selected_services=result.selected_services,
        output_format=payload.output_format,
        generated_template=result.generated_template,
        alternate_template=result.alternate_template,
        next_steps=result.next_steps,
    )


@router.post("/start-from-diagram", response_model=GenerateWorkflowResponse)
async def start_from_diagram(
    diagram: UploadFile = File(...),
    output_format: OutputFormat = Form("terraform"),
    region: str = Form("us-east-1"),
    environment: str = Form("development"),
    notes: str = Form(""),
    context: RequestContext = Depends(get_request_context),
):
    if not diagram.filename:
        raise HTTPException(status_code=400, detail="diagram filename is required")

    if diagram.content_type and not diagram.content_type.startswith(("image/", "application/pdf")):
        raise HTTPException(status_code=400, detail="diagram must be an image or PDF file")

    try:
        content = await diagram.read()
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Failed to read diagram: {err}") from err

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="diagram exceeds 10MB limit")

    try:
        result = iac_blueprint_generator_service.generate_from_diagram(
            filename=diagram.filename,
            content_type=diagram.content_type or "",
            notes=notes,
            output_format=output_format,
            region=region,
            environment=environment,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Generation failed: {err}") from err

    if settings.config_demo_auth_enabled:
        await get_demo_identity_store().record_feature_usage(
            str(context.user_id),
            feature="generate",
            tokens_used=estimate_text_tokens(notes) + estimate_text_tokens(result.generated_template),
            details={
                "mode": "diagram",
                "output_format": output_format,
                "filename": diagram.filename,
            },
        )

    return GenerateWorkflowResponse(
        mode="diagram",
        summary=result.summary,
        assumptions=result.assumptions,
        selected_services=result.selected_services,
        output_format=output_format,
        generated_template=result.generated_template,
        alternate_template=result.alternate_template,
        next_steps=result.next_steps,
        diagram_notes=f"Processed diagram: {diagram.filename}",
    )
