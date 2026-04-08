from __future__ import annotations

import pandas as pd

from backend.models.data_sources import DataSourceProvider
from backend.services.focus_normalizer import FocusNormalizer


class TestFocusNormalizer:
    def test_normalize_aws_cur_groups_by_month_provider_service(self):
        df = pd.DataFrame(
            [
                {
                    "line_item_usage_start_date": "2026-01-02T00:00:00Z",
                    "line_item_unblended_cost": 10.5,
                    "line_item_product_code": "AmazonEC2",
                    "line_item_usage_account_id": "111111111111",
                    "product_region": "us-east-1",
                    "line_item_usage_amount": 2,
                },
                {
                    "line_item_usage_start_date": "2026-01-05T00:00:00Z",
                    "line_item_unblended_cost": 9.5,
                    "line_item_product_code": "AmazonEC2",
                    "line_item_usage_account_id": "111111111111",
                    "product_region": "us-east-1",
                    "line_item_usage_amount": 1,
                },
            ]
        )

        records, errors = FocusNormalizer().normalize(DataSourceProvider.AWS_CUR, df)

        assert errors == []
        assert len(records) == 1
        assert records[0].provider_type == DataSourceProvider.AWS_CUR
        assert records[0].service_name == "AmazonEC2"
        assert records[0].cost_amount == 20.0
        assert records[0].usage_quantity == 3.0

    def test_normalize_azure_export_validates_required_columns(self):
        df = pd.DataFrame([{"foo": 1, "bar": 2}])

        records, errors = FocusNormalizer().normalize(DataSourceProvider.AZURE_EXPORT, df)

        assert records == []
        assert errors
        assert "Missing required cost column" in errors[0]

    def test_normalize_generic_cost_aggregates(self):
        df = pd.DataFrame(
            [
                {"date": "2026-02-01", "service": "Databricks", "cost": 12.0, "currency": "USD"},
                {"date": "2026-02-03", "service": "Databricks", "cost": 3.0, "currency": "USD"},
            ]
        )

        records, errors = FocusNormalizer().normalize(DataSourceProvider.GENERIC_COST, df)

        assert errors == []
        assert len(records) == 1
        assert records[0].service_name == "Databricks"
        assert records[0].cost_amount == 15.0
