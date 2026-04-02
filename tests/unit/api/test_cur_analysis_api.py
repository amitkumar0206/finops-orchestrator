"""
Tests for backend/api/cur_analysis.py — Feature 2 router.

A minimal FastAPI app is built containing only the cur_analysis router so the
tests do not pull in the full middleware/auth/DB stack from backend.main.
RequestContext is injected via dependency override (HIGH-20 tenant isolation
is asserted by removing the override and expecting 401).
"""

from __future__ import annotations

import gzip
import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import cur_analysis
from backend.models.opportunities import OpportunityIngestResult
from backend.services.request_context import RequestContext


# ---------------------------------------------------------------------------
# App + auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(cur_analysis.router, prefix="/api/v1")
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

    app.dependency_overrides[cur_analysis._get_context] = _ctx
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_opp_service():
    with patch("backend.api.cur_analysis.get_opportunities_service") as m:
        svc = MagicMock()
        svc.ingest_signals.return_value = OpportunityIngestResult(
            total_signals=3,
            new_opportunities=3,
            updated_opportunities=0,
            skipped=0,
            errors=0,
            error_details=None,
            ingested_at=datetime.now(timezone.utc),
        )
        m.return_value = svc
        yield svc


# ---------------------------------------------------------------------------
# Synthetic CUR CSV bytes — minimal but enough for ≥1 detector to fire
# ---------------------------------------------------------------------------


def _csv_bytes() -> bytes:
    df = pd.DataFrame(
        [
            {
                "lineItem/UsageStartDate": "2025-01-01T00:00:00Z",
                "lineItem/LineItemType": "Usage",
                "lineItem/UsageType": "USE1-EBS:VolumeUsage.gp2",
                "lineItem/ProductCode": "AmazonEC2",
                "lineItem/UnblendedCost": 25.0,
                "lineItem/UsageAmount": 0.0,
                "lineItem/ResourceId": "vol-idle-0001",
                "lineItem/UsageAccountId": "123456789012",
                "product/region": "us-east-1",
            },
            {
                "lineItem/UsageStartDate": "2025-01-01T00:00:00Z",
                "lineItem/LineItemType": "Usage",
                "lineItem/UsageType": "USE1-BoxUsage:m5.large",
                "lineItem/ProductCode": "AmazonEC2",
                "lineItem/UnblendedCost": 500.0,
                "lineItem/UsageAmount": 720.0,
                "lineItem/ResourceId": "i-busy",
                "lineItem/UsageAccountId": "123456789012",
                "product/region": "us-east-1",
            },
        ]
    )
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# GET /capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_returns_thresholds_and_modes(self, client):
        resp = client.get("/api/v1/cur-analysis/capabilities")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["advisory_mode_available"] is True
        assert isinstance(body["connected_mode_available"], bool)
        assert body["upload_max_size_mb"] > 0
        assert body["upload_max_rows"] > 0
        assert "min_idle_cost_usd" in body["thresholds"]
        assert "mom_increase_threshold_pct" in body["thresholds"]

    def test_requires_authentication(self, app):
        """Without an injected context, require_context() must 401."""
        with TestClient(app) as c:
            resp = c.get("/api/v1/cur-analysis/capabilities")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /upload (Advisory Mode)
# ---------------------------------------------------------------------------


class TestUpload:
    def test_advisory_upload_persists_and_returns_findings(
        self, client, context, mock_opp_service
    ):
        resp = client.post(
            "/api/v1/cur-analysis/upload",
            files={"file": ("cur-2025-01.csv", _csv_bytes(), "text/csv")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "advisory"
        assert body["account_id"] == "123456789012"
        assert body["summary"]["rows_analyzed"] == 2
        assert body["summary"]["total_opportunities"] >= 1
        assert len(body["opportunities"]) >= 1
        # Persisted into the caller's org
        mock_opp_service.ingest_signals.assert_called_once()
        ingested = mock_opp_service.ingest_signals.call_args[0][0]
        assert all(o["source"] == "cur_analysis" for o in ingested)
        assert body["ingest_result"]["new_opportunities"] == 3

    def test_advisory_upload_accepts_gzip(self, client, mock_opp_service):
        gz = gzip.compress(_csv_bytes())
        resp = client.post(
            "/api/v1/cur-analysis/upload",
            files={"file": ("cur-2025-01.csv.gz", gz, "application/gzip")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["mode"] == "advisory"

    def test_persistence_failure_still_returns_findings(self, client):
        """Per spec: persist + return — but persistence failure must not lose analysis."""
        with patch(
            "backend.api.cur_analysis.get_opportunities_service",
            side_effect=RuntimeError("db down"),
        ):
            resp = client.post(
                "/api/v1/cur-analysis/upload",
                files={"file": ("cur.csv", _csv_bytes(), "text/csv")},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["opportunities"]) >= 1
        assert body["ingest_result"] is None

    def test_rejects_non_csv_extension(self, client):
        resp = client.post(
            "/api/v1/cur-analysis/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
        assert "CSV" in resp.json()["detail"]

    def test_rejects_invalid_cur_columns(self, client):
        bad = b"foo,bar\n1,2\n"
        resp = client.post(
            "/api/v1/cur-analysis/upload",
            files={"file": ("cur.csv", bad, "text/csv")},
        )
        assert resp.status_code == 400
        assert "CUR" in resp.json()["detail"]

    def test_rejects_oversize_file(self, client):
        with patch.object(cur_analysis.settings, "cur_upload_max_size_mb", 0):
            resp = client.post(
                "/api/v1/cur-analysis/upload",
                files={"file": ("cur.csv", _csv_bytes(), "text/csv")},
            )
        assert resp.status_code == 413

    def test_disabled_returns_403(self, client):
        with patch.object(cur_analysis.settings, "cur_pattern_mining_enabled", False):
            resp = client.post(
                "/api/v1/cur-analysis/upload",
                files={"file": ("cur.csv", _csv_bytes(), "text/csv")},
            )
        assert resp.status_code == 403

    def test_requires_authentication(self, app):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/cur-analysis/upload",
                files={"file": ("cur.csv", _csv_bytes(), "text/csv")},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /mine (Connected Mode)
# ---------------------------------------------------------------------------


class TestMine:
    def test_connected_mine_returns_and_persists(self, client, mock_opp_service):
        fake_signals = [
            {
                "title": "Idle resource",
                "category": "idle_resources",
                "source": "cur_analysis",
                "estimated_monthly_savings": 42.0,
            }
        ]
        with patch(
            "backend.config.settings.Settings.validate_cur_configuration",
            return_value=[],
        ), patch(
            "backend.api.cur_analysis.CURPatternMiningSignalsService"
        ) as mock_cls:
            inst = MagicMock()
            inst.account_id = "123456789012"
            inst.fetch_all_cur_signals = AsyncMock(return_value=fake_signals)
            mock_cls.return_value = inst

            resp = client.post("/api/v1/cur-analysis/mine")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "connected"
        assert body["summary"]["total_opportunities"] == 1
        assert body["summary"]["estimated_monthly_savings_usd"] == 42.0
        assert body["summary"]["by_detector"] == {"idle_resources": 1}
        assert body["opportunities"] == fake_signals
        mock_opp_service.ingest_signals.assert_called_once_with(fake_signals)

    def test_connected_mine_503_when_athena_unconfigured(self, client):
        with patch(
            "backend.config.settings.Settings.validate_cur_configuration",
            return_value=["AWS_CUR_DATABASE not set"],
        ):
            resp = client.post("/api/v1/cur-analysis/mine")
        assert resp.status_code == 503
        assert "Advisory Mode" in resp.json()["detail"]["message"]

    def test_disabled_returns_403(self, client):
        with patch.object(cur_analysis.settings, "cur_pattern_mining_enabled", False):
            resp = client.post("/api/v1/cur-analysis/mine")
        assert resp.status_code == 403

    def test_requires_authentication(self, app):
        with TestClient(app) as c:
            resp = c.post("/api/v1/cur-analysis/mine")
        assert resp.status_code == 401
