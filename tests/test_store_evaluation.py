from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from config import REFERENCE_DATE
from Backend.services.store_evaluation import (
    active_store_sku_ids,
    evaluate_store,
    prepare_store_scope,
)
from Backend.forecasting.forecast_engine import FORECAST_METHODS


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def source_tables():
    return {
        path.stem: pd.read_csv(path)
        for path in (PROJECT_ROOT / "data" / "generated").glob("*.csv")
    }


def test_store_evaluation_is_store_scoped_and_deterministic(source_tables):
    store_id = source_tables["Store"].iloc[0]["store_id"]
    sku_ids = active_store_sku_ids(source_tables, store_id)[:2]

    first = evaluate_store(source_tables, store_id, sku_ids)
    repeated = evaluate_store(source_tables, store_id, sku_ids)

    pd.testing.assert_frame_equal(first["metrics"], repeated["metrics"])
    pd.testing.assert_frame_equal(
        first["forecast_data"]["Forecast"],
        repeated["forecast_data"]["Forecast"],
    )
    assert set(first["metrics"]["forecast_method"]) == set(FORECAST_METHODS)
    assert set(first["metrics"]["evaluation_scope"]) == {
        "HOLDOUT_ORIGIN",
        "OVERALL",
    }
    assert first["store_id"] == store_id
    assert first["sku_ids"] == sku_ids
    assert not first["replenishment_data"]["PurchaseRecommendation"].empty


def test_ground_truth_changes_scoring_not_historical_forecast_inputs(source_tables):
    store_id = source_tables["Store"].iloc[0]["store_id"]
    sku_ids = active_store_sku_ids(source_tables, store_id)[:2]
    original = evaluate_store(source_tables, store_id, sku_ids)

    changed_truth = deepcopy(source_tables)
    changed_truth["GroundTruthDemand"]["actual_demand"] += 50
    changed = evaluate_store(changed_truth, store_id, sku_ids)

    original_runs = original["forecast_data"]["ForecastRun"]
    changed_runs = changed["forecast_data"]["ForecastRun"]
    holdout_run_ids = set(
        original_runs.loc[
            original_runs["forecast_origin"].isin(original["holdout_origins"]),
            "run_id",
        ]
    )
    changed_holdout_ids = set(
        changed_runs.loc[
            changed_runs["forecast_origin"].isin(changed["holdout_origins"]),
            "run_id",
        ]
    )
    assert holdout_run_ids == changed_holdout_ids
    pd.testing.assert_frame_equal(
        original["forecast_data"]["Forecast"].loc[
            original["forecast_data"]["Forecast"]["run_id"].isin(holdout_run_ids)
        ].reset_index(drop=True),
        changed["forecast_data"]["Forecast"].loc[
            changed["forecast_data"]["Forecast"]["run_id"].isin(changed_holdout_ids)
        ].reset_index(drop=True),
    )
    assert not original["metrics"].equals(changed["metrics"])


def test_latest_inventory_updates_replenishment_without_changing_holdouts(
    source_tables,
):
    store_id = source_tables["Store"].iloc[0]["store_id"]
    sku_id = active_store_sku_ids(source_tables, store_id)[0]
    original = evaluate_store(source_tables, store_id, [sku_id])
    changed = deepcopy(source_tables)

    snapshot = changed["InventorySnapshot"].loc[
        changed["InventorySnapshot"]["store_id"].eq(store_id)
        & changed["InventorySnapshot"]["sku_id"].eq(sku_id)
        & pd.to_datetime(
            changed["InventorySnapshot"]["snapshot_date"]
        ).dt.date.eq(REFERENCE_DATE)
    ].iloc[0].copy()
    latest_date = REFERENCE_DATE + timedelta(days=1)
    snapshot["snapshot_id"] = (
        f"INV-{store_id}-{sku_id}-{latest_date.isoformat()}"
    )
    snapshot["snapshot_date"] = latest_date
    snapshot["on_hand"] = int(snapshot["on_hand"]) + 2
    snapshot["created_at"] = pd.Timestamp(
        latest_date,
        tz="UTC",
    )
    changed["InventorySnapshot"] = pd.concat(
        [
            changed["InventorySnapshot"],
            pd.DataFrame([snapshot]),
        ],
        ignore_index=True,
    )

    store_events = changed["InventoryEvent"].loc[
        changed["InventoryEvent"]["store_id"].eq(store_id)
    ]
    next_event_number = max(
        int(event_id[4:])
        for event_id in store_events["event_id"]
    ) + 1
    event = {
        "event_id": f"EVT-{next_event_number:08d}",
        "store_id": store_id,
        "sku_id": sku_id,
        "event_date": latest_date,
        "event_type": "ADJUSTMENT_IN",
        "quantity": 2,
        "reference_id": "TEST-CURRENT-INVENTORY",
        "created_at": pd.Timestamp(latest_date, tz="UTC"),
    }
    changed["InventoryEvent"] = pd.concat(
        [
            changed["InventoryEvent"],
            pd.DataFrame([event]),
        ],
        ignore_index=True,
    )

    refreshed = evaluate_store(changed, store_id, [sku_id])
    original_holdout_ids = set(
        original["forecast_data"]["ForecastRun"].loc[
            original["forecast_data"]["ForecastRun"]["forecast_origin"].isin(
                original["holdout_origins"]
            ),
            "run_id",
        ]
    )
    refreshed_holdout_ids = set(
        refreshed["forecast_data"]["ForecastRun"].loc[
            refreshed["forecast_data"]["ForecastRun"]["forecast_origin"].isin(
                refreshed["holdout_origins"]
            ),
            "run_id",
        ]
    )
    pd.testing.assert_frame_equal(
        original["forecast_data"]["Forecast"].loc[
            original["forecast_data"]["Forecast"]["run_id"].isin(
                original_holdout_ids
            )
        ].reset_index(drop=True),
        refreshed["forecast_data"]["Forecast"].loc[
            refreshed["forecast_data"]["Forecast"]["run_id"].isin(
                refreshed_holdout_ids
            )
        ].reset_index(drop=True),
    )
    original_position = original["replenishment_data"][
        "PurchaseRecommendation"
    ].iloc[0]["inventory_position"]
    refreshed_position = refreshed["replenishment_data"][
        "PurchaseRecommendation"
    ].iloc[0]["inventory_position"]
    assert refreshed_position == original_position + 2


def test_active_sku_selection_respects_lifecycle_dates(source_tables):
    store_id = source_tables["Store"].iloc[0]["store_id"]
    active = active_store_sku_ids(source_tables, store_id)
    assert active
    sku_id = active[0]
    changed = deepcopy(source_tables)
    mask = changed["SKU"]["sku_id"].eq(sku_id)
    changed["SKU"].loc[mask, "lifecycle_state"] = "DISCONTINUED"
    changed["SKU"].loc[mask, "discontinue_date"] = REFERENCE_DATE.isoformat()

    assert sku_id not in active_store_sku_ids(changed, store_id)


def test_store_scope_rejects_a_sku_from_another_location(source_tables):
    store_ids = source_tables["Store"]["store_id"].tolist()
    first_skus = set(
        source_tables["StoreSKU"].loc[
            source_tables["StoreSKU"]["store_id"].eq(store_ids[0]),
            "sku_id",
        ]
    )
    other_skus = sorted(
        set(
            source_tables["StoreSKU"].loc[
                source_tables["StoreSKU"]["store_id"].eq(store_ids[1]),
                "sku_id",
            ]
        )
        - first_skus
    )
    if not other_skus:
        pytest.skip("The test profile has no SKU exclusive to the second location.")

    with pytest.raises(ValueError, match="must belong to the chosen store"):
        prepare_store_scope(source_tables, store_ids[0], [other_skus[0]])
