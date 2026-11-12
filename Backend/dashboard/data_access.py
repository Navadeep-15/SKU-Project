import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st
from psycopg import sql
from streamlit.errors import StreamlitSecretNotFoundError

from Backend.database.connection import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_METRICS_FILE = (
    PROJECT_ROOT / "data" / "exports" / "forecast_evaluation_metrics.csv"
)

DASHBOARD_TABLES = (
    "SKU",
    "Store",
    "Supplier",
    "StoreSKU",
    "SupplierSKU",
    "SalesHistory",
    "InventorySnapshot",
    "LeadTimeObservation",
    "ReorderPolicy",
    "ForecastRun",
    "Forecast",
    "PurchaseRecommendation",
    "AnomalyFixture",
    "ValidationIssue",
)

STORE_EVALUATION_TABLES = (
    "Store",
    "StoreSKU",
    "SKU",
    "Supplier",
    "SupplierSKU",
    "SalesHistory",
    "InventorySnapshot",
    "InventoryEvent",
    "ReorderPolicy",
    "GroundTruthDemand",
)


def _deployment_database_url():
    if os.getenv("DATABASE_URL"):
        return None
    try:
        database_url = st.secrets.get("DATABASE_URL")
    except StreamlitSecretNotFoundError:
        database_url = None
    if not database_url:
        raise ValueError(
            "Configure DATABASE_URL in the local environment/.env or Streamlit secrets."
        )
    return str(database_url)


@contextmanager
def _read_only_connection():
    connection = get_connection(_deployment_database_url())
    try:
        connection.execute("SET TRANSACTION READ ONLY")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _frame_from_cursor(cursor):
    columns = [column.name for column in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def _select_by_value(connection, schema_name, table_name, column_name, value):
    query = sql.SQL("SELECT * FROM {} WHERE {} = %s").format(
        sql.Identifier(schema_name, table_name),
        sql.Identifier(column_name),
    )
    return _frame_from_cursor(connection.execute(query, (value,)))


def _select_by_values(connection, schema_name, table_name, column_name, values):
    query = sql.SQL("SELECT * FROM {} WHERE {} = ANY(%s)").format(
        sql.Identifier(schema_name, table_name),
        sql.Identifier(column_name),
    )
    return _frame_from_cursor(connection.execute(query, (values,)))


@st.cache_data(ttl=60, show_spinner=False)
def load_dashboard_tables():
    tables = {}
    with _read_only_connection() as connection:
        schema_name = connection.execute(
            "SELECT current_schema()"
        ).fetchone()[0]
        for table_name in DASHBOARD_TABLES:
            query = sql.SQL("SELECT * FROM {}").format(
                sql.Identifier(schema_name, table_name)
            )
            tables[table_name] = _frame_from_cursor(
                connection.execute(query)
            )
    return tables


@st.cache_data(ttl=60, show_spinner=False)
def load_store_evaluation_data(store_id):
    with _read_only_connection() as connection:
        schema_name = connection.execute(
            "SELECT current_schema()"
        ).fetchone()[0]

        store = _select_by_value(
            connection,
            schema_name,
            "Store",
            "store_id",
            store_id,
        )
        assortment = _select_by_value(
            connection,
            schema_name,
            "StoreSKU",
            "store_id",
            store_id,
        )
        sku_ids = sorted(assortment["sku_id"].dropna().unique().tolist())
        skus = _select_by_values(
            connection,
            schema_name,
            "SKU",
            "sku_id",
            sku_ids,
        )
        supplier_skus = _select_by_values(
            connection,
            schema_name,
            "SupplierSKU",
            "sku_id",
            sku_ids,
        )
        supplier_ids = sorted(
            supplier_skus["supplier_id"].dropna().unique().tolist()
        )

        return {
            "Store": store,
            "StoreSKU": assortment,
            "SKU": skus,
            "Supplier": _select_by_values(
                connection,
                schema_name,
                "Supplier",
                "supplier_id",
                supplier_ids,
            ),
            "SupplierSKU": supplier_skus,
            "SalesHistory": _select_by_value(
                connection,
                schema_name,
                "SalesHistory",
                "store_id",
                store_id,
            ),
            "InventorySnapshot": _select_by_value(
                connection,
                schema_name,
                "InventorySnapshot",
                "store_id",
                store_id,
            ),
            "InventoryEvent": _select_by_value(
                connection,
                schema_name,
                "InventoryEvent",
                "store_id",
                store_id,
            ),
            "ReorderPolicy": _select_by_value(
                connection,
                schema_name,
                "ReorderPolicy",
                "store_id",
                store_id,
            ),
            "GroundTruthDemand": _select_by_value(
                connection,
                schema_name,
                "GroundTruthDemand",
                "store_id",
                store_id,
            ),
        }


@st.cache_data(ttl=60, show_spinner=False)
def load_inventory_history(store_id, sku_id, limit=50):
    query = """
        WITH inventory_history AS (
            SELECT event_date,
                   created_at,
                   event_id,
                   event_type,
                   quantity,
                   reference_id,
                   SUM(quantity) OVER (
                       ORDER BY event_date, created_at, event_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS resulting_on_hand
            FROM "InventoryEvent"
            WHERE store_id = %s AND sku_id = %s
        )
        SELECT event_date,
               created_at,
               event_id,
               event_type,
               quantity,
               resulting_on_hand,
               reference_id
        FROM inventory_history
        ORDER BY event_date DESC, created_at DESC, event_id DESC
        LIMIT %s
    """
    with _read_only_connection() as connection:
        return _frame_from_cursor(
            connection.execute(query, (store_id, sku_id, limit))
        )


@st.cache_data(ttl=60, show_spinner=False)
def load_forecast_series(store_id, sku_id, forecast_origin):
    start_date = pd.Timestamp(forecast_origin).date() - pd.Timedelta(days=89)
    query = """
        SELECT sales_date AS target_date,
               units_sold::numeric AS units,
               'Observed sales'::text AS series,
               NULL::text AS model_name,
               stockout_flag
        FROM "SalesHistory"
        WHERE store_id = %s
          AND sku_id = %s
          AND sales_date BETWEEN %s AND %s
        UNION ALL
        SELECT forecast.target_date,
               forecast.forecast_units AS units,
               'Forecast'::text AS series,
               forecast_run.model_name::text AS model_name,
               NULL::boolean AS stockout_flag
        FROM "Forecast" AS forecast
        JOIN "ForecastRun" AS forecast_run
          ON forecast_run.run_id = forecast.run_id
        WHERE forecast.store_id = %s
          AND forecast.sku_id = %s
          AND forecast_run.forecast_origin = %s
          AND forecast.target_date > %s
        ORDER BY target_date, series, model_name
    """
    parameters = (
        store_id,
        sku_id,
        start_date,
        forecast_origin,
        store_id,
        sku_id,
        forecast_origin,
        forecast_origin,
    )
    with _read_only_connection() as connection:
        return _frame_from_cursor(connection.execute(query, parameters))


@st.cache_data(ttl=60, show_spinner=False)
def load_recommendations(
    store_id=None,
    capacity_status=None,
    recommendation_status=None,
):
    conditions = []
    parameters = []
    for column, value in (
        ("recommendation.store_id", store_id),
        ("recommendation.capacity_constraint_status", capacity_status),
        ("recommendation.status", recommendation_status),
    ):
        if value is not None:
            conditions.append(f"{column} = %s")
            parameters.append(value)
    where_clause = (
        "WHERE " + " AND ".join(conditions)
        if conditions
        else ""
    )
    query = f"""
        SELECT recommendation.*,
               store.store_name,
               sku.sku_name,
               supplier.supplier_name,
               supplier_sku.lead_time_days,
               supplier_sku.contract_cost
        FROM "PurchaseRecommendation" AS recommendation
        JOIN "Store" AS store
          ON store.store_id = recommendation.store_id
        JOIN "SKU" AS sku
          ON sku.sku_id = recommendation.sku_id
        JOIN "SupplierSKU" AS supplier_sku
          ON supplier_sku.supplier_sku_id = recommendation.supplier_sku_id
         AND supplier_sku.sku_id = recommendation.sku_id
        JOIN "Supplier" AS supplier
          ON supplier.supplier_id = supplier_sku.supplier_id
        {where_clause}
        ORDER BY recommendation.store_id, recommendation.sku_id
    """
    with _read_only_connection() as connection:
        return _frame_from_cursor(connection.execute(query, tuple(parameters)))


@st.cache_data(ttl=300, show_spinner=False)
def load_evaluation_metrics():
    if not EVALUATION_METRICS_FILE.is_file():
        return pd.DataFrame()
    return pd.read_csv(EVALUATION_METRICS_FILE)
