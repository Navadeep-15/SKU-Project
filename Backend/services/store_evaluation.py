from datetime import date, datetime, time, timezone

import pandas as pd

from config import REFERENCE_DATE
from Backend.evaluation.forecast_evaluator import evaluate_forecasts, get_holdout_origins
from Backend.forecasting.forecast_engine import generate_forecast_data
from Backend.replenishment.replenishment_engine import (
    calculate_required_forecast_horizon,
    create_recommendations,
)


def _as_date(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def active_store_sku_ids(store_data, store_id, as_of=REFERENCE_DATE):
    stores = store_data["Store"].loc[
        store_data["Store"]["store_id"].eq(store_id)
    ]
    if stores.empty or not bool(stores.iloc[0]["active_flag"]):
        return []

    skus = store_data["SKU"].set_index("sku_id")
    assortment = store_data["StoreSKU"].loc[
        store_data["StoreSKU"]["store_id"].eq(store_id)
    ]
    active_ids = []
    for row in assortment.itertuples(index=False):
        sku = skus.loc[row.sku_id]
        launch_date = _as_date(sku["launch_date"])
        discontinue_date = _as_date(sku["discontinue_date"])
        active_from = _as_date(row.active_from)
        active_to = _as_date(row.active_to)
        if (
            row.assortment_status == "ACTIVE"
            and active_from is not None
            and active_from <= as_of
            and (active_to is None or as_of < active_to)
            and sku["lifecycle_state"] != "DISCONTINUED"
            and launch_date is not None
            and launch_date <= as_of
            and (discontinue_date is None or as_of < discontinue_date)
        ):
            active_ids.append(row.sku_id)
    return sorted(set(active_ids))


def prepare_store_scope(tables, store_id, sku_ids=None):
    store = tables["Store"].loc[tables["Store"]["store_id"].eq(store_id)].copy()
    if len(store) != 1:
        raise ValueError(f"Expected one Store row for {store_id}.")

    assortment = tables["StoreSKU"].loc[
        tables["StoreSKU"]["store_id"].eq(store_id)
    ].copy()
    available_sku_ids = set(assortment["sku_id"])
    selected_sku_ids = (
        available_sku_ids
        if sku_ids is None
        else set(sku_ids)
    )
    if not selected_sku_ids:
        raise ValueError("Select at least one SKU in this store's assortment.")
    if not selected_sku_ids.issubset(available_sku_ids):
        raise ValueError("Selected SKUs must belong to the chosen store.")

    assortment = assortment.loc[
        assortment["sku_id"].isin(selected_sku_ids)
    ].copy()
    skus = tables["SKU"].loc[
        tables["SKU"]["sku_id"].isin(selected_sku_ids)
    ].copy()
    supplier_skus = tables["SupplierSKU"].loc[
        tables["SupplierSKU"]["sku_id"].isin(selected_sku_ids)
    ].copy()
    supplier_ids = set(supplier_skus["supplier_id"])
    suppliers = tables["Supplier"].loc[
        tables["Supplier"]["supplier_id"].isin(supplier_ids)
    ].copy()

    inventory_data = {
        "InventorySnapshot": tables["InventorySnapshot"].loc[
            tables["InventorySnapshot"]["store_id"].eq(store_id)
        ].copy(),
        "InventoryEvent": tables["InventoryEvent"].loc[
            tables["InventoryEvent"]["store_id"].eq(store_id)
        ].copy(),
        "ReorderPolicy": tables["ReorderPolicy"].loc[
            tables["ReorderPolicy"]["store_id"].eq(store_id)
            & tables["ReorderPolicy"]["sku_id"].isin(selected_sku_ids)
        ].copy(),
    }
    sales_history = tables["SalesHistory"].loc[
        tables["SalesHistory"]["store_id"].eq(store_id)
        & tables["SalesHistory"]["sku_id"].isin(selected_sku_ids)
    ].copy()

    return (
        {
            "Store": store,
            "SKU": skus,
            "StoreSKU": assortment,
            "Supplier": suppliers,
            "SupplierSKU": supplier_skus,
        },
        inventory_data,
        sales_history,
    )


def align_latest_inventory_to_forecast_origin(
    inventory_data,
    forecast_origin=REFERENCE_DATE,
):
    """Use latest persisted stock with the existing historical forecast origin."""
    snapshots = inventory_data["InventorySnapshot"].copy(deep=True)
    events = inventory_data["InventoryEvent"].copy(deep=True)
    if snapshots.empty:
        return {
            "InventorySnapshot": snapshots,
            "InventoryEvent": events,
            "ReorderPolicy": inventory_data["ReorderPolicy"].copy(deep=True),
        }

    snapshots["_snapshot_date_sort"] = pd.to_datetime(
        snapshots["snapshot_date"],
        errors="raise",
    ).dt.date
    snapshots["_created_at_sort"] = pd.to_datetime(
        snapshots["created_at"],
        errors="coerce",
        utc=True,
    )
    snapshots = (
        snapshots.sort_values(
            [
                "_snapshot_date_sort",
                "_created_at_sort",
                "snapshot_id",
            ],
            kind="stable",
        )
        .drop_duplicates(["store_id", "sku_id"], keep="last")
        .copy()
    )
    event_dates = pd.to_datetime(events["event_date"], errors="raise").dt.date
    events = events.loc[event_dates <= forecast_origin].copy()
    ledger_balances = (
        events.groupby(["store_id", "sku_id"], sort=False)["quantity"]
        .sum()
        .to_dict()
    )
    used_event_ids = set(events["event_id"].astype(str))
    event_numbers = [
        int(event_id[4:])
        for event_id in used_event_ids
        if event_id.startswith("EVT-") and event_id[4:].isdigit()
    ]
    next_event_number = max(event_numbers, default=0) + 1
    synthetic_events = []
    synthetic_created_at = datetime.combine(
        forecast_origin,
        time.min,
        tzinfo=timezone.utc,
    )

    for snapshot in snapshots.itertuples(index=False):
        pair = (snapshot.store_id, snapshot.sku_id)
        delta = int(snapshot.on_hand) - int(ledger_balances.get(pair, 0))
        if delta == 0:
            continue
        if next_event_number > 99_999_999:
            raise ValueError("No unused event ID is available for evaluation.")
        synthetic_events.append(
            {
                "event_id": f"EVT-{next_event_number:08d}",
                "store_id": snapshot.store_id,
                "sku_id": snapshot.sku_id,
                "event_date": forecast_origin,
                "event_type": (
                    "ADJUSTMENT_IN" if delta > 0 else "ADJUSTMENT_OUT"
                ),
                "quantity": delta,
                "reference_id": (
                    f"EVAL-{forecast_origin:%Y%m%d}-"
                    f"{snapshot.store_id[-6:]}-{snapshot.sku_id[-6:]}"
                ),
                "created_at": synthetic_created_at,
            }
        )
        next_event_number += 1

    if synthetic_events:
        events = pd.concat(
            [events, pd.DataFrame(synthetic_events, columns=events.columns)],
            ignore_index=True,
        )

    snapshots["snapshot_date"] = forecast_origin
    snapshots["snapshot_id"] = snapshots.apply(
        lambda row: (
            f"INV-{row['store_id']}-{row['sku_id']}-{forecast_origin.isoformat()}"
        ),
        axis=1,
    )
    snapshots = snapshots.drop(
        columns=["_snapshot_date_sort", "_created_at_sort"]
    ).reset_index(drop=True)
    return {
        "InventorySnapshot": snapshots,
        "InventoryEvent": events.reset_index(drop=True),
        "ReorderPolicy": inventory_data["ReorderPolicy"].copy(deep=True),
    }


def evaluate_store(tables, store_id, sku_ids):
    selected_sku_ids = sorted(set(sku_ids))
    if not selected_sku_ids:
        raise ValueError("Select at least one active SKU to evaluate.")

    active_ids = set(active_store_sku_ids(tables, store_id))
    if not set(selected_sku_ids).issubset(active_ids):
        raise ValueError("Evaluation is limited to currently eligible store SKUs.")

    master_data, inventory_data, sales_history = prepare_store_scope(
        tables,
        store_id,
        selected_sku_ids,
    )
    inventory_data = align_latest_inventory_to_forecast_origin(inventory_data)
    ground_truth = tables["GroundTruthDemand"].loc[
        tables["GroundTruthDemand"]["store_id"].eq(store_id)
        & tables["GroundTruthDemand"]["sku_id"].isin(selected_sku_ids)
    ].copy()

    holdout_origins = get_holdout_origins()
    holdout_forecasts = generate_forecast_data(
        master_data,
        sales_history,
        holdout_origins,
    )
    _, initial_selection = evaluate_forecasts(
        holdout_forecasts,
        ground_truth,
        holdout_origins,
    )

    required_horizon = calculate_required_forecast_horizon(
        master_data,
        inventory_data,
        REFERENCE_DATE,
    )
    forecast_data = generate_forecast_data(
        master_data,
        sales_history,
        (*holdout_origins, REFERENCE_DATE),
        {
            (REFERENCE_DATE, initial_selection["selected_method"]):
                required_horizon,
        },
    )
    metrics, selection = evaluate_forecasts(
        forecast_data,
        ground_truth,
        holdout_origins,
    )
    if selection["selected_method"] != initial_selection["selected_method"]:
        raise RuntimeError(
            "Extending the current forecast horizon changed holdout selection."
        )

    replenishment_data, selected_run_id = create_recommendations(
        master_data,
        inventory_data,
        forecast_data,
        selection["selected_method"],
        REFERENCE_DATE,
    )
    return {
        "metrics": metrics,
        "selection": selection,
        "forecast_data": forecast_data,
        "replenishment_data": replenishment_data,
        "selected_run_id": selected_run_id,
        "required_horizon": required_horizon,
        "holdout_origins": holdout_origins,
        "store_id": store_id,
        "sku_ids": selected_sku_ids,
    }
