"""StockLens Streamlit dashboard."""
import html
from datetime import date
from pathlib import Path
import sys
import uuid

import pandas as pd
import plotly.graph_objects as go
import psycopg
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import REFERENCE_DATE
from Backend.dashboard.data_access import (
    _deployment_database_url,
    load_dashboard_tables,
    load_evaluation_metrics,
    load_forecast_series,
    load_inventory_history,
    load_recommendations,
    load_store_evaluation_data,
)
from Backend.database.connection import get_connection
from Backend.services.inventory_service import (
    InventoryServiceError,
    save_inventory_adjustment,
)
from Backend.services.inventory_simulation import simulate_inventory_adjustment
from Backend.services.store_evaluation import active_store_sku_ids, evaluate_store
from Backend.forecasting.forecast_engine import FORECAST_METHODS

st.set_page_config(
    page_title="StockLens | Inventory Intelligence",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAVY = "#F5F7FB"
PANEL = "#FFFFFF"
TEAL = "#2B8066"
TEXT = "#263445"
MUTED = "#718093"
AMBER = "#E4A241"

st.markdown("""
<style>
:root { color-scheme:light; }
html,body,.stApp,[data-testid="stAppViewContainer"] { background:#F5F7FB!important; color:#263445!important; font-family:'Segoe UI',system-ui,sans-serif!important; }
[data-testid="stHeader"] { background:#FFFFFF!important; border-bottom:1px solid #E8EDF1; height:3.25rem!important; }
[data-testid="stToolbar"] { right:1rem; }
[data-testid="stMainBlockContainer"] { max-width:1500px!important; padding:1.55rem 2.25rem 3rem!important; }
[data-testid="stSidebar"] { background:#14251F!important; border-right:0!important; }
[data-testid="stSidebar"] * { color:#DCEAE2; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding:1.65rem 1.05rem!important; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:.65rem!important; }
[data-testid="stSidebar"] [role="radiogroup"] { gap:.3rem; }
[data-testid="stSidebar"] [role="radiogroup"] label { padding:.62rem .65rem!important; border-radius:9px!important; transition:background .15s; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background:#243F34!important; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background:#E9F4EF!important; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p { color:#1D5B48!important; font-weight:700!important; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) [data-testid="stMarkdownContainer"] * { color:#1D5B48!important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color:#93B0A2!important; }
[data-testid="stMetric"] { background:#FFFFFF!important; border:1px solid #E7EDF1!important; border-radius:13px!important; box-shadow:0 6px 22px #1B2C3F08!important; padding:18px 19px!important; min-height:120px; }
[data-testid="stMetricLabel"] p { color:#718093!important; font-size:.85rem!important; font-weight:600!important; }
[data-testid="stMetricValue"] { color:#263445!important; font-size:1.72rem!important; overflow-wrap:anywhere; }
[data-testid="stMetricValue"] div { white-space:normal!important; }
[data-testid="stSelectbox"] [data-baseweb="select"] > div { background:#FFFFFF!important; border:1px solid #DFE6EC!important; border-radius:9px!important; color:#263445!important; }
[data-testid="stSelectbox"] [data-baseweb="select"] * { color:#263445!important; }
[data-testid="stDataFrame"], [data-testid="stPlotlyChart"] { border-radius:12px!important; overflow:hidden; }
[data-testid="stDownloadButton"] button { background:#FFFFFF!important; color:#286B55!important; border:1px solid #B7D0C4!important; border-radius:9px!important; font-weight:650!important; }
[data-testid="stDownloadButton"] button:hover { background:#E9F4EF!important; }
[data-testid="stExpander"] { background:#FFFFFF!important; border:1px solid #E4EBF0!important; border-radius:12px!important; }
[data-testid="stExpander"] * { color:#334154; }
[data-testid="stAlert"] { border-radius:10px!important; }
.stButton button { border-radius:9px!important; }
hr { border-color:#E8EDF1!important; }
.hero { background:#FFFFFF; border:1px solid #E7EDF1; border-radius:14px; padding:25px 29px; margin:0 0 23px; box-shadow:0 8px 26px #1B2C3F07; position:relative; overflow:hidden; }
.hero:before { content:""; position:absolute; width:5px; left:0; top:0; bottom:0; background:#2B8066; }
.eyebrow { color:#2B8066!important; font-size:.72rem; font-weight:800; letter-spacing:.13em; text-transform:uppercase; margin-bottom:8px; }
.hero h1 { color:#172230!important; font-size:clamp(1.6rem,2.3vw,2.15rem); line-height:1.2; margin:0 0 9px; font-weight:750; }
.hero p { color:#718093!important; max-width:870px; margin:0; font-size:.93rem; line-height:1.6; }
.section { font-weight:730; color:#263445!important; margin:21px 0 12px; font-size:1.12rem; }
.note { color:#8492A2!important; font-size:.86rem; margin:3px 0 13px; }
.panel { background:#FFFFFF; border:1px solid #E7EDF1; border-radius:13px; padding:19px 21px; margin:10px 0 15px; box-shadow:0 6px 22px #1B2C3F06; }
.panel strong { color:#263445!important; }
.panel h3 { color:#263445!important; }
.panel p { color:#657487!important; margin:8px 0 0; line-height:1.65; }
.kicker { color:#2B8066!important; font-size:.75rem; letter-spacing:.1em; text-transform:uppercase; font-weight:700; }
.tag { display:inline-block; border-radius:30px; background:#E9F5EF; color:#30775D; padding:5px 11px; font-weight:700; font-size:.75rem; }
.tag-warn { background:#FFF4DF; color:#94651C; }
.brand-lockup { margin-bottom:17px; padding:5px 6px 18px; border-bottom:1px solid #FFFFFF22; }
.brand-name { color:#FFFFFF!important; font-size:1.22rem; font-weight:800; letter-spacing:-.02em; }
.brand-sub { color:#9EB8AA!important; font-size:.77rem; margin-top:5px; }
.brand-icon { display:inline-grid; place-items:center; background:#2B8066; width:35px; height:35px; border-radius:10px; color:white!important; margin-right:9px; }
.workspace-label { color:#8BA79A!important; font-size:.69rem; font-weight:700; letter-spacing:.12em; margin:17px 0 8px; }
.sidebar-footer { margin-top:30px; border-top:1px solid #FFFFFF22; padding:16px 5px; color:#9EB8AA!important; font-size:.76rem; line-height:1.8; }
[data-testid="stMarkdownContainer"] p { line-height:1.6; }
@media(max-width:850px){[data-testid="stMainBlockContainer"]{padding:1.1rem 1rem 2rem!important;}.hero{padding:19px 20px;}}
</style>
""", unsafe_allow_html=True)


PAGES = [
    "Operations Overview",
    "Demand Forecasting",
    "Replenishment Recommendations",
    "Inventory & Suppliers",
    "Validation Scenarios",
    "Forecast Evaluation & Exports",
    "Store Evaluation",
]


def esc(value):
    return html.escape(str(value))


def hero(label, title, description):
    st.markdown(f'<div class="hero"><div class="eyebrow">{esc(label)}</div><h1>{esc(title)}</h1><p>{esc(description)}</p></div>', unsafe_allow_html=True)


def panel(title, description):
    st.markdown(f'<div class="panel"><strong>{esc(title)}</strong><p>{esc(description)}</p></div>', unsafe_allow_html=True)


def section(title, note=None):
    st.markdown(f'<div class="section">{esc(title)}</div>', unsafe_allow_html=True)
    if note:
        st.markdown(f'<div class="note">{esc(note)}</div>', unsafe_allow_html=True)


def plot_style(fig, height=370):
    fig.update_layout(
        template="plotly_white", height=height, autosize=True,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(color=TEXT, family="Segoe UI, Arial, sans-serif", size=12),
        legend=dict(bgcolor="#FFFFFF", bordercolor="#E4EAF0", borderwidth=1,
                    font=dict(color=TEXT), orientation="h", y=1.13, x=0),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#DDE6EB", font=dict(color=TEXT)),
        margin=dict(l=30, r=20, t=75, b=35),
        xaxis=dict(showgrid=True, gridcolor="#EDF1F5", zeroline=False,
                   linecolor="#DCE4EA", tickfont=dict(color=MUTED)),
        yaxis=dict(showgrid=True, gridcolor="#EDF1F5", zeroline=False,
                   linecolor="#DCE4EA", tickfont=dict(color=MUTED)),
    )
    return fig


def as_num(frame, col):
    if frame.empty or col not in frame:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[col], errors="coerce")


def overall_metrics(metrics):
    if metrics.empty or "evaluation_scope" not in metrics:
        return pd.DataFrame()
    return metrics.loc[metrics["evaluation_scope"] == "OVERALL"].copy()


def selected_model(metrics):
    data = overall_metrics(metrics)
    if data.empty or "selected_method" not in data:
        return None
    values = data["selected_method"].dropna()
    return str(values.iloc[0]) if not values.empty else None


def model_label(method):
    return {"BASELINE_7D": "7-day baseline", "WEEKDAY_SEASONAL_28D": "Weekday seasonal"}.get(str(method), str(method or "Unavailable"))


def latest_origin(tables):
    runs = tables["ForecastRun"]
    if runs.empty or "forecast_origin" not in runs:
        return None
    dates = pd.to_datetime(runs["forecast_origin"], errors="coerce").dropna()
    return dates.max().date() if not dates.empty else None


def download(label, frame, filename, key):
    st.download_button(label, frame.to_csv(index=False).encode("utf-8"), filename, "text/csv", key=key, disabled=frame.empty)


def overview(tables, metrics):
    hero(
        "Inventory Intelligence",
        "Operations Overview",
        "SKU-level demand forecasting, inventory visibility, and replenishment decision support.",
    )
    rec = tables["PurchaseRecommendation"]
    fixtures = tables["AnomalyFixture"]
    model = selected_model(metrics)
    overall = overall_metrics(metrics)
    chosen = overall.loc[overall["forecast_method"].eq(model)] if not overall.empty and "forecast_method" in overall else pd.DataFrame()
    wape = as_num(chosen, "wape_percent").dropna()
    wape_label = f"{wape.iloc[0]:.1f}%" if not wape.empty else "N/A"
    units = as_num(rec, "recommended_qty").fillna(0).sum()
    a, b, c, d = st.columns(4)
    a.metric("Products", f"{len(tables['SKU']):,}")
    b.metric("Locations", f"{len(tables['Store']):,}")
    c.metric("Suppliers", f"{len(tables['Supplier']):,}")
    d.metric("Recommended units", f"{units:,.0f}")
    a, b, c, d = st.columns(4)
    a.metric("Forecast method", model_label(model))
    b.metric("Holdout WAPE", wape_label)
    c.metric("Purchase decisions", f"{len(rec):,}")
    d.metric("Anomaly tests passed", f"{int(fixtures['test_status'].eq('PASS').sum()) if 'test_status' in fixtures else 0} / {len(fixtures)}")
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        section("How the system makes a decision")
        panel("01 · Observe", "Sales history captures observed demand, promotions and stockout periods.")
        panel("02 · Forecast", "The selected method predicts daily SKU–store demand without accessing hidden ground truth.")
        panel("03 · Replenish", "Inventory position, supplier lead time, safety stock, MOQ, pack size and capacity determine the suggested order.")
    with right:
        section("Replenishment outcomes")
        if not rec.empty and "capacity_constraint_status" in rec:
            counts = rec["capacity_constraint_status"].fillna("UNKNOWN").value_counts()
            fig = go.Figure(go.Pie(labels=counts.index.tolist(), values=counts.values.tolist(), hole=.72, marker=dict(colors=[TEAL, AMBER, "#7797BB"]), textfont=dict(color=TEXT)))
            fig.update_layout(annotations=[dict(text=f"{len(rec)}<br>decisions", x=.5, y=.5, font=dict(size=20, color=TEXT), showarrow=False)], showlegend=True)
            st.plotly_chart(plot_style(fig, 345), width="stretch")
        else:
            st.info("No replenishment outcomes are available.")
        issues = tables["ValidationIssue"]
        unresolved = int(issues["resolved_flag"].eq(False).sum()) if "resolved_flag" in issues else 0
        panel(
            "Validation health",
            f"{unresolved} unresolved validation findings. The anomaly records are "
            "controlled validation test scenarios, not current operational issues.",
        )


def forecasting(tables):
    hero(
        "Demand intelligence",
        "Demand Forecasting",
        "Explore observed sales and model projections for a selected product at a selected location.",
    )
    origin = latest_origin(tables)
    runs, forecasts = tables["ForecastRun"], tables["Forecast"]
    if origin is None or forecasts.empty:
        st.info("No forecast data available.")
        return
    ids = runs.loc[pd.to_datetime(runs["forecast_origin"], errors="coerce").dt.date.eq(origin), "run_id"]
    pairs = forecasts.loc[forecasts["run_id"].isin(ids), ["store_id", "sku_id"]].drop_duplicates()
    pairs = pairs.merge(tables["Store"][["store_id", "store_name"]], on="store_id").merge(tables["SKU"][["sku_id", "sku_name"]], on="sku_id")
    if pairs.empty:
        st.info("No forecasted SKU–store combinations available.")
        return
    x, y = st.columns(2)
    stores = pairs[["store_id", "store_name"]].drop_duplicates().sort_values("store_name")
    store_names = dict(zip(stores.store_id, stores.store_name))
    with x:
        store = st.selectbox("Location", stores.store_id.tolist(), format_func=lambda value: store_names.get(value, value))
    skus = pairs.loc[pairs.store_id.eq(store), ["sku_id", "sku_name"]].drop_duplicates().sort_values("sku_name")
    sku_names = dict(zip(skus.sku_id, skus.sku_name))
    with y:
        sku = st.selectbox("Product", skus.sku_id.tolist(), format_func=lambda value: sku_names.get(value, value))
    st.caption(f"Forecast origin: {origin} · Historical observed sales and forecast data only · Ground truth excluded")
    series = load_forecast_series(store, sku, origin)
    if series.empty:
        st.info("No sales or forecasts for this selection.")
        return
    series["target_date"] = pd.to_datetime(series["target_date"], errors="coerce")
    series["units"] = pd.to_numeric(series["units"], errors="coerce")
    fig = go.Figure()
    palette = {"Observed sales": "#4D83C7", "BASELINE_7D": TEAL, "WEEKDAY_SEASONAL_28D": AMBER}
    series["display_series"] = series.apply(lambda row: "Observed sales" if row["series"] == "Observed sales" else str(row["model_name"]), axis=1)
    for name, group in series.groupby("display_series", sort=False):
        group = group.sort_values("target_date")
        fig.add_trace(go.Scatter(x=group.target_date, y=group.units, name=model_label(name) if name != "Observed sales" else name, mode="lines+markers", line=dict(color=palette.get(name, "#7C98F4"), width=3), marker=dict(size=5), hovertemplate="%{x|%b %d, %Y}<br>%{y:.2f} units<extra>%{fullData.name}</extra>"))
    fig.add_vline(x=pd.Timestamp(origin).timestamp() * 1000, line_dash="dot", line_color="#7394B4")
    fig.update_layout(yaxis_title="Demand (units)", xaxis_title="Date", hovermode="x unified")
    section("Observed sales vs projected demand", "The baseline projection may extend 35 days, while the seasonal method has a shorter horizon.")
    st.plotly_chart(plot_style(fig, 430), width="stretch")
    available = series.loc[series["series"].eq("Forecast")].groupby("model_name").size().reset_index(name="Days available")
    if not available.empty:
        available["Method"] = available["model_name"].map(model_label)
        st.dataframe(
            available[["Method", "Days available"]],
            hide_index=True,
            width="stretch",
        )


def recommendations(tables):
    hero("Supply decisions", "Replenishment recommendations", "See which products need stock, how much to order, and the business rules behind every decision.")
    all_rec = tables["PurchaseRecommendation"]
    if all_rec.empty:
        st.info("No purchase recommendations available.")
        return
    stores = tables["Store"]
    store_names = dict(zip(stores.store_id, stores.store_name))
    a, b, c = st.columns(3)
    with a:
        store = st.selectbox("Location", [None] + stores.store_id.tolist(), format_func=lambda v: "All locations" if v is None else store_names.get(v, v))
    with b:
        capacity = st.selectbox("Capacity status", [None] + sorted(all_rec["capacity_constraint_status"].dropna().astype(str).unique().tolist()), format_func=lambda v: "All capacity outcomes" if v is None else v)
    with c:
        statuses = sorted(all_rec["status"].dropna().astype(str).unique().tolist()) if "status" in all_rec else []
        status = st.selectbox("Decision status", [None] + statuses, format_func=lambda v: "All decisions" if v is None else v)
    data = load_recommendations(store_id=store, capacity_status=capacity, recommendation_status=status)
    if data.empty:
        st.info("No recommendations match these filters.")
        return
    total = as_num(data, "recommended_qty").fillna(0).sum()
    a, b, c = st.columns(3)
    a.metric("Matching decisions", len(data))
    b.metric("Units to order", f"{total:,.0f}")
    c.metric("Capacity blocked", int(data["capacity_constraint_status"].eq("BLOCKED").sum()))
    section("Purchase decision summary", "Business-readable columns first; technical details remain available below.")
    display_cols = ["store_name", "sku_name", "supplier_name", "inventory_position", "reorder_point", "recommended_qty", "capacity_constraint_status", "status", "expected_delivery_date"]
    visible = [column for column in display_cols if column in data]
    view = data[visible].rename(columns={"store_name":"Location", "sku_name":"Product", "supplier_name":"Supplier", "inventory_position":"Inventory position", "reorder_point":"Reorder point", "recommended_qty":"Order units", "capacity_constraint_status":"Capacity", "status":"Decision", "expected_delivery_date":"Expected delivery"})
    st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        height=min(420, 80 + 37 * len(view)),
    )
    section("Why was this order recommended?")
    selected_id = st.selectbox("Choose a decision", data.recommendation_id.tolist(), format_func=lambda rid: f"{rid} · {data.loc[data.recommendation_id.eq(rid), 'sku_name'].iloc[0]}")
    item = data.loc[data.recommendation_id.eq(selected_id)].iloc[0]
    qty = pd.to_numeric(pd.Series([item.get("recommended_qty")]), errors="coerce").iloc[0]
    state = "Order recommended" if pd.notna(qty) and qty > 0 else "No order recommended"
    st.markdown(f'<div class="panel"><span class="kicker">Decision explanation</span><h3 style="margin:9px 0;color:#263445">{esc(item.get("sku_name", selected_id))}</h3><span class="tag">{esc(state)}</span><p>Location: {esc(item.get("store_name", "—"))} · Supplier: {esc(item.get("supplier_name", "—"))}</p></div>', unsafe_allow_html=True)
    a, b, c, d = st.columns(4)
    a.metric("Inventory position", f"{float(item.get('inventory_position') or 0):,.0f}")
    b.metric("Reorder point", f"{float(item.get('reorder_point') or 0):,.2f}")
    c.metric("Target stock", f"{float(item.get('target_stock') or 0):,.2f}")
    d.metric("Order units", f"{float(item.get('recommended_qty') or 0):,.0f}")
    panel("Ordering constraints", f"Reason: {item.get('reason_code', 'Not recorded')} · Minimum order quantity: {item.get('minimum_order_qty', '—')} · Pack size: {item.get('pack_size', '—')} · Supplier lead time: {item.get('lead_time_days', '—')} days. {item.get('exception_reason') or ''}")
    with st.expander("View all technical fields for this decision"):
        details = item.map(
            lambda value: "" if pd.isna(value) else str(value)
        ).to_frame(name="Value")
        st.dataframe(details, width="stretch")
    download("Download filtered recommendations", data, "purchase_recommendations_filtered.csv", "filtered-rec")


def inventory(tables, metrics):
    hero("Stock visibility", "Inventory & supplier network", "Inspect stock positions, capacity, ordering constraints and product eligibility.")
    stores = tables["Store"]
    names = dict(zip(stores.store_id, stores.store_name))
    chosen = st.selectbox("Location", [None] + stores.store_id.tolist(), format_func=lambda v: "All locations" if v is None else names.get(v, v))
    saved_notice = st.session_state.pop("inventory_save_notice", None)
    if saved_notice:
        if saved_notice["duplicate"]:
            st.info("This save request was already recorded. No duplicate event was created.")
        else:
            st.success("Inventory adjustment saved and committed.")
        st.caption(
            f"Event {saved_notice['event_id']} · "
            f"{saved_notice['quantity']:+,} units · "
            f"On hand now {saved_notice['on_hand']:,} units."
        )
        try:
            refreshed_store_data = load_store_evaluation_data(
                saved_notice["store_id"]
            )
            refreshed_evaluation = evaluate_store(
                refreshed_store_data,
                saved_notice["store_id"],
                [saved_notice["sku_id"]],
            )
            refreshed_recommendations = refreshed_evaluation[
                "replenishment_data"
            ]["PurchaseRecommendation"]
            saved_recommendation = refreshed_recommendations.loc[
                refreshed_recommendations["sku_id"].eq(saved_notice["sku_id"])
            ]
            section("Refreshed replenishment decision")
            if saved_recommendation.empty:
                st.info(
                    "The saved inventory is current, but no replenishment "
                    "recommendation is eligible for this SKU."
                )
            else:
                recommendation = saved_recommendation.iloc[0]
                panel(
                    "Store Evaluation refreshed",
                    (
                        f"Order quantity: {int(recommendation['recommended_qty']):,} · "
                        f"Inventory position: {int(recommendation['inventory_position']):,} · "
                        f"Reorder point: {float(recommendation['reorder_point']):,.2f} · "
                        f"Reason: {recommendation['reason_code']}."
                    ),
                )
        except (ConnectionError, ValueError, RuntimeError, psycopg.Error) as exc:
            st.warning(
                "The inventory save committed, but Store Evaluation could not "
                f"refresh ({type(exc).__name__})."
            )

    snapshots = tables["InventorySnapshot"].copy()
    if snapshots.empty:
        st.info("No inventory snapshots available.")
    else:
        snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"], errors="coerce")
        latest = snapshots.sort_values("snapshot_date").drop_duplicates(["store_id", "sku_id"], keep="last")
        if chosen is not None:
            latest = latest.loc[latest.store_id.eq(chosen)]
        latest = latest.merge(tables["SKU"][["sku_id", "sku_name"]], on="sku_id", how="left")
        latest = latest.merge(stores[["store_id", "store_name"]], on="store_id", how="left")
        section("Current stock position")
        cols = [x for x in ["store_name", "sku_name", "snapshot_date", "on_hand", "on_order", "reserved", "backorders"] if x in latest]
        st.dataframe(latest[cols], hide_index=True, width="stretch")
        section("Location capacity")
        for _, store in stores.iterrows():
            if chosen is not None and store.store_id != chosen:
                continue
            rows = latest.loc[latest.store_id.eq(store.store_id)]
            occupied = as_num(rows, "on_hand").fillna(0).sum() + as_num(rows, "on_order").fillna(0).sum()
            capacity = float(store.get("capacity_units") or 0)
            st.write(f"**{store.store_name}** · {occupied:,.0f} / {capacity:,.0f} units")
            st.progress(min(1., max(0., occupied / capacity)) if capacity else 0.)
    section("Supplier ordering terms")
    terms = tables["SupplierSKU"].merge(tables["Supplier"][["supplier_id", "supplier_name"]], on="supplier_id", how="left").merge(tables["SKU"][["sku_id", "sku_name", "lifecycle_state"]], on="sku_id", how="left")
    cols = [x for x in ["supplier_name", "sku_name", "lifecycle_state", "lead_time_days", "min_order_qty", "pack_size", "contract_cost", "supplier_priority", "active_from", "active_to"] if x in terms]
    st.dataframe(terms[cols], hide_index=True, width="stretch")
    section("Store assortment and lifecycle")
    assortment = tables["StoreSKU"].merge(tables["SKU"][["sku_id", "sku_name", "lifecycle_state"]], on="sku_id", how="left").merge(stores[["store_id", "store_name"]], on="store_id", how="left")
    if chosen is not None:
        assortment = assortment.loc[assortment.store_id.eq(chosen)]
    cols = [x for x in ["store_name", "sku_name", "lifecycle_state", "assortment_status", "active_from", "active_to"] if x in assortment]
    st.dataframe(assortment[cols], hide_index=True, width="stretch")

    section(
        "Inventory adjustment",
        "Preview a proposed change, or save it as a traceable inventory event.",
    )
    st.caption(
        "Preview is calculated in memory. Save writes only an InventoryEvent "
        "and the current-day InventorySnapshot in one transaction. Preview "
        "uses the latest persisted stock with the configured forecast origin."
    )
    if chosen is None:
        st.info("Select one location above to preview or save an adjustment.")
        return
    try:
        store_data = load_store_evaluation_data(chosen)
    except (ConnectionError, ValueError, psycopg.Error) as exc:
        st.error(f"Could not load inventory adjustment inputs ({type(exc).__name__}).")
        return

    simulation_skus = active_store_sku_ids(store_data, chosen, date.today())
    if not simulation_skus:
        st.info("This location has no currently eligible products to adjust.")
        return
    sku_names = dict(
        zip(store_data["SKU"]["sku_id"], store_data["SKU"]["sku_name"])
    )
    default_method = selected_model(metrics)
    if default_method not in FORECAST_METHODS:
        default_method = FORECAST_METHODS[0]
    with st.form(f"inventory_adjustment_{chosen}"):
        simulation_sku = st.selectbox(
            "SKU",
            simulation_skus,
            format_func=lambda value: sku_names.get(value, value),
        )
        adjustment_type = st.selectbox(
            "Adjustment type",
            ["RECEIVE_STOCK", "REMOVE_STOCK"],
            format_func=lambda value: (
                "Receive Stock" if value == "RECEIVE_STOCK" else "Remove Stock"
            ),
        )
        quantity = st.number_input(
            "Quantity (units)",
            min_value=1,
            value=1,
            step=1,
        )
        reason = st.text_input("Reason (optional)", max_chars=22)
        forecast_method = st.selectbox(
            "Forecast method for Preview",
            FORECAST_METHODS,
            index=FORECAST_METHODS.index(default_method),
            format_func=model_label,
        )
        preview_column, save_column = st.columns(2)
        with preview_column:
            preview_clicked = st.form_submit_button("Preview")
        with save_column:
            save_clicked = st.form_submit_button("Save")

    signature = (
        chosen,
        simulation_sku,
        adjustment_type,
        int(quantity),
        reason.strip(),
    )
    if st.session_state.get("inventory_save_signature") != signature:
        st.session_state["inventory_save_signature"] = signature
        st.session_state["inventory_save_token"] = uuid.uuid4().hex[:24]

    section("Recent inventory activity")
    try:
        history = load_inventory_history(chosen, simulation_sku)
    except (ConnectionError, ValueError, psycopg.Error) as exc:
        st.error(f"Could not load inventory history ({type(exc).__name__}).")
        history = pd.DataFrame()
    if history.empty:
        st.info("No inventory events are available for this SKU.")
    else:
        history_view = history.copy()
        history_view["Reason or reference"] = history_view["reference_id"].map(
            lambda value: (
                value.split("|", 1)[1]
                if isinstance(value, str) and value.startswith("UI-")
                else value
            )
        )
        history_view = history_view.rename(
            columns={
                "event_date": "Event date",
                "event_type": "Event type",
                "quantity": "Units",
                "resulting_on_hand": "On hand after event",
            }
        )
        display_history_columns = [
            "Event date",
            "Event type",
            "Units",
            "On hand after event",
            "Reason or reference",
        ]
        st.dataframe(
            history_view[display_history_columns],
            hide_index=True,
            width="stretch",
            height=min(350, 80 + 35 * len(history_view)),
        )

    if not preview_clicked and not save_clicked:
        return
    adjustment_units = int(quantity) * (
        1 if adjustment_type == "RECEIVE_STOCK" else -1
    )
    if save_clicked:
        try:
            result = save_inventory_adjustment(
                chosen,
                simulation_sku,
                adjustment_type,
                int(quantity),
                st.session_state["inventory_save_token"],
                reason,
                connection_factory=lambda: get_connection(
                    _deployment_database_url()
                ),
            )
        except (InventoryServiceError, ConnectionError, ValueError) as exc:
            st.error(f"Inventory adjustment was not saved: {esc(exc)}")
            return

        st.session_state["inventory_save_notice"] = {
            "duplicate": result["duplicate"],
            "event_id": result["event_id"],
            "quantity": result["quantity"],
            "on_hand": result["on_hand"],
            "store_id": chosen,
            "sku_id": simulation_sku,
        }
        load_dashboard_tables.clear()
        load_store_evaluation_data.clear()
        load_inventory_history.clear()
        st.rerun()

    try:
        result = simulate_inventory_adjustment(
            store_data,
            chosen,
            simulation_sku,
            adjustment_units,
            forecast_method,
        )
    except (ValueError, RuntimeError) as exc:
        st.error(f"Preview could not complete: {esc(exc)}")
        return

    st.write(
        f"**Preview result:** {result['status'].replace('_', ' ').title()} · "
        f"{result['adjustment_units']:+,} units"
    )
    a, b, c = st.columns(3)
    a.metric("On hand before", f"{result['on_hand_before']:,}")
    b.metric("On hand after", f"{result['on_hand_after']:,}")
    c.metric("Inventory position after", f"{result['inventory_position_after']:,}")
    a, b, c = st.columns(3)
    a.metric(
        "Store capacity after adjustment",
        f"{result['projected_store_units']:,} / {result['capacity_units']:,}",
    )
    if result["status"] == "REJECTED_CAPACITY":
        b.metric("Capacity outcome", "Rejected")
        st.warning(result["rejection_reason"])
        return

    recommendation = result["recommendation"]
    if recommendation is None:
        b.metric("Capacity outcome", "Within capacity")
        st.info(
            "No replenishment recommendation was produced for this product. "
            "It may not be eligible on the current reference date."
        )
        return
    b.metric("Capacity outcome", recommendation["capacity_constraint_status"])
    c.metric("Recommended order", f"{int(recommendation['recommended_qty']):,}")
    panel(
        "Preview replenishment decision",
        (
            f"Capacity: {recommendation['capacity_constraint_status']} · "
            f"Reason: {recommendation['reason_code']} · "
            f"Reorder point: {float(recommendation['reorder_point']):,.2f} · "
            f"Target stock: {float(recommendation['target_stock']):,.2f} · "
            f"MOQ: {int(recommendation['minimum_order_qty'])} · "
            f"Pack size: {int(recommendation['pack_size'])} · "
            f"Expected delivery: {recommendation['expected_delivery_date']}."
        ),
    )


def anomalies(tables):
    hero(
        "Validation controls",
        "Validation Scenarios",
        "Five controlled validation test scenarios cover forecasting and replenishment rules.",
    )
    fixtures, issues = tables["AnomalyFixture"], tables["ValidationIssue"]
    st.info(
        "Stored AnomalyFixture and ValidationIssue rows are controlled validation "
        "test scenarios, not live operational incidents."
    )
    resolved_count = (
        int(issues["resolved_flag"].eq(True).sum())
        if "resolved_flag" in issues
        else 0
    )
    unresolved_count = (
        int(issues["resolved_flag"].eq(False).sum())
        if "resolved_flag" in issues
        else 0
    )
    a, b, c, d = st.columns(4)
    a.metric("Stored scenarios", len(fixtures))
    b.metric(
        "Scenario checks passed",
        int(fixtures["test_status"].eq("PASS").sum())
        if "test_status" in fixtures
        else 0,
    )
    c.metric("Resolved findings", resolved_count)
    d.metric("Unresolved findings", unresolved_count)

    if fixtures.empty:
        st.info("No stored validation scenarios are available.")
    else:
        section("Stored validation scenarios")
        options = fixtures["issue_type"].dropna().unique().tolist()
        chosen = st.selectbox(
            "Explore a scenario",
            options,
            format_func=lambda x: x.replace("_", " ").title(),
        )
        item = fixtures.loc[fixtures.issue_type.eq(chosen)].iloc[0]
        st.markdown(
            f'<div class="panel"><span class="kicker">{esc(item.get("test_status", "UNKNOWN"))}</span><h3 style="color:#263445">{esc(chosen.replace("_", " ").title())}</h3><p><b>Scenario:</b> {esc(item.get("scenario", "—"))}</p><p><b>Expected:</b> {esc(item.get("expected_result", "—"))}</p><p><b>Detected:</b> {esc(item.get("detected_result", "—"))}</p></div>',
            unsafe_allow_html=True,
        )
    with st.expander("Show all anomaly fixtures and validation findings"):
        if not fixtures.empty:
            st.dataframe(fixtures, hide_index=True, width="stretch")
        if not issues.empty:
            st.dataframe(issues, hide_index=True, width="stretch")

    section(
        "Current store evaluation checks",
        "These checks run from read-only source data and are not written to the validation tables.",
    )
    stores = tables["Store"]
    if stores.empty:
        st.info("No store records are available for evaluation.")
        return
    store_names = dict(zip(stores["store_id"], stores["store_name"]))
    store_id = st.selectbox(
        "Location to check",
        stores["store_id"].tolist(),
        format_func=lambda value: store_names.get(value, value),
        key="validation_store",
    )
    if st.button("Run current store checks", key="run_validation_store_checks"):
        try:
            store_data = load_store_evaluation_data(store_id)
            sku_ids = active_store_sku_ids(store_data, store_id)
            if not sku_ids:
                st.warning("No currently eligible products are available for checks.")
                return
            result = evaluate_store(store_data, store_id, sku_ids)
        except (ConnectionError, ValueError, RuntimeError, psycopg.Error) as exc:
            st.error(f"Store checks could not complete ({type(exc).__name__}).")
            return

        overall = overall_metrics(result["metrics"])
        expected_methods = set(FORECAST_METHODS)
        methods = set(overall.get("forecast_method", pd.Series(dtype=str)))
        recommendation_issues = result["replenishment_data"]["ValidationIssue"]
        checks = pd.DataFrame(
            [
                {
                    "Check": "Historical holdout evaluation",
                    "Result": "PASS"
                    if methods == expected_methods and not overall.empty
                    else "INCOMPLETE",
                    "Details": (
                        f"{len(result['holdout_origins'])} chronological origins; "
                        f"{len(methods)} forecast methods."
                    ),
                },
                {
                    "Check": "Forecast origin and input validation",
                    "Result": "PASS",
                    "Details": (
                        "Existing forecast validation accepted historical "
                        "SalesHistory inputs and target dates after each origin."
                    ),
                },
                {
                    "Check": "Replenishment rule validation",
                    "Result": "PASS"
                    if recommendation_issues.empty
                    else "REVIEW",
                    "Details": (
                        f"{len(recommendation_issues)} recorded data findings; "
                        "the replenishment engine validated generated decisions."
                    ),
                },
            ]
        )
        st.dataframe(checks, hide_index=True, width="stretch")
        if not recommendation_issues.empty:
            st.dataframe(
                recommendation_issues,
                hide_index=True,
                width="stretch",
            )


def evaluation(tables, metrics):
    hero(
        "Forecast quality",
        "Forecast Evaluation & Exports",
        "Compare holdout accuracy and download forecasts, replenishment decisions, and validation results.",
    )
    if metrics.empty:
        st.warning("Evaluation CSV is missing: data/exports/forecast_evaluation_metrics.csv. Include it when deploying.")
    else:
        overall = overall_metrics(metrics)
        chosen = selected_model(metrics)
        panel("Selected forecasting method", f"{model_label(chosen)} ({chosen or 'unavailable'}). The selection uses chronological holdout performance, not future data as an input.")
        if not overall.empty:
            section("Holdout model comparison")
            a, b, c, d = st.columns(4)
            best = overall.loc[overall.forecast_method.eq(chosen)] if "forecast_method" in overall else pd.DataFrame()
            for card, col, label, suffix in [(a, "mae", "MAE", ""), (b, "rmse", "RMSE", ""), (c, "wape_percent", "WAPE", "%"), (d, "bias", "Bias", "")]:
                values = as_num(best, col).dropna()
                card.metric(label, f"{values.iloc[0]:.2f}{suffix}" if not values.empty else "N/A")
            if {"forecast_method", "wape_percent"}.issubset(overall):
                fig = go.Figure(go.Bar(x=overall.forecast_method.map(model_label), y=pd.to_numeric(overall.wape_percent, errors="coerce"), marker_color=[TEAL, AMBER][:len(overall)], text=overall.wape_percent.map(lambda x: f"{float(x):.1f}%"), textposition="outside"))
                fig.update_layout(showlegend=False, yaxis_title="WAPE (%) · lower is better")
                st.plotly_chart(plot_style(fig, 360), width="stretch")
        with st.expander("View all evaluation records"):
            st.dataframe(metrics, hide_index=True, width="stretch")
    section(
        "Download operational outputs",
        "CSV exports contain existing records; downloading does not change the database.",
    )
    for label, frame, filename in [
        ("Forecasts", tables["Forecast"], "forecasts.csv"),
        ("Purchase recommendations", tables["PurchaseRecommendation"], "purchase_recommendations.csv"),
        ("Anomaly fixtures", tables["AnomalyFixture"], "anomaly_fixtures.csv"),
        ("Validation findings", tables["ValidationIssue"], "validation_issues.csv"),
        ("Model evaluation", metrics, "forecast_evaluation_metrics.csv"),
    ]:
        download(f"Download {label}", frame, filename, f"export-{filename}")


def store_evaluation_page(tables):
    hero(
        "Location performance",
        "Store Evaluation",
        "Review historical demand accuracy and replenishment decisions for one location.",
    )
    stores = tables["Store"]
    if stores.empty:
        st.info("No store records are available.")
        return
    store_names = dict(zip(stores["store_id"], stores["store_name"]))
    store_id = st.selectbox(
        "Location",
        stores["store_id"].tolist(),
        format_func=lambda value: store_names.get(value, value),
        key="store_evaluation_location",
    )
    try:
        store_data = load_store_evaluation_data(store_id)
    except (ConnectionError, ValueError, psycopg.Error) as exc:
        st.error(f"Could not load location data ({type(exc).__name__}).")
        return
    if store_data["Store"].empty:
        st.info("No current data is available for this location.")
        return
    active_skus = active_store_sku_ids(store_data, store_id)
    store_row = store_data["Store"].iloc[0]
    st.write(
        f"**{store_row['city']}, {store_row['region']}** · "
        f"{store_row['store_type']} · Capacity "
        f"{int(store_row['capacity_units']):,} units"
    )
    snapshot_dates = pd.to_datetime(
        store_data["InventorySnapshot"]["snapshot_date"],
        errors="coerce",
    ).dropna()
    latest_snapshot_date = (
        snapshot_dates.max().date().isoformat()
        if not snapshot_dates.empty
        else "Unavailable"
    )
    date_column, snapshot_column = st.columns(2)
    date_column.metric("Forecast reference date", REFERENCE_DATE.isoformat())
    snapshot_column.metric(
        "Latest inventory snapshot date",
        latest_snapshot_date,
    )
    if not active_skus:
        st.warning("No currently eligible products are available for evaluation.")
        return
    sku_names = dict(
        zip(store_data["SKU"]["sku_id"], store_data["SKU"]["sku_name"])
    )
    selected_skus = st.multiselect(
        "Products to evaluate",
        active_skus,
        default=active_skus,
        format_func=lambda value: sku_names.get(value, value),
        key=f"store_evaluation_skus_{store_id}",
    )
    st.caption(
        "Forecasts are recalculated from SalesHistory at chronological holdout "
        "origins. GroundTruthDemand is used only after forecasting to score "
        f"historical demand. Replenishment pairs the latest saved inventory "
        f"snapshot ({latest_snapshot_date}) with the configured forecast "
        f"baseline ({REFERENCE_DATE.isoformat()}). Forecast history and "
        "holdout metrics are not rewritten."
    )
    if not selected_skus:
        st.info("Select at least one product to run the evaluation.")
        return
    try:
        result = evaluate_store(store_data, store_id, selected_skus)
    except (ValueError, RuntimeError) as exc:
        st.warning(f"Evaluation could not complete: {esc(exc)}")
        return

    overall = overall_metrics(result["metrics"])
    chosen = result["selection"]["selected_method"]
    chosen_metrics = overall.loc[overall["forecast_method"].eq(chosen)]
    wape = as_num(chosen_metrics, "wape_percent").dropna()
    recommendations = result["replenishment_data"]["PurchaseRecommendation"]
    order_units = as_num(recommendations, "recommended_qty").fillna(0).sum()
    section("Location evaluation summary")
    a, b, c, d = st.columns(4)
    a.metric("Products evaluated", len(result["sku_ids"]))
    b.metric("Selected method", model_label(chosen))
    c.metric(
        "Holdout WAPE",
        f"{wape.iloc[0]:.1f}%" if not wape.empty else "N/A",
    )
    d.metric("Recommended order units", f"{order_units:,.0f}")
    st.caption(f"Current replenishment forecast horizon: {result['required_horizon']} days")

    section(
        "Historical method comparison",
        "Metrics use only the selected location and products across chronological holdout dates.",
    )
    metric_display = overall[
        [
            column
            for column in (
                "forecast_method",
                "forecast_count",
                "mae",
                "rmse",
                "wape_percent",
                "bias",
            )
            if column in overall
        ]
    ].copy()
    if "forecast_method" in metric_display:
        metric_display["forecast_method"] = metric_display[
            "forecast_method"
        ].map(model_label)
    st.dataframe(
        metric_display.rename(
            columns={
                "forecast_method": "Forecast method",
                "forecast_count": "Holdout records",
                "mae": "MAE",
                "rmse": "RMSE",
                "wape_percent": "WAPE (%)",
                "bias": "Bias",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    if not overall.empty and "wape_percent" in overall:
        chart = go.Figure(
            go.Bar(
                x=overall["forecast_method"].map(model_label),
                y=pd.to_numeric(overall["wape_percent"], errors="coerce"),
                marker_color=[TEAL, AMBER][:len(overall)],
                text=pd.to_numeric(
                    overall["wape_percent"], errors="coerce"
                ).map(lambda value: f"{value:.1f}%" if pd.notna(value) else "N/A"),
                textposition="outside",
            )
        )
        chart.update_layout(showlegend=False, yaxis_title="WAPE (%) · lower is better")
        st.plotly_chart(plot_style(chart, 350), width="stretch")

    section(
        "Replenishment recalculated for this location",
        "The existing replenishment engine applies supplier terms, inventory, reorder policy and store capacity.",
    )
    if recommendations.empty:
        st.info("No recommendations were produced for the selected products.")
    else:
        recommendation_view = recommendations.merge(
            store_data["SKU"][["sku_id", "sku_name"]],
            on="sku_id",
            how="left",
        )
        display_columns = [
            column
            for column in (
                "sku_name",
                "inventory_position",
                "reorder_point",
                "recommended_qty",
                "capacity_constraint_status",
                "reason_code",
                "expected_delivery_date",
            )
            if column in recommendation_view
        ]
        st.dataframe(
            recommendation_view[display_columns].rename(
                columns={
                    "sku_name": "Product",
                    "inventory_position": "Inventory position",
                    "reorder_point": "Reorder point",
                    "recommended_qty": "Order units",
                    "capacity_constraint_status": "Capacity",
                    "reason_code": "Reason",
                    "expected_delivery_date": "Expected delivery",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    download(
        "Download location evaluation metrics",
        result["metrics"],
        "store_evaluation_metrics.csv",
        "store-evaluation-metrics",
    )
    download(
        "Download location replenishment results",
        recommendations,
        "store_replenishment_results.csv",
        "store-evaluation-recommendations",
    )


def main():
    with st.sidebar:
        st.markdown(
            '''<div class="brand-lockup"><div><span class="brand-icon">◈</span><span class="brand-name">StockLens</span></div><div class="brand-sub">Inventory Intelligence</div></div><div class="workspace-label">OPERATIONS WORKSPACE</div>''',
            unsafe_allow_html=True,
        )
        page = st.radio("Navigation", PAGES, label_visibility="collapsed")
        st.markdown(
            '''<div class="sidebar-footer">PostgreSQL · Controlled inventory updates<br>Forecasting · Inventory · Decisions</div>''',
            unsafe_allow_html=True,
        )
    try:
        with st.spinner("Loading dashboard data..."):
            tables = load_dashboard_tables()
            metrics = load_evaluation_metrics()
    except Exception as exc:
        st.error(f"Could not load dashboard data ({type(exc).__name__}).")
        st.info("Check your local DATABASE_URL or Streamlit deployment secrets. No credentials are shown.")
        return
    pages = {
        "Operations Overview": lambda: overview(tables, metrics),
        "Demand Forecasting": lambda: forecasting(tables),
        "Replenishment Recommendations": lambda: recommendations(tables),
        "Inventory & Suppliers": lambda: inventory(tables, metrics),
        "Validation Scenarios": lambda: anomalies(tables),
        "Forecast Evaluation & Exports": lambda: evaluation(tables, metrics),
        "Store Evaluation": lambda: store_evaluation_page(tables),
    }
    pages[page]()


if __name__ == "__main__":
    main()
