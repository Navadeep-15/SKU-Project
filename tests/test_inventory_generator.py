from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from config import RANDOM_SEED, REFERENCE_DATE
from Backend.data_generation.inventory_generator import (
    INVENTORY_EVENT_COLUMNS,
    INVENTORY_SNAPSHOT_COLUMNS,
    LEAD_TIME_OBSERVATION_COLUMNS,
    REORDER_POLICY_COLUMNS,
    _build_inventory_events,
    _build_inventory_snapshots,
    _build_lead_time_observations,
    _build_reorder_policies,
    export_inventory_data,
    generate_inventory_data,
    validate_inventory_data,
)
from Backend.data_generation.master_generator import generate_master_data
from Backend.data_generation.sales_generator import generate_sales_data


@pytest.fixture(scope="module")
def generated_inventory_data():
    master_data = generate_master_data("test")
    sales_data = generate_sales_data("test")
    inventory_data = generate_inventory_data("test")
    return master_data, sales_data, inventory_data


def _copy_inventory_data(data):
    return {
        table_name: frame.copy(deep=True)
        for table_name, frame in data.items()
    }


def test_generation_is_deterministic():
    first = generate_inventory_data("test")
    second = generate_inventory_data("test")

    for table_name in first:
        pd.testing.assert_frame_equal(first[table_name], second[table_name])


def test_schema_columns_and_foreign_keys(generated_inventory_data):
    master_data, sales_data, inventory_data = generated_inventory_data
    validate_inventory_data(
        inventory_data,
        master_data,
        sales_data,
        "test",
    )

    assert list(inventory_data["InventoryEvent"].columns) == INVENTORY_EVENT_COLUMNS
    assert (
        list(inventory_data["InventorySnapshot"].columns)
        == INVENTORY_SNAPSHOT_COLUMNS
    )
    assert (
        list(inventory_data["LeadTimeObservation"].columns)
        == LEAD_TIME_OBSERVATION_COLUMNS
    )
    assert (
        list(inventory_data["ReorderPolicy"].columns)
        == REORDER_POLICY_COLUMNS
    )
    assert inventory_data["InventoryEvent"]["store_id"].isin(
        master_data["Store"]["store_id"]
    ).all()
    assert inventory_data["InventoryEvent"]["sku_id"].isin(
        master_data["SKU"]["sku_id"]
    ).all()
    assert inventory_data["LeadTimeObservation"]["supplier_sku_id"].isin(
        master_data["SupplierSKU"]["supplier_sku_id"]
    ).all()


def test_sale_events_reconcile_with_positive_sales(generated_inventory_data):
    _, sales_data, inventory_data = generated_inventory_data
    positive_sales = sales_data["SalesHistory"].query("units_sold > 0")
    sale_events = inventory_data["InventoryEvent"].query("event_type == 'SALE'")

    assert len(sale_events) == len(positive_sales)
    reconciled = positive_sales.merge(
        sale_events,
        left_on="sales_id",
        right_on="reference_id",
        how="left",
        validate="one_to_one",
        suffixes=("_sales", "_event"),
        indicator=True,
    )
    assert (reconciled["_merge"] == "both").all()
    assert (reconciled["quantity"] == -reconciled["units_sold"]).all()
    assert (reconciled["event_date"] == reconciled["sales_date"]).all()


def test_running_inventory_and_capacity_at_every_positive_event(
    generated_inventory_data,
):
    master_data, _, inventory_data = generated_inventory_data
    capacities = master_data["Store"].set_index("store_id")["capacity_units"].to_dict()
    balances = defaultdict(int)
    store_totals = defaultdict(int)

    for event in inventory_data["InventoryEvent"].itertuples(index=False):
        relationship = (event.store_id, event.sku_id)
        balances[relationship] += int(event.quantity)
        store_totals[event.store_id] += int(event.quantity)

        assert balances[relationship] >= 0
        if event.quantity > 0:
            assert store_totals[event.store_id] <= capacities[event.store_id]


def test_stockout_days_reconcile_and_use_adjustment_events(
    generated_inventory_data,
):
    _, sales_data, inventory_data = generated_inventory_data
    stockout_sales = sales_data["SalesHistory"].query("stockout_flag")
    events = inventory_data["InventoryEvent"]
    balances = defaultdict(int)
    pre_sale_balances = {}

    for event in events.itertuples(index=False):
        relationship = (event.store_id, event.sku_id)
        if event.event_type == "SALE":
            pre_sale_balances[event.reference_id] = balances[relationship]
        balances[relationship] += int(event.quantity)

    positive_stockouts = stockout_sales.query("units_sold > 0")
    for sale in positive_stockouts.itertuples(index=False):
        assert pre_sale_balances[sale.sales_id] == sale.units_sold

    zero_sales_stockouts = stockout_sales.query("units_sold == 0")
    for sale in zero_sales_stockouts.itertuples(index=False):
        balance_at_close = events.loc[
            (events["store_id"] == sale.store_id)
            & (events["sku_id"] == sale.sku_id)
            & (events["event_date"] <= sale.sales_date),
            "quantity",
        ].sum()
        assert balance_at_close == 0

    reconciliation_adjustments = events[
        (events["event_type"] == "ADJUSTMENT_OUT")
        & events["reference_id"].str.startswith("STOCKOUT-RECON-")
    ]
    assert not positive_stockouts.empty
    assert not zero_sales_stockouts.empty
    assert not reconciliation_adjustments.empty


def test_snapshots_reconcile_and_include_month_end_and_reference_date(
    generated_inventory_data,
):
    _, _, inventory_data = generated_inventory_data
    events = inventory_data["InventoryEvent"]
    snapshots = inventory_data["InventorySnapshot"]
    assert snapshots["on_order"].eq(0).all()
    assert snapshots["reserved"].eq(0).all()
    assert snapshots["backorders"].eq(0).all()

    for snapshot in snapshots.itertuples(index=False):
        ledger_balance = int(
            events.loc[
                (events["store_id"] == snapshot.store_id)
                & (events["sku_id"] == snapshot.sku_id)
                & (events["event_date"] <= snapshot.snapshot_date),
                "quantity",
            ].sum()
        )
        assert snapshot.on_hand == ledger_balance

    current_snapshots = snapshots[snapshots["snapshot_date"] == REFERENCE_DATE]
    assert not current_snapshots.empty


def test_lead_time_observations_and_reorder_policies_are_valid(
    generated_inventory_data,
):
    master_data, _, inventory_data = generated_inventory_data
    observations = inventory_data["LeadTimeObservation"]
    supplier_skus = master_data["SupplierSKU"].set_index("supplier_sku_id")

    assert (observations["receipt_date"] >= observations["order_date"]).all()
    assert (
        observations["lead_time_days"]
        == [
            (receipt_date - order_date).days
            for receipt_date, order_date in zip(
                observations["receipt_date"],
                observations["order_date"],
            )
        ]
    ).all()
    assert observations["issue_type"].isin(
        {"NORMAL", "SUPPLIER_DELAY", "EARLY_DELIVERY"}
    ).all()
    assert observations["supplier_sku_id"].isin(supplier_skus.index).all()

    policies = inventory_data["ReorderPolicy"]
    assert policies["review_period_days"].eq(7).all()
    assert policies["reorder_method"].eq("PERIODIC_REVIEW").all()
    assert policies["safety_stock"].ge(0).all()
    assert policies["effective_to"].isna().all() or (
        policies["effective_to"].isna()
        | (policies["effective_to"] > policies["effective_from"])
    ).all()
    assert not policies.duplicated(["store_id", "sku_id"]).any()


def test_events_and_snapshots_stay_within_lifecycle_dates(
    generated_inventory_data,
):
    master_data, _, inventory_data = generated_inventory_data
    relationship_dates = master_data["StoreSKU"][
        ["store_id", "sku_id", "active_from", "active_to"]
    ]
    sku_dates = master_data["SKU"][
        ["sku_id", "launch_date", "discontinue_date"]
    ]
    for table_name, date_column in (
        ("InventoryEvent", "event_date"),
        ("InventorySnapshot", "snapshot_date"),
    ):
        records = (
            inventory_data[table_name]
            .merge(
                relationship_dates,
                on=["store_id", "sku_id"],
                validate="many_to_one",
            )
            .merge(sku_dates, on="sku_id", validate="many_to_one")
        )
        assert (records[date_column] >= records["active_from"]).all()
        assert (records[date_column] >= records["launch_date"]).all()
        assert (
            records["active_to"].isna()
            | (records[date_column] < records["active_to"])
        ).all()
        assert (
            records["discontinue_date"].isna()
            | (records[date_column] < records["discontinue_date"])
        ).all()


def test_ended_assortments_are_cleared_after_their_final_sales_day(
    generated_inventory_data,
):
    master_data, sales_data, inventory_data = generated_inventory_data
    sales = sales_data["SalesHistory"]
    events = inventory_data["InventoryEvent"]
    skus = master_data["SKU"].set_index("sku_id")
    closure_events = events[
        events["reference_id"].str.startswith("ASSORT-CLOSE-")
    ]
    ended_relationship_count = 0

    for assortment in master_data["StoreSKU"].itertuples(index=False):
        sku = skus.loc[assortment.sku_id]
        end_dates = [
            value
            for value in (assortment.active_to, sku["discontinue_date"])
            if not pd.isna(value)
        ]
        if not end_dates or min(end_dates) > REFERENCE_DATE:
            continue

        relationship_sales = sales[
            (sales["store_id"] == assortment.store_id)
            & (sales["sku_id"] == assortment.sku_id)
        ]
        if relationship_sales.empty:
            continue

        ended_relationship_count += 1
        final_sales_date = relationship_sales["sales_date"].max()
        effective_end = min(end_dates)
        assert final_sales_date < effective_end

        relationship_events = events[
            (events["store_id"] == assortment.store_id)
            & (events["sku_id"] == assortment.sku_id)
        ]
        assert (relationship_events["event_date"] < effective_end).all()
        ending_balance = relationship_events.loc[
            relationship_events["event_date"] <= final_sales_date,
            "quantity",
        ].sum()
        assert ending_balance == 0

        relationship_closures = closure_events[
            (closure_events["store_id"] == assortment.store_id)
            & (closure_events["sku_id"] == assortment.sku_id)
        ]
        assert (
            relationship_closures["event_date"] == final_sales_date
        ).all()
        assert relationship_closures["event_type"].eq("ADJUSTMENT_OUT").all()
        assert relationship_closures["quantity"].lt(0).all()

    assert ended_relationship_count > 0

    assortments_at_reference = master_data["StoreSKU"].merge(
        master_data["SKU"][["sku_id", "discontinue_date"]],
        on="sku_id",
    )
    active_mask = (
        (assortments_at_reference["assortment_status"] == "ACTIVE")
        & (assortments_at_reference["active_from"] <= REFERENCE_DATE)
        & (
            assortments_at_reference["active_to"].isna()
            | (assortments_at_reference["active_to"] > REFERENCE_DATE)
        )
        & (
            assortments_at_reference["discontinue_date"].isna()
            | (assortments_at_reference["discontinue_date"] > REFERENCE_DATE)
        )
    )
    active_relationships = set(
        zip(
            assortments_at_reference.loc[active_mask, "store_id"],
            assortments_at_reference.loc[active_mask, "sku_id"],
        )
    )
    closure_relationships = set(
        zip(closure_events["store_id"], closure_events["sku_id"])
    )
    assert not active_relationships.intersection(closure_relationships)


def test_remaining_inventory_gets_close_adjustment(generated_inventory_data):
    original_master, original_sales_data, _ = generated_inventory_data
    master_data = {
        table_name: frame.copy(deep=True)
        for table_name, frame in original_master.items()
    }
    sales_data = _copy_inventory_data(original_sales_data)
    skus = master_data["SKU"].set_index("sku_id")
    selected_relationship = None

    for assortment in master_data["StoreSKU"].itertuples(index=False):
        sku = skus.loc[assortment.sku_id]
        end_dates = [
            value
            for value in (assortment.active_to, sku["discontinue_date"])
            if not pd.isna(value)
        ]
        if not end_dates or min(end_dates) > REFERENCE_DATE:
            continue

        relationship_sales = sales_data["SalesHistory"][
            (sales_data["SalesHistory"]["store_id"] == assortment.store_id)
            & (sales_data["SalesHistory"]["sku_id"] == assortment.sku_id)
        ]
        if not relationship_sales.empty:
            selected_relationship = (assortment.store_id, assortment.sku_id)
            original_end = min(end_dates)
            last_sales_date = relationship_sales["sales_date"].max()
            break

    assert selected_relationship is not None
    store_id, sku_id = selected_relationship
    final_sales_date = last_sales_date - timedelta(days=last_sales_date.weekday())
    exclusive_end = final_sales_date + timedelta(days=1)
    assert exclusive_end <= original_end

    assortment_mask = (
        (master_data["StoreSKU"]["store_id"] == store_id)
        & (master_data["StoreSKU"]["sku_id"] == sku_id)
    )
    master_data["StoreSKU"].loc[assortment_mask, "active_to"] = exclusive_end

    sales = sales_data["SalesHistory"]
    sales_mask = (sales["store_id"] == store_id) & (sales["sku_id"] == sku_id)
    sales_data["SalesHistory"] = sales.loc[
        ~(
            sales_mask
            & (sales["sales_date"] >= exclusive_end)
        )
    ].copy()
    ground_truth = sales_data["GroundTruthDemand"]
    truth_mask = (
        (ground_truth["store_id"] == store_id)
        & (ground_truth["sku_id"] == sku_id)
    )
    sales_data["GroundTruthDemand"] = ground_truth.loc[
        ~(
            truth_mask
            & (ground_truth["demand_date"] >= exclusive_end)
        )
    ].copy()

    final_sales = sales_data["SalesHistory"]
    final_index = final_sales.index[
        (final_sales["store_id"] == store_id)
        & (final_sales["sku_id"] == sku_id)
        & (final_sales["sales_date"] == final_sales_date)
    ][0]
    final_sale = final_sales.loc[final_index]
    final_sales.loc[final_index, "stockout_flag"] = False

    final_truth = sales_data["GroundTruthDemand"]
    truth_index = final_truth.index[
        (final_truth["store_id"] == store_id)
        & (final_truth["sku_id"] == sku_id)
        & (final_truth["demand_date"] == final_sales_date)
    ][0]
    final_truth.loc[
        truth_index,
        ["actual_demand", "observed_sales", "stockout_impact", "stockout_flag"],
    ] = [int(final_sale["units_sold"]), int(final_sale["units_sold"]), 0, False]

    rng = np.random.default_rng(RANDOM_SEED)
    events = _build_inventory_events(
        master_data,
        sales_data["SalesHistory"],
        rng,
    )
    inventory_data = {
        "InventoryEvent": events,
        "InventorySnapshot": _build_inventory_snapshots(
            master_data,
            sales_data["SalesHistory"],
            events,
        ),
        "LeadTimeObservation": _build_lead_time_observations(master_data, rng),
        "ReorderPolicy": _build_reorder_policies(master_data, rng),
    }
    validate_inventory_data(inventory_data, master_data, sales_data, "test")

    closure_event = events[
        (events["store_id"] == store_id)
        & (events["sku_id"] == sku_id)
        & events["reference_id"].str.startswith("ASSORT-CLOSE-")
    ]
    assert len(closure_event) == 1
    assert closure_event.iloc[0]["event_date"] == final_sales_date
    assert closure_event.iloc[0]["event_date"] < exclusive_end
    assert closure_event.iloc[0]["event_type"] == "ADJUSTMENT_OUT"
    assert closure_event.iloc[0]["quantity"] < 0
    assert events.loc[
        (events["store_id"] == store_id)
        & (events["sku_id"] == sku_id)
        & (events["event_date"] <= final_sales_date),
        "quantity",
    ].sum() == 0


def test_csv_export_writes_schema_columns(tmp_path, generated_inventory_data):
    _, _, inventory_data = generated_inventory_data
    export_inventory_data(inventory_data, tmp_path)

    for table_name, expected_columns in (
        ("InventoryEvent", INVENTORY_EVENT_COLUMNS),
        ("InventorySnapshot", INVENTORY_SNAPSHOT_COLUMNS),
        ("LeadTimeObservation", LEAD_TIME_OBSERVATION_COLUMNS),
        ("ReorderPolicy", REORDER_POLICY_COLUMNS),
    ):
        exported = pd.read_csv(tmp_path / f"{table_name}.csv")
        assert list(exported.columns) == expected_columns
        assert len(exported) == len(inventory_data[table_name])


def test_validation_rejects_capacity_violation(generated_inventory_data):
    master_data, sales_data, inventory_data = generated_inventory_data
    invalid_data = _copy_inventory_data(inventory_data)
    stores = master_data["Store"].set_index("store_id")
    first_event = invalid_data["InventoryEvent"].iloc[0]
    capacity = int(stores.loc[first_event["store_id"], "capacity_units"])
    invalid_data["InventoryEvent"].loc[0, "quantity"] = capacity + 1

    with pytest.raises(ValueError, match="capacity exceeded"):
        validate_inventory_data(invalid_data, master_data, sales_data, "test")
