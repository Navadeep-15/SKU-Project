from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from Backend.dashboard import data_access
from Backend.services import store_evaluation
from Backend.services.store_evaluation import prepare_store_scope


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_project_data():
    generated = PROJECT_ROOT / "data" / "generated"
    tables = {
        path.stem: pd.read_csv(path)
        for path in generated.glob("*.csv")
    }
    exports = PROJECT_ROOT / "data" / "exports"
    tables["AnomalyFixture"] = pd.read_csv(exports / "anomaly_fixtures.csv")
    tables["ValidationIssue"] = pd.read_csv(
        exports / "anomaly_validation_issues.csv"
    )
    return tables


def _store_tables(tables, store_id):
    assortment = tables["StoreSKU"].loc[
        tables["StoreSKU"]["store_id"].eq(store_id)
    ]
    sku_ids = set(assortment["sku_id"])
    supplier_skus = tables["SupplierSKU"].loc[
        tables["SupplierSKU"]["sku_id"].isin(sku_ids)
    ]
    supplier_ids = set(supplier_skus["supplier_id"])
    return {
        "Store": tables["Store"].loc[
            tables["Store"]["store_id"].eq(store_id)
        ].copy(),
        "StoreSKU": assortment.copy(),
        "SKU": tables["SKU"].loc[
            tables["SKU"]["sku_id"].isin(sku_ids)
        ].copy(),
        "Supplier": tables["Supplier"].loc[
            tables["Supplier"]["supplier_id"].isin(supplier_ids)
        ].copy(),
        "SupplierSKU": supplier_skus.copy(),
        "SalesHistory": tables["SalesHistory"].loc[
            tables["SalesHistory"]["store_id"].eq(store_id)
        ].copy(),
        "InventorySnapshot": tables["InventorySnapshot"].loc[
            tables["InventorySnapshot"]["store_id"].eq(store_id)
        ].copy(),
        "InventoryEvent": tables["InventoryEvent"].loc[
            tables["InventoryEvent"]["store_id"].eq(store_id)
        ].copy(),
        "ReorderPolicy": tables["ReorderPolicy"].loc[
            tables["ReorderPolicy"]["store_id"].eq(store_id)
        ].copy(),
        "GroundTruthDemand": tables["GroundTruthDemand"].loc[
            tables["GroundTruthDemand"]["store_id"].eq(store_id)
        ].copy(),
    }


@pytest.fixture
def dashboard_data(monkeypatch):
    all_tables = _read_project_data()
    dashboard_tables = {
        table_name: all_tables[table_name]
        for table_name in data_access.DASHBOARD_TABLES
    }
    metrics = pd.read_csv(
        PROJECT_ROOT / "data" / "exports" / "forecast_evaluation_metrics.csv"
    )
    monkeypatch.setattr(
        data_access,
        "load_dashboard_tables",
        lambda: dashboard_tables,
    )
    monkeypatch.setattr(data_access, "load_evaluation_metrics", lambda: metrics)
    monkeypatch.setattr(
        data_access,
        "load_store_evaluation_data",
        lambda store_id: _store_tables(all_tables, store_id),
    )
    monkeypatch.setattr(
        data_access,
        "load_inventory_history",
        lambda store_id, sku_id, limit=50: pd.DataFrame(
            columns=[
                "event_date",
                "created_at",
                "event_id",
                "event_type",
                "quantity",
                "resulting_on_hand",
                "reference_id",
            ]
        ),
    )
    selected_method = str(
        metrics.loc[metrics["evaluation_scope"].eq("OVERALL"), "selected_method"]
        .dropna()
        .iloc[0]
    )
    recommendation_rows = all_tables["PurchaseRecommendation"]
    monkeypatch.setattr(
        store_evaluation,
        "evaluate_store",
        lambda source, store_id, sku_ids: {
            "metrics": metrics,
            "selection": {"selected_method": selected_method},
            "replenishment_data": {
                "PurchaseRecommendation": recommendation_rows.loc[
                    recommendation_rows["store_id"].eq(store_id)
                ].copy(),
                "ValidationIssue": pd.DataFrame(),
            },
            "required_horizon": 35,
            "holdout_origins": (),
            "sku_ids": list(sku_ids),
        },
    )

    def load_forecast_series(store_id, sku_id, forecast_origin):
        origin = pd.to_datetime(forecast_origin).date()
        history = all_tables["SalesHistory"].loc[
            all_tables["SalesHistory"]["store_id"].eq(store_id)
            & all_tables["SalesHistory"]["sku_id"].eq(sku_id)
            & (
                pd.to_datetime(all_tables["SalesHistory"]["sales_date"]).dt.date
                <= origin
            )
        ].copy()
        history["target_date"] = pd.to_datetime(history["sales_date"])
        history["units"] = history["units_sold"]
        history["series"] = "Observed sales"
        history["model_name"] = None
        observed = history[
            ["target_date", "units", "series", "model_name", "stockout_flag"]
        ]
        runs = all_tables["ForecastRun"].loc[
            pd.to_datetime(all_tables["ForecastRun"]["forecast_origin"]).dt.date
            .eq(origin),
            ["run_id", "model_name"],
        ]
        forecasts = all_tables["Forecast"].merge(
            runs,
            on="run_id",
            suffixes=("", "_run"),
        )
        forecasts = forecasts.loc[
            forecasts["store_id"].eq(store_id)
            & forecasts["sku_id"].eq(sku_id)
            & pd.to_datetime(forecasts["target_date"]).dt.date.gt(origin)
        ].copy()
        forecasts["target_date"] = pd.to_datetime(forecasts["target_date"])
        forecasts["units"] = forecasts["forecast_units"]
        forecasts["series"] = "Forecast"
        forecasts["model_name"] = forecasts["model_name_run"]
        forecasts["stockout_flag"] = None
        forecast_view = forecasts[
            ["target_date", "units", "series", "model_name", "stockout_flag"]
        ]
        return pd.concat([observed, forecast_view], ignore_index=True)

    def load_recommendations(
        store_id=None,
        capacity_status=None,
        recommendation_status=None,
    ):
        recommendations = all_tables["PurchaseRecommendation"].copy()
        if store_id is not None:
            recommendations = recommendations.loc[
                recommendations["store_id"].eq(store_id)
            ]
        if capacity_status is not None:
            recommendations = recommendations.loc[
                recommendations["capacity_constraint_status"].eq(capacity_status)
            ]
        if recommendation_status is not None:
            recommendations = recommendations.loc[
                recommendations["status"].eq(recommendation_status)
            ]
        return (
            recommendations.merge(
                all_tables["Store"][["store_id", "store_name"]],
                on="store_id",
            )
            .merge(
                all_tables["SKU"][["sku_id", "sku_name"]],
                on="sku_id",
            )
            .merge(
                all_tables["SupplierSKU"][
                    [
                        "supplier_sku_id",
                        "sku_id",
                        "supplier_id",
                        "lead_time_days",
                        "contract_cost",
                    ]
                ],
                on=["supplier_sku_id", "sku_id"],
            )
            .merge(
                all_tables["Supplier"][["supplier_id", "supplier_name"]],
                on="supplier_id",
            )
        )

    monkeypatch.setattr(data_access, "load_forecast_series", load_forecast_series)
    monkeypatch.setattr(data_access, "load_recommendations", load_recommendations)
    return all_tables


def test_all_seven_dashboard_pages_render_without_data_access_writes(
    dashboard_data,
):
    app_test = AppTest.from_file(
        str(PROJECT_ROOT / "Frontend" / "app.py")
    ).run(timeout=10)
    assert not app_test.exception
    pages = list(app_test.sidebar.radio[0].options)
    assert len(pages) == 7
    for page in pages:
        app_test.sidebar.radio[0].set_value(page).run(timeout=10)
        assert not app_test.exception, page

    assert not dashboard_data["GroundTruthDemand"].empty


def test_store_evaluation_displays_reference_and_inventory_dates(dashboard_data):
    store_id = dashboard_data["Store"].iloc[0]["store_id"]
    store_snapshots = dashboard_data["InventorySnapshot"].loc[
        dashboard_data["InventorySnapshot"]["store_id"].eq(store_id)
    ]
    latest_snapshot_date = (
        pd.to_datetime(store_snapshots["snapshot_date"])
        .max()
        .date()
        .isoformat()
    )
    app_test = AppTest.from_file(
        str(PROJECT_ROOT / "Frontend" / "app.py")
    ).run(timeout=10)
    app_test.sidebar.radio[0].set_value("Store Evaluation").run(timeout=10)

    metrics = {metric.label: metric.value for metric in app_test.metric}
    assert metrics["Forecast reference date"] == "2026-10-22"
    assert metrics["Latest inventory snapshot date"] == latest_snapshot_date
    assert any(
        latest_snapshot_date in caption.value
        and "configured forecast baseline (2026-10-22)" in caption.value
        for caption in app_test.caption
    )


def test_forecast_and_store_evaluation_inputs_remain_separated(dashboard_data):
    store_id = dashboard_data["Store"].iloc[0]["store_id"]
    store_data = _store_tables(dashboard_data, store_id)
    master_data, _, sales_history = prepare_store_scope(
        store_data,
        store_id,
    )

    assert "actual_demand" not in sales_history
    assert "GroundTruthDemand" not in master_data


def test_validation_page_can_run_current_store_checks(dashboard_data):
    app_test = AppTest.from_file(
        str(PROJECT_ROOT / "Frontend" / "app.py")
    ).run(timeout=10)
    app_test.sidebar.radio[0].set_value("Validation Scenarios").run(timeout=10)
    app_test.button[0].click().run(timeout=10)

    assert not app_test.exception
    assert len(app_test.dataframe) >= 1


def test_inventory_preview_does_not_call_persistence(dashboard_data, monkeypatch):
    from Backend.services import inventory_simulation
    from Backend.services import inventory_service

    calls = []
    monkeypatch.setattr(
        inventory_service,
        "save_inventory_adjustment",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        inventory_simulation,
        "simulate_inventory_adjustment",
        lambda *args, **kwargs: {
            "status": "SIMULATED",
            "adjustment_units": 1,
            "on_hand_before": 10,
            "on_hand_after": 11,
            "inventory_position_after": 11,
            "projected_store_units": 11,
            "capacity_units": 100,
            "recommendation": None,
        },
    )
    app_test = AppTest.from_file(
        str(PROJECT_ROOT / "Frontend" / "app.py")
    ).run(timeout=10)
    app_test.sidebar.radio[0].set_value("Inventory & Suppliers").run(timeout=10)
    app_test.selectbox[0].set_value(dashboard_data["Store"].iloc[0]["store_id"]).run(
        timeout=10
    )

    assert [button.label for button in app_test.form_submit_button] == [
        "Preview",
        "Save",
    ]
    app_test.form_submit_button[0].click().run(timeout=10)

    assert not app_test.exception
    assert calls == []


def test_inventory_save_uses_persistence_and_shows_commit_notice(
    dashboard_data,
    monkeypatch,
):
    from Backend.dashboard import data_access
    from Backend.services import inventory_service

    calls = []

    def fake_save(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "status": "SAVED",
            "duplicate": False,
            "event_id": "EVT-00099999",
            "event_type": "ADJUSTMENT_IN",
            "quantity": 1,
            "snapshot_date": pd.Timestamp("2026-11-12").date(),
            "on_hand": 11,
            "inventory_position": 11,
        }

    monkeypatch.setattr(
        inventory_service,
        "save_inventory_adjustment",
        fake_save,
    )
    for cached_function in (
        data_access.load_dashboard_tables,
        data_access.load_store_evaluation_data,
        data_access.load_inventory_history,
    ):
        cached_function.clear = lambda: None

    app_test = AppTest.from_file(
        str(PROJECT_ROOT / "Frontend" / "app.py")
    ).run(timeout=10)
    app_test.sidebar.radio[0].set_value("Inventory & Suppliers").run(timeout=10)
    app_test.selectbox[0].set_value(dashboard_data["Store"].iloc[0]["store_id"]).run(
        timeout=10
    )
    app_test.form_submit_button[1].click().run(timeout=10)

    assert not app_test.exception
    assert len(calls) == 1
    assert calls[0][0][2] == "RECEIVE_STOCK"
    assert calls[0][0][3] == 1
    assert any(
        "Inventory adjustment saved and committed." in item.value
        for item in app_test.success
    )
