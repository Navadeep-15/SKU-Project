from types import SimpleNamespace

import pandas as pd

from Backend.dashboard import data_access


class FakeCursor:
    description = [SimpleNamespace(name="recommendation_id")]

    def fetchall(self):
        return [("PO-0001-000001",)]

    def fetchone(self):
        return ("public",)


class FakeConnection:
    def __init__(self):
        self.executions = []
        self.rollback_count = 0
        self.closed = False

    def execute(self, query, parameters=None):
        query_text = (
            query.as_string(None)
            if hasattr(query, "as_string")
            else query
        )
        self.executions.append((query_text, parameters))
        return FakeCursor()

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True


def _mock_connection(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(
        data_access, "_deployment_database_url", lambda: "configured-url"
    )
    monkeypatch.setattr(
        data_access, "get_connection", lambda database_url: connection
    )
    return connection


def test_dashboard_connection_uses_read_only_transaction_and_closes(monkeypatch):
    connection = _mock_connection(monkeypatch)

    with data_access._read_only_connection():
        pass

    assert connection.executions[0][0] == "SET TRANSACTION READ ONLY"
    assert connection.rollback_count == 1
    assert connection.closed


def test_recommendation_filters_are_parameterized(monkeypatch):
    connection = _mock_connection(monkeypatch)
    data_access.load_recommendations.clear()

    result = data_access.load_recommendations(
        store_id="STORE-000001' OR TRUE --",
        capacity_status="BLOCKED",
        recommendation_status=None,
    )

    query, parameters = connection.executions[-1]
    assert "recommendation.store_id = %s" in query
    assert "recommendation.capacity_constraint_status = %s" in query
    assert "STORE-000001' OR TRUE --" not in query
    assert parameters == ("STORE-000001' OR TRUE --", "BLOCKED")
    assert result.iloc[0]["recommendation_id"] == "PO-0001-000001"


def test_forecast_series_reads_observed_sales_and_forecasts_only(monkeypatch):
    connection = _mock_connection(monkeypatch)
    data_access.load_forecast_series.clear()

    data_access.load_forecast_series("STORE-000001", "SKU-000001", "2026-10-22")

    query, parameters = connection.executions[-1]
    assert '"SalesHistory"' in query
    assert '"Forecast"' in query
    assert '"ForecastRun"' in query
    assert "GroundTruthDemand" not in query
    assert query.count("%s") == len(parameters) == 8
    assert parameters[0:2] == ("STORE-000001", "SKU-000001")


def test_inventory_history_is_parameterized_and_read_only(monkeypatch):
    connection = _mock_connection(monkeypatch)
    data_access.load_inventory_history.clear()

    data_access.load_inventory_history(
        "STORE-000001' OR TRUE --",
        "SKU-000001",
        25,
    )

    query, parameters = connection.executions[-1]
    assert connection.executions[0][0] == "SET TRANSACTION READ ONLY"
    assert '"InventoryEvent"' in query
    assert "STORE-000001' OR TRUE --" not in query
    assert parameters == ("STORE-000001' OR TRUE --", "SKU-000001", 25)
    assert connection.rollback_count == 1
    assert connection.closed


def test_evaluation_metrics_load_from_existing_export():
    metrics = data_access.load_evaluation_metrics()

    assert not metrics.empty
    assert {"mae", "rmse", "wape_percent", "bias", "selected_method"} <= set(
        metrics.columns
    )
    assert isinstance(metrics, pd.DataFrame)


def test_store_evaluation_queries_are_parameterized_and_read_only(monkeypatch):
    connection = _mock_connection(monkeypatch)
    store_id = "STORE-000001"
    sku_id = "SKU-000001"
    supplier_id = "SUP-000001"
    frames = iter(
        [
            pd.DataFrame({"store_id": [store_id]}),
            pd.DataFrame({"sku_id": [sku_id]}),
            pd.DataFrame({"sku_id": [sku_id]}),
            pd.DataFrame({"supplier_id": [supplier_id], "sku_id": [sku_id]}),
            pd.DataFrame({"supplier_id": [supplier_id]}),
            pd.DataFrame({"store_id": [store_id]}),
            pd.DataFrame({"store_id": [store_id]}),
            pd.DataFrame({"store_id": [store_id]}),
            pd.DataFrame({"store_id": [store_id]}),
            pd.DataFrame({"store_id": [store_id]}),
        ]
    )
    monkeypatch.setattr(
        data_access,
        "_frame_from_cursor",
        lambda cursor: next(frames),
    )
    data_access.load_store_evaluation_data.clear()

    tables = data_access.load_store_evaluation_data(store_id)

    assert set(tables) == set(data_access.STORE_EVALUATION_TABLES)
    queries = connection.executions
    assert queries[0][0] == "SET TRANSACTION READ ONLY"
    select_queries = [
        (query, parameters)
        for query, parameters in queries[1:]
        if query.startswith("SELECT")
    ]
    assert len(select_queries) == 11
    assert all("%s" in query for query, _ in select_queries[1:])
    assert any("GroundTruthDemand" in query for query, _ in select_queries)
    sales_query = next(
        query
        for query, _ in select_queries
        if '"SalesHistory"' in query
    )
    assert "GroundTruthDemand" not in sales_query
    assert not any(
        query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for query, _ in queries
    )
    assert connection.rollback_count == 1
    assert connection.closed
