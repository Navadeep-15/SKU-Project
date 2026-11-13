from datetime import date, timedelta


# Single supported dataset configuration: 10 SKUs, 3 stores, 5 suppliers.
PROFILES = {
    "test": {
        "sku_count": 10,
        "store_count": 3,
        "supplier_count": 5,
    },
}

DEFAULT_PROFILE = "test"
RANDOM_SEED = 20261022
DATASET_VERSION = "master-data-v1.0"
REFERENCE_DATE = date(2026, 10, 22)
SALES_HISTORY_DAYS = 365
SALES_START_DATE = REFERENCE_DATE - timedelta(days=364)
LAUNCH_WINDOW_DAYS = 90
