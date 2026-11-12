import argparse
from datetime import datetime, time, timezone
from pathlib import Path

import pandas as pd

from config import REFERENCE_DATE
from Backend.data_generation.inventory_generator import generate_inventory_data
from Backend.data_generation.master_generator import generate_master_data
from Backend.data_generation.sales_generator import generate_sales_data
from Backend.forecasting.forecast_engine import (
    generate_forecast_data,
    predict_daily_demand,
)
from Backend.replenishment.replenishment_engine import (
    VALIDATION_ISSUE_COLUMNS,
    calculate_required_forecast_horizon,
    create_recommendations,
    generate_replenishment_data,
)


ANOMALY_FIXTURE_COLUMNS = [
    "anomaly_id",
    "issue_type",
    "scenario",
    "affected_entity",
    "affected_record_key",
    "expected_result",
    "detected_result",
    "test_status",
    "created_at",
]

ANOMALY_TYPES = (
    "STOCKOUT_AS_ZERO_DEMAND",
    "PACK_SIZE_IGNORED",
    "DISCONTINUED_SKU",
    "NEGATIVE_LEAD_TIME",
    "FORECAST_LEAKAGE",
)

ANOMALY_ID_PATTERN = r"ANM-[0-9]{6}"
VALIDATION_ID_PATTERN = r"VAL-[0-9]{6}"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORT_DIRECTORY = PROJECT_ROOT / "data" / "exports"
CREATED_AT = datetime.combine(
    REFERENCE_DATE,
    time.min,
    tzinfo=timezone.utc,
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _build_test_context():
    master_data = generate_master_data("test")
    sales_data = generate_sales_data("test")
    inventory_data = generate_inventory_data("test")
    replenishment_data = generate_replenishment_data("test")
    forecast_data = {
        "ForecastRun": replenishment_data["ForecastRun"],
        "Forecast": replenishment_data["Forecast"],
    }
    return {
        "master_data": master_data,
        "sales_data": sales_data,
        "inventory_data": inventory_data,
        "forecast_data": forecast_data,
        "replenishment_data": replenishment_data,
    }


def _stockout_scenario(context):
    sales = context["sales_data"]["SalesHistory"]
    ground_truth = context["sales_data"]["GroundTruthDemand"]
    zero_stockouts = sales.loc[
        (sales["units_sold"] == 0) & sales["stockout_flag"].astype(bool)
    ]
    _require(not zero_stockouts.empty, "Test profile has no zero-sales stockout.")

    sale = zero_stockouts.iloc[0]
    key = (sale["store_id"], sale["sku_id"])
    history = sales.loc[
        (sales["store_id"] == key[0])
        & (sales["sku_id"] == key[1])
        & (sales["sales_date"] <= sale["sales_date"])
    ].copy()
    history_without_censored_zero = history.loc[
        history["sales_id"] != sale["sales_id"]
    ]
    origin = sale["sales_date"]
    target_date = origin + pd.Timedelta(days=1)
    prediction = predict_daily_demand(
        history,
        origin,
        target_date,
        "BASELINE_7D",
    )
    comparison_prediction = predict_daily_demand(
        history_without_censored_zero,
        origin,
        target_date,
        "BASELINE_7D",
    )
    truth_match = ground_truth.loc[
        (ground_truth["store_id"] == key[0])
        & (ground_truth["sku_id"] == key[1])
        & (ground_truth["demand_date"] == origin),
        "actual_demand",
    ]
    _require(len(truth_match) == 1, "Stockout has no unique ground-truth record.")
    actual_demand = int(
        truth_match.iloc[0]
    )
    passed = (
        bool(sale["stockout_flag"])
        and int(sale["units_sold"]) == 0
        and actual_demand > 0
        and prediction == comparison_prediction
    )
    return {
        "issue_type": "STOCKOUT_AS_ZERO_DEMAND",
        "scenario": (
            "A stockout-censored zero-sales observation is treated as genuine "
            "zero demand."
        ),
        "affected_entity": "SalesHistory",
        "record_key": sale["sales_id"],
        "expected_result": (
            "The zero-sales stockout is excluded from uncensored demand history; "
            "ground truth is used only to confirm that demand was positive."
        ),
        "detected_result": (
            f"stockout_flag={bool(sale['stockout_flag'])}, "
            f"units_sold={int(sale['units_sold'])}, "
            f"evaluation-only actual_demand={actual_demand}; forecast "
            f"{'was unchanged' if prediction == comparison_prediction else 'changed'} "
            "when the censored zero was removed."
        ),
        "passed": passed,
        "rule_name": "STOCKOUT_CENSORED_ZERO",
        "table_name": "SalesHistory",
    }


def _pack_size_scenario(context):
    recommendations = context["replenishment_data"]["PurchaseRecommendation"]
    eligible = recommendations.loc[
        (recommendations["recommended_qty"] > 0)
        & (recommendations["pack_size"] > 1)
    ]
    _require(
        not eligible.empty,
        "Test profile has no positive recommendation with pack_size greater than 1.",
    )
    recommendation = eligible.iloc[0]
    pack_size = int(recommendation["pack_size"])
    invalid_quantity = max(
        int(recommendation["minimum_order_qty"]),
        int(recommendation["recommended_qty"]) + 1,
    )
    while invalid_quantity % pack_size == 0:
        invalid_quantity += 1
    invalid_recommendation = recommendation.copy()
    invalid_recommendation["recommended_qty"] = invalid_quantity

    generated_quantities_are_valid = bool(
        (
            (recommendations["recommended_qty"] == 0)
            | (
                (recommendations["recommended_qty"] >= recommendations["minimum_order_qty"])
                & (recommendations["recommended_qty"] % recommendations["pack_size"] == 0)
            )
        ).all()
    )
    detected = (
        int(invalid_recommendation["recommended_qty"]) % pack_size != 0
    )
    passed = detected and generated_quantities_are_valid
    return {
        "issue_type": "PACK_SIZE_IGNORED",
        "scenario": (
            f"An isolated recommendation quantity of {invalid_quantity} is "
            f"not aligned to pack size {pack_size}."
        ),
        "affected_entity": "PurchaseRecommendation",
        "record_key": recommendation["recommendation_id"],
        "expected_result": (
            "The deliberately invalid quantity is detected, while the normal "
            "engine output remains MOQ- and pack-size-compliant."
        ),
        "detected_result": (
            f"invalid quantity remainder={invalid_quantity % pack_size}; "
            f"generated quantity={int(recommendation['recommended_qty'])}, "
            f"pack_size={pack_size}, MOQ={int(recommendation['minimum_order_qty'])}; "
            f"all generated quantities valid={generated_quantities_are_valid}."
        ),
        "passed": passed,
        "rule_name": "SUPPLIER_PACK_SIZE_MULTIPLE",
        "table_name": "PurchaseRecommendation",
    }


def _discontinued_sku_scenario(context):
    recommendations = context["replenishment_data"]["PurchaseRecommendation"]
    _require(
        not recommendations.empty,
        "Test profile has no recommendation for the discontinued-SKU scenario.",
    )
    recommendation = recommendations.iloc[0]
    changed_master = {
        table_name: frame.copy(deep=True)
        for table_name, frame in context["master_data"].items()
    }
    sku_mask = changed_master["SKU"]["sku_id"] == recommendation["sku_id"]
    sku = changed_master["SKU"].loc[sku_mask].iloc[0]
    _require(
        REFERENCE_DATE > pd.to_datetime(sku["launch_date"]).date(),
        "Cannot discontinue the selected SKU on the reference date.",
    )
    changed_master["SKU"].loc[sku_mask, "lifecycle_state"] = "DISCONTINUED"
    changed_master["SKU"].loc[sku_mask, "discontinue_date"] = REFERENCE_DATE

    changed_recommendations, _ = create_recommendations(
        changed_master,
        context["inventory_data"],
        context["forecast_data"],
        context["replenishment_data"]["selection"]["selected_method"],
    )
    pair_is_absent = not (
        (changed_recommendations["PurchaseRecommendation"]["store_id"]
         == recommendation["store_id"])
        & (changed_recommendations["PurchaseRecommendation"]["sku_id"]
           == recommendation["sku_id"])
    ).any()
    return {
        "issue_type": "DISCONTINUED_SKU",
        "scenario": (
            "A previously eligible SKU is marked discontinued on the "
            "forecast origin date in an isolated master-data copy."
        ),
        "affected_entity": "StoreSKU",
        "record_key": f"{recommendation['store_id']}/{recommendation['sku_id']}",
        "expected_result": (
            "The replenishment engine omits the discontinued SKU-store pair."
        ),
        "detected_result": (
            "The recommendation was prevented."
            if pair_is_absent
            else "A recommendation remained for the discontinued SKU-store pair."
        ),
        "passed": pair_is_absent,
        "rule_name": "SKU_OR_ASSORTMENT_INACTIVE",
        "table_name": "PurchaseRecommendation",
    }


def _negative_lead_time_scenario(context):
    recommendations = context["replenishment_data"]["PurchaseRecommendation"]
    _require(
        not recommendations.empty,
        "Test profile has no recommendation for the negative-lead-time scenario.",
    )
    recommendation = recommendations.iloc[0]
    changed_master = {
        table_name: frame.copy(deep=True)
        for table_name, frame in context["master_data"].items()
    }
    supplier_mask = (
        changed_master["SupplierSKU"]["supplier_sku_id"]
        == recommendation["supplier_sku_id"]
    )
    changed_master["SupplierSKU"].loc[supplier_mask, "lead_time_days"] = -1

    rejection_message = None
    try:
        create_recommendations(
            changed_master,
            context["inventory_data"],
            context["forecast_data"],
            context["replenishment_data"]["selection"]["selected_method"],
        )
    except ValueError as error:
        rejection_message = str(error)

    rejected = (
        rejection_message is not None
        and "lead time must be nonnegative" in rejection_message
    )
    return {
        "issue_type": "NEGATIVE_LEAD_TIME",
        "scenario": (
            "The selected SupplierSKU has lead_time_days=-1 in an isolated "
            "master-data copy."
        ),
        "affected_entity": "SupplierSKU",
        "record_key": recommendation["supplier_sku_id"],
        "expected_result": (
            "The invalid supplier configuration is rejected before it can "
            "produce a replenishment recommendation."
        ),
        "detected_result": (
            f"rejected: {rejection_message}"
            if rejection_message
            else "The replenishment engine accepted the invalid supplier lead time."
        ),
        "passed": rejected,
        "rule_name": "SUPPLIER_LEAD_TIME_NONNEGATIVE",
        "table_name": "SupplierSKU",
    }


def _forecast_leakage_scenario(context):
    master_data = context["master_data"]
    sales = context["sales_data"]["SalesHistory"]
    ground_truth = context["sales_data"]["GroundTruthDemand"]
    recommendation = context["replenishment_data"][
        "PurchaseRecommendation"
    ].iloc[0]
    store_id = recommendation["store_id"]
    sku_id = recommendation["sku_id"]
    origin = REFERENCE_DATE - pd.Timedelta(days=14)
    relationship_sales = sales.loc[
        (sales["store_id"] == store_id) & (sales["sku_id"] == sku_id)
    ].copy()
    future_rows = relationship_sales.loc[
        pd.to_datetime(relationship_sales["sales_date"]).dt.date > origin
    ]
    past_rows = relationship_sales.loc[
        pd.to_datetime(relationship_sales["sales_date"]).dt.date <= origin
    ]
    _require(
        not future_rows.empty and not past_rows.empty,
        "Test profile lacks history on both sides of the leakage origin.",
    )

    full_history_prediction = predict_daily_demand(
        relationship_sales,
        origin,
        origin + pd.Timedelta(days=1),
        "BASELINE_7D",
    )
    cutoff_prediction = predict_daily_demand(
        past_rows,
        origin,
        origin + pd.Timedelta(days=1),
        "BASELINE_7D",
    )

    contaminated_sales = sales.merge(
        ground_truth[
            ["store_id", "sku_id", "demand_date", "actual_demand"]
        ],
        left_on=["store_id", "sku_id", "sales_date"],
        right_on=["store_id", "sku_id", "demand_date"],
        how="left",
        validate="one_to_one",
    )
    truth_input_rejected = False
    try:
        generate_forecast_data(
            master_data,
            contaminated_sales,
            [origin],
        )
    except ValueError as error:
        truth_input_rejected = "observed SalesHistory only" in str(error)

    cutoff_respected = full_history_prediction == cutoff_prediction
    passed = (
        not future_rows.empty
        and cutoff_respected
        and truth_input_rejected
    )
    return {
        "issue_type": "FORECAST_LEAKAGE",
        "scenario": (
            "An isolated forecasting input contains future-dated SalesHistory "
            "rows and a GroundTruthDemand-only actual_demand field."
        ),
        "affected_entity": "Forecast",
        "record_key": f"{store_id}/{sku_id}/{origin.isoformat()}",
        "expected_result": (
            "The predictor uses only observations on or before its origin, and "
            "the forecast generator rejects GroundTruthDemand fields."
        ),
        "detected_result": (
            f"{len(future_rows)} future observations were present; forecast "
            f"unchanged after origin cutoff={cutoff_respected}; "
            f"GroundTruthDemand input rejected={truth_input_rejected}."
        ),
        "passed": passed,
        "rule_name": "FORECAST_ORIGIN_AND_SOURCE_PROVENANCE",
        "table_name": "Forecast",
    }


def _build_output_frames(scenario_results):
    fixtures = []
    issues = []
    for index, result in enumerate(scenario_results, start=1):
        test_status = "PASS" if result["passed"] else "FAIL"
        fixtures.append(
            (
                f"ANM-{index:06d}",
                result["issue_type"],
                result["scenario"],
                result["affected_entity"],
                result["record_key"],
                result["expected_result"],
                result["detected_result"],
                test_status,
                CREATED_AT,
            )
        )
        issues.append(
            (
                f"VAL-{index:06d}",
                result["table_name"],
                result["rule_name"],
                "HIGH",
                result["record_key"],
                result["detected_result"],
                bool(result["passed"]),
                CREATED_AT,
            )
        )

    return {
        "AnomalyFixture": pd.DataFrame(
            fixtures,
            columns=ANOMALY_FIXTURE_COLUMNS,
        ),
        "ValidationIssue": pd.DataFrame(
            issues,
            columns=VALIDATION_ISSUE_COLUMNS,
        ),
    }


def validate_anomaly_outputs(data):
    _require(
        set(data) == {"AnomalyFixture", "ValidationIssue"},
        "Anomaly output tables do not match the frozen schema.",
    )
    fixtures = data["AnomalyFixture"]
    issues = data["ValidationIssue"]
    _require(
        list(fixtures.columns) == ANOMALY_FIXTURE_COLUMNS,
        "AnomalyFixture columns do not match Backend/database/schema.sql.",
    )
    _require(
        list(issues.columns) == VALIDATION_ISSUE_COLUMNS,
        "ValidationIssue columns do not match Backend/database/schema.sql.",
    )
    _require(
        len(fixtures) == len(ANOMALY_TYPES)
        and set(fixtures["issue_type"]) == set(ANOMALY_TYPES)
        and not fixtures["issue_type"].duplicated().any(),
        "AnomalyFixture must contain exactly one row per required anomaly type.",
    )
    _require(
        fixtures["anomaly_id"].astype(str).str.fullmatch(ANOMALY_ID_PATTERN).all()
        and not fixtures["anomaly_id"].duplicated().any(),
        "AnomalyFixture IDs are invalid or duplicated.",
    )
    _require(
        fixtures["test_status"].isin({"PASS", "FAIL", "PENDING"}).all(),
        "AnomalyFixture contains an invalid test_status.",
    )
    _require(
        fixtures["affected_record_key"].notna().all()
        and fixtures["affected_record_key"].astype(str).str.len().le(100).all(),
        "AnomalyFixture has an invalid affected record key.",
    )
    _require(
        len(issues) == len(fixtures)
        and issues["validation_id"].astype(str).str.fullmatch(
            VALIDATION_ID_PATTERN
        ).all()
        and not issues["validation_id"].duplicated().any(),
        "ValidationIssue IDs or row count are invalid.",
    )
    _require(
        issues["severity"].isin({"LOW", "MEDIUM", "HIGH", "CRITICAL"}).all(),
        "ValidationIssue contains an invalid severity.",
    )
    _require(
        issues["resolved_flag"].isin({True, False}).all(),
        "ValidationIssue contains an invalid resolved_flag.",
    )


def run_anomaly_validation(profile_name="test"):
    _require(
        profile_name == "test",
        "Phase 8A anomaly scenarios are restricted to the test profile.",
    )
    context = _build_test_context()
    scenario_results = [
        _stockout_scenario(context),
        _pack_size_scenario(context),
        _discontinued_sku_scenario(context),
        _negative_lead_time_scenario(context),
        _forecast_leakage_scenario(context),
    ]
    data = _build_output_frames(scenario_results)
    validate_anomaly_outputs(data)
    return data


def export_anomaly_results(data, output_directory=DEFAULT_EXPORT_DIRECTORY):
    validate_anomaly_outputs(data)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "AnomalyFixture": output_directory / "anomaly_fixtures.csv",
        "ValidationIssue": output_directory / "anomaly_validation_issues.csv",
    }
    for table_name, path in paths.items():
        data[table_name].to_csv(path, index=False)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run isolated test-profile anomaly and validation scenarios."
    )
    parser.add_argument("--profile", choices=["test"], default="test")
    parser.add_argument(
        "--output-directory",
        default=str(DEFAULT_EXPORT_DIRECTORY),
    )
    args = parser.parse_args(argv)

    data = run_anomaly_validation(args.profile)
    paths = export_anomaly_results(data, args.output_directory)
    print(f"Profile: {args.profile}")
    print(f"AnomalyFixture: {len(data['AnomalyFixture'])} rows")
    print(f"ValidationIssue: {len(data['ValidationIssue'])} rows")
    print(data["AnomalyFixture"][["issue_type", "test_status"]].to_string(index=False))
    for table_name, path in paths.items():
        print(f"{table_name} export: {path}")


if __name__ == "__main__":
    main()
