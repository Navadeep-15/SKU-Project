from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from Backend.services.inventory_simulation import simulate_inventory_adjustment
from Backend.services.store_evaluation import active_store_sku_ids
from Backend.forecasting.forecast_engine import FORECAST_METHODS


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def source_tables():
    return {
        path.stem: pd.read_csv(path)
        for path in (PROJECT_ROOT / "data" / "generated").glob("*.csv")
    }


def _selection(source_tables):
    store_id = source_tables["Store"].iloc[0]["store_id"]
    sku_id = active_store_sku_ids(source_tables, store_id)[0]
    return store_id, sku_id


def test_simulation_reuses_replenishment_rules_without_mutating_source(
    source_tables,
    monkeypatch,
):
    import Backend.services.inventory_simulation as simulation

    store_id, sku_id = _selection(source_tables)
    before = deepcopy(source_tables)
    captured_sales = []
    generate_forecasts = simulation.generate_forecast_data

    def capture_forecast_inputs(master_data, sales_history, *args, **kwargs):
        captured_sales.append(sales_history.copy())
        return generate_forecasts(master_data, sales_history, *args, **kwargs)

    monkeypatch.setattr(
        simulation,
        "generate_forecast_data",
        capture_forecast_inputs,
    )
    result = simulate_inventory_adjustment(
        source_tables,
        store_id,
        sku_id,
        1,
        FORECAST_METHODS[0],
    )

    assert result["status"] == "SIMULATED"
    assert result["on_hand_after"] == result["on_hand_before"] + 1
    assert result["replenishment_data"] is not None
    assert captured_sales
    assert "actual_demand" not in captured_sales[0].columns
    assert not source_tables["GroundTruthDemand"].empty
    for table_name, original in before.items():
        pd.testing.assert_frame_equal(source_tables[table_name], original)


def test_negative_resulting_on_hand_is_rejected_without_source_changes(source_tables):
    store_id, sku_id = _selection(source_tables)
    before = deepcopy(source_tables)
    current = source_tables["InventorySnapshot"].loc[
        source_tables["InventorySnapshot"]["store_id"].eq(store_id)
        & source_tables["InventorySnapshot"]["sku_id"].eq(sku_id)
        & source_tables["InventorySnapshot"]["snapshot_date"].astype(str).str[:10].eq(
            "2026-10-22"
        )
    ].iloc[0]
    invalid_adjustment = -int(current["on_hand"]) - 1

    with pytest.raises(ValueError, match="make on-hand inventory negative"):
        simulate_inventory_adjustment(
            source_tables,
            store_id,
            sku_id,
            invalid_adjustment,
            FORECAST_METHODS[0],
        )
    for table_name, original in before.items():
        pd.testing.assert_frame_equal(source_tables[table_name], original)


def test_capacity_overflow_is_reported_before_replenishment(source_tables):
    store_id, sku_id = _selection(source_tables)
    capacity = int(
        source_tables["Store"].loc[
            source_tables["Store"]["store_id"].eq(store_id),
            "capacity_units",
        ].iloc[0]
    )
    result = simulate_inventory_adjustment(
        source_tables,
        store_id,
        sku_id,
        capacity,
        FORECAST_METHODS[0],
    )

    assert result["status"] == "REJECTED_CAPACITY"
    assert result["projected_store_units"] > result["capacity_units"]
    assert result["replenishment_data"] is None


def test_preview_uses_latest_persisted_inventory_snapshot(source_tables):
    store_id, sku_id = _selection(source_tables)
    changed = deepcopy(source_tables)
    snapshot = changed["InventorySnapshot"].loc[
        changed["InventorySnapshot"]["store_id"].eq(store_id)
        & changed["InventorySnapshot"]["sku_id"].eq(sku_id)
        & pd.to_datetime(
            changed["InventorySnapshot"]["snapshot_date"]
        ).dt.date.eq(pd.Timestamp("2026-10-22").date())
    ].iloc[0].copy()
    latest_date = pd.Timestamp("2026-10-23").date()
    snapshot["snapshot_id"] = (
        f"INV-{store_id}-{sku_id}-{latest_date.isoformat()}"
    )
    snapshot["snapshot_date"] = latest_date
    snapshot["on_hand"] = int(snapshot["on_hand"]) + 2
    snapshot["created_at"] = pd.Timestamp(latest_date, tz="UTC")
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
    changed["InventoryEvent"] = pd.concat(
        [
            changed["InventoryEvent"],
            pd.DataFrame(
                [
                    {
                        "event_id": f"EVT-{next_event_number:08d}",
                        "store_id": store_id,
                        "sku_id": sku_id,
                        "event_date": latest_date,
                        "event_type": "ADJUSTMENT_IN",
                        "quantity": 2,
                        "reference_id": "TEST-CURRENT-INVENTORY",
                        "created_at": pd.Timestamp(latest_date, tz="UTC"),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    result = simulate_inventory_adjustment(
        changed,
        store_id,
        sku_id,
        1,
        FORECAST_METHODS[0],
    )

    original = source_tables["InventorySnapshot"].loc[
        source_tables["InventorySnapshot"]["store_id"].eq(store_id)
        & source_tables["InventorySnapshot"]["sku_id"].eq(sku_id)
        & pd.to_datetime(
            source_tables["InventorySnapshot"]["snapshot_date"]
        ).dt.date.eq(pd.Timestamp("2026-10-22").date())
    ].iloc[0]
    assert result["on_hand_before"] == int(original["on_hand"]) + 2
    assert result["on_hand_after"] == result["on_hand_before"] + 1


def test_zero_adjustment_is_not_run(source_tables):
    store_id, sku_id = _selection(source_tables)

    with pytest.raises(ValueError, match="non-zero"):
        simulate_inventory_adjustment(
            source_tables,
            store_id,
            sku_id,
            0,
            FORECAST_METHODS[0],
        )
