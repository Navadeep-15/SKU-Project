from datetime import timedelta

import pandas as pd

from config import REFERENCE_DATE, SALES_START_DATE
from Backend.data_generation.master_generator import generate_master_data
from Backend.data_generation.sales_generator import (
    GROUND_TRUTH_COLUMNS,
    SALES_COLUMNS,
    export_sales_data,
    generate_sales_data,
    validate_sales_data,
)


def _copy_data(data):
    return {
        table_name: frame.copy(deep=True)
        for table_name, frame in data.items()
    }


def test_generation_is_deterministic():
    first = generate_sales_data("test")
    second = generate_sales_data("test")

    for table_name in first:
        pd.testing.assert_frame_equal(first[table_name], second[table_name])


def test_foreign_keys_and_unique_store_sku_dates():
    master_data = generate_master_data("test")
    data = _copy_data(generate_sales_data("test"))
    sales = data["SalesHistory"]
    ground_truth = data["GroundTruthDemand"]
    validate_sales_data(sales, ground_truth, master_data)

    assert sales["store_id"].isin(master_data["Store"]["store_id"]).all()
    assert sales["sku_id"].isin(master_data["SKU"]["sku_id"]).all()
    assert ground_truth["store_id"].isin(master_data["Store"]["store_id"]).all()
    assert ground_truth["sku_id"].isin(master_data["SKU"]["sku_id"]).all()
    assert not sales.duplicated(["store_id", "sku_id", "sales_date"]).any()
    assert not ground_truth.duplicated(
        ["store_id", "sku_id", "demand_date"]
    ).any()


def test_dates_respect_sales_window_lifecycle_and_assortments():
    master_data = generate_master_data("test")
    sales = generate_sales_data("test")["SalesHistory"]
    sku_data = master_data["SKU"]
    store_sku_data = master_data["StoreSKU"]
    stores = master_data["Store"]

    joined = (
        sales.merge(
            store_sku_data[
                [
                    "store_id",
                    "sku_id",
                    "active_from",
                    "active_to",
                    "assortment_status",
                ]
            ],
            on=["store_id", "sku_id"],
            validate="many_to_one",
        )
        .merge(
            sku_data[
                ["sku_id", "launch_date", "discontinue_date", "lifecycle_state"]
            ],
            on="sku_id",
            validate="many_to_one",
        )
        .merge(
            stores[["store_id", "active_flag"]],
            on="store_id",
            validate="many_to_one",
        )
    )

    assert sales["sales_date"].between(SALES_START_DATE, REFERENCE_DATE).all()
    assert (joined["sales_date"] >= joined["launch_date"]).all()
    assert (joined["sales_date"] >= joined["active_from"]).all()
    assert (
        joined["discontinue_date"].isna()
        | (joined["sales_date"] < joined["discontinue_date"])
    ).all()
    assert (
        joined["active_to"].isna() | (joined["sales_date"] < joined["active_to"])
    ).all()
    assert joined["assortment_status"].isin(["ACTIVE", "DISCONTINUED"]).all()
    assert joined["active_flag"].all()

    discontinued_sales = joined[joined["lifecycle_state"] == "DISCONTINUED"]
    discontinued_skus = sku_data[
        sku_data["lifecycle_state"] == "DISCONTINUED"
    ]
    assert not discontinued_skus.empty
    assert not discontinued_sales.empty
    assert (
        discontinued_sales["sales_date"] < discontinued_sales["discontinue_date"]
    ).all()


def test_demand_sales_and_amounts_reconcile():
    data = generate_sales_data("test")
    sales = data["SalesHistory"]
    ground_truth = data["GroundTruthDemand"]

    assert (ground_truth["actual_demand"] >= 0).all()
    assert (sales["units_sold"] >= 0).all()
    assert (sales["units_sold"] <= ground_truth["actual_demand"]).all()
    assert (
        ground_truth["stockout_impact"]
        == ground_truth["actual_demand"] - sales["units_sold"]
    ).all()
    assert (sales["sales_amount"] >= 0).all()

    master_skus = generate_master_data("test")["SKU"].set_index("sku_id")
    expected_amounts = (
        sales["units_sold"]
        * sales["sku_id"].map(master_skus["unit_price"])
    ).round(2)
    pd.testing.assert_series_equal(
        sales["sales_amount"].rename("sales_amount"),
        expected_amounts.rename("sales_amount"),
        check_dtype=False,
    )


def test_test_profile_has_genuine_zero_demand_days():
    ground_truth = generate_sales_data("test")["GroundTruthDemand"]
    zero_demand = ground_truth[
        (ground_truth["actual_demand"] == 0)
        & (ground_truth["stockout_flag"] == False)
    ]

    assert not zero_demand.empty


def test_test_profile_has_stockout_censored_and_zero_sales_stockouts():
    data = generate_sales_data("test")
    sales = data["SalesHistory"]
    ground_truth = data["GroundTruthDemand"]
    censored = ground_truth[ground_truth["stockout_impact"] > 0]
    zero_sales_stockouts = sales[
        (sales["units_sold"] == 0) & sales["stockout_flag"]
    ]

    assert not censored.empty
    assert not zero_sales_stockouts.empty


def test_test_profile_contains_promotions_and_no_ground_truth_leakage():
    data = generate_sales_data("test")
    sales = data["SalesHistory"]

    assert sales["promotion_flag"].any()
    assert sales["promotion_id"].notna().any()
    assert set(sales.columns) == set(SALES_COLUMNS)
    assert set(data["GroundTruthDemand"].columns) == set(GROUND_TRUTH_COLUMNS)
    assert not {
        "actual_demand",
        "stockout_impact",
        "generation_scenario",
        "observed_sales",
    }.intersection(sales.columns)


def test_csv_export_uses_schema_columns_and_expected_files(tmp_path):
    data = generate_sales_data("test")
    export_sales_data(data, tmp_path)

    for table_name, expected_columns in (
        ("SalesHistory", SALES_COLUMNS),
        ("GroundTruthDemand", GROUND_TRUTH_COLUMNS),
    ):
        csv_path = tmp_path / f"{table_name}.csv"
        exported = pd.read_csv(csv_path)
        assert csv_path.exists()
        assert list(exported.columns) == expected_columns
        assert len(exported) == len(data[table_name])
