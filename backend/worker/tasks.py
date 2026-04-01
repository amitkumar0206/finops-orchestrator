"""
Celery Tasks

Background tasks for the FinOps Orchestrator.

Key tasks:
- ingest_optimization_signals: Runs nightly to refresh all optimization opportunities
  from CloudWatch, Cost Explorer, Trusted Advisor, Compute Optimizer, and storage APIs.
"""

import asyncio
from typing import Any, Dict, Optional

import structlog

from backend.worker import celery_app

logger = structlog.get_logger(__name__)


def _run_async(coro) -> Any:
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already inside an event loop (e.g. test), create a new thread loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(
    name="backend.worker.tasks.ingest_optimization_signals",
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes between retries
    soft_time_limit=1800,     # 30 minute soft limit
    time_limit=2100,          # 35 minute hard limit
)
def ingest_optimization_signals(
    self,
    organization_id: Optional[str] = None,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Nightly background ingestion of all optimization signals.

    Orchestrates all three new signal sources:
    1. CloudWatch idle resource detection (EC2, RDS, ELB, Lambda)
    2. RI and Savings Plans coverage, utilization, and recommendations
    3. S3 and EBS storage lifecycle optimization

    Plus the existing sources:
    - Cost Explorer rightsizing
    - Trusted Advisor
    - Compute Optimizer

    Args:
        organization_id: Optional UUID string to scope ingestion to a specific org.
        account_id: Optional AWS account ID to scope ingestion.

    Returns:
        Dict with counts of new/updated opportunities and any errors.
    """
    from uuid import UUID
    from backend.services.aws_optimization_signals import AWSOptimizationSignalsService
    from backend.services.cloudwatch_optimization_signals import CloudWatchOptimizationSignalsService
    from backend.services.ri_savings_plans_signals import RISavingsPlansSignalsService
    from backend.services.storage_optimization_signals import StorageOptimizationSignalsService
    from backend.services.opportunities_service import OpportunitiesService

    org_uuid = UUID(organization_id) if organization_id else None

    all_signals = []
    errors = []

    logger.info(
        "Starting nightly optimization ingestion",
        organization_id=organization_id,
        account_id=account_id,
    )

    # --- Existing sources ---
    existing_svc = AWSOptimizationSignalsService(
        account_id=account_id,
        organization_id=org_uuid,
    )

    for label, fetch_coro in [
        ("Cost Explorer", existing_svc.fetch_cost_explorer_recommendations()),
        ("Trusted Advisor", existing_svc.fetch_trusted_advisor_recommendations()),
        ("Compute Optimizer", existing_svc.fetch_compute_optimizer_recommendations()),
    ]:
        try:
            signals = _run_async(fetch_coro)
            all_signals.extend(signals)
            logger.info(f"Fetched {len(signals)} signals from {label}")
        except Exception as e:
            errors.append(f"{label}: {str(e)[:200]}")
            logger.error(f"Failed to fetch {label} signals: {e}")

    # --- Feature 1: CloudWatch idle resource detection ---
    try:
        cw_svc = CloudWatchOptimizationSignalsService(
            account_id=account_id,
            organization_id=org_uuid,
        )
        cw_signals = _run_async(cw_svc.fetch_all_cloudwatch_signals())
        all_signals.extend(cw_signals)
        logger.info(f"Fetched {len(cw_signals)} CloudWatch signals")
    except Exception as e:
        errors.append(f"CloudWatch: {str(e)[:200]}")
        logger.error(f"Failed to fetch CloudWatch signals: {e}")

    # --- Feature 2: RI and Savings Plans ---
    try:
        ri_svc = RISavingsPlansSignalsService(
            account_id=account_id,
            organization_id=org_uuid,
        )
        ri_signals = _run_async(ri_svc.fetch_all_ri_sp_signals())
        all_signals.extend(ri_signals)
        logger.info(f"Fetched {len(ri_signals)} RI/SP signals")
    except Exception as e:
        errors.append(f"RI/Savings Plans: {str(e)[:200]}")
        logger.error(f"Failed to fetch RI/SP signals: {e}")

    # --- Feature 3: Storage optimization ---
    try:
        storage_svc = StorageOptimizationSignalsService(
            account_id=account_id,
            organization_id=org_uuid,
        )
        storage_signals = _run_async(storage_svc.fetch_all_storage_signals())
        all_signals.extend(storage_signals)
        logger.info(f"Fetched {len(storage_signals)} storage signals")
    except Exception as e:
        errors.append(f"Storage: {str(e)[:200]}")
        logger.error(f"Failed to fetch storage signals: {e}")

    # --- Deduplicate and persist ---
    deduped = existing_svc.deduplicate_opportunities(all_signals)

    try:
        opp_svc = OpportunitiesService(organization_id=org_uuid)
        result = opp_svc.ingest_signals(deduped)

        summary = {
            "total_signals": result.total_signals,
            "new_opportunities": result.new_opportunities,
            "updated_opportunities": result.updated_opportunities,
            "errors": errors,
        }

        logger.info(
            "Nightly ingestion complete",
            total=result.total_signals,
            new=result.new_opportunities,
            updated=result.updated_opportunities,
            error_count=len(errors),
        )

        return summary

    except Exception as e:
        logger.error(f"Failed to persist signals: {e}")
        self.retry(exc=e)
