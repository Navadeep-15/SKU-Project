from datetime import timedelta

import pandas as pd
import pytest

from config import (
    PROFILES,
    REFERENCE_DATE,
    SALES_HISTORY_DAYS,
    SALES_START_DATE,
)
from Backend.data_generation.master_generator import (
    generate_master_data,
    validate_master_data,
)


@pytest.fixture(scope="module")
def generated_test_data():
    return generate_master_data("test")


def _copy_data(data):
    return {
        table_name: frame.copy(deep=True)
        for table_name, frame in data.items()
    }


def test_sales_window_contains_365_calendar_dates():
    assert SALES_HISTORY_DAYS == 365
    assert (REFERENCE_DATE - SALES_START_DATE).days + 1 == SALES_HISTORY_DAYS


def test_test_profile_record_counts_and_primary_keys(generated_test_data):
    data = _copy_data(generated_test_data)

    assert len(data["SKU"]) == PROFILES["test"]["sku_count"]
    assert len(data["Store"]) == PROFILES["test"]["store_count"]
    assert len(data["Supplier"]) == PROFILES["test"]["supplier_count"]

    for table_name, primary_key in (
        ("SKU", "sku_id"),
        ("Store", "store_id"),
        ("Supplier", "supplier_id"),
        ("StoreSKU", "store_sku_id"),
        ("SupplierSKU", "supplier_sku_id"),
    ):
        assert data[table_name][primary_key].is_unique


def test_generation_is_reproducible():
    first = generate_master_data("test")
    second = generate_master_data("test")

    for table_name in first:
        pd.testing.assert_frame_equal(first[table_name], second[table_name])


def test_generated_relationships_and_constraints(generated_test_data):
    data = _copy_data(generated_test_data)
    validate_master_data(data, "test")

    sku_ids = set(data["SKU"]["sku_id"])
    store_ids = set(data["Store"]["store_id"])
    supplier_ids = set(data["Supplier"]["supplier_id"])

    assert data["StoreSKU"]["sku_id"].isin(sku_ids).all()
    assert data["StoreSKU"]["store_id"].isin(store_ids).all()
    assert data["SupplierSKU"]["sku_id"].isin(sku_ids).all()
    assert data["SupplierSKU"]["supplier_id"].isin(supplier_ids).all()

    assert (data["Store"]["capacity_units"] > 0).all()
    assert (data["SupplierSKU"]["pack_size"] > 0).all()
    assert (data["SupplierSKU"]["min_order_qty"] > 0).all()
    assert (data["SupplierSKU"]["lead_time_days"] >= 0).all()
    assert (data["SupplierSKU"]["contract_cost"] >= 0).all()


def test_validation_rejects_duplicate_primary_key(generated_test_data):
    data = _copy_data(generated_test_data)
    duplicate = data["StoreSKU"].iloc[[0]].copy()
    data["StoreSKU"] = pd.concat([data["StoreSKU"], duplicate], ignore_index=True)

    with pytest.raises(ValueError, match="Duplicate primary key in StoreSKU"):
        validate_master_data(data, "test")


def test_validation_rejects_invalid_foreign_key(generated_test_data):
    data = _copy_data(generated_test_data)
    data["StoreSKU"].loc[0, "store_id"] = "STORE-999999"

    with pytest.raises(ValueError, match="broken store or supplier foreign key"):
        validate_master_data(data, "test")


def test_validation_rejects_overlapping_effective_periods(generated_test_data):
    data = _copy_data(generated_test_data)
    overlapping_row = data["StoreSKU"].iloc[[0]].copy()
    overlapping_row.loc[:, "store_sku_id"] = "SSK-999999"
    overlapping_row.loc[:, "active_from"] = (
        overlapping_row.iloc[0]["active_from"] + timedelta(days=1)
    )
    data["StoreSKU"] = pd.concat(
        [data["StoreSKU"], overlapping_row],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="Overlapping effective periods"):
        validate_master_data(data, "test")


def test_validation_rejects_active_assortment_without_active_supplier(
    generated_test_data,
):
    data = _copy_data(generated_test_data)
    active_sku_ids = set(
        data["SKU"].loc[
            data["SKU"]["lifecycle_state"] == "ACTIVE",
            "sku_id",
        ]
    )
    assortment = data["StoreSKU"].loc[
        data["StoreSKU"]["sku_id"].isin(active_sku_ids)
        & (data["StoreSKU"]["assortment_status"] == "ACTIVE")
    ].iloc[0]
    supplier_sku_mask = data["SupplierSKU"]["sku_id"] == assortment["sku_id"]
    data["SupplierSKU"].loc[supplier_sku_mask, "active_to"] = REFERENCE_DATE

    with pytest.raises(ValueError, match="has no active supplier"):
        validate_master_data(data, "test")


def test_validation_rejects_negative_supplier_lead_time(generated_test_data):
    data = _copy_data(generated_test_data)
    data["SupplierSKU"].loc[0, "lead_time_days"] = -1

    with pytest.raises(ValueError, match="lead times must be nonnegative"):
        validate_master_data(data, "test")


def test_validation_rejects_invalid_discontinued_sku_dates(generated_test_data):
    data = _copy_data(generated_test_data)
    discontinued_index = data["SKU"].index[
        data["SKU"]["lifecycle_state"] == "DISCONTINUED"
    ][0]
    launch_date = data["SKU"].loc[discontinued_index, "launch_date"]
    data["SKU"].loc[discontinued_index, "discontinue_date"] = launch_date

    with pytest.raises(ValueError, match="invalid discontinued dates"):
        validate_master_data(data, "test")
