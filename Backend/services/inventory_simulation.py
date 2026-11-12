from datetime import datetime, time, timezone

import pandas as pd

from config import REFERENCE_DATE
from Backend.data_generation.inventory_generator import INVENTORY_EVENT_COLUMNS
from Backend.forecasting.forecast_engine import (
    FORECAST_METHODS,
    generate_forecast_data,
)
from Backend.replenishment.replenishment_engine import (
    calculate_required_forecast_horizon,
    create_recommendations,
)
from Backend.services.store_evaluation import (
    align_latest_inventory_to_forecast_origin,
    prepare_store_scope,
)


def _simulation_event_id(events):
    used_ids = set(events["event_id"].astype(str))
    numbers = [
        int(event_id[4:])
        for event_id in used_ids
        if event_id.startswith("EVT-")
        and event_id[4:].isdigit()
    ]
    next_number = max(numbers, default=0) + 1
    while next_number <= 99_999_999:
        candidate = f"EVT-{next_number:08d}"
        if candidate not in used_ids:
            return candidate
        next_number += 1
    raise ValueError("No unused event ID is available for this simulation.")


def simulate_inventory_adjustment(
    tables,
    store_id,
    sku_id,
    adjustment_units,
    forecast_method,
):
    if isinstance(adjustment_units, bool) or int(adjustment_units) != adjustment_units:
        raise ValueError("Inventory adjustment must be a whole number of units.")
    adjustment_units = int(adjustment_units)
    if adjustment_units == 0:
        raise ValueError("Enter a non-zero inventory adjustment.")
    if forecast_method not in FORECAST_METHODS:
        raise ValueError(f"Unsupported forecast method: {forecast_method}.")

    master_data, inventory_data, sales_history = prepare_store_scope(
        tables,
        store_id,
    )
    inventory_data = align_latest_inventory_to_forecast_origin(inventory_data)
    snapshots = inventory_data["InventorySnapshot"]
    snapshot_mask = (
        snapshots["store_id"].eq(store_id)
        & snapshots["sku_id"].eq(sku_id)
        & pd.to_datetime(snapshots["snapshot_date"]).dt.date.eq(REFERENCE_DATE)
    )
    if int(snapshot_mask.sum()) != 1:
        raise ValueError(
            "A unique current inventory snapshot is required for this SKU."
        )

    snapshot_index = snapshots.index[snapshot_mask][0]
    snapshot = snapshots.loc[snapshot_index].copy()
    on_hand_before = int(snapshot["on_hand"])
    on_hand_after = on_hand_before + adjustment_units
    if on_hand_after < 0:
        raise ValueError("The adjustment would make on-hand inventory negative.")

    events = inventory_data["InventoryEvent"]
    event_type = "ADJUSTMENT_IN" if adjustment_units > 0 else "ADJUSTMENT_OUT"
    event_row = {
        "event_id": _simulation_event_id(events),
        "store_id": store_id,
        "sku_id": sku_id,
        "event_date": REFERENCE_DATE,
        "event_type": event_type,
        "quantity": adjustment_units,
        "reference_id": (
            f"SIM-{store_id[-6:]}-{sku_id[-6:]}-{REFERENCE_DATE:%Y%m%d}"
        ),
        "created_at": datetime.combine(
            REFERENCE_DATE,
            time.min,
            tzinfo=timezone.utc,
        ),
    }
    events = pd.concat(
        [
            events,
            pd.DataFrame([event_row], columns=INVENTORY_EVENT_COLUMNS),
        ],
        ignore_index=True,
    )
    snapshots.loc[snapshot_index, "on_hand"] = on_hand_after
    inventory_data["InventoryEvent"] = events
    inventory_data["InventorySnapshot"] = snapshots

    current_snapshots = snapshots.loc[
        pd.to_datetime(snapshots["snapshot_date"]).dt.date.eq(REFERENCE_DATE)
    ]
    store = master_data["Store"].iloc[0]
    projected_store_units = int(
        current_snapshots["on_hand"].sum()
        + current_snapshots["on_order"].sum()
    )
    capacity_units = int(store["capacity_units"])
    result = {
        "status": "SIMULATED",
        "store_id": store_id,
        "sku_id": sku_id,
        "adjustment_units": adjustment_units,
        "on_hand_before": on_hand_before,
        "on_hand_after": on_hand_after,
        "inventory_position_after": (
            on_hand_after
            + int(snapshot["on_order"])
            - int(snapshot["reserved"])
            - int(snapshot["backorders"])
        ),
        "projected_store_units": projected_store_units,
        "capacity_units": capacity_units,
        "recommendation": None,
        "replenishment_data": None,
        "selected_run_id": None,
        "required_horizon": None,
    }
    if projected_store_units > capacity_units:
        result["status"] = "REJECTED_CAPACITY"
        result["rejection_reason"] = (
            f"Adjusted on-hand plus on-order inventory would be "
            f"{projected_store_units} units, exceeding the store capacity of "
            f"{capacity_units} units."
        )
        return result

    required_horizon = calculate_required_forecast_horizon(
        master_data,
        inventory_data,
        REFERENCE_DATE,
    )
    forecast_data = generate_forecast_data(
        master_data,
        sales_history,
        [REFERENCE_DATE],
        {(REFERENCE_DATE, forecast_method): required_horizon},
    )
    replenishment_data, selected_run_id = create_recommendations(
        master_data,
        inventory_data,
        forecast_data,
        forecast_method,
        REFERENCE_DATE,
    )
    selected_recommendations = replenishment_data[
        "PurchaseRecommendation"
    ]
    selected_recommendations = selected_recommendations.loc[
        selected_recommendations["store_id"].eq(store_id)
        & selected_recommendations["sku_id"].eq(sku_id)
    ]
    result.update(
        {
            "recommendation": (
                selected_recommendations.iloc[0]
                if not selected_recommendations.empty
                else None
            ),
            "replenishment_data": replenishment_data,
            "selected_run_id": selected_run_id,
            "required_horizon": required_horizon,
        }
    )
    return result
