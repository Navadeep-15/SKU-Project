import argparse
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

import pandas as pd

from config import (
    PROFILES,
    REFERENCE_DATE,
)
from Backend.data_generation.inventory_generator import (
    INVENTORY_EVENT_COLUMNS,
    INVENTORY_SNAPSHOT_COLUMNS,
    REORDER_POLICY_COLUMNS,
    generate_inventory_data,
)
from Backend.data_generation.master_generator import (
    TABLE_COLUMNS,
    generate_master_data,
)
from Backend.data_generation.sales_generator import generate_sales_data
from Backend.evaluation.forecast_evaluator import (
    EVALUATION_EXPORT_DIRECTORY,
    METRIC_COLUMNS,
    METRICS_FILENAME,
    evaluate_forecasts,
    get_holdout_origins,
)
from Backend.forecasting.forecast_engine import (
    FORECAST_COLUMNS,
    FORECAST_HORIZON_DAYS,
    FORECAST_METHODS,
    FORECAST_RUN_COLUMNS,
    export_forecast_data,
    generate_forecast_data,
)


PURCHASE_RECOMMENDATION_COLUMNS = [
    "recommendation_id",
    "run_id",
    "store_id",
    "sku_id",
    "supplier_sku_id",
    "policy_id",
    "inventory_position",
    "lead_time_demand",
    "safety_stock",
    "reorder_point",
    "target_stock",
    "recommended_qty",
    "pack_size",
    "minimum_order_qty",
    "capacity_constraint_status",
    "reason_code",
    "exception_reason",
    "recommended_order_date",
    "expected_delivery_date",
    "status",
    "created_at",
]

VALIDATION_ISSUE_COLUMNS = [
    "validation_id",
    "table_name",
    "rule_name",
    "severity",
    "record_key",
    "issue_description",
    "resolved_flag",
    "detected_at",
]

PURCHASE_RECOMMENDATION_ID_PATTERN = r"PO-[0-9]{4}-[0-9]{6}"
VALIDATION_ISSUE_ID_PATTERN = r"VAL-[0-9]{6}"
CAPACITY_STATUSES = {"WITHIN_CAPACITY", "CAPACITY_EXCEEDED", "BLOCKED"}
RECOMMENDATION_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "generated"
CREATED_AT = datetime.combine(
    REFERENCE_DATE,
    time.min,
    tzinfo=timezone.utc,
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _as_date(value):
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value, errors="raise").date()


def _date_or_none(value):
    if pd.isna(value):
        return None
    return _as_date(value)


def _active_relationship_on(assortment, sku, store, check_date):
    active_to = _date_or_none(assortment.active_to)
    discontinue_date = _date_or_none(sku["discontinue_date"])
    return (
        bool(store["active_flag"])
        and assortment.assortment_status == "ACTIVE"
        and _as_date(assortment.active_from) <= check_date
        and (active_to is None or check_date < active_to)
        and _as_date(sku["launch_date"]) <= check_date
        and sku["lifecycle_state"] != "DISCONTINUED"
        and (discontinue_date is None or check_date < discontinue_date)
    )


def _relationship_end_date(assortment, sku):
    end_dates = [
        value
        for value in (
            _date_or_none(assortment.active_to),
            _date_or_none(sku["discontinue_date"]),
        )
        if value is not None
    ]
    return min(end_dates) if end_dates else None


def _period_active(start, end, check_date):
    start = _as_date(start)
    end = _date_or_none(end)
    return start <= check_date and (end is None or check_date < end)


def _current_policies(inventory_data, forecast_origin):
    policies = inventory_data["ReorderPolicy"]
    active = {}
    for policy in policies.itertuples(index=False):
        if _period_active(
            policy.effective_from,
            policy.effective_to,
            forecast_origin,
        ):
            key = (policy.store_id, policy.sku_id)
            _require(key not in active, f"Overlapping active policies for {key}.")
            active[key] = policy
    return active


def _eligible_supplier_rows(master_data, sku_id, forecast_origin):
    suppliers = master_data["Supplier"].set_index("supplier_id")
    eligible = []
    for supplier_sku in master_data["SupplierSKU"].itertuples(index=False):
        if supplier_sku.sku_id != sku_id:
            continue
        _require(
            int(supplier_sku.lead_time_days) >= 0,
            (
                "SupplierSKU lead time must be nonnegative: "
                f"{supplier_sku.supplier_sku_id}."
            ),
        )
        if not _period_active(
            supplier_sku.active_from,
            supplier_sku.active_to,
            forecast_origin,
        ):
            continue
        supplier = suppliers.loc[supplier_sku.supplier_id]
        if bool(supplier["active_flag"]):
            eligible.append(supplier_sku)
    return eligible


def _supplier_sort_key(supplier_sku):
    return (
        not bool(supplier_sku.is_preferred_supplier),
        int(supplier_sku.supplier_priority),
        float(supplier_sku.contract_cost),
        int(supplier_sku.lead_time_days),
        supplier_sku.supplier_sku_id,
    )


def calculate_required_forecast_horizon(
    master_data,
    inventory_data,
    forecast_origin=REFERENCE_DATE,
):
    forecast_origin = _as_date(forecast_origin)
    policies = _current_policies(inventory_data, forecast_origin)
    stores = master_data["Store"].set_index("store_id")
    skus = master_data["SKU"].set_index("sku_id")
    required_horizon = FORECAST_HORIZON_DAYS

    for assortment in master_data["StoreSKU"].itertuples(index=False):
        sku = skus.loc[assortment.sku_id]
        store = stores.loc[assortment.store_id]
        if not _active_relationship_on(
            assortment,
            sku,
            store,
            forecast_origin,
        ):
            continue

        policy = policies.get((assortment.store_id, assortment.sku_id))
        if policy is None:
            continue
        relationship_end = _relationship_end_date(assortment, sku)
        for supplier_sku in _eligible_supplier_rows(
            master_data,
            assortment.sku_id,
            forecast_origin,
        ):
            expected_delivery = forecast_origin + timedelta(
                days=int(supplier_sku.lead_time_days)
            )
            if (
                relationship_end is not None
                and expected_delivery >= relationship_end
            ):
                continue
            required_horizon = max(
                required_horizon,
                int(supplier_sku.lead_time_days)
                + int(policy.review_period_days),
            )

    return required_horizon


def _inventory_state(inventory_data, forecast_origin):
    snapshots = inventory_data["InventorySnapshot"]
    events = inventory_data["InventoryEvent"]
    _require(
        list(snapshots.columns) == INVENTORY_SNAPSHOT_COLUMNS,
        "InventorySnapshot columns do not match Backend/database/schema.sql.",
    )
    _require(
        list(events.columns) == INVENTORY_EVENT_COLUMNS,
        "InventoryEvent columns do not match Backend/database/schema.sql.",
    )

    current_snapshots = snapshots.loc[
        snapshots["snapshot_date"].map(_as_date) == forecast_origin
    ].copy()
    _require(
        (
            current_snapshots[
                ["on_hand", "on_order", "reserved", "backorders"]
            ]
            >= 0
        ).all().all(),
        "Current InventorySnapshot quantities must be nonnegative.",
    )
    _require(
        not current_snapshots.duplicated(["store_id", "sku_id"]).any(),
        "Duplicate current InventorySnapshot for a store/SKU.",
    )

    balances = {}
    for event in events.itertuples(index=False):
        event_date = _as_date(event.event_date)
        if event_date <= forecast_origin:
            pair = (event.store_id, event.sku_id)
            balances[pair] = balances.get(pair, 0) + int(event.quantity)

    snapshots_by_pair = {}
    on_order_by_pair = {}
    for snapshot in current_snapshots.itertuples(index=False):
        pair = (snapshot.store_id, snapshot.sku_id)
        snapshots_by_pair[pair] = snapshot
        on_order_by_pair[pair] = int(snapshot.on_order)
        _require(
            int(snapshot.on_hand) == balances.get(pair, 0),
            (
                "InventorySnapshot does not reconcile to InventoryEvent for "
                f"{pair[0]}/{pair[1]}."
            ),
        )

    return balances, snapshots_by_pair, on_order_by_pair


def _eligible_suppliers_for_delivery(
    master_data,
    assortment,
    sku,
    forecast_origin,
):
    relationship_end = _relationship_end_date(assortment, sku)
    candidates = _eligible_supplier_rows(
        master_data,
        assortment.sku_id,
        forecast_origin,
    )
    deliverable = []
    for supplier_sku in candidates:
        expected_delivery = forecast_origin + timedelta(
            days=int(supplier_sku.lead_time_days)
        )
        if (
            relationship_end is None
            or expected_delivery < relationship_end
        ):
            deliverable.append(supplier_sku)
    return sorted(deliverable, key=_supplier_sort_key), candidates


def _forecast_demand(
    forecast_by_key,
    store_id,
    sku_id,
    assortment,
    sku,
    store,
    forecast_origin,
    day_count,
):
    demand = 0.0
    for offset in range(1, day_count + 1):
        target_date = forecast_origin + timedelta(days=offset)
        if not _active_relationship_on(
            assortment,
            sku,
            store,
            target_date,
        ):
            continue
        key = (store_id, sku_id, target_date)
        _require(
            key in forecast_by_key,
            f"Missing eligible forecast for {store_id}/{sku_id}/{target_date}.",
        )
        demand += float(forecast_by_key[key])
    return round(demand, 2)


def _round_order_quantity(stock_gap, minimum_order_qty, pack_size):
    gap = Decimal(str(round(float(stock_gap), 2)))
    minimum = Decimal(int(minimum_order_qty))
    pack = Decimal(int(pack_size))
    pack_count = (max(gap, minimum) / pack).to_integral_value(
        rounding=ROUND_CEILING
    )
    return int(pack_count * pack)


def _urgency_score(reorder_point, inventory_position, lead_time_demand):
    """Score shortage relative to lead-time demand; higher scores allocate first.

    score = max(0, reorder_point - inventory_position) / max(lead_time_demand, 1)
    Ties are resolved by ascending SKU ID within each store.
    """
    shortage = max(0.0, float(reorder_point) - int(inventory_position))
    return shortage / max(float(lead_time_demand), 1.0)


def _diagnostic(
    table_name,
    rule_name,
    severity,
    store_id,
    sku_id,
    description,
):
    return {
        "table_name": table_name,
        "rule_name": rule_name,
        "severity": severity,
        "record_key": f"{store_id}/{sku_id}",
        "issue_description": description,
        "resolved_flag": False,
        "detected_at": CREATED_AT,
    }


def _make_validation_issue_frame(issue_details):
    ordered_issues = sorted(
        issue_details,
        key=lambda issue: (
            issue["table_name"],
            issue["rule_name"],
            issue["record_key"],
        ),
    )
    rows = []
    for index, issue in enumerate(ordered_issues, start=1):
        _require(index <= 999_999, "ValidationIssue ID limit exceeded.")
        rows.append((f"VAL-{index:06d}",) + tuple(issue[key] for key in (
            "table_name",
            "rule_name",
            "severity",
            "record_key",
            "issue_description",
            "resolved_flag",
            "detected_at",
        )))
    return pd.DataFrame(rows, columns=VALIDATION_ISSUE_COLUMNS)


def _build_recommendation_candidates(
    master_data,
    inventory_data,
    forecast_data,
    selected_method,
    forecast_origin,
):
    policies = _current_policies(inventory_data, forecast_origin)
    balances, snapshots_by_pair, on_order_by_pair = _inventory_state(
        inventory_data,
        forecast_origin,
    )
    stores = master_data["Store"].set_index("store_id")
    skus = master_data["SKU"].set_index("sku_id")
    run_rows = forecast_data["ForecastRun"].loc[
        (forecast_data["ForecastRun"]["forecast_origin"].map(_as_date)
         == forecast_origin)
        & (forecast_data["ForecastRun"]["model_name"] == selected_method)
    ]
    _require(
        len(run_rows) == 1,
        "Expected exactly one current-origin ForecastRun for the selected method.",
    )
    selected_run = run_rows.iloc[0]
    run_id = selected_run["run_id"]
    _require(
        int(selected_run["horizon_days"])
        >= calculate_required_forecast_horizon(
            master_data,
            inventory_data,
            forecast_origin,
        ),
        "Selected ForecastRun does not cover the required replenishment horizon.",
    )
    forecasts = forecast_data["Forecast"].loc[
        forecast_data["Forecast"]["run_id"] == run_id
    ]
    forecast_by_key = {
        (row.store_id, row.sku_id, _as_date(row.target_date)): float(
            row.forecast_units
        )
        for row in forecasts.itertuples(index=False)
    }

    candidates = []
    issues = []
    for assortment in master_data["StoreSKU"].itertuples(index=False):
        sku = skus.loc[assortment.sku_id]
        store = stores.loc[assortment.store_id]
        if not _active_relationship_on(
            assortment,
            sku,
            store,
            forecast_origin,
        ):
            continue

        key = (assortment.store_id, assortment.sku_id)
        policy = policies.get(key)
        if policy is None:
            issues.append(
                _diagnostic(
                    "ReorderPolicy",
                    "NO_ACTIVE_POLICY",
                    "HIGH",
                    *key,
                    "No ReorderPolicy is effective on the recommendation date.",
                )
            )
            continue

        suppliers, active_candidates = _eligible_suppliers_for_delivery(
            master_data,
            assortment,
            sku,
            forecast_origin,
        )
        if not suppliers:
            if active_candidates:
                rule_name = "SUPPLIER_ARRIVAL_AFTER_ELIGIBILITY_END"
                description = (
                    "No active supplier can deliver before the SKU or "
                    "assortment eligibility period ends."
                )
            else:
                rule_name = "NO_ELIGIBLE_ACTIVE_SUPPLIER"
                description = (
                    "No active SupplierSKU and active Supplier are eligible "
                    "on the recommendation date."
                )
            issues.append(
                _diagnostic(
                    "SupplierSKU",
                    rule_name,
                    "HIGH",
                    *key,
                    description,
                )
            )
            continue

        snapshot = snapshots_by_pair.get(key)
        if snapshot is None:
            issues.append(
                _diagnostic(
                    "InventorySnapshot",
                    "NO_CURRENT_SNAPSHOT",
                    "HIGH",
                    *key,
                    "No InventorySnapshot exists on the recommendation date.",
                )
            )
            continue

        supplier_sku = suppliers[0]
        lead_time_days = int(supplier_sku.lead_time_days)
        review_period_days = int(policy.review_period_days)
        expected_delivery = forecast_origin + timedelta(days=lead_time_days)
        lead_time_demand = _forecast_demand(
            forecast_by_key,
            assortment.store_id,
            assortment.sku_id,
            assortment,
            sku,
            store,
            forecast_origin,
            lead_time_days,
        )
        target_demand = _forecast_demand(
            forecast_by_key,
            assortment.store_id,
            assortment.sku_id,
            assortment,
            sku,
            store,
            forecast_origin,
            lead_time_days + review_period_days,
        )
        safety_stock = int(policy.safety_stock)
        reorder_point = round(lead_time_demand + safety_stock, 2)
        target_stock = round(target_demand + safety_stock, 2)
        inventory_position = (
            int(snapshot.on_hand)
            + int(snapshot.on_order)
            - int(snapshot.reserved)
            - int(snapshot.backorders)
        )
        stock_gap = round(target_stock - inventory_position, 2)

        if inventory_position < reorder_point and stock_gap > 0:
            desired_quantity = _round_order_quantity(
                stock_gap,
                int(supplier_sku.min_order_qty),
                int(supplier_sku.pack_size),
            )
            reason_code = "REORDER_REQUIRED"
        else:
            desired_quantity = 0
            reason_code = "NO_REPLENISHMENT_REQUIRED"

        candidates.append(
            {
                "run_id": run_id,
                "store_id": assortment.store_id,
                "sku_id": assortment.sku_id,
                "supplier_sku_id": supplier_sku.supplier_sku_id,
                "policy_id": policy.policy_id,
                "inventory_position": inventory_position,
                "lead_time_demand": lead_time_demand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "target_stock": target_stock,
                "desired_quantity": desired_quantity,
                "pack_size": int(supplier_sku.pack_size),
                "minimum_order_qty": int(supplier_sku.min_order_qty),
                "reason_code": reason_code,
                "recommended_order_date": forecast_origin,
                "expected_delivery_date": expected_delivery,
                "urgency_score": _urgency_score(
                    reorder_point,
                    inventory_position,
                    lead_time_demand,
                ),
                "snapshot": snapshot,
            }
        )

    return candidates, issues, balances, on_order_by_pair, run_id


def _allocate_store_capacity(
    candidates,
    master_data,
    balances,
    on_order_by_pair,
    forecast_origin,
):
    stores = master_data["Store"].set_index("store_id")
    projected_by_store = {}
    for (store_id, sku_id), on_hand in balances.items():
        projected_by_store[store_id] = (
            projected_by_store.get(store_id, 0)
            + int(on_hand)
            + int(on_order_by_pair.get((store_id, sku_id), 0))
        )

    for store_id, store in stores.iterrows():
        projected_by_store.setdefault(store_id, 0)
        _require(
            projected_by_store[store_id] <= int(store["capacity_units"]),
            (
                f"Existing inventory exceeds capacity at store {store_id} "
                f"on {forecast_origin}."
            ),
        )

    capacities = stores["capacity_units"].to_dict()
    allocated = {}
    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate["store_id"],
            -candidate["urgency_score"],
            candidate["sku_id"],
        ),
    )
    for candidate in ordered_candidates:
        key = (candidate["store_id"], candidate["sku_id"])
        quantity = int(candidate["desired_quantity"])
        current_projected = projected_by_store[candidate["store_id"]]
        remaining_capacity = (
            int(capacities[candidate["store_id"]]) - current_projected
        )

        if quantity == 0:
            allocated[key] = {
                "recommended_qty": 0,
                "capacity_constraint_status": "WITHIN_CAPACITY",
                "reason_code": candidate["reason_code"],
                "exception_reason": None,
            }
        elif quantity <= remaining_capacity:
            projected_by_store[candidate["store_id"]] += quantity
            allocated[key] = {
                "recommended_qty": quantity,
                "capacity_constraint_status": "WITHIN_CAPACITY",
                "reason_code": candidate["reason_code"],
                "exception_reason": None,
            }
        else:
            allocated[key] = {
                "recommended_qty": 0,
                "capacity_constraint_status": "BLOCKED",
                "reason_code": "STORE_CAPACITY_BLOCKED",
                "exception_reason": (
                    f"Attempted quantity {quantity}; available store capacity "
                    f"was {max(remaining_capacity, 0)} units."
                ),
            }

    return allocated, projected_by_store


def _recommendation_frame(candidates, allocated, selected_run_id, forecast_origin):
    rows = []
    ordered = sorted(
        candidates,
        key=lambda candidate: (candidate["store_id"], candidate["sku_id"]),
    )
    for index, candidate in enumerate(ordered, start=1):
        _require(index <= 999_999, "PurchaseRecommendation ID limit exceeded.")
        allocation = allocated[(candidate["store_id"], candidate["sku_id"])]
        rows.append(
            (
                f"PO-{forecast_origin.year:04d}-{index:06d}",
                selected_run_id,
                candidate["store_id"],
                candidate["sku_id"],
                candidate["supplier_sku_id"],
                candidate["policy_id"],
                candidate["inventory_position"],
                candidate["lead_time_demand"],
                candidate["safety_stock"],
                candidate["reorder_point"],
                candidate["target_stock"],
                allocation["recommended_qty"],
                candidate["pack_size"],
                candidate["minimum_order_qty"],
                allocation["capacity_constraint_status"],
                allocation["reason_code"],
                allocation["exception_reason"],
                candidate["recommended_order_date"],
                candidate["expected_delivery_date"],
                "PENDING",
                CREATED_AT,
            )
        )
    return pd.DataFrame(rows, columns=PURCHASE_RECOMMENDATION_COLUMNS)


def validate_replenishment_data(
    data,
    master_data,
    inventory_data,
    forecast_data,
    selected_run_id,
    forecast_origin=REFERENCE_DATE,
):
    forecast_origin = _as_date(forecast_origin)
    _require(
        set(data) == {"PurchaseRecommendation", "ValidationIssue"},
        "Generated replenishment tables do not match the schema output set.",
    )
    recommendations = data["PurchaseRecommendation"]
    issues = data["ValidationIssue"]
    _require(
        list(recommendations.columns) == PURCHASE_RECOMMENDATION_COLUMNS,
        "PurchaseRecommendation columns do not match Backend/database/schema.sql.",
    )
    _require(
        list(issues.columns) == VALIDATION_ISSUE_COLUMNS,
        "ValidationIssue columns do not match Backend/database/schema.sql.",
    )
    _require(
        not recommendations["recommendation_id"].duplicated().any(),
        "Duplicate PurchaseRecommendation ID.",
    )
    _require(
        recommendations["recommendation_id"]
        .astype(str)
        .str.fullmatch(PURCHASE_RECOMMENDATION_ID_PATTERN)
        .all(),
        "Invalid PurchaseRecommendation ID format.",
    )
    _require(
        not issues["validation_id"].duplicated().any(),
        "Duplicate ValidationIssue ID.",
    )
    _require(
        issues["validation_id"].astype(str).str.fullmatch(
            VALIDATION_ISSUE_ID_PATTERN
        ).all(),
        "Invalid ValidationIssue ID format.",
    )
    _require(
        not recommendations.duplicated(["run_id", "store_id", "sku_id"]).any(),
        "Duplicate recommendation for a run/store/SKU.",
    )
    _require(
        recommendations["run_id"].eq(selected_run_id).all(),
        "Recommendations must reference the selected current ForecastRun.",
    )

    stores = master_data["Store"].set_index("store_id")
    suppliers = master_data["Supplier"].set_index("supplier_id")
    skus = master_data["SKU"].set_index("sku_id")
    supplier_skus = master_data["SupplierSKU"].set_index("supplier_sku_id")
    policies = inventory_data["ReorderPolicy"].set_index("policy_id")
    assortments = master_data["StoreSKU"].set_index(["store_id", "sku_id"])
    balances, snapshots_by_pair, on_order_by_pair = _inventory_state(
        inventory_data,
        forecast_origin,
    )
    run_forecasts = forecast_data["Forecast"].loc[
        forecast_data["Forecast"]["run_id"] == selected_run_id
    ]
    forecast_by_key = {
        (row.store_id, row.sku_id, _as_date(row.target_date)): float(
            row.forecast_units
        )
        for row in run_forecasts.itertuples(index=False)
    }
    active_policies = _current_policies(inventory_data, forecast_origin)

    _require(
        recommendations["capacity_constraint_status"]
        .isin(CAPACITY_STATUSES)
        .all(),
        "Invalid capacity_constraint_status.",
    )
    _require(
        recommendations["status"].isin(RECOMMENDATION_STATUSES).all(),
        "Invalid PurchaseRecommendation status.",
    )
    _require(
        (recommendations["lead_time_demand"] >= 0).all()
        and (recommendations["safety_stock"] >= 0).all()
        and (recommendations["reorder_point"] >= 0).all()
        and (recommendations["target_stock"] >= 0).all()
        and (recommendations["recommended_qty"] >= 0).all()
        and (recommendations["pack_size"] > 0).all()
        and (recommendations["minimum_order_qty"] > 0).all(),
        "Recommendation quantities and thresholds are invalid.",
    )
    _require(
        (
            (recommendations["recommended_qty"] == 0)
            | (
                (recommendations["recommended_qty"]
                 >= recommendations["minimum_order_qty"])
                & (
                    recommendations["recommended_qty"]
                    % recommendations["pack_size"]
                    == 0
                )
            )
        ).all(),
        "Positive recommendation quantities must satisfy MOQ and pack size.",
    )
    _require(
        (
            recommendations.loc[
                recommendations["capacity_constraint_status"] == "BLOCKED",
                "exception_reason",
            ]
            .fillna("")
            .str.strip()
            .ne("")
        ).all(),
        "Blocked recommendations require an exception_reason.",
    )
    _require(
        (
            recommendations.loc[
                recommendations["capacity_constraint_status"] == "BLOCKED",
                "recommended_qty",
            ]
            == 0
        ).all(),
        "Blocked recommendations must have recommended_qty=0.",
    )
    _require(
        recommendations["store_id"].isin(stores.index).all()
        and recommendations["sku_id"].isin(skus.index).all(),
        "PurchaseRecommendation contains an invalid store or SKU foreign key.",
    )
    _require(
        recommendations["supplier_sku_id"].isin(supplier_skus.index).all(),
        "PurchaseRecommendation contains an invalid SupplierSKU foreign key.",
    )
    _require(
        recommendations["policy_id"].isin(policies.index).all(),
        "PurchaseRecommendation contains an invalid ReorderPolicy foreign key.",
    )
    _require(
        issues["severity"].isin({"LOW", "MEDIUM", "HIGH", "CRITICAL"}).all(),
        "ValidationIssue contains an invalid severity.",
    )

    projected_by_store = {}
    for (store_id, sku_id), on_hand in balances.items():
        projected_by_store[store_id] = (
            projected_by_store.get(store_id, 0)
            + int(on_hand)
            + int(on_order_by_pair.get((store_id, sku_id), 0))
        )

    sku_rows = skus
    store_rows = stores
    for recommendation in recommendations.itertuples(index=False):
        pair = (recommendation.store_id, recommendation.sku_id)
        _require(
            pair in assortments.index,
            f"Recommendation references unknown StoreSKU pair {pair}.",
        )
        assortment = assortments.loc[pair]
        sku = sku_rows.loc[recommendation.sku_id]
        store = store_rows.loc[recommendation.store_id]
        supplier_sku = supplier_skus.loc[recommendation.supplier_sku_id]
        supplier = suppliers.loc[supplier_sku.supplier_id]
        policy = policies.loc[recommendation.policy_id]
        _require(
            supplier_sku.sku_id == recommendation.sku_id,
            "SupplierSKU foreign key does not match recommendation SKU.",
        )
        _require(
            policy.store_id == recommendation.store_id
            and policy.sku_id == recommendation.sku_id,
            "ReorderPolicy foreign key does not match store/SKU.",
        )
        _require(
            _active_relationship_on(assortment, sku, store, forecast_origin),
            "Recommendation is outside active SKU/assortment eligibility.",
        )
        _require(
            _period_active(
                supplier_sku.active_from,
                supplier_sku.active_to,
                forecast_origin,
            )
            and bool(supplier["active_flag"])
            and _period_active(
                policy.effective_from,
                policy.effective_to,
                forecast_origin,
            ),
            "SupplierSKU or ReorderPolicy is not effective on order date.",
        )
        _require(
            pair in snapshots_by_pair,
            "Recommendation has no current InventorySnapshot.",
        )
        _require(
            int(recommendation.inventory_position)
            == (
                int(snapshots_by_pair[pair].on_hand)
                + int(snapshots_by_pair[pair].on_order)
                - int(snapshots_by_pair[pair].reserved)
                - int(snapshots_by_pair[pair].backorders)
            ),
            "Recommendation inventory_position does not match its snapshot.",
        )

        expected_delivery = forecast_origin + timedelta(
            days=int(supplier_sku.lead_time_days)
        )
        relationship_end = _relationship_end_date(assortment, sku)
        _require(
            _as_date(recommendation.recommended_order_date) == forecast_origin
            and _as_date(recommendation.expected_delivery_date) == expected_delivery,
            "Recommendation order/delivery dates are inconsistent.",
        )
        _require(
            relationship_end is None or expected_delivery < relationship_end,
            "Recommendation arrives after SKU/assortment eligibility ends.",
        )
        _require(
            int(recommendation.pack_size) == int(supplier_sku.pack_size)
            and int(recommendation.minimum_order_qty)
            == int(supplier_sku.min_order_qty),
            "Recommendation supplier terms do not match SupplierSKU.",
        )
        _require(
            int(recommendation.safety_stock) == int(policy.safety_stock),
            "Recommendation safety stock does not match ReorderPolicy.",
        )

        lead_time_demand = _forecast_demand(
            forecast_by_key,
            recommendation.store_id,
            recommendation.sku_id,
            assortment,
            sku,
            store,
            forecast_origin,
            int(supplier_sku.lead_time_days),
        )
        target_demand = _forecast_demand(
            forecast_by_key,
            recommendation.store_id,
            recommendation.sku_id,
            assortment,
            sku,
            store,
            forecast_origin,
            int(supplier_sku.lead_time_days)
            + int(policy.review_period_days),
        )
        expected_reorder_point = round(
            lead_time_demand + int(policy.safety_stock),
            2,
        )
        expected_target_stock = round(
            target_demand + int(policy.safety_stock),
            2,
        )
        _require(
            abs(float(recommendation.lead_time_demand) - lead_time_demand) < 0.005
            and abs(float(recommendation.reorder_point) - expected_reorder_point)
            < 0.005
            and abs(float(recommendation.target_stock) - expected_target_stock)
            < 0.005,
            "Recommendation demand/reorder calculations are inconsistent.",
        )

        expected_gap = round(
            expected_target_stock - int(recommendation.inventory_position),
            2,
        )
        if (
            int(recommendation.inventory_position) < expected_reorder_point
            and expected_gap > 0
        ):
            expected_quantity = _round_order_quantity(
                expected_gap,
                int(supplier_sku.min_order_qty),
                int(supplier_sku.pack_size),
            )
        else:
            expected_quantity = 0
        if recommendation.capacity_constraint_status != "BLOCKED":
            _require(
                int(recommendation.recommended_qty) == expected_quantity,
                "Recommendation quantity does not match reorder rules.",
            )
        elif expected_quantity <= 0:
            raise ValueError("A blocked recommendation has no positive order need.")

        if int(recommendation.recommended_qty) > 0:
            projected_by_store[recommendation.store_id] = (
                projected_by_store.get(recommendation.store_id, 0)
                + int(recommendation.recommended_qty)
            )

    for store_id, projected in projected_by_store.items():
        _require(
            projected <= int(stores.loc[store_id, "capacity_units"]),
            f"Projected inventory exceeds capacity at store {store_id}.",
        )

    expected_forecast_run = forecast_data["ForecastRun"].loc[
        forecast_data["ForecastRun"]["run_id"] == selected_run_id
    ]
    _require(len(expected_forecast_run) == 1, "Selected ForecastRun is missing.")
    _require(
        expected_forecast_run.iloc[0]["model_name"] in FORECAST_METHODS
        and _as_date(expected_forecast_run.iloc[0]["forecast_origin"])
        == forecast_origin
        and int(expected_forecast_run.iloc[0]["horizon_days"])
        >= calculate_required_forecast_horizon(
            master_data,
            inventory_data,
            forecast_origin,
        ),
        "Selected ForecastRun method or horizon is invalid.",
    )


def create_recommendations(
    master_data,
    inventory_data,
    forecast_data,
    selected_method,
    forecast_origin=REFERENCE_DATE,
):
    candidates, issues, balances, on_order_by_pair, selected_run_id = (
        _build_recommendation_candidates(
            master_data,
            inventory_data,
            forecast_data,
            selected_method,
            forecast_origin,
        )
    )
    allocated, _ = _allocate_store_capacity(
        candidates,
        master_data,
        balances,
        on_order_by_pair,
        forecast_origin,
    )
    data = {
        "PurchaseRecommendation": _recommendation_frame(
            candidates,
            allocated,
            selected_run_id,
            forecast_origin,
        ),
        "ValidationIssue": _make_validation_issue_frame(issues),
    }
    validate_replenishment_data(
        data,
        master_data,
        inventory_data,
        forecast_data,
        selected_run_id,
        forecast_origin,
    )
    return data, selected_run_id


def generate_replenishment_data(profile_name="test"):
    _require(
        profile_name == "test",
        "Phase 6 generation is restricted to the test profile.",
    )
    _require(profile_name in PROFILES, f"Unknown profile: {profile_name}")

    master_data = generate_master_data(profile_name)
    _require(
        all(
            list(master_data[table_name].columns) == columns
            for table_name, columns in TABLE_COLUMNS.items()
        ),
        "Master-data columns do not match the generated schema.",
    )
    sales_data = generate_sales_data(profile_name)
    inventory_data = generate_inventory_data(profile_name)
    holdout_origins = get_holdout_origins()
    forecast_origins = (*holdout_origins, REFERENCE_DATE)

    initial_forecast_data = generate_forecast_data(
        master_data,
        sales_data["SalesHistory"],
        forecast_origins,
    )
    _, initial_selection = evaluate_forecasts(
        initial_forecast_data,
        sales_data["GroundTruthDemand"],
        holdout_origins,
    )
    required_horizon = calculate_required_forecast_horizon(
        master_data,
        inventory_data,
        REFERENCE_DATE,
    )
    selected_method = initial_selection["selected_method"]
    forecast_data = generate_forecast_data(
        master_data,
        sales_data["SalesHistory"],
        forecast_origins,
        {
            (REFERENCE_DATE, selected_method): required_horizon,
        },
    )
    metrics, selection = evaluate_forecasts(
        forecast_data,
        sales_data["GroundTruthDemand"],
        holdout_origins,
    )
    _require(
        selection["selected_method"] == selected_method,
        "Extending the current run changed the historical holdout selection.",
    )

    recommendation_data, selected_run_id = create_recommendations(
        master_data,
        inventory_data,
        forecast_data,
        selected_method,
        REFERENCE_DATE,
    )
    selected_run = forecast_data["ForecastRun"].loc[
        forecast_data["ForecastRun"]["run_id"] == selected_run_id
    ].iloc[0]
    return {
        **recommendation_data,
        "ForecastRun": forecast_data["ForecastRun"],
        "Forecast": forecast_data["Forecast"],
        "metrics": metrics,
        "selection": selection,
        "selected_run": selected_run,
        "required_horizon": required_horizon,
        "holdout_origins": holdout_origins,
    }


def export_replenishment_data(
    data,
    generated_data_directory=GENERATED_DATA_DIRECTORY,
    evaluation_export_directory=EVALUATION_EXPORT_DIRECTORY,
):
    _require(
        list(data["metrics"].columns) == METRIC_COLUMNS,
        "Evaluation metrics columns do not match the expected export schema.",
    )
    generated_data_directory = Path(generated_data_directory)
    evaluation_export_directory = Path(evaluation_export_directory)
    generated_data_directory.mkdir(parents=True, exist_ok=True)
    evaluation_export_directory.mkdir(parents=True, exist_ok=True)

    forecast_data = {
        "ForecastRun": data["ForecastRun"],
        "Forecast": data["Forecast"],
    }
    export_forecast_data(forecast_data, generated_data_directory)
    data["PurchaseRecommendation"].to_csv(
        generated_data_directory / "PurchaseRecommendation.csv",
        index=False,
    )
    data["ValidationIssue"].to_csv(
        generated_data_directory / "ValidationIssue.csv",
        index=False,
    )
    data["metrics"].to_csv(
        evaluation_export_directory / METRICS_FILENAME,
        index=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate test-profile replenishment recommendations."
    )
    parser.add_argument(
        "--profile",
        choices=["test"],
        default="test",
        help="Data volume profile to generate.",
    )
    args = parser.parse_args(argv)

    data = generate_replenishment_data(args.profile)
    export_replenishment_data(data)

    recommendations = data["PurchaseRecommendation"]
    accepted = int(
        (
            (recommendations["recommended_qty"] > 0)
            & (recommendations["capacity_constraint_status"] == "WITHIN_CAPACITY")
        ).sum()
    )
    blocked = int(
        (recommendations["capacity_constraint_status"] == "BLOCKED").sum()
    )
    print(f"Profile: {args.profile}")
    print(f"Selected method: {data['selection']['selected_method']}")
    print(f"Selected current ForecastRun: {data['selected_run']['run_id']}")
    print(f"Forecast horizon: {data['selected_run']['horizon_days']} days")
    print(f"Required horizon: {data['required_horizon']} days")
    print(f"PurchaseRecommendation: {len(recommendations)} rows")
    print(f"Accepted orders: {accepted}")
    print(f"Blocked orders: {blocked}")
    print(f"ValidationIssue: {len(data['ValidationIssue'])} rows")
    print(f"Generated data directory: {GENERATED_DATA_DIRECTORY}")
    print(f"Evaluation export directory: {EVALUATION_EXPORT_DIRECTORY}")


if __name__ == "__main__":
    main()
