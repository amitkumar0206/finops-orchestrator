import pytest
from datetime import date

from backend.agents.cost_data_processor import CostDataProcessorAgent
from backend.agents.base import AgentConfig
from models.schemas import AgentType


class FakeCostExplorerClient:
    """Stubbed Cost Explorer client that simulates paginated responses."""

    def __init__(self):
        self.calls = 0

    def get_cost_and_usage(self, **kwargs):
        token = kwargs.get("NextPageToken")
        self.calls += 1

        base_result = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2025-09-28", "End": "2025-09-29"},
                    "Groups": [],
                    "Estimated": False
                }
            ]
        }

        if token is None:
            base_result["ResultsByTime"][0]["Groups"] = [
                {
                    "Keys": ["Amazon Elastic Compute Cloud - Compute"],
                    "Metrics": {
                        "BlendedCost": {"Amount": "5.00", "Unit": "USD"},
                        "UsageQuantity": {"Amount": "10", "Unit": "Hrs"}
                    }
                }
            ]
            base_result["NextPageToken"] = "page-2"
            return base_result

        if token == "page-2":
            base_result["ResultsByTime"][0]["Groups"] = [
                {
                    "Keys": ["Amazon Simple Storage Service"],
                    "Metrics": {
                        "BlendedCost": {"Amount": "10.00", "Unit": "USD"},
                        "UsageQuantity": {"Amount": "20", "Unit": "GB"}
                    }
                }
            ]
            return base_result

        raise AssertionError(f"Unexpected NextPageToken request: {token}")


class DummyCostDataProcessorAgent(CostDataProcessorAgent):
    """Agent that injects a fake Cost Explorer client for testing."""

    def __init__(self, config: AgentConfig, fake_client: FakeCostExplorerClient):
        self._fake_ce_client = fake_client
        super().__init__(config)

    def _initialize_aws_clients(self):
        self.ce_client = self._fake_ce_client
        self.athena_client = None
        self.s3_client = None


@pytest.mark.asyncio
async def test_fetch_cost_explorer_data_handles_pagination():
    fake_client = FakeCostExplorerClient()
    agent = DummyCostDataProcessorAgent(
        AgentConfig(
            agent_type=AgentType.COST_DATA_PROCESSOR,
            name="test-agent",
            description="Test agent"
        ),
        fake_client
    )

    time_range = {
        "start_date": date(2025, 9, 28),
        "end_date": date(2025, 9, 29),
        "period": "2d"
    }

    results = await agent._fetch_cost_explorer_data(
        time_range=time_range,
        services=None,
        granularity="DAILY"
    )

    assert fake_client.calls == 2
    assert len(results) == 2
    services = {item["service"] for item in results}
    assert services == {
        "Amazon Elastic Compute Cloud - Compute",
        "Amazon Simple Storage Service"
    }
    total_cost = sum(item["cost"] for item in results)
    assert total_cost == pytest.approx(15.0)
