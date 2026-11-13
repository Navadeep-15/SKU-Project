import re
from pathlib import Path

import pandas as pd
import pytest

from Backend.replenishment.replenishment_engine import VALIDATION_ISSUE_COLUMNS
from Backend.validation.anomaly_detector import (
    ANOMALY_FIXTURE_COLUMNS,
    ANOMALY_ID_PATTERN,
    ANOMALY_TYPES,
    VALIDATION_ID_PATTERN,
    export_anomaly_results,
    run_anomaly_validation,
    validate_anomaly_outputs,
)


@pytest.fixture(scope="module")
def anomaly_data():
    return run_anomaly_validation("test")


def test_all_required_anomalies_are_detected(anomaly_data):
    fixtures = anomaly_data["AnomalyFixture"].set_index("issue_type")
    issues = anomaly_data["ValidationIssue"]

    assert set(fixtures.index) == set(ANOMALY_TYPES)
    assert fixtures["test_status"].eq("PASS").all()
    assert len(issues) == 5
    assert issues["resolved_flag"].all()


@pytest.mark.parametrize(
    ("issue_type", "result_text"),
    [
        ("STOCKOUT_AS_ZERO_DEMAND", "actual_demand="),
        ("PACK_SIZE_IGNORED", "all generated quantities valid=True"),
        ("DISCONTINUED_SKU", "recommendation was prevented"),
        ("NEGATIVE_LEAD_TIME", "lead time must be nonnegative"),
        ("FORECAST_LEAKAGE", "GroundTruthDemand input rejected=True"),
    ],
)
def test_each_anomaly_records_the_detected_result(
    anomaly_data,
    issue_type,
    result_text,
):
    row = anomaly_data["AnomalyFixture"].loc[
        anomaly_data["AnomalyFixture"]["issue_type"] == issue_type
    ].iloc[0]

    assert row["test_status"] == "PASS"
    assert result_text in row["detected_result"]


def test_anomaly_outputs_match_frozen_schema_and_id_formats(anomaly_data):
    fixtures = anomaly_data["AnomalyFixture"]
    issues = anomaly_data["ValidationIssue"]

    assert list(fixtures.columns) == ANOMALY_FIXTURE_COLUMNS
    assert list(issues.columns) == VALIDATION_ISSUE_COLUMNS
    assert fixtures["anomaly_id"].map(
        lambda value: re.fullmatch(ANOMALY_ID_PATTERN, value) is not None
    ).all()
    assert issues["validation_id"].map(
        lambda value: re.fullmatch(VALIDATION_ID_PATTERN, value) is not None
    ).all()
    assert set(fixtures["test_status"]) == {"PASS"}
    assert set(issues["severity"]) == {"HIGH"}
    validate_anomaly_outputs(anomaly_data)


def test_repeated_runs_are_deterministic_and_do_not_change_clean_csvs(
    anomaly_data,
):
    generated_directory = Path(__file__).resolve().parents[1] / "data" / "generated"
    before = {
        path.name: path.read_bytes()
        for path in generated_directory.glob("*.csv")
    }

    repeated = run_anomaly_validation("test")

    after = {
        path.name: path.read_bytes()
        for path in generated_directory.glob("*.csv")
    }
    assert before == after
    for table_name in anomaly_data:
        pd.testing.assert_frame_equal(
            anomaly_data[table_name],
            repeated[table_name],
        )


def test_dedicated_csv_exports_are_schema_aligned(tmp_path, anomaly_data):
    paths = export_anomaly_results(anomaly_data, tmp_path)

    assert set(paths) == {"AnomalyFixture", "ValidationIssue"}
    assert list(pd.read_csv(paths["AnomalyFixture"]).columns) == (
        ANOMALY_FIXTURE_COLUMNS
    )
    assert list(pd.read_csv(paths["ValidationIssue"]).columns) == (
        VALIDATION_ISSUE_COLUMNS
    )
    assert len(pd.read_csv(paths["AnomalyFixture"])) == 5
    assert len(pd.read_csv(paths["ValidationIssue"])) == 5


def test_unknown_dataset_configuration_is_rejected():
    with pytest.raises(ValueError):
        run_anomaly_validation("unknown")
