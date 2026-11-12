import argparse
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    DATASET_VERSION,
    DEFAULT_PROFILE,
    PROFILES,
    RANDOM_SEED,
    REFERENCE_DATE,
    SALES_HISTORY_DAYS,
    SALES_START_DATE,
)
from Backend.data_generation.master_generator import (
    EXPORT_DIRECTORY,
    generate_master_data,
)


SALES_COLUMNS = [
    "sales_id",
    "store_id",
    "sku_id",
    "sales_date",
    "units_sold",
    "sales_amount",
    "promotion_flag",
    "stockout_flag",
    "promotion_id",
    "created_at",
]

GROUND_TRUTH_COLUMNS = [
    "truth_id",
    "store_id",
    "sku_id",
    "demand_date",
    "actual_demand",
    "observed_sales",
    "stockout_impact",
    "stockout_flag",
    "generation_scenario",
    "created_at",
]

SALES_ID_PATTERN = r"SALE-STORE-[0-9]{6}-SKU-[0-9]{6}-[0-9]{4}-[0-9]{2}-[0-9]{2}"
TRUTH_ID_PATTERN = r"GT-[0-9]{8}"
ELIGIBLE_ASSORTMENT_STATUSES = {"ACTIVE", "DISCONTINUED"}
CREATED_AT = datetime.combine(
    REFERENCE_DATE,
    time.min,
    tzinfo=timezone.utc,
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _date_or_none(value):
    return None if pd.isna(value) else value


def _get_eligible_periods(master_data):
    skus = master_data["SKU"].set_index("sku_id")
    stores = master_data["Store"].set_index("store_id")
    periods = []
    reference_end = REFERENCE_DATE + timedelta(days=1)

    for assortment in master_data["StoreSKU"].itertuples(index=False):
        store = stores.loc[assortment.store_id]
        sku = skus.loc[assortment.sku_id]

        if not bool(store["active_flag"]):
            continue
        if assortment.assortment_status not in ELIGIBLE_ASSORTMENT_STATUSES:
            continue

        start_date = max(
            SALES_START_DATE,
            sku["launch_date"],
            assortment.active_from,
        )
        end_date = reference_end

        discontinue_date = _date_or_none(sku["discontinue_date"])
        assortment_end = _date_or_none(assortment.active_to)

        if discontinue_date is not None:
            end_date = min(end_date, discontinue_date)
        if assortment_end is not None:
            end_date = min(end_date, assortment_end)
        if end_date <= start_date:
            continue

        periods.append(
            {
                "store_id": assortment.store_id,
                "sku_id": assortment.sku_id,
                "valid_from": start_date,
                "valid_to": end_date,
                "unit_price": float(sku["unit_price"]),
            }
        )

    return periods


def _simulate_demand(rng, dates, sku_baseline, store_multiplier, promotion_flags):
    weekdays = np.array([1.0 if day.weekday() < 5 else 1.2 for day in dates])
    annual_seasonality = np.array(
        [
            1.0 + 0.15 * np.sin(2 * np.pi * (day.timetuple().tm_yday / 365.25))
            for day in dates
        ]
    )
    promotion_multiplier = np.where(promotion_flags, 1.4, 1.0)
    demand_mean = (
        sku_baseline
        * store_multiplier
        * weekdays
        * annual_seasonality
        * promotion_multiplier
    )

    actual_demand = rng.poisson(demand_mean)
    available_stock = rng.poisson(np.maximum(1.0, demand_mean * 1.7))
    return demand_mean, actual_demand, available_stock


def _generation_scenario(actual_demand, promotion_flag, stockout_flag):
    if actual_demand == 0 and not stockout_flag:
        return "ZERO_DEMAND"
    if promotion_flag and stockout_flag:
        return "PROMOTION_STOCKOUT"
    if promotion_flag:
        return "PROMOTION"
    if stockout_flag:
        return "STOCKOUT"
    return "BASELINE"


def _build_sales_records(master_data, profile_name):
    rng = np.random.default_rng(RANDOM_SEED)
    sku_ids = master_data["SKU"]["sku_id"].tolist()
    store_ids = master_data["Store"]["store_id"].tolist()
    sku_baselines = {
        sku_id: float(rng.uniform(1.5, 9.0))
        for sku_id in sku_ids
    }
    store_multipliers = {
        store_id: float(rng.uniform(0.7, 1.5))
        for store_id in store_ids
    }

    sales_rows = []
    truth_rows = []
    record_number = 0

    for period in _get_eligible_periods(master_data):
        dates = pd.date_range(
            start=period["valid_from"],
            end=period["valid_to"] - timedelta(days=1),
            freq="D",
        ).date
        if len(dates) == 0:
            continue

        promotion_flags = rng.random(len(dates)) < 0.06
        if profile_name == "dev" and record_number == 0:
            promotion_flags[0] = True

        demand_mean, actual_values, available_values = _simulate_demand(
            rng,
            dates,
            sku_baselines[period["sku_id"]],
            store_multipliers[period["store_id"]],
            promotion_flags,
        )

        for day_index, sales_date in enumerate(dates):
            actual_demand = int(actual_values[day_index])
            available_stock = int(available_values[day_index])
            promotion_flag = bool(promotion_flags[day_index])
            scenario_override = None

            if profile_name == "test":
                if record_number == 0:
                    actual_demand = 0
                    available_stock = max(1, available_stock)
                    promotion_flag = False
                    scenario_override = "TEST_ZERO_DEMAND"
                elif record_number == 1:
                    actual_demand = max(1, actual_demand)
                    available_stock = actual_demand + 1
                    promotion_flag = False
                    scenario_override = "TEST_NORMAL_SALE"
                elif record_number == 2:
                    actual_demand = max(1, actual_demand)
                    available_stock = 0
                    promotion_flag = False
                    scenario_override = "TEST_ZERO_SALES_STOCKOUT"
                elif record_number == 3:
                    actual_demand = max(
                        1,
                        int(np.ceil(demand_mean[day_index] * 1.4)),
                    )
                    available_stock = actual_demand + 1
                    promotion_flag = True
                    scenario_override = "TEST_PROMOTION"

            stockout_flag = actual_demand > available_stock
            units_sold = min(actual_demand, available_stock)
            stockout_impact = actual_demand - units_sold
            sales_date_text = sales_date.isoformat()
            sales_id = (
                f"SALE-{period['store_id']}-{period['sku_id']}-{sales_date_text}"
            )
            promotion_id = (
                f"PROMO-{sales_date:%Y%m%d}-{period['sku_id'][-6:]}"
                if promotion_flag
                else None
            )
            sales_amount = round(units_sold * period["unit_price"], 2)

            sales_rows.append(
                (
                    sales_id,
                    period["store_id"],
                    period["sku_id"],
                    sales_date,
                    units_sold,
                    sales_amount,
                    promotion_flag,
                    stockout_flag,
                    promotion_id,
                    CREATED_AT,
                )
            )
            truth_rows.append(
                (
                    f"GT-{record_number + 1:08d}",
                    period["store_id"],
                    period["sku_id"],
                    sales_date,
                    actual_demand,
                    units_sold,
                    stockout_impact,
                    stockout_flag,
                    scenario_override
                    or _generation_scenario(
                        actual_demand,
                        promotion_flag,
                        stockout_flag,
                    ),
                    CREATED_AT,
                )
            )
            record_number += 1

    return (
        pd.DataFrame(sales_rows, columns=SALES_COLUMNS),
        pd.DataFrame(truth_rows, columns=GROUND_TRUTH_COLUMNS),
    )


def validate_sales_data(sales, ground_truth, master_data):
    _require(
        list(sales.columns) == SALES_COLUMNS,
        "SalesHistory columns do not match Backend/database/schema.sql.",
    )
    _require(
        list(ground_truth.columns) == GROUND_TRUTH_COLUMNS,
        "GroundTruthDemand columns do not match Backend/database/schema.sql.",
    )
    _require(
        not {"actual_demand", "stockout_impact", "generation_scenario"}
        & set(sales.columns),
        "SalesHistory contains ground-truth-only fields.",
    )
    _require(len(sales) == len(ground_truth), "Sales and ground-truth row counts differ.")
    _require(
        not sales["sales_id"].duplicated().any(),
        "Duplicate SalesHistory primary key.",
    )
    _require(
        not ground_truth["truth_id"].duplicated().any(),
        "Duplicate GroundTruthDemand primary key.",
    )
    _require(
        sales["sales_id"].astype(str).str.fullmatch(SALES_ID_PATTERN).all(),
        "Invalid SalesHistory ID format.",
    )
    _require(
        ground_truth["truth_id"].astype(str).str.fullmatch(TRUTH_ID_PATTERN).all(),
        "Invalid GroundTruthDemand ID format.",
    )
    _require(
        not sales.duplicated(["store_id", "sku_id", "sales_date"]).any(),
        "Duplicate StoreSKU/sales_date record.",
    )
    _require(
        not ground_truth.duplicated(["store_id", "sku_id", "demand_date"]).any(),
        "Duplicate StoreSKU/demand_date record.",
    )

    valid_store_ids = set(master_data["Store"]["store_id"])
    valid_sku_ids = set(master_data["SKU"]["sku_id"])
    _require(
        sales["store_id"].isin(valid_store_ids).all()
        and ground_truth["store_id"].isin(valid_store_ids).all(),
        "Sales data contains an invalid store foreign key.",
    )
    _require(
        sales["sku_id"].isin(valid_sku_ids).all()
        and ground_truth["sku_id"].isin(valid_sku_ids).all(),
        "Sales data contains an invalid SKU foreign key.",
    )

    periods = _get_eligible_periods(master_data)
    expected_count = sum(
        (period["valid_to"] - period["valid_from"]).days
        for period in periods
    )
    _require(
        len(sales) == expected_count,
        "Sales data does not contain one row for every eligible StoreSKU/date.",
    )

    period_frame = pd.DataFrame(
        periods,
        columns=["store_id", "sku_id", "valid_from", "valid_to"],
    )
    joined_sales = sales.merge(
        period_frame,
        on=["store_id", "sku_id"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    _require(
        (joined_sales["_merge"] == "both").all(),
        "Sales data contains a relationship outside an eligible assortment.",
    )
    _require(
        (
            (joined_sales["sales_date"] >= joined_sales["valid_from"])
            & (joined_sales["sales_date"] < joined_sales["valid_to"])
        ).all(),
        "Sales data contains a date outside its assortment lifecycle window.",
    )
    _require(
        sales["sales_date"].between(SALES_START_DATE, REFERENCE_DATE).all(),
        "Sales data contains a date outside the configured sales window.",
    )

    sales_keys = sales[["store_id", "sku_id", "sales_date"]].reset_index(drop=True)
    truth_keys = (
        ground_truth[["store_id", "sku_id", "demand_date"]]
        .rename(columns={"demand_date": "sales_date"})
        .reset_index(drop=True)
    )
    _require(
        sales_keys.equals(truth_keys),
        "SalesHistory and GroundTruthDemand keys do not match.",
    )

    _require((sales["units_sold"] >= 0).all(), "Observed sales must be nonnegative.")
    _require((sales["sales_amount"] >= 0).all(), "Sales amounts must be nonnegative.")
    _require(
        (ground_truth["actual_demand"] >= 0).all()
        and (ground_truth["observed_sales"] >= 0).all()
        and (ground_truth["stockout_impact"] >= 0).all(),
        "Ground-truth quantities must be nonnegative.",
    )
    _require(
        (ground_truth["actual_demand"] >= ground_truth["observed_sales"]).all(),
        "Actual demand cannot be less than observed sales.",
    )
    _require(
        (
            ground_truth["actual_demand"]
            == ground_truth["observed_sales"] + ground_truth["stockout_impact"]
        ).all(),
        "Stockout impact does not reconcile to actual demand.",
    )
    _require(
        np.array_equal(
            sales["units_sold"].to_numpy(),
            ground_truth["observed_sales"].to_numpy(),
        ),
        "Observed sales do not match GroundTruthDemand.",
    )
    _require(
        np.array_equal(
            sales["stockout_flag"].to_numpy(),
            ground_truth["stockout_flag"].to_numpy(),
        )
        and np.array_equal(
            ground_truth["stockout_flag"].to_numpy(),
            (ground_truth["stockout_impact"] > 0).to_numpy(),
        ),
        "Stockout flags are inconsistent with censored demand.",
    )

    unit_prices = master_data["SKU"].set_index("sku_id")["unit_price"]
    expected_amounts = np.round(
        sales["units_sold"].to_numpy(dtype=float)
        * sales["sku_id"].map(unit_prices).to_numpy(dtype=float),
        2,
    )
    _require(
        np.allclose(
            sales["sales_amount"].to_numpy(dtype=float),
            expected_amounts,
            rtol=0,
            atol=1e-9,
        ),
        "Sales amounts do not match units_sold multiplied by SKU unit_price.",
    )
    _require(
        (
            sales["promotion_flag"]
            == sales["promotion_id"].notna()
        ).all(),
        "Promotion flags and promotion IDs are inconsistent.",
    )


def generate_sales_data(profile_name=DEFAULT_PROFILE):
    if profile_name not in PROFILES:
        valid_profiles = ", ".join(sorted(PROFILES))
        raise ValueError(
            f"Unknown profile {profile_name!r}. Choose one of: {valid_profiles}."
        )

    master_data = generate_master_data(profile_name)
    sales, ground_truth = _build_sales_records(master_data, profile_name)
    validate_sales_data(sales, ground_truth, master_data)

    return {
        "SalesHistory": sales,
        "GroundTruthDemand": ground_truth,
    }


def export_sales_data(data, output_directory=EXPORT_DIRECTORY):
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    for table_name, frame in data.items():
        frame.to_csv(output_directory / f"{table_name}.csv", index=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate synthetic daily sales data.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=DEFAULT_PROFILE,
        help="Data volume profile to generate.",
    )
    args = parser.parse_args(argv)

    data = generate_sales_data(args.profile)
    export_sales_data(data)

    sales = data["SalesHistory"]
    ground_truth = data["GroundTruthDemand"]
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Profile: {args.profile}")
    print(f"Sales window: {SALES_START_DATE} through {REFERENCE_DATE}")
    print(f"Configured window length: {SALES_HISTORY_DAYS} days")
    print(f"CSV output: {EXPORT_DIRECTORY}")
    print(f"SalesHistory: {len(sales)} rows")
    print(f"GroundTruthDemand: {len(ground_truth)} rows")
    print(f"Promotion records: {int(sales['promotion_flag'].sum())}")
    print(f"Stockout records: {int(sales['stockout_flag'].sum())}")
    print(
        "True zero-demand records: "
        f"{int(((ground_truth['actual_demand'] == 0) & ~ground_truth['stockout_flag']).sum())}"
    )
    print(
        "Zero-sales stockout records: "
        f"{int(((sales['units_sold'] == 0) & sales['stockout_flag']).sum())}"
    )


if __name__ == "__main__":
    main()
