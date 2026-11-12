import argparse
from bisect import bisect_right
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    DATASET_VERSION,
    DEFAULT_PROFILE,
    PROFILES,
    RANDOM_SEED,
    REFERENCE_DATE,
    SALES_START_DATE,
)
from Backend.data_generation.master_generator import (
    EXPORT_DIRECTORY,
    generate_master_data,
)
from Backend.data_generation.sales_generator import (
    generate_sales_data,
    validate_sales_data,
)


INVENTORY_EVENT_COLUMNS = [
    "event_id",
    "store_id",
    "sku_id",
    "event_date",
    "event_type",
    "quantity",
    "reference_id",
    "created_at",
]

INVENTORY_SNAPSHOT_COLUMNS = [
    "snapshot_id",
    "store_id",
    "sku_id",
    "snapshot_date",
    "on_hand",
    "on_order",
    "reserved",
    "backorders",
    "created_at",
]

LEAD_TIME_OBSERVATION_COLUMNS = [
    "observation_id",
    "supplier_sku_id",
    "order_date",
    "receipt_date",
    "lead_time_days",
    "issue_type",
    "created_at",
]

REORDER_POLICY_COLUMNS = [
    "policy_id",
    "store_id",
    "sku_id",
    "review_period_days",
    "service_level",
    "safety_stock",
    "reorder_method",
    "effective_from",
    "effective_to",
    "created_at",
]

INVENTORY_EVENT_TYPES = {
    "RECEIPT",
    "ADJUSTMENT_IN",
    "TRANSFER_IN",
    "SALE",
    "ADJUSTMENT_OUT",
    "SCRAP",
    "TRANSFER_OUT",
}
POSITIVE_EVENT_TYPES = {"RECEIPT", "ADJUSTMENT_IN", "TRANSFER_IN"}
NEGATIVE_EVENT_TYPES = {
    "SALE",
    "ADJUSTMENT_OUT",
    "SCRAP",
    "TRANSFER_OUT",
}
LEAD_TIME_ISSUE_TYPES = {"NORMAL", "SUPPLIER_DELAY", "EARLY_DELIVERY"}
REORDER_METHOD = "PERIODIC_REVIEW"
REVIEW_PERIOD_DAYS = 7
EVENT_ID_PATTERN = r"EVT-[0-9]{8}"
SNAPSHOT_ID_PATTERN = (
    r"INV-STORE-[0-9]{6}-SKU-[0-9]{6}-[0-9]{4}-[0-9]{2}-[0-9]{2}"
)
LEAD_TIME_ID_PATTERN = r"LTO-[0-9]{6}"
REORDER_POLICY_ID_PATTERN = r"POL-[0-9]{6}"
CREATED_AT = datetime.combine(
    REFERENCE_DATE,
    time.min,
    tzinfo=timezone.utc,
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _date_or_none(value):
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date()
    return value


def _month_end_dates(start_date, end_date):
    dates = []
    year = start_date.year
    month = start_date.month

    while (year, month) <= (end_date.year, end_date.month):
        month_end = date(year, month, monthrange(year, month)[1])
        if start_date <= month_end <= end_date:
            dates.append(month_end)

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    return dates


def _relationship_is_current(assortment, sku, store):
    assortment_end = _date_or_none(assortment.active_to)
    discontinue_date = _date_or_none(sku.discontinue_date)
    return (
        bool(store.active_flag)
        and assortment.assortment_status == "ACTIVE"
        and sku.lifecycle_state != "DISCONTINUED"
        and assortment.active_from <= REFERENCE_DATE
        and (assortment_end is None or assortment_end > REFERENCE_DATE)
        and (discontinue_date is None or discontinue_date > REFERENCE_DATE)
    )


def _eligible_assortments(master_data):
    skus = master_data["SKU"].set_index("sku_id")
    stores = master_data["Store"].set_index("store_id")
    eligible = []

    for assortment in master_data["StoreSKU"].itertuples(index=False):
        sku = skus.loc[assortment.sku_id]
        store = stores.loc[assortment.store_id]
        if not bool(store["active_flag"]):
            continue
        if assortment.assortment_status not in {"ACTIVE", "DISCONTINUED"}:
            continue
        if assortment.active_from > REFERENCE_DATE:
            continue
        if sku["launch_date"] > REFERENCE_DATE:
            continue

        assortment_end = _date_or_none(assortment.active_to)
        discontinue_date = _date_or_none(sku["discontinue_date"])
        end_dates = [
            value
            for value in (assortment_end, discontinue_date)
            if value is not None
        ]
        effective_to = min(end_dates) if end_dates else None
        effective_from = max(assortment.active_from, sku["launch_date"])
        if effective_to is not None and effective_to <= effective_from:
            continue

        eligible.append(
            {
                "store_id": assortment.store_id,
                "sku_id": assortment.sku_id,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "assortment": assortment,
                "sku": sku,
                "store": store,
            }
        )

    return sorted(
        eligible,
        key=lambda relationship: (
            relationship["store_id"],
            relationship["sku_id"],
            relationship["effective_from"],
        ),
    )


def _relationship_end_dates(master_data):
    skus = master_data["SKU"].set_index("sku_id")
    end_dates = {}

    for assortment in master_data["StoreSKU"].itertuples(index=False):
        sku = skus.loc[assortment.sku_id]
        effective_ends = [
            value
            for value in (
                _date_or_none(assortment.active_to),
                _date_or_none(sku["discontinue_date"]),
            )
            if value is not None
        ]
        if effective_ends:
            end_dates[(assortment.store_id, assortment.sku_id)] = min(
                effective_ends
            )

    return end_dates


def _build_inventory_events(master_data, sales_history, rng):
    stores = master_data["Store"].set_index("store_id")
    capacities = {
        store_id: int(row["capacity_units"])
        for store_id, row in stores.iterrows()
    }
    sales = sales_history.sort_values(
        ["sales_date", "store_id", "sku_id"],
        kind="mergesort",
    ).reset_index(drop=True)

    relationship_counts = (
        sales[["store_id", "sku_id"]]
        .drop_duplicates()
        .groupby("store_id")
        .size()
        .to_dict()
    )
    opening_targets = {}
    last_sales_dates = {}
    for (store_id, sku_id), group in sales.groupby(
        ["store_id", "sku_id"],
        sort=True,
    ):
        coverage_days = int(rng.integers(3, 8))
        planned_units = int(group["units_sold"].head(coverage_days).sum())
        capacity_share = max(
            1,
            capacities[store_id] // (4 * relationship_counts[store_id]),
        )
        opening_targets[(store_id, sku_id)] = min(
            max(1, planned_units),
            capacity_share,
        )
        last_sales_dates[(store_id, sku_id)] = max(
            _date_or_none(value) for value in group["sales_date"]
        )

    closure_dates = {}
    for relationship, effective_end in _relationship_end_dates(master_data).items():
        last_sales_date = last_sales_dates.get(relationship)
        if (
            effective_end <= REFERENCE_DATE
            and last_sales_date is not None
            and last_sales_date < effective_end
        ):
            closure_dates[relationship] = last_sales_date
    closures_by_store_date = {}
    for relationship, closure_date in closure_dates.items():
        key = (relationship[0], closure_date)
        closures_by_store_date.setdefault(key, []).append(relationship)
    for relationships in closures_by_store_date.values():
        relationships.sort()

    event_rows = []
    balances = {}
    store_totals = {store_id: 0 for store_id in capacities}
    recent_sales = {}
    opened_relationships = set()
    last_event_date = None

    def add_event(store_id, sku_id, event_date, event_type, quantity, reference_id):
        nonlocal last_event_date

        quantity = int(quantity)
        _require(quantity != 0, "InventoryEvent quantity cannot be zero.")
        _require(
            (event_type in POSITIVE_EVENT_TYPES and quantity > 0)
            or (event_type in NEGATIVE_EVENT_TYPES and quantity < 0),
            f"Invalid quantity sign for {event_type}.",
        )
        _require(
            len(reference_id) <= 50 and bool(reference_id),
            "InventoryEvent reference_id must contain 1 to 50 characters.",
        )
        _require(
            last_event_date is None or event_date >= last_event_date,
            "Inventory events must be generated chronologically.",
        )

        relationship = (store_id, sku_id)
        new_balance = balances.get(relationship, 0) + quantity
        _require(new_balance >= 0, "Inventory balance cannot become negative.")

        new_store_total = store_totals[store_id] + quantity
        if quantity > 0:
            _require(
                new_store_total <= capacities[store_id],
                f"Store {store_id} capacity would be exceeded by {event_type}.",
            )

        event_number = len(event_rows) + 1
        _require(event_number <= 99_999_999, "InventoryEvent ID limit exceeded.")
        event_rows.append(
            (
                f"EVT-{event_number:08d}",
                store_id,
                sku_id,
                event_date,
                event_type,
                quantity,
                reference_id,
                CREATED_AT,
            )
        )
        balances[relationship] = new_balance
        store_totals[store_id] = new_store_total
        last_event_date = event_date

    for sales_date, date_rows in sales.groupby("sales_date", sort=True):
        sales_date = _date_or_none(sales_date)
        for store_id, store_rows in date_rows.groupby("store_id", sort=True):
            for sale in store_rows.itertuples(index=False):
                relationship = (sale.store_id, sale.sku_id)
                units_sold = int(sale.units_sold)
                current_balance = balances.get(relationship, 0)

                if relationship not in opened_relationships:
                    opening_units = opening_targets[relationship]
                    add_event(
                        sale.store_id,
                        sale.sku_id,
                        sales_date,
                        "RECEIPT",
                        opening_units,
                        (
                            f"OPENING-RECEIPT-{sale.store_id}-{sale.sku_id}-"
                            f"{sales_date.isoformat()}"
                        ),
                    )
                    opened_relationships.add(relationship)
                    current_balance = balances[relationship]

                if bool(sale.stockout_flag):
                    if current_balance > units_sold:
                        add_event(
                            sale.store_id,
                            sale.sku_id,
                            sales_date,
                            "ADJUSTMENT_OUT",
                            units_sold - current_balance,
                            (
                                f"STOCKOUT-RECON-{sale.store_id}-{sale.sku_id}-"
                                f"{sales_date.isoformat()}"
                            ),
                        )
                    elif current_balance < units_sold:
                        add_event(
                            sale.store_id,
                            sale.sku_id,
                            sales_date,
                            "RECEIPT",
                            units_sold - current_balance,
                            (
                                f"STOCKOUT-RECON-{sale.store_id}-{sale.sku_id}-"
                                f"{sales_date.isoformat()}"
                            ),
                        )
                elif current_balance < units_sold:
                    add_event(
                        sale.store_id,
                        sale.sku_id,
                        sales_date,
                        "RECEIPT",
                        units_sold - current_balance,
                        f"SALE-COVER-{sale.sales_id}",
                    )

                if units_sold > 0:
                    add_event(
                        sale.store_id,
                        sale.sku_id,
                        sales_date,
                        "SALE",
                        -units_sold,
                        sale.sales_id,
                    )

                if relationship not in recent_sales:
                    recent_sales[relationship] = []
                recent_sales[relationship].append(units_sold)
                if len(recent_sales[relationship]) > 7:
                    recent_sales[relationship].pop(0)

            if sales_date.weekday() == 0:
                replenishment_limit = max(
                    1,
                    int(capacities[store_id] * 0.8),
                )
                for sale in store_rows.itertuples(index=False):
                    if bool(sale.stockout_flag):
                        continue

                    relationship = (sale.store_id, sale.sku_id)
                    target_units = sum(recent_sales[relationship])
                    current_balance = balances.get(relationship, 0)
                    available_capacity = max(
                        0,
                        replenishment_limit - store_totals[store_id],
                    )
                    replenishment_units = min(
                        max(0, target_units - current_balance),
                        available_capacity,
                    )
                    if replenishment_units > 0:
                        add_event(
                            sale.store_id,
                            sale.sku_id,
                            sales_date,
                            "RECEIPT",
                            replenishment_units,
                            (
                                f"REPLENISH-{sale.store_id}-{sale.sku_id}-"
                                f"{sales_date.isoformat()}"
                            ),
                        )

            for relationship in closures_by_store_date.get(
                (store_id, sales_date),
                [],
            ):
                remaining_units = balances.get(relationship, 0)
                if remaining_units > 0:
                    add_event(
                        relationship[0],
                        relationship[1],
                        sales_date,
                        "ADJUSTMENT_OUT",
                        -remaining_units,
                        (
                            f"ASSORT-CLOSE-{relationship[0]}-{relationship[1]}-"
                            f"{sales_date.isoformat()}"
                        ),
                    )

    return pd.DataFrame(event_rows, columns=INVENTORY_EVENT_COLUMNS)


def _build_inventory_snapshots(master_data, sales_history, inventory_events):
    skus = master_data["SKU"].set_index("sku_id")
    stores = master_data["Store"].set_index("store_id")
    assortments = master_data["StoreSKU"].set_index(["store_id", "sku_id"])
    event_balances = _daily_event_balances(inventory_events)
    rows = []

    for (store_id, sku_id), group in sales_history.groupby(
        ["store_id", "sku_id"],
        sort=True,
    ):
        start_date = min(_date_or_none(value) for value in group["sales_date"])
        end_date = max(_date_or_none(value) for value in group["sales_date"])
        snapshot_dates = set(_month_end_dates(start_date, end_date))

        assortment = assortments.loc[(store_id, sku_id)]
        sku = skus.loc[sku_id]
        store = stores.loc[store_id]
        if _relationship_is_current(assortment, sku, store):
            snapshot_dates.add(REFERENCE_DATE)

        for snapshot_date in sorted(snapshot_dates):
            on_hand = _balance_for_date(
                event_balances,
                store_id,
                sku_id,
                snapshot_date,
            )
            rows.append(
                (
                    (
                        f"INV-{store_id}-{sku_id}-"
                        f"{snapshot_date.isoformat()}"
                    ),
                    store_id,
                    sku_id,
                    snapshot_date,
                    on_hand,
                    0,
                    0,
                    0,
                    CREATED_AT,
                )
            )

    return pd.DataFrame(rows, columns=INVENTORY_SNAPSHOT_COLUMNS)


def _eligible_supplier_skus(master_data):
    skus = master_data["SKU"].set_index("sku_id")
    suppliers = master_data["Supplier"].set_index("supplier_id")
    eligible = []

    for supplier_sku in master_data["SupplierSKU"].itertuples(index=False):
        sku = skus.loc[supplier_sku.sku_id]
        supplier = suppliers.loc[supplier_sku.supplier_id]
        if not bool(supplier["active_flag"]):
            continue

        start_date = max(
            _date_or_none(supplier_sku.active_from),
            _date_or_none(sku["launch_date"]),
            SALES_START_DATE,
        )
        end_dates = [
            value
            for value in (
                _date_or_none(supplier_sku.active_to),
                _date_or_none(sku["discontinue_date"]),
                REFERENCE_DATE + timedelta(days=1),
            )
            if value is not None
        ]
        end_exclusive = min(end_dates)
        if start_date >= end_exclusive:
            continue

        eligible.append(
            {
                "supplier_sku": supplier_sku,
                "sku": sku,
                "start_date": start_date,
                "last_date": end_exclusive - timedelta(days=1),
            }
        )

    return sorted(
        eligible,
        key=lambda relationship: relationship["supplier_sku"].supplier_sku_id,
    )


def _build_lead_time_observations(master_data, rng):
    rows = []
    for index, relationship in enumerate(
        _eligible_supplier_skus(master_data),
        start=1,
    ):
        _require(index <= 999_999, "LeadTimeObservation ID limit exceeded.")
        supplier_sku = relationship["supplier_sku"]
        start_date = relationship["start_date"]
        last_date = relationship["last_date"]
        available_days = (last_date - start_date).days
        observed_lead_time = min(
            max(
                0,
                int(supplier_sku.lead_time_days) + int(rng.integers(-2, 3)),
            ),
            available_days,
        )

        latest_order_date = last_date - timedelta(days=observed_lead_time)
        order_offset = int(
            rng.integers(0, (latest_order_date - start_date).days + 1)
        )
        order_date = start_date + timedelta(days=order_offset)
        receipt_date = order_date + timedelta(days=observed_lead_time)
        quoted_lead_time = int(supplier_sku.lead_time_days)

        if observed_lead_time > quoted_lead_time:
            issue_type = "SUPPLIER_DELAY"
        elif observed_lead_time < quoted_lead_time:
            issue_type = "EARLY_DELIVERY"
        else:
            issue_type = "NORMAL"

        rows.append(
            (
                f"LTO-{index:06d}",
                supplier_sku.supplier_sku_id,
                order_date,
                receipt_date,
                observed_lead_time,
                issue_type,
                CREATED_AT,
            )
        )

    return pd.DataFrame(rows, columns=LEAD_TIME_OBSERVATION_COLUMNS)


def _build_reorder_policies(master_data, rng):
    rows = []
    for index, relationship in enumerate(
        _eligible_assortments(master_data),
        start=1,
    ):
        _require(index <= 999_999, "ReorderPolicy ID limit exceeded.")
        rows.append(
            (
                f"POL-{index:06d}",
                relationship["store_id"],
                relationship["sku_id"],
                REVIEW_PERIOD_DAYS,
                float(rng.choice([0.90, 0.95, 0.98])),
                int(rng.integers(0, 6)),
                REORDER_METHOD,
                relationship["effective_from"],
                relationship["effective_to"],
                CREATED_AT,
            )
        )

    return pd.DataFrame(rows, columns=REORDER_POLICY_COLUMNS)


def _daily_event_balances(inventory_events):
    daily_changes = {}
    if inventory_events.empty:
        return {}

    for event in inventory_events.itertuples(index=False):
        key = (event.store_id, event.sku_id, _date_or_none(event.event_date))
        daily_changes[key] = daily_changes.get(key, 0) + int(event.quantity)

    balances_by_pair = {}
    for (store_id, sku_id, event_date), quantity in sorted(daily_changes.items()):
        relationship = (store_id, sku_id)
        if relationship not in balances_by_pair:
            balances_by_pair[relationship] = {"dates": [], "balances": []}
        prior_balance = (
            balances_by_pair[relationship]["balances"][-1]
            if balances_by_pair[relationship]["balances"]
            else 0
        )
        balances_by_pair[relationship]["dates"].append(event_date)
        balances_by_pair[relationship]["balances"].append(prior_balance + quantity)

    return balances_by_pair


def _balance_for_date(event_balances, store_id, sku_id, snapshot_date):
    relationship = event_balances.get((store_id, sku_id))
    if relationship is None:
        return 0

    index = bisect_right(relationship["dates"], snapshot_date) - 1
    return relationship["balances"][index] if index >= 0 else 0


def _expected_snapshot_keys(master_data, sales_history):
    skus = master_data["SKU"].set_index("sku_id")
    stores = master_data["Store"].set_index("store_id")
    assortments = master_data["StoreSKU"].set_index(["store_id", "sku_id"])
    expected = set()

    for (store_id, sku_id), group in sales_history.groupby(
        ["store_id", "sku_id"],
        sort=True,
    ):
        start_date = min(_date_or_none(value) for value in group["sales_date"])
        end_date = max(_date_or_none(value) for value in group["sales_date"])
        dates = set(_month_end_dates(start_date, end_date))

        assortment = assortments.loc[(store_id, sku_id)]
        if _relationship_is_current(
            assortment,
            skus.loc[sku_id],
            stores.loc[store_id],
        ):
            dates.add(REFERENCE_DATE)

        for snapshot_date in dates:
            expected.add((store_id, sku_id, snapshot_date))

    return expected


def _expected_policy_periods(master_data):
    return {
        (relationship["store_id"], relationship["sku_id"]): (
            relationship["effective_from"],
            relationship["effective_to"],
        )
        for relationship in _eligible_assortments(master_data)
    }


def _expected_lead_time_ids(master_data):
    return {
        relationship["supplier_sku"].supplier_sku_id
        for relationship in _eligible_supplier_skus(master_data)
    }


def _check_effective_periods(frame, relationship_columns, start_column, end_column):
    for relationship, group in frame.groupby(relationship_columns, sort=True):
        intervals = sorted(
            (
                (
                    _date_or_none(row[start_column]),
                    _date_or_none(row[end_column]),
                )
                for _, row in group.iterrows()
            ),
            key=lambda interval: interval[0],
        )
        prior_end = None
        for index, (start, end) in enumerate(intervals):
            _require(
                end is None or end > start,
                f"Invalid effective period for {relationship}.",
            )
            if index > 0:
                _require(
                    prior_end is not None and start >= prior_end,
                    f"Overlapping policy periods for {relationship}.",
                )
            prior_end = end


def validate_inventory_data(data, master_data, sales_data, profile_name):
    _require(profile_name in PROFILES, f"Unknown profile: {profile_name}")
    expected_tables = {
        "InventoryEvent",
        "InventorySnapshot",
        "LeadTimeObservation",
        "ReorderPolicy",
    }
    _require(set(data) == expected_tables, "Generated table set does not match schema.")
    _require(
        set(sales_data) == {"SalesHistory", "GroundTruthDemand"},
        "Sales data must contain SalesHistory and GroundTruthDemand.",
    )
    validate_sales_data(
        sales_data["SalesHistory"],
        sales_data["GroundTruthDemand"],
        master_data,
    )

    expected_columns = {
        "InventoryEvent": INVENTORY_EVENT_COLUMNS,
        "InventorySnapshot": INVENTORY_SNAPSHOT_COLUMNS,
        "LeadTimeObservation": LEAD_TIME_OBSERVATION_COLUMNS,
        "ReorderPolicy": REORDER_POLICY_COLUMNS,
    }
    for table_name, columns in expected_columns.items():
        _require(
            list(data[table_name].columns) == columns,
            f"{table_name} columns do not match Backend/database/schema.sql.",
        )

    events = data["InventoryEvent"]
    snapshots = data["InventorySnapshot"]
    observations = data["LeadTimeObservation"]
    policies = data["ReorderPolicy"]
    sales_history = sales_data["SalesHistory"]

    _require(
        len(events) <= 99_999_999,
        "InventoryEvent count exceeds the supported ID range.",
    )
    for table_name, frame, id_column, pattern, maximum in (
        (
            "InventoryEvent",
            events,
            "event_id",
            EVENT_ID_PATTERN,
            99_999_999,
        ),
        (
            "InventorySnapshot",
            snapshots,
            "snapshot_id",
            SNAPSHOT_ID_PATTERN,
            None,
        ),
        (
            "LeadTimeObservation",
            observations,
            "observation_id",
            LEAD_TIME_ID_PATTERN,
            999_999,
        ),
        (
            "ReorderPolicy",
            policies,
            "policy_id",
            REORDER_POLICY_ID_PATTERN,
            999_999,
        ),
    ):
        _require(
            not frame[id_column].duplicated().any(),
            f"Duplicate primary key in {table_name}.",
        )
        _require(
            frame[id_column].astype(str).str.fullmatch(pattern).all(),
            f"Invalid {id_column} format in {table_name}.",
        )
        if maximum is not None:
            _require(
                len(frame) <= maximum,
                f"{table_name} count exceeds the supported ID range.",
            )

    store_ids = set(master_data["Store"]["store_id"])
    sku_ids = set(master_data["SKU"]["sku_id"])
    supplier_sku_ids = set(master_data["SupplierSKU"]["supplier_sku_id"])
    _require(
        events["store_id"].isin(store_ids).all()
        and snapshots["store_id"].isin(store_ids).all()
        and policies["store_id"].isin(store_ids).all(),
        "Inventory data contains an invalid store foreign key.",
    )
    _require(
        events["sku_id"].isin(sku_ids).all()
        and snapshots["sku_id"].isin(sku_ids).all()
        and policies["sku_id"].isin(sku_ids).all(),
        "Inventory data contains an invalid SKU foreign key.",
    )
    _require(
        observations["supplier_sku_id"].isin(supplier_sku_ids).all(),
        "LeadTimeObservation contains an invalid SupplierSKU foreign key.",
    )

    sales_periods = {}
    for (store_id, sku_id), group in sales_history.groupby(
        ["store_id", "sku_id"],
        sort=True,
    ):
        sales_periods[(store_id, sku_id)] = (
            min(_date_or_none(value) for value in group["sales_date"]),
            max(_date_or_none(value) for value in group["sales_date"]),
        )
    relationship_end_dates = _relationship_end_dates(master_data)
    closure_dates = {}
    for relationship, effective_end in relationship_end_dates.items():
        period = sales_periods.get(relationship)
        if effective_end <= REFERENCE_DATE and period is not None:
            _require(
                period[1] < effective_end,
                "The final eligible sales day must precede the exclusive end date.",
            )
            closure_dates[relationship] = period[1]

    capacities = master_data["Store"].set_index("store_id")["capacity_units"].to_dict()
    balances = {}
    store_totals = {store_id: 0 for store_id in capacities}
    sale_events_by_reference = {}
    balance_before_sale = {}
    prior_event_date = None
    prior_event_number = 0

    for event in events.itertuples(index=False):
        event_number = int(event.event_id[4:])
        _require(
            event_number == prior_event_number + 1,
            "InventoryEvent IDs must be sequential and preserve event ordering.",
        )
        prior_event_number = event_number
        event_date = _date_or_none(event.event_date)
        _require(
            prior_event_date is None or event_date >= prior_event_date,
            "Inventory events are not in chronological order.",
        )
        prior_event_date = event_date
        _require(
            event.event_type in INVENTORY_EVENT_TYPES,
            f"Invalid InventoryEvent type: {event.event_type}.",
        )
        quantity = int(event.quantity)
        _require(quantity != 0, "InventoryEvent quantity cannot be zero.")
        _require(
            (event.event_type in POSITIVE_EVENT_TYPES and quantity > 0)
            or (event.event_type in NEGATIVE_EVENT_TYPES and quantity < 0),
            f"Invalid quantity sign for {event.event_type}.",
        )
        _require(
            bool(event.reference_id) and len(event.reference_id) <= 50,
            "InventoryEvent reference_id must contain 1 to 50 characters.",
        )

        relationship = (event.store_id, event.sku_id)
        effective_end = relationship_end_dates.get(relationship)
        if effective_end is not None:
            _require(
                event_date < effective_end,
                "InventoryEvent falls on or after an exclusive relationship end date.",
            )
        balance_before = balances.get(relationship, 0)
        if event.reference_id.startswith("ASSORT-CLOSE-"):
            _require(
                relationship in closure_dates
                and event_date == closure_dates[relationship]
                and event.event_type == "ADJUSTMENT_OUT"
                and quantity == -balance_before,
                "Invalid assortment-close adjustment.",
            )
        if event.event_type == "SALE":
            _require(
                event.reference_id not in sale_events_by_reference,
                "Duplicate SALE reference_id.",
            )
            sale_events_by_reference[event.reference_id] = event
            balance_before_sale[event.reference_id] = balance_before

        new_balance = balance_before + quantity
        _require(new_balance >= 0, "Inventory balance cannot become negative.")
        new_store_total = store_totals[event.store_id] + quantity
        if quantity > 0:
            _require(
                new_store_total <= int(capacities[event.store_id]),
                f"Store {event.store_id} capacity exceeded after a positive event.",
            )
        balances[relationship] = new_balance
        store_totals[event.store_id] = new_store_total

    positive_sales = sales_history[sales_history["units_sold"] > 0]
    _require(
        len(sale_events_by_reference) == len(positive_sales),
        "SALE event count does not match positive SalesHistory records.",
    )
    for sale in positive_sales.itertuples(index=False):
        event = sale_events_by_reference.get(sale.sales_id)
        _require(event is not None, f"Missing SALE event for {sale.sales_id}.")
        _require(
            event.store_id == sale.store_id
            and event.sku_id == sale.sku_id
            and _date_or_none(event.event_date) == _date_or_none(sale.sales_date)
            and int(event.quantity) == -int(sale.units_sold),
            f"SALE event does not reconcile with {sale.sales_id}.",
        )

    event_dates_by_pair = _daily_event_balances(events)
    for event in events.itertuples(index=False):
        period = sales_periods.get((event.store_id, event.sku_id))
        event_date = _date_or_none(event.event_date)
        _require(
            period is not None and period[0] <= event_date <= period[1],
            "InventoryEvent falls outside its eligible SKU-assortment period.",
        )

    for relationship, closure_date in closure_dates.items():
        _require(
            _balance_for_date(
                event_dates_by_pair,
                relationship[0],
                relationship[1],
                closure_date,
            )
            == 0,
            (
                "Inventory remains after the final eligible sales day for "
                f"{relationship[0]}/{relationship[1]}."
            ),
        )

    stockout_sales = sales_history[sales_history["stockout_flag"]]
    for sale in stockout_sales.itertuples(index=False):
        if int(sale.units_sold) > 0:
            _require(
                balance_before_sale[sale.sales_id] == int(sale.units_sold),
                f"Stockout pre-sale balance does not match {sale.sales_id}.",
            )
        else:
            daily_balance = _balance_for_date(
                event_dates_by_pair,
                sale.store_id,
                sale.sku_id,
                _date_or_none(sale.sales_date),
            )
            _require(
                daily_balance == 0,
                f"Zero-sales stockout did not reconcile to zero for {sale.sales_id}.",
            )

    expected_snapshot_keys = _expected_snapshot_keys(master_data, sales_history)
    snapshot_keys = {
        (
            row.store_id,
            row.sku_id,
            _date_or_none(row.snapshot_date),
        )
        for row in snapshots.itertuples(index=False)
    }
    _require(
        len(snapshot_keys) == len(snapshots),
        "Duplicate InventorySnapshot store/SKU/date record.",
    )
    _require(
        snapshot_keys == expected_snapshot_keys,
        "InventorySnapshot dates do not match eligible month-end and reference dates.",
    )
    _require(
        (snapshots[["on_hand", "on_order", "reserved", "backorders"]] >= 0)
        .all()
        .all(),
        "InventorySnapshot quantities must be nonnegative.",
    )
    _require(
        (
            (snapshots["on_order"] == 0)
            & (snapshots["reserved"] == 0)
            & (snapshots["backorders"] == 0)
        ).all(),
        "Demo InventorySnapshot on_order, reserved, and backorders must be zero.",
    )
    for snapshot in snapshots.itertuples(index=False):
        snapshot_date = _date_or_none(snapshot.snapshot_date)
        expected_balance = _balance_for_date(
            event_dates_by_pair,
            snapshot.store_id,
            snapshot.sku_id,
            snapshot_date,
        )
        _require(
            int(snapshot.on_hand) == expected_balance,
            (
                "InventorySnapshot does not reconcile to the event ledger for "
                f"{snapshot.store_id}/{snapshot.sku_id}/{snapshot_date}."
            ),
        )

    supplier_skus = master_data["SupplierSKU"].set_index("supplier_sku_id")
    skus_by_id = master_data["SKU"].set_index("sku_id")
    _require(
        set(observations["supplier_sku_id"]) == _expected_lead_time_ids(master_data),
        "LeadTimeObservation records do not match eligible SupplierSKU relationships.",
    )
    _require(
        not observations["observation_id"].duplicated().any(),
        "Duplicate LeadTimeObservation primary key.",
    )
    for observation in observations.itertuples(index=False):
        supplier_sku = supplier_skus.loc[observation.supplier_sku_id]
        sku = skus_by_id.loc[supplier_sku.sku_id]
        order_date = _date_or_none(observation.order_date)
        receipt_date = _date_or_none(observation.receipt_date)
        lead_time_days = int(observation.lead_time_days)
        _require(
            receipt_date >= order_date
            and lead_time_days == (receipt_date - order_date).days
            and lead_time_days >= 0,
            f"Invalid lead-time dates for {observation.observation_id}.",
        )
        _require(
            observation.issue_type in LEAD_TIME_ISSUE_TYPES,
            f"Invalid lead-time issue type for {observation.observation_id}.",
        )
        _require(
            max(
                _date_or_none(supplier_sku.active_from),
                _date_or_none(sku.launch_date),
                SALES_START_DATE,
            )
            <= order_date
            and receipt_date <= REFERENCE_DATE
            and (
                pd.isna(supplier_sku.active_to)
                or receipt_date < _date_or_none(supplier_sku.active_to)
            ),
            f"Lead-time observation falls outside its SupplierSKU period.",
        )
        discontinue_date = _date_or_none(sku.discontinue_date)
        _require(
            discontinue_date is None or receipt_date < discontinue_date,
            f"Lead-time observation falls outside its SKU lifecycle.",
        )

    policy_periods = _expected_policy_periods(master_data)
    _require(
        set(zip(policies["store_id"], policies["sku_id"])) == set(policy_periods),
        "ReorderPolicy records do not match eligible StoreSKU relationships.",
    )
    _require(
        not policies.duplicated(["store_id", "sku_id"]).any(),
        "Duplicate ReorderPolicy for a StoreSKU relationship.",
    )
    _check_effective_periods(
        policies,
        ["store_id", "sku_id"],
        "effective_from",
        "effective_to",
    )
    for policy in policies.itertuples(index=False):
        expected_from, expected_to = policy_periods[(policy.store_id, policy.sku_id)]
        effective_from = _date_or_none(policy.effective_from)
        effective_to = _date_or_none(policy.effective_to)
        _require(
            effective_from == expected_from and effective_to == expected_to,
            f"ReorderPolicy period is invalid for {policy.store_id}/{policy.sku_id}.",
        )
        _require(
            int(policy.review_period_days) == REVIEW_PERIOD_DAYS
            and 0 < float(policy.service_level) < 1
            and int(policy.safety_stock) >= 0
            and policy.reorder_method == REORDER_METHOD,
            f"Invalid ReorderPolicy values for {policy.policy_id}.",
        )


def generate_inventory_data(profile_name=DEFAULT_PROFILE):
    if profile_name not in PROFILES:
        valid_profiles = ", ".join(sorted(PROFILES))
        raise ValueError(
            f"Unknown profile {profile_name!r}. Choose one of: {valid_profiles}."
        )

    master_data = generate_master_data(profile_name)
    sales_data = generate_sales_data(profile_name)
    rng = np.random.default_rng(RANDOM_SEED)

    inventory_events = _build_inventory_events(
        master_data,
        sales_data["SalesHistory"],
        rng,
    )
    inventory_snapshots = _build_inventory_snapshots(
        master_data,
        sales_data["SalesHistory"],
        inventory_events,
    )
    lead_time_observations = _build_lead_time_observations(master_data, rng)
    reorder_policies = _build_reorder_policies(master_data, rng)

    data = {
        "InventoryEvent": inventory_events,
        "InventorySnapshot": inventory_snapshots,
        "LeadTimeObservation": lead_time_observations,
        "ReorderPolicy": reorder_policies,
    }
    validate_inventory_data(data, master_data, sales_data, profile_name)
    return data


def export_inventory_data(data, output_directory=EXPORT_DIRECTORY):
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    for table_name, frame in data.items():
        frame.to_csv(output_directory / f"{table_name}.csv", index=False)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate synthetic inventory and policy data."
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=DEFAULT_PROFILE,
        help="Data volume profile to generate.",
    )
    args = parser.parse_args(argv)

    data = generate_inventory_data(args.profile)
    export_inventory_data(data)

    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Profile: {args.profile}")
    print(f"CSV output: {EXPORT_DIRECTORY}")
    for table_name, frame in data.items():
        print(f"{table_name}: {len(frame)} rows")

    event_counts = data["InventoryEvent"]["event_type"].value_counts().sort_index()
    print("InventoryEvent counts by type:")
    for event_type in sorted(INVENTORY_EVENT_TYPES):
        print(f"  {event_type}: {int(event_counts.get(event_type, 0))}")
    reconciliation_count = int(
        (
            (data["InventoryEvent"]["event_type"] == "ADJUSTMENT_OUT")
            & data["InventoryEvent"]["reference_id"].str.startswith(
                "STOCKOUT-RECON-"
            )
        ).sum()
    )
    print(f"Stockout reconciliation adjustments: {reconciliation_count}")


if __name__ == "__main__":
    main()
