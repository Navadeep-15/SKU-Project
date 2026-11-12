import re
from datetime import timedelta

import pandas as pd
import pytest

from config import RANDOM_SEED, REFERENCE_DATE
from Backend.data_generation.master_generator import generate_master_data
from Backend.data_generation.sales_generator import generate_sales_data
from Backend.forecasting.forecast_engine import (
    FORECAST_COLUMNS,
    FORECAST_METHODS,
    FORECAST_RUN_COLUMNS,
    FORECAST_HORIZON_DAYS,
    FORECAST_ID_PATTERN,
    RUN_ID_PATTERN,
    export_forecast_data,
    generate_forecast_data,
    predict_daily_demand,
)


@pytest.fixture(scope="module")
def generated_forecast_data():
    master_data = generate_master_data("test")
    sales_data = generate_sales_data("test")
    origins = [
        REFERENCE_DATE - timedelta(days=21),
        REFERENCE_DATE - timedelta(days=14),
        REFERENCE_DATE - timedelta(days=7),
        REFERENCE_DATE,
    ]
    forecast_data = generate_forecast_data(
        master_data,
        sales_data["SalesHistory"],
        origins,
    )
    return master_data, sales_data, origins, forecast_data


def test_forecast_generation_is_deterministic(generated_forecast_data):
    master_data, sales_data, origins, first = generated_forecast_data
    second = generate_forecast_data(
        master_data,
        sales_data["SalesHistory"],
        origins,
    )

    for table_name in first:
        pd.testing.assert_frame_equal(first[table_name], second[table_name])


def test_forecast_schema_ids_methods_and_foreign_keys(generated_forecast_data):
    master_data, _, origins, data = generated_forecast_data
    runs = data["ForecastRun"]
    forecasts = data["Forecast"]

    assert list(runs.columns) == FORECAST_RUN_COLUMNS
    assert list(forecasts.columns) == FORECAST_COLUMNS
    assert len(runs) == len(origins) * len(FORECAST_METHODS)
    assert runs["run_id"].astype(str).map(
        lambda value: re.fullmatch(RUN_ID_PATTERN, value) is not None
    ).all()
    assert forecasts["forecast_id"].astype(str).map(
        lambda value: re.fullmatch(FORECAST_ID_PATTERN, value) is not None
    ).all()
    assert set(runs["model_name"]) == set(FORECAST_METHODS)
    assert set(forecasts["forecast_method"]) == set(FORECAST_METHODS)
    assert forecasts["run_id"].isin(runs["run_id"]).all()
    assert forecasts["store_id"].isin(master_data["Store"]["store_id"]).all()
    assert forecasts["sku_id"].isin(master_data["SKU"]["sku_id"]).all()


def test_forecast_quantities_and_seven_day_horizons(generated_forecast_data):
    _, _, _, data = generated_forecast_data
    runs = data["ForecastRun"].set_index("run_id")
    forecasts = data["Forecast"]

    assert (runs["horizon_days"] == FORECAST_HORIZON_DAYS).all()
    assert (runs["feature_cutoff_date"] <= runs["forecast_origin"]).all()
    assert (runs["random_seed"] == RANDOM_SEED).all()
    assert (forecasts["forecast_units"] >= 0).all()
    assert (
        (forecasts["lower_bound"] >= 0)
        & (forecasts["lower_bound"] <= forecasts["forecast_units"])
        & (forecasts["forecast_units"] <= forecasts["upper_bound"])
    ).all()

    joined = forecasts.merge(
        runs.reset_index()[["run_id", "forecast_origin", "horizon_days"]],
        on="run_id",
        validate="many_to_one",
    )
    assert all(
        origin < target <= origin + timedelta(days=int(horizon))
        for origin, target, horizon in zip(
            joined["forecast_origin"],
            joined["target_date"],
            joined["horizon_days"],
        )
    )


def test_horizon_override_extends_only_the_requested_run(generated_forecast_data):
    master_data, sales_data, origins, _ = generated_forecast_data
    extended_horizon = 14
    forecast_data = generate_forecast_data(
        master_data,
        sales_data["SalesHistory"],
        origins,
        {(REFERENCE_DATE, "BASELINE_7D"): extended_horizon},
    )
    runs = forecast_data["ForecastRun"]
    current_runs = runs[runs["forecast_origin"] == REFERENCE_DATE].set_index(
        "model_name"
    )

    assert len(runs) == len(origins) * len(FORECAST_METHODS)
    assert not runs.duplicated(["forecast_origin", "model_name"]).any()
    assert current_runs.loc["BASELINE_7D", "horizon_days"] == extended_horizon
    assert (
        current_runs.loc["WEEKDAY_SEASONAL_28D", "horizon_days"]
        == FORECAST_HORIZON_DAYS
    )
    historical_runs = runs[runs["forecast_origin"] != REFERENCE_DATE]
    assert historical_runs["horizon_days"].eq(FORECAST_HORIZON_DAYS).all()

    extended_run_id = current_runs.loc["BASELINE_7D", "run_id"]
    extended_rows = forecast_data["Forecast"].loc[
        forecast_data["Forecast"]["run_id"] == extended_run_id
    ]
    assert (
        extended_rows["target_date"].map(lambda target: target - REFERENCE_DATE)
        <= timedelta(days=extended_horizon)
    ).all()
    assert (
        extended_rows["target_date"].map(lambda target: target - REFERENCE_DATE)
        > timedelta(days=FORECAST_HORIZON_DAYS)
    ).any()


def test_horizon_override_rejects_unknown_forecast_origin(generated_forecast_data):
    master_data, sales_data, origins, _ = generated_forecast_data

    with pytest.raises(ValueError, match="unknown origin or method"):
        generate_forecast_data(
            master_data,
            sales_data["SalesHistory"],
            origins,
            {(REFERENCE_DATE - timedelta(days=1), "BASELINE_7D"): 14},
        )


def test_forecasts_respect_sku_and_assortment_effective_dates(
    generated_forecast_data,
):
    master_data, _, _, data = generated_forecast_data
    joined = (
        data["Forecast"]
        .merge(
            data["ForecastRun"][["run_id", "forecast_origin"]],
            on="run_id",
            validate="many_to_one",
        )
        .merge(
            master_data["StoreSKU"][
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
            master_data["SKU"][
                ["sku_id", "launch_date", "discontinue_date"]
            ],
            on="sku_id",
            validate="many_to_one",
        )
    )

    assert joined["assortment_status"].isin(["ACTIVE", "DISCONTINUED"]).all()
    assert (joined["active_from"] <= joined["forecast_origin"]).all()
    assert (joined["launch_date"] <= joined["forecast_origin"]).all()
    assert (
        joined["active_to"].isna()
        | (joined["target_date"] < joined["active_to"])
    ).all()
    assert (
        joined["discontinue_date"].isna()
        | (joined["target_date"] < joined["discontinue_date"])
    ).all()
    assert joined["target_date"].gt(joined["forecast_origin"]).all()


def test_baseline_uses_only_previous_seven_sales_and_ignores_future_values():
    origin = REFERENCE_DATE
    dates = [origin - timedelta(days=offset) for offset in range(7, -1, -1)]
    history = pd.DataFrame(
        {
            "sales_date": dates + [origin + timedelta(days=1)],
            "units_sold": list(range(1, 9)) + [10000],
            "stockout_flag": [False] * 9,
            "actual_demand": [50000] * 9,
        }
    )

    prediction = predict_daily_demand(
        history,
        origin,
        origin + timedelta(days=1),
        "BASELINE_7D",
    )

    assert prediction["forecast_units"] == 5.0
    assert prediction["history_count"] == 7


def test_stockout_censoring_prefers_uncensored_history_and_excludes_zero_stockouts():
    origin = REFERENCE_DATE
    dates = [origin - timedelta(days=offset) for offset in range(4, -1, -1)]
    sufficient_history = pd.DataFrame(
        {
            "sales_date": dates,
            "units_sold": [2, 4, 6, 100, 0],
            "stockout_flag": [False, False, False, True, True],
        }
    )
    uncensored_prediction = predict_daily_demand(
        sufficient_history,
        origin,
        origin + timedelta(days=1),
        "BASELINE_7D",
    )
    assert uncensored_prediction["forecast_units"] == 4.0
    assert uncensored_prediction["history_count"] == 3
    assert uncensored_prediction["history_policy"] == "UN_CENSORED"

    sparse_history = sufficient_history.iloc[[0, 1, 3, 4]].copy()
    fallback_prediction = predict_daily_demand(
        sparse_history,
        origin,
        origin + timedelta(days=1),
        "BASELINE_7D",
    )
    assert fallback_prediction["forecast_units"] == pytest.approx(106 / 3, abs=0.01)
    assert fallback_prediction["history_count"] == 3
    assert fallback_prediction["history_policy"] == "CENSORED_POSITIVE_FALLBACK"


def test_cold_start_fallback_is_identified_and_nonnegative():
    empty_history = pd.DataFrame(
        columns=["sales_date", "units_sold", "stockout_flag"]
    )
    prediction = predict_daily_demand(
        empty_history,
        REFERENCE_DATE,
        REFERENCE_DATE + timedelta(days=1),
        "BASELINE_7D",
    )

    assert prediction["forecast_units"] == 0
    assert prediction["history_policy"] == "COLD_START_ZERO"


def test_generated_cold_start_forecasts_are_identified_in_model_name(
    generated_forecast_data,
):
    master_data, sales_data, _, _ = generated_forecast_data
    assortment = master_data["StoreSKU"].loc[
        (master_data["StoreSKU"]["assortment_status"] == "ACTIVE")
        & master_data["StoreSKU"]["active_to"].isna()
    ].iloc[0]
    sales_without_history = sales_data["SalesHistory"].loc[
        ~(
            (sales_data["SalesHistory"]["store_id"] == assortment["store_id"])
            & (sales_data["SalesHistory"]["sku_id"] == assortment["sku_id"])
        )
    ]
    forecasts = generate_forecast_data(
        master_data,
        sales_without_history,
        [REFERENCE_DATE],
    )["Forecast"]
    cold_start_rows = forecasts[
        (forecasts["store_id"] == assortment["store_id"])
        & (forecasts["sku_id"] == assortment["sku_id"])
    ]

    assert len(cold_start_rows) == FORECAST_HORIZON_DAYS * len(FORECAST_METHODS)
    assert cold_start_rows["forecast_units"].eq(0).all()
    assert cold_start_rows["model_name"].str.endswith(
        "_COLD_START_ZERO"
    ).all()
    assert cold_start_rows["forecast_method"].isin(FORECAST_METHODS).all()


def test_weekday_seasonal_forecast_uses_matching_weekday_average():
    origin = REFERENCE_DATE
    dates = list(pd.date_range(end=origin, periods=28).date)
    values = []
    monday_value = 10
    for historical_date in dates:
        if historical_date.weekday() == 0:
            values.append(monday_value)
            monday_value += 4
        else:
            values.append(2)
    history = pd.DataFrame(
        {
            "sales_date": dates,
            "units_sold": values,
            "stockout_flag": [False] * len(dates),
        }
    )
    next_monday = origin + timedelta(days=(7 - origin.weekday()) % 7 or 7)

    prediction = predict_daily_demand(
        history,
        origin,
        next_monday,
        "WEEKDAY_SEASONAL_28D",
    )

    mondays = [
        value
        for historical_date, value in zip(dates, values)
        if historical_date.weekday() == 0
    ]
    assert prediction["forecast_units"] == sum(mondays) / len(mondays)
    assert prediction["history_policy"].endswith("_WEEKDAY")


def test_forecast_csv_export_uses_exact_schema(tmp_path, generated_forecast_data):
    _, _, _, data = generated_forecast_data
    export_forecast_data(data, tmp_path)

    for table_name, expected_columns in (
        ("ForecastRun", FORECAST_RUN_COLUMNS),
        ("Forecast", FORECAST_COLUMNS),
    ):
        exported = pd.read_csv(tmp_path / f"{table_name}.csv")
        assert list(exported.columns) == expected_columns
        assert len(exported) == len(data[table_name])
