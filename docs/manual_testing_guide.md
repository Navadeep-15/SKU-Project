# StockLens Manual Testing Guide

I manually reviewed the running application, successfully tested Inventory
Preview and Save, and verified application reads and inventory operations
using the restricted Supabase evaluator account. This guide provides a
repeatable walkthrough for evaluators. Automated AppTest
coverage for all seven pages is summarized in the
[test execution report](test_execution_report.md).

## Before You Begin

Use the preloaded evaluation database with its restricted account, or an
independent local PostgreSQL database that you control. The local backup
workflow is documented in the [README](../README.md). Confirm the configured
database before saving inventory changes. Use the configured evaluator account for the walkthrough.

Launch the application from the repository root:

```powershell
python -m streamlit run Frontend/app.py
```

Open the local URL printed by Streamlit.

## Dashboard Walkthrough

1. **Operations Overview** — review the configured forecast method, accuracy
   summary, replenishment recommendations, and validation summary.
2. **Demand Forecasting** — choose a store and SKU; compare sales history with
   the generated forecast.
3. **Replenishment Recommendations** — filter recommendations and inspect
   inventory position, order constraints, capacity status, and explanations.
4. **Inventory & Suppliers** — review inventory snapshots, supplier terms, and
   inventory events. Follow the Preview and Save steps below.
5. **Validation Scenarios** — inspect the five controlled anomaly fixtures and
   their validation issues. These are test scenarios, not live operational
   alerts.
6. **Forecast Evaluation & Exports** — review stored evaluation metrics and
   download available forecast, recommendation, anomaly, and evaluation CSVs.
7. **Store Evaluation** — select a store and product subset; review
   chronological holdouts and replenishment using the latest saved inventory
   snapshot.

## Inventory Preview

1. Open **Inventory & Suppliers** and select a location and eligible SKU.
   Note the latest on-hand quantity and recent event history.
2. Choose **Receive Stock** or **Remove Stock**, enter a positive whole-number
   quantity, and select **Preview**.
3. Review the projected quantity, capacity outcome, and replenishment
   explanation. Preview is an in-memory calculation and should not write an
   `InventoryEvent` or `InventorySnapshot`.

## Inventory Save

1. Use a database you are authorized to modify and select a small valid
   adjustment.
2. Select **Save** and confirm that the success notice appears only after the
   transaction completes.
3. Confirm that activity history includes the event, the current stock view
   refreshes, and Store Evaluation reflects the latest saved snapshot.
4. A receipt should create an `ADJUSTMENT_IN` event with positive quantity; a
   removal should create an `ADJUSTMENT_OUT` event with negative quantity.
   Existing historical snapshots remain unchanged. The first adjustment on a
   date inserts that day's snapshot; later same-day adjustments update that
   current-day row and add separate events.

The application retains an idempotency token while submitted fields remain
unchanged; changing a field creates a new save request. Unit tests cover
transaction rollback, same-token retries, capacity, eligibility, and lock
acquisition. 
