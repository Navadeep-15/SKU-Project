import argparse
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    DATASET_VERSION,
    DEFAULT_PROFILE,
    LAUNCH_WINDOW_DAYS,
    PROFILES,
    RANDOM_SEED,
    REFERENCE_DATE,
)


TABLE_COLUMNS = {
    "SKU": [
        "sku_id",
        "sku_name",
        "category",
        "brand",
        "unit_cost",
        "unit_price",
        "lifecycle_state",
        "launch_date",
        "discontinue_date",
        "created_at",
    ],
    "Store": [
        "store_id",
        "store_name",
        "city",
        "region",
        "store_type",
        "capacity_units",
        "active_flag",
        "created_at",
    ],
    "Supplier": [
        "supplier_id",
        "supplier_name",
        "supplier_type",
        "active_flag",
        "created_at",
    ],
    "StoreSKU": [
        "store_sku_id",
        "store_id",
        "sku_id",
        "active_from",
        "active_to",
        "assortment_status",
        "created_at",
    ],
    "SupplierSKU": [
        "supplier_sku_id",
        "supplier_id",
        "sku_id",
        "lead_time_days",
        "min_order_qty",
        "pack_size",
        "contract_cost",
        "supplier_priority",
        "is_preferred_supplier",
        "active_from",
        "active_to",
    ],
}

ID_PATTERNS = {
    "SKU": ("sku_id", r"SKU-[0-9]{6}"),
    "Store": ("store_id", r"STORE-[0-9]{6}"),
    "Supplier": ("supplier_id", r"SUP-[0-9]{6}"),
    "StoreSKU": ("store_sku_id", r"SSK-[0-9]{6}"),
    "SupplierSKU": ("supplier_sku_id", r"PSK-[0-9]{6}"),
}

PRODUCT_CATEGORIES = {
    "Beverages": (0.50, 18.00),
    "Grocery": (1.00, 45.00),
    "Household": (2.00, 80.00),
    "Personal Care": (2.00, 60.00),
    "Beauty": (4.00, 120.00),
    "Apparel": (8.00, 180.00),
    "Electronics": (12.00, 300.00),
}

BRANDS = [
    "Northstar",
    "Evergreen",
    "Brightway",
    "Fieldstone",
    "Harbor & Pine",
    "Summit",
    "Cedar Grove",
    "Clearwater",
    "Redwood",
    "Bluebird",
]

PRODUCT_NAMES = [
    "Classic",
    "Everyday",
    "Premium",
    "Essential",
    "Value",
    "Select",
    "Comfort",
    "Signature",
]

CITIES = [
    ("Seattle", "WASHINGTON"),
    ("Portland", "OREGON"),
    ("San Francisco", "CALIFORNIA"),
    ("Los Angeles", "CALIFORNIA"),
    ("San Diego", "CALIFORNIA"),
    ("Phoenix", "ARIZONA"),
    ("Denver", "COLORADO"),
    ("Dallas", "TEXAS"),
    ("Austin", "TEXAS"),
    ("Houston", "TEXAS"),
    ("Chicago", "ILLINOIS"),
    ("Minneapolis", "MINNESOTA"),
    ("Nashville", "TENNESSEE"),
    ("Atlanta", "GEORGIA"),
    ("Miami", "FLORIDA"),
    ("Charlotte", "NORTH CAROLINA"),
    ("Washington", "DISTRICT OF COLUMBIA"),
    ("Philadelphia", "PENNSYLVANIA"),
    ("New York", "NEW YORK"),
    ("Boston", "MASSACHUSETTS"),
]

STORE_TYPES = {
    "URBAN": (800, 2500),
    "SUBURBAN": (600, 2000),
    "EXPRESS": (200, 900),
}

SUPPLIER_TYPES = ["MANUFACTURER", "DISTRIBUTOR", "WHOLESALER"]
LIFECYCLE_STATES = ["ACTIVE", "LAUNCHED", "DISCONTINUED"]
ASSORTMENT_STATUSES = ["ACTIVE", "INACTIVE", "DISCONTINUED"]
PACK_SIZES = [1, 2, 4, 6, 12]

CREATED_AT = datetime.combine(
    REFERENCE_DATE,
    time.min,
    tzinfo=timezone.utc,
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_DIRECTORY = PROJECT_ROOT / "data" / "generated"


def _make_frame(table_name, rows):
    return pd.DataFrame(rows, columns=TABLE_COLUMNS[table_name])


def _create_skus(rng, sku_count):
    discontinued_count = max(1, sku_count // 20)
    launched_count = max(1, sku_count // 10)
    if discontinued_count + launched_count >= sku_count:
        discontinued_count = 1
        launched_count = max(0, sku_count - 2)

    states = (
        ["DISCONTINUED"] * discontinued_count
        + ["LAUNCHED"] * launched_count
        + ["ACTIVE"] * (sku_count - discontinued_count - launched_count)
    )
    states = [str(state) for state in rng.permutation(states)]

    rows = []
    category_names = list(PRODUCT_CATEGORIES)

    for index, lifecycle_state in enumerate(states, start=1):
        sku_id = f"SKU-{index:06d}"
        category = str(rng.choice(category_names))
        brand = str(rng.choice(BRANDS))
        product_name = str(rng.choice(PRODUCT_NAMES))
        unit_cost = round(float(rng.uniform(*PRODUCT_CATEGORIES[category])), 2)
        unit_price = round(unit_cost * float(rng.uniform(1.15, 2.10)), 2)
        discontinue_date = None

        if lifecycle_state == "LAUNCHED":
            launch_age_days = int(rng.integers(0, LAUNCH_WINDOW_DAYS + 1))
        elif lifecycle_state == "DISCONTINUED":
            discontinue_age_days = int(rng.integers(1, 181))
            launch_age_days = int(rng.integers(discontinue_age_days + 1, 1826))
            discontinue_date = REFERENCE_DATE - timedelta(days=discontinue_age_days)
        else:
            launch_age_days = int(rng.integers(LAUNCH_WINDOW_DAYS + 1, 1826))

        launch_date = REFERENCE_DATE - timedelta(days=launch_age_days)

        rows.append(
            {
                "sku_id": sku_id,
                "sku_name": f"{brand} {product_name} Product {index:03d}",
                "category": category,
                "brand": brand,
                "unit_cost": unit_cost,
                "unit_price": max(unit_cost, unit_price),
                "lifecycle_state": lifecycle_state,
                "launch_date": launch_date,
                "discontinue_date": discontinue_date,
                "created_at": CREATED_AT,
            }
        )

    return _make_frame("SKU", rows)


def _create_stores(rng, store_count):
    rows = []
    store_type_names = list(STORE_TYPES)

    for index in range(store_count):
        city, region = CITIES[index % len(CITIES)]
        store_type = str(rng.choice(store_type_names))
        capacity_min, capacity_max = STORE_TYPES[store_type]

        rows.append(
            {
                "store_id": f"STORE-{index + 1:06d}",
                "store_name": f"{city} Store {index + 1:03d}",
                "city": city,
                "region": region,
                "store_type": store_type,
                "capacity_units": int(rng.integers(capacity_min, capacity_max + 1)),
                "active_flag": True,
                "created_at": CREATED_AT,
            }
        )

    return _make_frame("Store", rows)


def _create_suppliers(rng, supplier_count):
    rows = []

    for index in range(supplier_count):
        supplier_type = str(rng.choice(SUPPLIER_TYPES))
        rows.append(
            {
                "supplier_id": f"SUP-{index + 1:06d}",
                "supplier_name": f"{supplier_type.title()} Partner {index + 1:03d}",
                "supplier_type": supplier_type,
                "active_flag": True,
                "created_at": CREATED_AT,
            }
        )

    return _make_frame("Supplier", rows)


def _create_store_skus(rng, skus, stores):
    rows = []
    store_count = len(stores)
    next_id = 1

    for sku_index, sku in enumerate(skus.itertuples(index=False)):
        base_store_index = sku_index % store_count
        extra_count = int(rng.integers(0, min(4, store_count - 1) + 1))
        other_store_indexes = [
            index for index in range(store_count) if index != base_store_index
        ]
        extra_store_indexes = (
            rng.choice(other_store_indexes, size=extra_count, replace=False).tolist()
            if extra_count
            else []
        )
        selected_store_indexes = sorted({base_store_index, *extra_store_indexes})

        for store_index in selected_store_indexes:
            if sku.lifecycle_state == "DISCONTINUED":
                assortment_status = "DISCONTINUED"
                active_to = sku.discontinue_date
            else:
                assortment_status = "ACTIVE"
                active_to = None

            rows.append(
                {
                    "store_sku_id": f"SSK-{next_id:06d}",
                    "store_id": stores.iloc[store_index]["store_id"],
                    "sku_id": sku.sku_id,
                    "active_from": sku.launch_date,
                    "active_to": active_to,
                    "assortment_status": assortment_status,
                    "created_at": CREATED_AT,
                }
            )
            next_id += 1

    return _make_frame("StoreSKU", rows)


def _create_supplier_skus(rng, skus, suppliers):
    rows = []
    supplier_count = len(suppliers)
    supplier_ids = suppliers["supplier_id"].tolist()

    for sku_index, sku in enumerate(skus.itertuples(index=False)):
        preferred_supplier_id = supplier_ids[sku_index % supplier_count]
        other_supplier_ids = [
            supplier_id
            for supplier_id in supplier_ids
            if supplier_id != preferred_supplier_id
        ]
        extra_count = int(rng.integers(0, min(2, supplier_count - 1) + 1))
        selected_other_ids = (
            rng.choice(other_supplier_ids, size=extra_count, replace=False).tolist()
            if extra_count
            else []
        )
        selected_supplier_ids = [preferred_supplier_id] + sorted(selected_other_ids)

        for priority, supplier_id in enumerate(selected_supplier_ids, start=1):
            pack_size = int(rng.choice(PACK_SIZES))
            min_order_qty = pack_size * int(rng.integers(1, 9))
            cost_factor = float(rng.uniform(0.85, 1.15))
            active_to = (
                sku.discontinue_date
                if sku.lifecycle_state == "DISCONTINUED"
                else None
            )

            rows.append(
                {
                    "supplier_sku_id": f"PSK-{len(rows) + 1:06d}",
                    "supplier_id": supplier_id,
                    "sku_id": sku.sku_id,
                    "lead_time_days": int(rng.integers(2, 31)),
                    "min_order_qty": min_order_qty,
                    "pack_size": pack_size,
                    "contract_cost": round(float(sku.unit_cost) * cost_factor, 2),
                    "supplier_priority": priority,
                    "is_preferred_supplier": supplier_id == preferred_supplier_id,
                    "active_from": sku.launch_date,
                    "active_to": active_to,
                }
            )

    return _make_frame("SupplierSKU", rows)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _date_or_none(value):
    return None if pd.isna(value) else value


def _validate_nonoverlapping_periods(frame, relationship_columns, start_column, end_column):
    for relationship, group in frame.groupby(relationship_columns, sort=True):
        intervals = sorted(
            (
                (
                    row[start_column],
                    _date_or_none(row[end_column]),
                )
                for _, row in group.iterrows()
            ),
            key=lambda interval: interval[0],
        )

        for index, (start, end) in enumerate(intervals):
            for next_start, _ in intervals[index + 1 :]:
                _require(
                    end is not None and next_start >= end,
                    f"Overlapping effective periods for relationship {relationship}.",
                )


def validate_master_data(data, profile_name):
    _require(profile_name in PROFILES, f"Unknown profile: {profile_name}")
    _require(set(data) == set(TABLE_COLUMNS), "Generated table set does not match schema.")

    for table_name, expected_columns in TABLE_COLUMNS.items():
        frame = data[table_name]
        _require(
            list(frame.columns) == expected_columns,
            f"{table_name} columns do not match Backend/database/schema.sql.",
        )

    profile = PROFILES[profile_name]
    for table_name, count_key in (
        ("SKU", "sku_count"),
        ("Store", "store_count"),
        ("Supplier", "supplier_count"),
    ):
        _require(
            len(data[table_name]) == profile[count_key],
            f"{table_name} count does not match profile {profile_name}.",
        )

    for table_name, (id_column, pattern) in ID_PATTERNS.items():
        frame = data[table_name]
        _require(
            not frame[id_column].duplicated().any(),
            f"Duplicate primary key in {table_name}.",
        )
        _require(
            frame[id_column].astype(str).str.fullmatch(pattern).all(),
            f"Invalid {id_column} format in {table_name}.",
        )

    skus = data["SKU"]
    stores = data["Store"]
    suppliers = data["Supplier"]
    store_skus = data["StoreSKU"]
    supplier_skus = data["SupplierSKU"]

    _require((skus["unit_cost"] >= 0).all(), "SKU unit_cost must be nonnegative.")
    _require(
        (skus["unit_price"] >= skus["unit_cost"]).all(),
        "SKU unit_price must be at least unit_cost.",
    )
    _require(
        skus["lifecycle_state"].isin(LIFECYCLE_STATES).all(),
        "Invalid SKU lifecycle_state.",
    )
    _require((stores["capacity_units"] > 0).all(), "Store capacity must be positive.")
    _require(
        stores["store_type"].isin(STORE_TYPES).all(),
        "Invalid Store store_type.",
    )
    _require(
        suppliers["supplier_type"].isin(SUPPLIER_TYPES).all(),
        "Invalid Supplier supplier_type.",
    )
    _require(
        (supplier_skus["lead_time_days"] >= 0).all(),
        "SupplierSKU lead times must be nonnegative.",
    )
    _require((supplier_skus["pack_size"] > 0).all(), "Pack sizes must be positive.")
    _require(
        (supplier_skus["min_order_qty"] > 0).all(),
        "Minimum order quantities must be positive.",
    )
    _require(
        (supplier_skus["contract_cost"] >= 0).all(),
        "SupplierSKU contract costs must be nonnegative.",
    )

    sku_by_id = skus.set_index("sku_id")
    for sku in skus.itertuples(index=False):
        discontinue_date = _date_or_none(sku.discontinue_date)
        _require(
            sku.launch_date <= REFERENCE_DATE,
            f"{sku.sku_id} has a launch date after the reference date.",
        )

        if sku.lifecycle_state == "LAUNCHED":
            launch_age = (REFERENCE_DATE - sku.launch_date).days
            _require(
                0 <= launch_age <= LAUNCH_WINDOW_DAYS,
                f"{sku.sku_id} is outside the configured launch window.",
            )
        elif sku.lifecycle_state == "DISCONTINUED":
            _require(
                discontinue_date is not None
                and sku.launch_date < discontinue_date <= REFERENCE_DATE,
                f"{sku.sku_id} has invalid discontinued dates.",
            )
        else:
            _require(
                discontinue_date is None,
                f"{sku.sku_id} must not have a discontinue_date.",
            )

    store_ids = set(stores["store_id"])
    active_store_ids = set(stores.loc[stores["active_flag"], "store_id"])
    sku_ids = set(skus["sku_id"])
    supplier_ids = set(suppliers["supplier_id"])
    active_supplier_ids = set(
        suppliers.loc[suppliers["active_flag"], "supplier_id"]
    )
    _require(
        store_skus["store_id"].isin(store_ids).all()
        and supplier_skus["supplier_id"].isin(supplier_ids).all(),
        "A bridge table contains a broken store or supplier foreign key.",
    )
    _require(
        store_skus["sku_id"].isin(sku_ids).all()
        and supplier_skus["sku_id"].isin(sku_ids).all(),
        "A bridge table contains a broken SKU foreign key.",
    )
    _require(
        not store_skus.duplicated(["store_id", "sku_id", "active_from"]).any(),
        "Duplicate StoreSKU store/SKU/effective-start relationship.",
    )
    _require(
        not supplier_skus.duplicated(
            ["supplier_id", "sku_id", "active_from"]
        ).any(),
        "Duplicate SupplierSKU supplier/SKU/effective-start relationship.",
    )
    _require(
        store_skus["assortment_status"].isin(ASSORTMENT_STATUSES).all(),
        "Invalid StoreSKU assortment_status.",
    )

    for table_name, frame, start_column, end_column in (
        ("StoreSKU", store_skus, "active_from", "active_to"),
        ("SupplierSKU", supplier_skus, "active_from", "active_to"),
    ):
        for row in frame.itertuples(index=False):
            start = getattr(row, start_column)
            end = _date_or_none(getattr(row, end_column))
            _require(
                end is None or end > start,
                f"{table_name} contains an invalid effective period.",
            )

    _validate_nonoverlapping_periods(
        store_skus,
        ["store_id", "sku_id"],
        "active_from",
        "active_to",
    )
    _validate_nonoverlapping_periods(
        supplier_skus,
        ["supplier_id", "sku_id"],
        "active_from",
        "active_to",
    )
    _validate_nonoverlapping_periods(
        supplier_skus[supplier_skus["is_preferred_supplier"]],
        ["sku_id"],
        "active_from",
        "active_to",
    )

    active_supplier_skus = supplier_skus[
        (supplier_skus["active_from"] <= REFERENCE_DATE)
        & (
            supplier_skus["active_to"].isna()
            | (supplier_skus["active_to"] > REFERENCE_DATE)
        )
    ]
    preferred_counts = (
        active_supplier_skus[active_supplier_skus["is_preferred_supplier"]]
        .groupby("sku_id")
        .size()
    )
    _require(
        (preferred_counts <= 1).all(),
        "A SKU has multiple active preferred suppliers.",
    )

    active_assortments = store_skus[
        (store_skus["assortment_status"] == "ACTIVE")
        & (store_skus["active_from"] <= REFERENCE_DATE)
        & (store_skus["active_to"].isna() | (store_skus["active_to"] > REFERENCE_DATE))
    ]
    for assortment in active_assortments.itertuples(index=False):
        sku = sku_by_id.loc[assortment.sku_id]
        _require(
            sku["lifecycle_state"] != "DISCONTINUED",
            f"Discontinued SKU {assortment.sku_id} has an active assortment.",
        )
        eligible_supplier_skus = active_supplier_skus[
            (active_supplier_skus["sku_id"] == assortment.sku_id)
            & (active_supplier_skus["supplier_id"].isin(active_supplier_ids))
        ]
        _require(
            not eligible_supplier_skus.empty,
            f"Active assortment {assortment.store_sku_id} has no active supplier.",
        )
        _require(
            assortment.store_id in active_store_ids,
            f"Active assortment {assortment.store_sku_id} belongs to an inactive store.",
        )


def generate_master_data(profile_name=DEFAULT_PROFILE):
    if profile_name not in PROFILES:
        valid_profiles = ", ".join(sorted(PROFILES))
        raise ValueError(
            f"Unknown profile {profile_name!r}. Choose one of: {valid_profiles}."
        )

    rng = np.random.default_rng(RANDOM_SEED)
    profile = PROFILES[profile_name]

    skus = _create_skus(rng, profile["sku_count"])
    stores = _create_stores(rng, profile["store_count"])
    suppliers = _create_suppliers(rng, profile["supplier_count"])
    store_skus = _create_store_skus(rng, skus, stores)
    supplier_skus = _create_supplier_skus(rng, skus, suppliers)

    data = {
        "SKU": skus,
        "Store": stores,
        "Supplier": suppliers,
        "StoreSKU": store_skus,
        "SupplierSKU": supplier_skus,
    }
    validate_master_data(data, profile_name)
    return data


def export_master_data(data, output_directory=EXPORT_DIRECTORY):
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    for table_name, frame in data.items():
        frame.to_csv(output_directory / f"{table_name}.csv", index=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate synthetic master data.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=DEFAULT_PROFILE,
        help="Data volume profile to generate.",
    )
    args = parser.parse_args(argv)

    data = generate_master_data(args.profile)
    export_master_data(data)

    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Profile: {args.profile}")
    print(f"Reference date: {REFERENCE_DATE.isoformat()}")
    print(f"CSV output: {EXPORT_DIRECTORY}")
    for table_name, frame in data.items():
        print(f"{table_name}: {len(frame)} rows")


if __name__ == "__main__":
    main()
