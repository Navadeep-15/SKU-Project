# StockLens implementation compliance audit

This audit records the requirements and implementation state observed in the
repository. It does not change the frozen database schema or existing dataset.

The consolidated final tally is in the
[requirements traceability matrix](requirements_traceability_matrix.md):
39 of 42 mandatory requirements are fully satisfied, three are partial, and
none are missing. The earlier 38/41 tally omitted `DATA-13`, which records the
original requirement to use deterministic or database-generated identifiers
instead of hardcoded IDs. All 41 earlier rows remain in the final matrix.

| Requirement | Status | Evidence and notes |
|---|---|---|
| Preserve the finalized 16-table schema | Implemented | `Backend/database/schema.sql` defines the 16 logical tables; the application changes in this phase do not modify it. |
| Generate master data before dependent records | Implemented | The generation pipeline builds master tables before sales, inventory, forecasts, and replenishment; module tests validate foreign keys. |
| Deterministic IDs and fixed random seed | Implemented | `config.py` defines `RANDOM_SEED`; generator tests check repeatability and identifiers. |
| Configured development profile of 250 SKUs, 20 stores, 365 days | Partial end-to-end | `config.py` and the master, sales, and inventory generators support the configured profile. The full replenishment pipeline and anomaly runner remain restricted to `test`; see DATA-09 in the final matrix. |
| Synthetic demand, seasonality, and promotions | Implemented | `Backend/data_generation/sales_generator.py` generates seasonal and promotion-adjusted demand. |
| Record stockouts separately from zero demand | Implemented | `SalesHistory.stockout_flag` and separate `GroundTruthDemand` fields distinguish observed sales from censored demand; generator and forecast tests exercise the cases. |
| Keep ground truth out of forecast inputs | Implemented | `Backend/forecasting/forecast_engine.py` rejects ground-truth-only columns; `Backend/evaluation/forecast_evaluator.py` joins truth only after forecasts exist. |
| Valid supplier terms and nonnegative lead times | Implemented | `Backend/data_generation/master_generator.py` validates supplier relationships and terms; replenishment rejects negative lead times. |
| Validate identifiers, keys, dates, enums, and business rules | Implemented | Generation, schema preflight, and focused module tests cover primary/foreign keys and application-level constraints. |
| Export generated data to CSV | Implemented | Generator modules export schema-aligned CSVs; evaluation and anomaly results have dedicated exports. |
| Explainable forecasts and chronological holdout evaluation | Implemented | `Backend/forecasting/forecast_engine.py` provides baseline and weekday-seasonal methods; `Backend/evaluation/forecast_evaluator.py` applies chronological holdouts and reports MAE, RMSE, WAPE, and bias. |
| Prevent future-data leakage | Implemented | Forecast inputs are observed sales only, cut off at each origin; forecast and evaluation modules validate origin, target, and horizon relationships. |
| Reorder point and safety stock calculations | Implemented | `Backend/replenishment/replenishment_engine.py` derives lead-time demand, reorder point, and target stock from existing policies and forecasts. |
| MOQ and pack-size rules | Implemented | The replenishment engine rounds positive orders to valid MOQ and pack multiples; tests cover ordering constraints. |
| Store capacity constraints and recorded exceptions | Implemented | The engine allocates within capacity and reports blocked orders and validation findings rather than silently exceeding capacity. |
| Forecast and recommendation traceability | Implemented | `ForecastRun`, `Forecast`, and `PurchaseRecommendation` records include run IDs, origins, and method/provenance fields. |
| Required controlled anomaly scenarios | Implemented | `Backend/validation/anomaly_detector.py` creates the five required anomaly types; `tests/test_anomaly_detector.py` verifies outputs and isolation. |
| Idempotent database loading and transaction rollback | Implemented and unit-tested; live repeat not retested | `Backend/database/loader.py` has unit coverage for identical repeats, conflicts, and rollback. The final audit did not perform a live write; read-only Supabase checks found the expected anomaly rows. |
| Supabase schema and dataset integrity | Verified read-only in the final audit | Supabase contained all 16 tables, 23 valid FK relationships with zero orphans, and 18,885 rows. This comprises the 18,873 generated rows, ten anomaly/validation rows, and one saved inventory event plus one snapshot. No audit writes were performed. |
| Read-only dashboard data access | Implemented for dashboard reads | `Backend/dashboard/data_access.py` starts a read-only transaction and rolls it back after reads. Filtered queries are parameterized. Inventory persistence is separate. |
| Executive, forecasting, replenishment, inventory, validation, and evaluation views | Implemented | `Frontend/app.py` retains the six existing views and adds Store Evaluation as a seventh page. |
| Location-specific historical evaluation | Implemented | `Backend/services/store_evaluation.py` recalculates forecasts from selected-location `SalesHistory`, scores chronological holdouts against `GroundTruthDemand`, and recalculates replenishment with the existing engine and latest persisted inventory state. |
| In-memory inventory adjustment Preview | Implemented | `Backend/services/inventory_simulation.py` adjusts a temporary copy of a location's latest snapshot and event ledger, reruns the existing replenishment engine, and never saves the preview. |
| Inventory adjustment Save | Implemented and unit-tested; persisted state verified read-only | `Backend/services/inventory_service.py` validates eligibility, on-hand, capacity, and ledger reconciliation; uses a transaction-scoped store-level advisory lock and an inventory-event-ID advisory lock; and atomically inserts an immutable event plus the current-day snapshot. Existing historical snapshots are retained. The final audit read the saved event and snapshot without writing. |
| Inventory save idempotency and rollback | Implemented and unit-tested | A stable request token skips identical retries; conflicting reuse is rejected. Mock-connection tests verify transaction rollback. |
| Validation presentation | Implemented | `Frontend/app.py` distinguishes stored controlled test scenarios from current read-only store checks and separates resolved from unresolved findings. |
| Local launch documentation | Implemented | The new root `README.md` documents the current product, data profiles, and local launch steps. |
| Browser rendering across all seven pages | Implemented | `tests/test_dashboard_app.py` uses Streamlit AppTest to load all seven pages and verify Preview does not persist and Save invokes the mocked persistence service. |

## Scale recommendation

Do not switch the configured profile directly to 2,000 SKUs and 100 stores.
First estimate memory and disk requirements using measured rows per eligible
SKU-store pair and the dependent event, forecast, and validation tables. Then
benchmark bounded batches with a smaller, representative subset. Ask for approval
before changing the configured scale, data-generation approach, or database
loading workflow.

## Scope and limitations

The dashboard does not generate data. Preview is an isolated what-if calculation.
Save writes only `InventoryEvent` and `InventorySnapshot`; it does not update
forecasts, recommendations, or generated CSVs. Because the frozen schema allows
one snapshot per store/SKU/date, the first save on a date inserts that day's
snapshot and later same-day saves update only that current-day row while
retaining separate events. Store Evaluation uses the latest persisted stock
against the existing configured forecast origin; historical forecast inputs
and holdout metrics are unchanged. No Supabase connection or write was made
during this phase. Use the optional isolated workflow in
`docs/manual_testing_guide.md` before enabling Save against a deployment.
