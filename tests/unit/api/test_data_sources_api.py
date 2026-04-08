"""Unit tests for F-001 data-sources API router."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import data_sources
from backend.models.data_sources import (
    DataSourceCapabilitiesResponse,
    DataSourceIngestResponse,
    DataSourceProvider,
    DataSourceRunStatus,
    DataSourceTestResponse,
)
from backend.services.request_context import RequestContext


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(data_sources.router, prefix="/api/v1")
    return a


@pytest.fixture
def context():
    return RequestContext(
        user_id=uuid4(),
        user_email="finops@example.com",
        is_admin=False,
        organization_id=uuid4(),
    )


@pytest.fixture
def client(app, context):
    async def _ctx():
        return context

    app.dependency_overrides[data_sources._get_context] = _ctx
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def service_mock():
    svc = AsyncMock()
    svc.capabilities.return_value = DataSourceCapabilitiesResponse(
        enabled=True,
        providers=[
            DataSourceProvider.AWS_CUR,
            DataSourceProvider.AZURE_EXPORT,
            DataSourceProvider.GCP_BILLING,
            DataSourceProvider.GENERIC_COST,
        ],
        modes=["connected", "advisory_upload"],
        max_upload_size_mb=250,
        max_upload_rows=2_000_000,
        supports_async_ingest=False,
    )
    svc.list_data_sources.return_value = []
    svc.get_data_source.return_value = None
    svc.get_runs.return_value = []
    svc.test_connection.return_value = DataSourceTestResponse(
        success=True,
        provider_type=DataSourceProvider.AWS_CUR,
        checked_at=datetime.now(timezone.utc),
        details={"valid": True},
    )
    svc.ingest.return_value = DataSourceIngestResponse(
        run_id=uuid4(),
        status=DataSourceRunStatus.FAILED,
        records_read=0,
        records_normalized=0,
        validation_errors=["not enabled"],
    )
    svc.upload_and_ingest.return_value = {
        "data_source_id": str(uuid4()),
        "run_id": str(uuid4()),
        "status": "completed",
        "file_name": "azure.csv",
        "file_checksum": "abc",
        "records_read": 10,
        "records_normalized": 3,
        "validation_errors": [],
    }
    return svc


class TestDataSourcesApi:
    def test_capabilities_requires_auth(self, app):
        with TestClient(app) as c:
            resp = c.get("/api/v1/data-sources/capabilities")
        assert resp.status_code == 401

    def test_capabilities_success(self, client, service_mock):
        with patch("backend.api.data_sources.get_data_source_registry_service", return_value=service_mock):
            resp = client.get("/api/v1/data-sources/capabilities")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_capabilities_returns_503_when_database_disabled(self, client):
        with patch.object(data_sources.settings, "database_enabled", False):
            resp = client.get("/api/v1/data-sources/capabilities")
        assert resp.status_code == 503
        assert "PostgreSQL-backed mode" in resp.json()["detail"]

    def test_list_data_sources(self, client, service_mock):
        with patch("backend.api.data_sources.get_data_source_registry_service", return_value=service_mock):
            resp = client.get("/api/v1/data-sources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_ingest_404_on_missing_data_source(self, client, service_mock):
        service_mock.ingest.side_effect = KeyError("missing")
        with patch("backend.api.data_sources.get_data_source_registry_service", return_value=service_mock):
            resp = client.post("/api/v1/data-sources/11111111-1111-1111-1111-111111111111/ingest", json={})
        assert resp.status_code == 404

    def test_upload_400_for_missing_filename(self, client):
        resp = client.post(
            "/api/v1/data-sources/upload",
            data={"data_source_id": str(uuid4())},
            files={"file": ("", b"", "text/plain")},
        )
        assert resp.status_code in (400, 422)
