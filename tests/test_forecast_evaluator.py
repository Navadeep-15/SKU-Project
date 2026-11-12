from datetime import datetime, time, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from config import DATASET_VERSION, RANDOM_SEED, REFERENCE_DATE
from Backend.data_generation.master_generator import generate_master_data
from Backend.data_generation.sales_generator import generate_sales_data
from Backend.evaluation.forecast_evaluator import (
    METRIC_COLUMNS,
    METRICS_FILENAME,
    calculate_forecast_metrics,
    evaluate_forecasts,
    export_evaluation_metrics,
    get_holdout_origins,
    run_forecast_evaluation,
)
from Backend.forecasting.forecast_engine import (
    FORECAST_COLUMNS,
    FORECAST_METHODS,
    FORECAST_RUN_COLUMNS,
    generate_forecast_data,
)


@pytest.fixture(scope="module")
def evaluated_test_forecasts():
    master_data = generate_master_data("test")
    generated_sales = generate_sales_data("test")
    holdout_origins = get_holdout_origins()
    forecast_origins = (*holdout_origins, REFERENCE_DATE)
    forecast_data = generate_forecast_data(
        master_data,
        generated_sales["SalesHistory"],
        forecast_origins,
    )
    metrics, selection = evaluate_forecasts(
        forecast_data,
        generated_sales["GroundTruthDemand"],
        holdout_origins,
    )
    return forecast_data, generated_sales, holdout_origins, metrics, selection


def test_mae_rmse_wape_and_bias_calculations():
    metrics = calculate_forecast_metrics([2, 0, 4], [3, 0, 2])

    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(np.sqrt(5 / 3))
    assert metrics["wape_percent"] == pytest.approx(50.0)
    assert metrics["bias"] == pytest.approx(-1 / 3)


def test_holdout_origins_are_seven_days_apart_and_end_at_reference():
    origins = get_holdout_origins()

    assert origins == (
        REFERENCE_DATE - timedelta(days=21),
        REFERENCE_DATE - timedelta(days=14),
        REFERENCE_DATE - timedelta(days=7),
    )
    assert all(
        right - left == timedelta(days=7)
        for left, right in zip(origins, origins[1:])
    )
    assert origins[-1] + timedelta(days=7) == REFERENCE_DATE


def test_evaluation_uses_only_future_holdout_dates(evaluated_test_forecasts):
    forecast_data, _, holdout_origins, metrics, _ = evaluated_test_forecasts
    origin_rows = metrics[metrics["evaluation_scope"] == "HOLDOUT_ORIGIN"]
    run_origins = forecast_data["ForecastRun"].set_index("run_id")[
        "forecast_origin"
    ]

    assert set(origin_rows["forecast_origin"]) == set(holdout_origins)
    assert set(origin_rows["forecast_method"]) == set(FORECAST_METHODS)
    for forecast in forecast_data["Forecast"].itertuples(index=False):
        origin = run_origins.loc[forecast.run_id]
        if origin in holdout_origins:
            assert forecast.target_date > origin
            assert forecast.target_date <= origin + timedelta(days=7)


def test_evaluation_produces_metrics_for_both_methods(evaluated_test_forecasts):
    _, _, holdout_origins, metrics, selection = evaluated_test_forecasts
    overall = metrics[metrics["evaluation_scope"] == "OVERALL"]

    assert list(metrics.columns) == METRIC_COLUMNS
    assert set(overall["forecast_method"]) == set(FORECAST_METHODS)
    assert (overall["forecast_count"] > 0).all()
    assert selection["selected_method"] in FORECAST_METHODS
    assert selection["holdout_origins"] == holdout_origins
    assert "pooled holdout WAPE" in selection["selection_reason"]


def test_wape_tie_uses_lower_mae_then_method_name():
    origin = REFERENCE_DATE - timedelta(days=7)
    created_at = datetime.combine(
        REFERENCE_DATE,
        time.min,
        tzinfo=timezone.utc,
    )
    run_rows = []
    forecast_rows = []
    for index, method in enumerate(FORECAST_METHODS, start=1):
        run_id = f"RUN-{index:06d}"
        run_rows.append(
            (
                run_id,
                method,
                "test-v1",
                origin,
                7,
                RANDOM_SEED,
                DATASET_VERSION,
                origin,
                created_at,
            )
        )
        target_date = origin + timedelta(days=1)
        forecast_rows.append(
            (
                (
                    f"FC-{run_id}-STORE-000001-SKU-000001-"
                    f"{target_date.isoformat()}"
                ),
                run_id,
                "STORE-000001",
                "SKU-000001",
                target_date,
                3.0,
                0.0,
                5.0,
                method,
                method,
                created_at,
            )
        )

    forecast_data = {
        "ForecastRun": pd.DataFrame(run_rows, columns=FORECAST_RUN_COLUMNS),
        "Forecast": pd.DataFrame(forecast_rows, columns=FORECAST_COLUMNS),
    }
    ground_truth = pd.DataFrame(
        {
            "store_id": ["STORE-000001"],
            "sku_id": ["SKU-000001"],
            "demand_date": [origin + timedelta(days=1)],
            "actual_demand": [3],
        }
    )
    _, selection = evaluate_forecasts(
        forecast_data,
        ground_truth,
        [origin],
    )

    assert selection["selected_method"] == "BASELINE_7D"
    assert "alphabetic method name" in selection["selection_reason"]


def test_evaluation_metrics_csv_export(tmp_path, evaluated_test_forecasts):
    _, _, _, metrics, _ = evaluated_test_forecasts
    export_evaluation_metrics(metrics, tmp_path)

    exported = pd.read_csv(tmp_path / METRICS_FILENAME)
    assert list(exported.columns) == METRIC_COLUMNS
    assert len(exported) == len(metrics)


def test_pipeline_exports_test_profile_forecasts_and_evaluation(tmp_path):
    forecast_directory = tmp_path / "generated"
    metrics_directory = tmp_path / "exports"
    result = run_forecast_evaluation(
        "test",
        forecast_directory,
        metrics_directory,
    )

    assert (forecast_directory / "ForecastRun.csv").exists()
    assert (forecast_directory / "Forecast.csv").exists()
    assert (metrics_directory / METRICS_FILENAME).exists()
    assert len(pd.read_csv(forecast_directory / "ForecastRun.csv")) == len(
        result["forecast_data"]["ForecastRun"]
    )
    assert len(pd.read_csv(forecast_directory / "Forecast.csv")) == len(
        result["forecast_data"]["Forecast"]
    )
