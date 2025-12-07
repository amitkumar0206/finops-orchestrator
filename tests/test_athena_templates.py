from backend.services.athena_cur_templates import AthenaCURTemplates


def test_ec2_reserved_savings_projection_filters_families():
    templates = AthenaCURTemplates(database="cost_usage_db", table="cur_table")

    sql = templates.ec2_reserved_savings_projection(
        start_date="2024-08-01",
        end_date="2024-08-31",
        assumed_discount=0.4,
        families=["m5", "c6g"]
    )

    assert "LOWER(SPLIT_PART" in sql
    assert "'m5'" in sql and "'c6g'" in sql
    assert "est_savings_usd" in sql
