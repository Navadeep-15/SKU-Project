import argparse
from datetime import date, datetime, timedelta
import math
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    DATASET_VERSION,
    PROFILES,
    RANDOM_SEED,
    REFERENCE_DATE,
)
from Backend.data_generation.master_generator import generate_master_data
from Backend.data_generation.sales_generator import generate_sales_data
from Backend.forecasting.forecast_engine import (
    FORECAST_METHODS,
    FORECAST_COLUMNS,
    FORECAST_RUN_COLUMNS,
    generate_forecast_data,
    export_forecast_data,
)


HOLDOUT_ORIGIN_OFFSETS = (21, 14, 7)
METRIC_COLUMNS = [
    "evaluation_scope",
    "forecast_method",
    "forecast_origin",
    "forecast_count",
    "mae",
    "rmse",
    "wape_percent",
    "bias",
    "selected_method",
    "selection_reason",
]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_EXPORT_DIRECTORY = PROJECT_ROOT / "data" / "exports"
METRICS_FILENAME = "forecast_evaluation_metrics.csv"
TIE_BREAKER = "Lower MAE, then alphabetic method name."
SELECTION_REASON = (
    "Lowest pooled holdout WAPE; ties are broken by lower MAE, "
    "then alphabetic method name."
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


def get_holdout_origins(reference_date=REFERENCE_DATE):
    reference_date = _as_date(reference_date)
    return tuple(
        reference_date - timedelta(days=offset)
        for offset in HOLDOUT_ORIGIN_OFFSETS
    )


def calculate_forecast_metrics(actual_demand, forecast_units):
    actual = np.asarray(actual_demand, dtype=float)
    forecast = np.asarray(forecast_units, dtype=float)
    _require(actual.ndim == 1 and forecast.ndim == 1, "Metrics inputs must be 1D.")
    _require(len(actual) > 0, "At least one holdout forecast is required.")
    _require(len(actual) == len(forecast), "Actual and forecast lengths differ.")
    _require(
        np.isfinite(actual).all() and np.isfinite(forecast).all(),
        "Metrics inputs must be finite.",
    )
    _require((actual >= 0).all(), "Actual demand must be nonnegative.")
    _require((forecast >= 0).all(), "Forecast demand must be nonnegative.")

    errors = forecast - actual
    denominator = float(actual.sum())
    wape_percent = (
        float(np.abs(errors).sum() / denominator * 100)
        if denominator > 0
        else float("nan")
    )
    return {
        "mae": float(np.abs(errors).mean()),
        "rmse": float(np.sqrt(np.square(errors).mean())),
        "wape_percent": wape_percent,
        "bias": float(errors.mean()),
    }


def evaluate_forecasts(forecast_data, ground_truth, holdout_origins):
    _require(
        set(forecast_data) == {"ForecastRun", "Forecast"},
        "Forecast input tables do not match the database schema.",
    )
    _require(
        list(forecast_data["ForecastRun"].columns) == FORECAST_RUN_COLUMNS
        and list(forecast_data["Forecast"].columns) == FORECAST_COLUMNS,
        "Forecast input columns do not match Backend/database/schema.sql.",
    )
    required_truth_columns = {
        "store_id",
        "sku_id",
        "demand_date",
        "actual_demand",
    }
    _require(
        required_truth_columns.issubset(ground_truth.columns),
        "Ground truth input is missing required columns.",
    )

    holdout_origins = tuple(sorted({_as_date(value) for value in holdout_origins}))
    _require(holdout_origins, "At least one holdout origin is required.")
    runs = forecast_data["ForecastRun"].copy()
    runs["_origin"] = runs["forecast_origin"].map(_as_date)
    _require(
        (runs["feature_cutoff_date"] <= runs["forecast_origin"]).all(),
        "ForecastRun feature cutoff cannot exceed forecast origin.",
    )
    selected_runs = runs[runs["_origin"].isin(holdout_origins)]
    _require(not selected_runs.empty, "No forecast runs match the holdout origins.")

    forecasts = forecast_data["Forecast"].merge(
        selected_runs[["run_id", "_origin", "horizon_days"]],
        on="run_id",
        how="inner",
        validate="many_to_one",
    )
    _require(not forecasts.empty, "No forecast rows are available for holdout.")
    forecasts["_target_date"] = forecasts["target_date"].map(_as_date)
    _require(
        all(
            origin < target <= origin + timedelta(days=int(horizon))
            for origin, target, horizon in zip(
                forecasts["_origin"],
                forecasts["_target_date"],
                forecasts["horizon_days"],
            )
        ),
        "Holdout targets must be after their origins and within the horizon.",
    )

    truth = ground_truth[
        ["store_id", "sku_id", "demand_date", "actual_demand"]
    ].copy()
    truth["_target_date"] = truth["demand_date"].map(_as_date)
    _require(
        not truth.duplicated(["store_id", "sku_id", "_target_date"]).any(),
        "Ground truth contains duplicate store/SKU/date keys.",
    )
    holdout = forecasts.merge(
        truth[["store_id", "sku_id", "_target_date", "actual_demand"]],
        on=["store_id", "sku_id", "_target_date"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    _require(
        (holdout["_merge"] == "both").all(),
        "A holdout forecast has no matching GroundTruthDemand record.",
    )
    _require(
        (holdout["actual_demand"] >= 0).all(),
        "Ground-truth actual demand must be nonnegative.",
    )

    per_origin_metrics = []
    for (method, origin), group in holdout.groupby(
        ["forecast_method", "_origin"],
        sort=True,
    ):
        metrics = calculate_forecast_metrics(
            group["actual_demand"],
            group["forecast_units"],
        )
        per_origin_metrics.append(
            {
                "evaluation_scope": "HOLDOUT_ORIGIN",
                "forecast_method": method,
                "forecast_origin": origin,
                "forecast_count": len(group),
                **metrics,
            }
        )

    overall_metrics = []
    for method, group in holdout.groupby("forecast_method", sort=True):
        metrics = calculate_forecast_metrics(
            group["actual_demand"],
            group["forecast_units"],
        )
        overall_metrics.append(
            {
                "evaluation_scope": "OVERALL",
                "forecast_method": method,
                "forecast_origin": None,
                "forecast_count": len(group),
                **metrics,
            }
        )

    _require(
        {row["forecast_method"] for row in overall_metrics}
        == set(FORECAST_METHODS),
        "Holdout evaluation must include both forecast methods.",
    )
    selected = min(
        overall_metrics,
        key=lambda row: (
            row["wape_percent"]
            if math.isfinite(row["wape_percent"])
            else math.inf,
            row["mae"],
            row["forecast_method"],
        ),
    )
    selection = {
        "selected_method": selected["forecast_method"],
        "selection_reason": SELECTION_REASON,
        "tie_breaker": TIE_BREAKER,
        "holdout_origins": holdout_origins,
    }

    metric_rows = per_origin_metrics + overall_metrics
    for row in metric_rows:
        row["selected_method"] = selection["selected_method"]
        row["selection_reason"] = selection["selection_reason"]
    metrics_frame = pd.DataFrame(metric_rows, columns=METRIC_COLUMNS)
    return metrics_frame, selection


def export_evaluation_metrics(
    metrics,
    output_directory=EVALUATION_EXPORT_DIRECTORY,
):
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output_directory / METRICS_FILENAME, index=False)


def run_forecast_evaluation(
    profile_name="test",
    forecast_output_directory=None,
    evaluation_output_directory=EVALUATION_EXPORT_DIRECTORY,
):
    _require(profile_name in PROFILES, f"Unknown profile: {profile_name}")
    master_data = generate_master_data(profile_name)
    generated_sales = generate_sales_data(profile_name)
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

    if forecast_output_directory is None:
        export_forecast_data(forecast_data)
    else:
        export_forecast_data(forecast_data, forecast_output_directory)
    export_evaluation_metrics(metrics, evaluation_output_directory)
    return {
        "forecast_data": forecast_data,
        "metrics": metrics,
        "selection": selection,
        "holdout_origins": holdout_origins,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate and evaluate test-profile SKU-store forecasts."
    )
    args = parser.parse_args(argv)

    result = run_forecast_evaluation()
    forecast_data = result["forecast_data"]
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Random seed: {RANDOM_SEED}")
    print(f"Holdout origins: {', '.join(map(str, result['holdout_origins']))}")
    print(f"ForecastRun: {len(forecast_data['ForecastRun'])} rows")
    print(f"Forecast: {len(forecast_data['Forecast'])} rows")
    print(result["metrics"].to_string(index=False))
    print(f"Selected method: {result['selection']['selected_method']}")
    print(f"Selection reason: {result['selection']['selection_reason']}")


if __name__ == "__main__":
    main()
