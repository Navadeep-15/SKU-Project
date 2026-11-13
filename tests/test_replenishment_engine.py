from datetime import timedelta

import pandas as pd
import pytest

from config import REFERENCE_DATE
from Backend.data_generation.inventory_generator import generate_inventory_data
from Backend.data_generation.master_generator import generate_master_data
from Backend.forecasting.forecast_engine import (
    FORECAST_COLUMNS,
    FORECAST_HORIZON_DAYS,
    FORECAST_RUN_COLUMNS,
)
from Backend.replenishment.replenishment_engine import (
    PURCHASE_RECOMMENDATION_COLUMNS,
    PURCHASE_RECOMMENDATION_ID_PATTERN,
    VALIDATION_ISSUE_COLUMNS,
    VALIDATION_ISSUE_ID_PATTERN,
    _allocate_store_capacity,
    _urgency_score,
    calculate_required_forecast_horizon,
    create_recommendations,
    export_replenishment_data,
    generate_replenishment_data,
    validate_replenishment_data,
)


@pytest.fixture(scope="module")
def generated_result():
    return generate_replenishment_data("test")


@pytest.fixture(scope="module")
def source_data(generated_result):
    return (
        generate_master_data("test"),
        generate_inventory_data("test"),
        {
            "ForecastRun": generated_result["ForecastRun"],
            "Forecast": generated_result["Forecast"],
        },
        generated_result["selection"],
    )


def test_pipeline_uses_one_selected_extended_current_run(generated_result):
    runs = generated_result["ForecastRun"]
    selected_method = generated_result["selection"]["selected_method"]
    current_runs = runs[runs["forecast_origin"] == REFERENCE_DATE]

    assert list(runs.columns) == FORECAST_RUN_COLUMNS
    assert not runs.duplicated(["forecast_origin", "model_name"]).any()
    assert current_runs.loc[
        current_runs["model_name"] == selected_method, "horizon_days"
    ].item() == generated_result["required_horizon"]
    assert current_runs.loc[
        current_runs["model_name"] != selected_method, "horizon_days"
    ].eq(FORECAST_HORIZON_DAYS).all()
    assert runs.loc[
        runs["forecast_origin"] != REFERENCE_DATE, "horizon_days"
    ].eq(FORECAST_HORIZON_DAYS).all()


def test_recommendation_schema_ids_and_foreign_keys(generated_result, source_data):
    master_data, inventory_data, forecast_data, _ = source_data
    recommendations = generated_result["PurchaseRecommendation"]
    issues = generated_result["ValidationIssue"]

    assert list(recommendations.columns) == PURCHASE_RECOMMENDATION_COLUMNS
    assert list(issues.columns) == VALIDATION_ISSUE_COLUMNS
    assert recommendations["recommendation_id"].astype(str).str.fullmatch(
        PURCHASE_RECOMMENDATION_ID_PATTERN
    ).all()
    assert recommendations["recommendation_id"].str.len().le(30).all()
    assert issues["validation_id"].astype(str).str.fullmatch(
        VALIDATION_ISSUE_ID_PATTERN
    ).all()
    assert recommendations["run_id"].isin(
        generated_result["ForecastRun"]["run_id"]
    ).all()
    assert recommendations["store_id"].isin(
        master_data["Store"]["store_id"]
    ).all()
    assert recommendations["sku_id"].isin(master_data["SKU"]["sku_id"]).all()

    supplier_relationships = set(
        zip(
            master_data["SupplierSKU"]["supplier_sku_id"],
            master_data["SupplierSKU"]["sku_id"],
        )
    )
    assert set(
        zip(recommendations["supplier_sku_id"], recommendations["sku_id"])
    ).issubset(supplier_relationships)

    policy_relationships = set(
        zip(
            inventory_data["ReorderPolicy"]["policy_id"],
            inventory_data["ReorderPolicy"]["store_id"],
            inventory_data["ReorderPolicy"]["sku_id"],
        )
    )
    assert set(
        zip(
            recommendations["policy_id"],
            recommendations["store_id"],
            recommendations["sku_id"],
        )
    ).issubset(policy_relationships)
    assert list(forecast_data["Forecast"].columns) == FORECAST_COLUMNS
    assert not {"actual_demand", "stockout_impact"}.intersection(
        forecast_data["Forecast"].columns
    )


def test_recommendations_are_deterministic(generated_result, source_data):
    master_data, inventory_data, forecast_data, selection = source_data
    first, first_run_id = create_recommendations(
        master_data,
        inventory_data,
        forecast_data,
        selection["selected_method"],
    )
    second, second_run_id = create_recommendations(
        master_data,
        inventory_data,
        forecast_data,
        selection["selected_method"],
    )

    assert first_run_id == second_run_id
    pd.testing.assert_frame_equal(
        first["PurchaseRecommendation"],
        second["PurchaseRecommendation"],
    )
    pd.testing.assert_frame_equal(
        first["ValidationIssue"],
        second["ValidationIssue"],
    )
    pd.testing.assert_frame_equal(
        first["PurchaseRecommendation"],
        generated_result["PurchaseRecommendation"],
    )


def test_recommendation_calculations_and_lifecycle_are_valid(
    generated_result,
    source_data,
):
    master_data, inventory_data, forecast_data, _ = source_data
    recommendations = generated_result["PurchaseRecommendation"]
    validate_replenishment_data(
        {
            "PurchaseRecommendation": recommendations,
            "ValidationIssue": generated_result["ValidationIssue"],
        },
        master_data,
        inventory_data,
        forecast_data,
        generated_result["selected_run"]["run_id"],
    )

    suppliers = master_data["SupplierSKU"].set_index("supplier_sku_id")
    assortment_index = master_data["StoreSKU"].set_index(
        ["store_id", "sku_id"]
    )
    skus = master_data["SKU"].set_index("sku_id")
    assert (recommendations["lead_time_demand"] >= 0).all()
    assert (recommendations["reorder_point"] >= 0).all()
    assert (recommendations["target_stock"] >= 0).all()
    for row in recommendations.itertuples(index=False):
        supplier = suppliers.loc[row.supplier_sku_id]
        assortment = assortment_index.loc[(row.store_id, row.sku_id)]
        sku = skus.loc[row.sku_id]
        expected_end_dates = [
            value
            for value in (assortment.active_to, sku.discontinue_date)
            if not pd.isna(value)
        ]
        if expected_end_dates:
            end_date = min(pd.to_datetime(value).date() for value in expected_end_dates)
            assert row.expected_delivery_date < end_date
        assert row.expected_delivery_date == (
            REFERENCE_DATE + timedelta(days=int(supplier.lead_time_days))
        )
        if row.recommended_qty > 0:
            assert row.recommended_qty >= supplier.min_order_qty
            assert row.recommended_qty % supplier.pack_size == 0


def test_supplier_selection_uses_approved_deterministic_order(
    generated_result,
    source_data,
):
    master_data, _, _, _ = source_data
    suppliers = master_data["Supplier"].set_index("supplier_id")
    supplier_skus = master_data["SupplierSKU"]

    for row in generated_result["PurchaseRecommendation"].itertuples(
        index=False
    ):
        candidates = supplier_skus.loc[
            (supplier_skus["sku_id"] == row.sku_id)
            & (supplier_skus["active_from"] <= REFERENCE_DATE)
            & (
                supplier_skus["active_to"].isna()
                | (supplier_skus["active_to"] > REFERENCE_DATE)
            )
        ].copy()
        candidates = candidates.loc[
            candidates["supplier_id"].map(
                lambda supplier_id: bool(
                    suppliers.loc[supplier_id, "active_flag"]
                )
            )
        ]
        assortment = master_data["StoreSKU"].loc[
            (master_data["StoreSKU"]["store_id"] == row.store_id)
            & (master_data["StoreSKU"]["sku_id"] == row.sku_id)
        ].iloc[0]
        sku = master_data["SKU"].set_index("sku_id").loc[row.sku_id]
        end_dates = [
            pd.to_datetime(value).date()
            for value in (assortment["active_to"], sku["discontinue_date"])
            if not pd.isna(value)
        ]
        if end_dates:
            end_date = min(end_dates)
            candidates = candidates.loc[
                candidates["lead_time_days"].map(
                    lambda lead_time: (
                        REFERENCE_DATE + timedelta(days=int(lead_time))
                    )
                    < end_date
                )
            ]
        candidates = candidates.sort_values(
            [
                "is_preferred_supplier",
                "supplier_priority",
                "contract_cost",
                "lead_time_days",
                "supplier_sku_id",
            ],
            ascending=[False, True, True, True, True],
        )
        assert row.supplier_sku_id == candidates.iloc[0]["supplier_sku_id"]


def test_capacity_allocation_blocks_complete_orders_in_urgency_order(source_data):
    master_data, _, _, _ = source_data
    store_id = master_data["Store"].iloc[0]["store_id"]
    sku_ids = (
        master_data["StoreSKU"].loc[
            master_data["StoreSKU"]["store_id"] == store_id, "sku_id"
        ]
        .drop_duplicates()
        .tolist()
    )
    assert len(sku_ids) >= 2
    first_sku, second_sku = sorted(sku_ids[:2])
    stores = master_data["Store"].copy(deep=True)
    stores.loc[stores["store_id"] == store_id, "capacity_units"] = 16
    test_master = {"Store": stores}
    candidates = [
        {
            "store_id": store_id,
            "sku_id": first_sku,
            "desired_quantity": 6,
            "urgency_score": 2.0,
            "reason_code": "REORDER_REQUIRED",
        },
        {
            "store_id": store_id,
            "sku_id": second_sku,
            "desired_quantity": 5,
            "urgency_score": 1.0,
            "reason_code": "REORDER_REQUIRED",
        },
    ]

    allocations, projected = _allocate_store_capacity(
        candidates,
        test_master,
        {(store_id, first_sku): 10},
        {},
        REFERENCE_DATE,
    )

    assert allocations[(store_id, first_sku)]["recommended_qty"] == 6
    assert allocations[(store_id, second_sku)]["recommended_qty"] == 0
    assert allocations[(store_id, second_sku)][
        "capacity_constraint_status"
    ] == "BLOCKED"
    assert "Attempted quantity 5" in allocations[(store_id, second_sku)][
        "exception_reason"
    ]
    assert projected[store_id] == 16


def test_urgency_is_shortage_relative_to_lead_time_demand():
    assert _urgency_score(12, 7, 5) == pytest.approx(1.0)
    assert _urgency_score(3, 1, 0) == pytest.approx(2.0)


def test_missing_supplier_or_policy_creates_validation_finding(
    source_data,
    generated_result,
):
    master_data, inventory_data, forecast_data, selection = source_data
    first_recommendation = generated_result["PurchaseRecommendation"].iloc[0]
    pair = (
        first_recommendation["store_id"],
        first_recommendation["sku_id"],
    )

    no_supplier_master = {
        table: frame.copy(deep=True) for table, frame in master_data.items()
    }
    sku_supplier_ids = no_supplier_master["SupplierSKU"].loc[
        no_supplier_master["SupplierSKU"]["sku_id"] == pair[1],
        "supplier_id",
    ]
    no_supplier_master["Supplier"].loc[
        no_supplier_master["Supplier"]["supplier_id"].isin(sku_supplier_ids),
        "active_flag",
    ] = False
    no_supplier_data, _ = create_recommendations(
        no_supplier_master,
        inventory_data,
        forecast_data,
        selection["selected_method"],
    )
    assert not (
        (no_supplier_data["PurchaseRecommendation"]["store_id"] == pair[0])
        & (no_supplier_data["PurchaseRecommendation"]["sku_id"] == pair[1])
    ).any()
    assert no_supplier_data["ValidationIssue"]["rule_name"].eq(
        "NO_ELIGIBLE_ACTIVE_SUPPLIER"
    ).any()

    no_policy_inventory = {
        table: frame.copy(deep=True) for table, frame in inventory_data.items()
    }
    pair_mask = (
        (no_policy_inventory["ReorderPolicy"]["store_id"] == pair[0])
        & (no_policy_inventory["ReorderPolicy"]["sku_id"] == pair[1])
    )
    no_policy_inventory["ReorderPolicy"].loc[
        pair_mask, "effective_to"
    ] = REFERENCE_DATE
    no_policy_data, _ = create_recommendations(
        master_data,
        no_policy_inventory,
        forecast_data,
        selection["selected_method"],
    )
    assert not (
        (no_policy_data["PurchaseRecommendation"]["store_id"] == pair[0])
        & (no_policy_data["PurchaseRecommendation"]["sku_id"] == pair[1])
    ).any()
    assert no_policy_data["ValidationIssue"]["rule_name"].eq(
        "NO_ACTIVE_POLICY"
    ).any()


def test_order_is_omitted_when_delivery_is_after_eligibility_end(
    source_data,
    generated_result,
):
    master_data, inventory_data, forecast_data, selection = source_data
    target = generated_result["PurchaseRecommendation"].iloc[0]
    changed_master = {
        table: frame.copy(deep=True) for table, frame in master_data.items()
    }
    sku_mask = changed_master["SKU"]["sku_id"] == target["sku_id"]
    changed_master["SKU"].loc[sku_mask, "discontinue_date"] = (
        REFERENCE_DATE + timedelta(days=1)
    )

    data, _ = create_recommendations(
        changed_master,
        inventory_data,
        forecast_data,
        selection["selected_method"],
    )

    assert not (
        (data["PurchaseRecommendation"]["store_id"] == target["store_id"])
        & (data["PurchaseRecommendation"]["sku_id"] == target["sku_id"])
    ).any()
    issue = data["ValidationIssue"].loc[
        data["ValidationIssue"]["record_key"]
        == f"{target['store_id']}/{target['sku_id']}"
    ]
    assert issue["rule_name"].eq(
        "SUPPLIER_ARRIVAL_AFTER_ELIGIBILITY_END"
    ).any()


def test_replenishment_exports_schema_aligned_csvs(tmp_path, generated_result):
    generated_dir = tmp_path / "generated"
    export_dir = tmp_path / "exports"
    export_replenishment_data(generated_result, generated_dir, export_dir)

    assert list(
        pd.read_csv(generated_dir / "PurchaseRecommendation.csv").columns
    ) == PURCHASE_RECOMMENDATION_COLUMNS
    assert list(
        pd.read_csv(generated_dir / "ValidationIssue.csv").columns
    ) == VALIDATION_ISSUE_COLUMNS
    assert list(pd.read_csv(generated_dir / "ForecastRun.csv").columns) == (
        FORECAST_RUN_COLUMNS
    )
    assert list(pd.read_csv(generated_dir / "Forecast.csv").columns) == (
        FORECAST_COLUMNS
    )
    assert list(
        pd.read_csv(export_dir / "forecast_evaluation_metrics.csv").columns
    ) == generated_result["metrics"].columns.tolist()


def test_unknown_dataset_configuration_is_rejected():
    with pytest.raises(ValueError):
        generate_replenishment_data("unknown")
