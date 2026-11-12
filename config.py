from datetime import date, timedelta


PROFILES = {
    "dev": {
        "sku_count": 250,
        "store_count": 20,
        "supplier_count": 30,
    },
    "test": {
        "sku_count": 10,
        "store_count": 3,
        "supplier_count": 5,
    },
}

DEFAULT_PROFILE = "dev"
RANDOM_SEED = 20261022
DATASET_VERSION = "master-data-v1.0"
REFERENCE_DATE = date(2026, 10, 22)
SALES_HISTORY_DAYS = 365
SALES_START_DATE = REFERENCE_DATE - timedelta(days=364)
LAUNCH_WINDOW_DAYS = 90
