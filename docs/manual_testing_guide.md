# StockLens Manual Testing Guide

The project owner reports manually opening and reviewing the application,
successfully testing Inventory Preview and Save, and testing application reads
and inventory operations with the restricted Supabase evaluator account. This
guide provides a repeatable walkthrough for evaluators. Automated AppTest
coverage for all seven pages is summarized in the
[test execution report](test_execution_report.md).

## Before You Begin

Use the preloaded evaluation database with its restricted account, or an
independent local PostgreSQL database that you control. The local backup
workflow is documented in the [README](../README.md). Confirm the configured
database before saving inventory changes. Do not use a privileged role to
bypass a permission or row-policy error.

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
4. Optionally preview a removal larger than on-hand or a receipt that exceeds
   store capacity. Both should be rejected without a database change.

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
acquisition. Concurrent database writes and repeated live submissions require
a separate authorized integration test.

## Optional Isolated Integration Checks

These are additional checks beyond the completed user-reported manual
verification. Run them only against a disposable PostgreSQL database or a
dedicated test schema, not the shared evaluation database.

1. Apply the unchanged `Backend/database/schema.sql` to the isolated target
   and load the existing test-profile CSVs.
2. Use a dedicated non-owner role with only the table privileges and
   row-scoped policies needed for the test. Do not disable RLS, broaden
   policies, or use a service-role key.
3. Verify the target database, schema, and baseline row counts before opening
   the application.
4. Exercise same-token retry, capacity limits, inactive-SKU rejection, and
   concurrent requests. Confirm event history, snapshot reconciliation, and
   store capacity in that isolated target.
5. Discard the disposable target or remove only known test records there.
   Never run cleanup against the shared evaluation database.

Automated browser screenshot testing is not part of the recorded validation.
