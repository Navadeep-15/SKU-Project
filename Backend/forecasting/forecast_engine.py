from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    DATASET_VERSION,
    RANDOM_SEED,
    REFERENCE_DATE,
)


FORECAST_RUN_COLUMNS = [
    "run_id",
    "model_name",
    "model_version",
    "forecast_origin",
    "horizon_days",
    "random_seed",
    "dataset_version",
    "feature_cutoff_date",
    "created_at",
]

FORECAST_COLUMNS = [
    "forecast_id",
    "run_id",
    "store_id",
    "sku_id",
    "target_date",
    "forecast_units",
    "lower_bound",
    "upper_bound",
    "model_name",
    "forecast_method",
    "created_at",
]

FORECAST_METHODS = ("BASELINE_7D", "WEEKDAY_SEASONAL_28D")
FORECAST_HORIZON_DAYS = 7
MIN_UNCENSORED_OBSERVATIONS = 3
MIN_WEEKDAY_OBSERVATIONS = 2
COLD_START_FORECAST = 0.0
PREDICTION_INTERVAL_Z = 1.96
MODEL_VERSION = "v1.0;unc_min=3;weekday_min=2;cold=0;pi95"
RUN_ID_PATTERN = r"RUN-[0-9]{6}"
FORECAST_ID_PATTERN = (
    r"FC-RUN-[0-9]{6}-STORE-[0-9]{6}-SKU-[0-9]{6}-"
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
)
FORECAST_INPUT_COLUMNS = {"sales_date", "units_sold", "stockout_flag"}
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
    converted = pd.to_datetime(value, errors="raise")
    return converted.date()


def _date_or_none(value):
    if pd.isna(value):
        return None
    return _as_date(value)


def _relationship_active_on(assortment, sku, store, check_date):
    assortment_end = _date_or_none(assortment.active_to)
    discontinue_date = _date_or_none(sku["discontinue_date"])
    return (
        bool(store["active_flag"])
        and assortment.assortment_status in {"ACTIVE", "DISCONTINUED"}
        and _as_date(assortment.active_from) <= check_date
        and (assortment_end is None or check_date < assortment_end)
        and _as_date(sku["launch_date"]) <= check_date
        and (discontinue_date is None or check_date < discontinue_date)
    )


def _prepare_forecast_history(historical_sales, forecast_origin, method):
    missing_columns = FORECAST_INPUT_COLUMNS - set(historical_sales.columns)
    _require(
        not missing_columns,
        "SalesHistory input is missing required columns: "
        + ", ".join(sorted(missing_columns)),
    )
    _require(method in FORECAST_METHODS, f"Unsupported forecast method: {method}.")

    history = historical_sales[
        ["sales_date", "units_sold", "stockout_flag"]
    ].copy()
    history["_sales_date"] = history["sales_date"].map(_as_date)
    history = history.loc[history["_sales_date"] <= forecast_origin]
    history = history.sort_values("_sales_date", kind="mergesort")
    window_days = 7 if method == "BASELINE_7D" else 28
    return history.tail(window_days)


def predict_daily_demand(
    historical_sales,
    forecast_origin,
    target_date,
    forecast_method,
):
    forecast_origin = _as_date(forecast_origin)
    target_date = _as_date(target_date)
    _require(
        target_date > forecast_origin,
        "Forecast target_date must be after forecast_origin.",
    )

    history = _prepare_forecast_history(
        historical_sales,
        forecast_origin,
        forecast_method,
    )
    uncensored = history.loc[~history["stockout_flag"].astype(bool)]

    if len(uncensored) >= MIN_UNCENSORED_OBSERVATIONS:
        usable_history = uncensored
        history_policy = "UN_CENSORED"
    else:
        usable_history = history.loc[
            (~history["stockout_flag"].astype(bool))
            | (history["units_sold"] > 0)
        ]
        history_policy = (
            "CENSORED_POSITIVE_FALLBACK"
            if (usable_history["stockout_flag"].astype(bool)).any()
            else "UNCENSORED_SPARSE"
        )

    if usable_history.empty:
        return {
            "forecast_units": COLD_START_FORECAST,
            "lower_bound": COLD_START_FORECAST,
            "upper_bound": COLD_START_FORECAST,
            "history_count": 0,
            "history_policy": "COLD_START_ZERO",
        }

    selected_history = usable_history
    if forecast_method == "WEEKDAY_SEASONAL_28D":
        matching_weekday = usable_history.loc[
            usable_history["_sales_date"].map(
                lambda historical_date: historical_date.weekday()
            )
            == target_date.weekday()
        ]
        if len(matching_weekday) >= MIN_WEEKDAY_OBSERVATIONS:
            selected_history = matching_weekday
            history_policy += "_WEEKDAY"
        else:
            history_policy += "_OVERALL_FALLBACK"

    values = selected_history["units_sold"].to_numpy(dtype=float)
    mean_forecast = max(0.0, float(np.mean(values)))
    if len(values) > 1:
        standard_deviation = float(np.std(values, ddof=1))
    else:
        standard_deviation = float(np.sqrt(mean_forecast))

    forecast_units = round(mean_forecast, 2)
    margin = PREDICTION_INTERVAL_Z * standard_deviation
    lower_bound = round(max(0.0, mean_forecast - margin), 2)
    upper_bound = round(max(mean_forecast, mean_forecast + margin), 2)
    lower_bound = min(lower_bound, forecast_units)
    upper_bound = max(upper_bound, forecast_units)

    return {
        "forecast_units": forecast_units,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "history_count": len(selected_history),
        "history_policy": history_policy,
    }


def validate_forecast_data(data, master_data):
    _require(
        set(data) == {"ForecastRun", "Forecast"},
        "Generated table set does not match the Forecast schema.",
    )
    runs = data["ForecastRun"]
    forecasts = data["Forecast"]
    _require(
        list(runs.columns) == FORECAST_RUN_COLUMNS,
        "ForecastRun columns do not match Backend/database/schema.sql.",
    )
    _require(
        list(forecasts.columns) == FORECAST_COLUMNS,
        "Forecast columns do not match Backend/database/schema.sql.",
    )

    _require(not runs["run_id"].duplicated().any(), "Duplicate ForecastRun ID.")
    _require(
        runs["run_id"].astype(str).str.fullmatch(RUN_ID_PATTERN).all(),
        "Invalid ForecastRun ID format.",
    )
    _require(
        not forecasts["forecast_id"].duplicated().any(),
        "Duplicate Forecast ID.",
    )
    _require(
        forecasts["forecast_id"].astype(str).str.fullmatch(FORECAST_ID_PATTERN).all(),
        "Invalid Forecast ID format.",
    )
    _require(
        not runs.duplicated(["forecast_origin", "model_name"]).any(),
        "Duplicate ForecastRun method/origin combination.",
    )

    store_ids = set(master_data["Store"]["store_id"])
    sku_ids = set(master_data["SKU"]["sku_id"])
    _require(
        forecasts["store_id"].isin(store_ids).all()
        and forecasts["sku_id"].isin(sku_ids).all(),
        "Forecast contains an invalid store or SKU foreign key.",
    )
    _require(
        set(forecasts["run_id"]).issubset(set(runs["run_id"])),
        "Forecast contains an invalid ForecastRun foreign key.",
    )
    _require(
        runs["model_name"].isin(FORECAST_METHODS).all()
        and forecasts["forecast_method"].isin(FORECAST_METHODS).all(),
        "Forecast data contains an invalid forecasting method.",
    )
    _require(
        (runs["horizon_days"] > 0).all()
        and (runs["horizon_days"] % 1 == 0).all(),
        "ForecastRun horizons must be positive whole numbers of days.",
    )
    _require(
        (runs["feature_cutoff_date"] <= runs["forecast_origin"]).all(),
        "ForecastRun feature cutoff cannot exceed forecast origin.",
    )
    _require(
        (runs["random_seed"] == RANDOM_SEED).all()
        and (runs["dataset_version"] == DATASET_VERSION).all(),
        "ForecastRun provenance does not match the configured dataset.",
    )
    _require(
        runs["model_version"].eq(MODEL_VERSION).all(),
        "ForecastRun model version does not match the configured forecast rules.",
    )
    _require(
        (forecasts["forecast_units"] >= 0).all(),
        "Forecast quantities must be nonnegative.",
    )
    _require(
        (
            (forecasts["lower_bound"] >= 0)
            & (forecasts["lower_bound"] <= forecasts["forecast_units"])
            & (forecasts["forecast_units"] <= forecasts["upper_bound"])
        ).all(),
        "Forecast bounds are invalid.",
    )
    _require(
        not forecasts.duplicated(
            ["run_id", "store_id", "sku_id", "target_date"]
        ).any(),
        "Duplicate run/store/SKU/target-date forecast.",
    )

    run_details = runs.set_index("run_id")
    stores = master_data["Store"].set_index("store_id")
    skus = master_data["SKU"].set_index("sku_id")
    assortments = master_data["StoreSKU"].set_index(["store_id", "sku_id"])
    expected_forecasts = set()

    for run in runs.itertuples(index=False):
        forecast_origin = _as_date(run.forecast_origin)
        for assortment in master_data["StoreSKU"].itertuples(index=False):
            sku = skus.loc[assortment.sku_id]
            store = stores.loc[assortment.store_id]
            if not _relationship_active_on(
                assortment,
                sku,
                store,
                forecast_origin,
            ):
                continue
            for horizon_day in range(1, int(run.horizon_days) + 1):
                target_date = forecast_origin + timedelta(days=horizon_day)
                if _relationship_active_on(assortment, sku, store, target_date):
                    expected_forecasts.add(
                        (
                            run.run_id,
                            assortment.store_id,
                            assortment.sku_id,
                            target_date,
                        )
                    )

    actual_forecasts = set()
    for forecast in forecasts.itertuples(index=False):
        run = run_details.loc[forecast.run_id]
        forecast_origin = _as_date(run["forecast_origin"])
        target_date = _as_date(forecast.target_date)
        _require(
            forecast.forecast_method == run["model_name"]
            and forecast.model_name
            in {
                run["model_name"],
                f"{run['model_name']}_COLD_START_ZERO",
            },
            "Forecast method/model name does not match its ForecastRun.",
        )
        _require(
            forecast_origin < target_date
            <= forecast_origin + timedelta(days=int(run["horizon_days"])),
            "Forecast target date falls outside its ForecastRun horizon.",
        )
        assortment = assortments.loc[(forecast.store_id, forecast.sku_id)]
        sku = skus.loc[forecast.sku_id]
        store = stores.loc[forecast.store_id]
        _require(
            _relationship_active_on(
                assortment,
                sku,
                store,
                forecast_origin,
            )
            and _relationship_active_on(
                assortment,
                sku,
                store,
                target_date,
            ),
            "Forecast falls outside its eligible SKU-store dates.",
        )
        actual_forecasts.add(
            (
                forecast.run_id,
                forecast.store_id,
                forecast.sku_id,
                target_date,
            )
        )
    _require(
        actual_forecasts == expected_forecasts,
        "Forecast rows do not match the eligible SKU-store horizon dates.",
    )


def generate_forecast_data(
    master_data,
    sales_history,
    forecast_origins=None,
    forecast_horizon_overrides=None,
):
    required_sales_columns = {
        "sales_id",
        "store_id",
        "sku_id",
        "sales_date",
        "units_sold",
        "stockout_flag",
    }
    _require(
        required_sales_columns.issubset(sales_history.columns),
        "SalesHistory input is missing required columns.",
    )
    _require(
        not {"actual_demand", "stockout_impact", "generation_scenario"}.intersection(
            sales_history.columns
        ),
        "Forecasting accepts observed SalesHistory only.",
    )
    _require(
        (sales_history["units_sold"] >= 0).all(),
        "SalesHistory units_sold must be nonnegative.",
    )

    if forecast_origins is None:
        forecast_origins = [REFERENCE_DATE]
    origins = [_as_date(origin) for origin in forecast_origins]
    _require(origins, "At least one forecast origin is required.")
    _require(
        len(origins) == len(set(origins)),
        "Forecast origins must be unique.",
    )
    _require(
        all(origin <= REFERENCE_DATE for origin in origins),
        "Forecast origins cannot be later than the configured reference date.",
    )

    horizon_overrides = {}
    if forecast_horizon_overrides is not None:
        for key, horizon_days in forecast_horizon_overrides.items():
            _require(
                isinstance(key, tuple) and len(key) == 2,
                "Forecast horizon override keys must be (origin, method) pairs.",
            )
            forecast_origin = _as_date(key[0])
            forecast_method = key[1]
            _require(
                forecast_origin in origins
                and forecast_method in FORECAST_METHODS,
                "Forecast horizon override has an unknown origin or method.",
            )
            _require(
                not isinstance(horizon_days, bool)
                and int(horizon_days) == horizon_days
                and int(horizon_days) > 0,
                "Forecast horizon overrides must be positive whole numbers.",
            )
            horizon_overrides[(forecast_origin, forecast_method)] = int(
                horizon_days
            )

    history_by_relationship = {
        key: group.sort_values("sales_date", kind="mergesort")
        for key, group in sales_history.groupby(
            ["store_id", "sku_id"],
            sort=True,
        )
    }
    skus_by_id = master_data["SKU"].set_index("sku_id")
    stores_by_id = master_data["Store"].set_index("store_id")
    run_rows = []
    forecast_rows = []
    run_number = 0

    for forecast_origin in sorted(origins):
        for forecast_method in FORECAST_METHODS:
            horizon_days = horizon_overrides.get(
                (forecast_origin, forecast_method),
                FORECAST_HORIZON_DAYS,
            )
            run_number += 1
            _require(run_number <= 999_999, "ForecastRun ID limit exceeded.")
            run_id = f"RUN-{run_number:06d}"
            run_rows.append(
                (
                    run_id,
                    forecast_method,
                    MODEL_VERSION,
                    forecast_origin,
                    horizon_days,
                    RANDOM_SEED,
                    DATASET_VERSION,
                    forecast_origin,
                    CREATED_AT,
                )
            )

            for assortment in master_data["StoreSKU"].itertuples(index=False):
                sku = skus_by_id.loc[assortment.sku_id]
                store = stores_by_id.loc[assortment.store_id]
                if not _relationship_active_on(
                    assortment,
                    sku,
                    store,
                    forecast_origin,
                ):
                    continue

                relationship = (assortment.store_id, assortment.sku_id)
                history = history_by_relationship.get(
                    relationship,
                    sales_history.iloc[0:0],
                )
                for horizon_day in range(1, horizon_days + 1):
                    target_date = forecast_origin + timedelta(days=horizon_day)
                    if not _relationship_active_on(
                        assortment,
                        sku,
                        store,
                        target_date,
                    ):
                        continue

                    prediction = predict_daily_demand(
                        history,
                        forecast_origin,
                        target_date,
                        forecast_method,
                    )
                    forecast_rows.append(
                        (
                            (
                                f"FC-{run_id}-{assortment.store_id}-"
                                f"{assortment.sku_id}-{target_date.isoformat()}"
                            ),
                            run_id,
                            assortment.store_id,
                            assortment.sku_id,
                            target_date,
                            prediction["forecast_units"],
                            prediction["lower_bound"],
                            prediction["upper_bound"],
                            (
                                f"{forecast_method}_COLD_START_ZERO"
                                if prediction["history_policy"] == "COLD_START_ZERO"
                                else forecast_method
                            ),
                            forecast_method,
                            CREATED_AT,
                        )
                    )

    data = {
        "ForecastRun": pd.DataFrame(run_rows, columns=FORECAST_RUN_COLUMNS),
        "Forecast": pd.DataFrame(forecast_rows, columns=FORECAST_COLUMNS),
    }
    validate_forecast_data(data, master_data)
    return data


def export_forecast_data(data, output_directory=GENERATED_DATA_DIRECTORY):
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    for table_name, frame in data.items():
        frame.to_csv(output_directory / f"{table_name}.csv", index=False)
