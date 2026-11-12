# StockLens requirements traceability matrix

**Audit date:** 2026-11-12  
**Scope:** Read-only audit. No application code, generated data, schema, or database records were changed.

## Scope and status rules

The original problem statement is present in the conversation, but is not stored
as a source document in the repository. This matrix uses that user-provided
statement and its explicit audit checklist, checked against the repository's
[data dictionary](data_dictionary.md), [implementation compliance audit](implementation_compliance.md),
README, schema, source code, tests, and observed data. No additional business
requirements have been inferred.

### Reconciliation with the earlier tally

The earlier **38/41** tally omitted `DATA-13`, the original requirement not to
use hardcoded IDs where deterministic or database-generated IDs are required.
This final matrix retains all 41 earlier rows and adds that original
requirement, which is satisfied. The resulting final tally is **39/42 fully
satisfied, 3 partial, and 0 missing**. The two tallies reflect different row
sets; 39/42 is the authoritative final count.

The mandatory matrix contains **42 requirements**. `YES` means the behavior was
supported by code and relevant test or execution evidence; `PARTIAL` means an
implementation or evidence limitation remains; `NO` means the required
functionality is absent. Evidence below distinguishes actual execution from
source-code presence. Items added by later dashboard/database phases and
optional scalability suggestions are reported separately and are not counted
as original functional requirements.

The suggested scale of 2,000 SKUs × 100 stores × 365 days is **optional**, not
a compliance minimum or submission blocker. The configured development
profile (250 SKUs, 20 stores, 30 suppliers, 365 days) is assessed separately
from the 10-SKU/3-store test-profile dataset.

## Core workflows

| ID | Original requirement | Implemented? | Source and function | Test and execution evidence | Gap or recommended action |
|---|---|---|---|---|---|
| CORE-01 | Forecast demand for each SKU at each store. | YES | [forecast_engine.py](../Backend/forecasting/forecast_engine.py), `generate_forecast_data` | `test_forecast_schema_ids_methods_and_foreign_keys`; temporary test-profile run generated 1,298 forecasts for 17 eligible SKU-store pairs. | None for the configured assortment. |
| CORE-02 | Calculate reorder points using lead time and safety stock. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `_build_recommendation_candidates` | `test_recommendation_calculations_and_lifecycle_are_valid`; test-profile run generated 16 recommendations. | None identified. |
| CORE-03 | Generate purchase recommendations. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `create_recommendations` | `test_recommendation_schema_ids_and_foreign_keys`; 15 positive and one zero-quantity recommendation generated. | The generated run had no blocked recommendation; capacity-blocking behavior is covered by a boundary test. |
| CORE-04 | Consider supplier MOQ and pack sizes. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `_round_order_quantity` and `validate_replenishment_data` | `test_recommendation_calculations_and_lifecycle_are_valid`; an audit-only in-memory mutation to quantity 93 with pack size 4 was rejected by the validator. | None identified. |
| CORE-05 | Consider store inventory capacity. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `_allocate_store_capacity` | `test_capacity_allocation_blocks_complete_orders_in_urgency_order`; all 16 generated recommendations were within capacity. | A capacity-blocked result is demonstrated by a constructed test case, not by this generated dataset. |
| CORE-06 | Identify exceptions and invalid data. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `validate_replenishment_data`; [master_generator.py](../Backend/data_generation/master_generator.py), `validate_master_data` | Negative lead time, missing supplier/policy, capacity overflow, duplicate keys, invalid FKs, and invalid effective dates have focused tests. | None identified for the tested rules. |
| CORE-07 | Evaluate forecast accuracy against actual/ground-truth demand. | YES | [forecast_evaluator.py](../Backend/evaluation/forecast_evaluator.py), `evaluate_forecasts` | `test_evaluation_uses_only_future_holdout_dates`; both methods were evaluated over 313 holdout predictions each. | None identified. |
| CORE-08 | Maintain traceability for forecast runs and recommendations. | YES | [schema.sql](../Backend/database/schema.sql), `ForecastRun`, `Forecast`, and `PurchaseRecommendation`; corresponding generation in [forecast_engine.py](../Backend/forecasting/forecast_engine.py) and [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py) | `test_forecast_schema_ids_methods_and_foreign_keys` and `test_recommendation_schema_ids_and_foreign_keys`; generated IDs and run relationships were checked. | None identified. |

## Schema and data generation

| ID | Original requirement | Implemented? | Source and function | Test and execution evidence | Gap or recommended action |
|---|---|---|---|---|---|
| SCH-01 | Preserve the finalized 16 logical tables and their frozen schema. | YES | [schema.sql](../Backend/database/schema.sql); [loader.py](../Backend/database/loader.py), `parse_schema` | The SQL file and parser define 16 tables. Read-only Supabase inspection found exactly those 16 base tables. | No schema edits were made. See SCH-02 for the one constraint comparison not performed. |
| SCH-02 | Preserve column types, keys, relationships, and constraints from the data dictionary/schema. | PARTIAL | [schema.sql](../Backend/database/schema.sql); [loader.py](../Backend/database/loader.py), `parse_schema` | Live read-only comparison matched column types/nullability, 16 primary keys, 23 foreign-key relationships, 8 unique constraints, and all 66 named/validated CHECK constraints. All 23 FK relationships had zero orphans. | Exact live CHECK-expression text was not compared: the existing comparator creates and drops temporary tables, which was not used in this read-only audit. Compare expressions using a read-only-safe method if exact parity evidence is required. |
| DATA-01 | Generate master data before dependent records. | YES | [master_generator.py](../Backend/data_generation/master_generator.py), `generate_master_data`; [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `generate_replenishment_data` | The temporary end-to-end test-profile generation completed and passed CSV preflight; dependent tables had valid parent keys. | None identified. |
| DATA-02 | Use deterministic IDs and a fixed random seed. | YES | [config.py](../config.py), `RANDOM_SEED`; generator modules | `test_generation_is_reproducible` tests exist for master, sales, inventory, and forecasts. Two complete temporary runs matched row counts, primary keys, and all 19 CSV SHA-256 hashes. | Checksums are not emitted as a product artifact; see optional export checks. |
| DATA-03 | Generate realistic synthetic demand with seasonality and promotions. | PARTIAL | [sales_generator.py](../Backend/data_generation/sales_generator.py), `_simulate_demand` and `_build_sales_records` | The generator applies weekday and annual seasonal factors and a promotion multiplier; the existing dataset has 323 promotion rows. | “Realistic” is not calibrated or compared against an external demand baseline. For this interview-scale synthetic dataset, the seasonal/promotion mechanisms are present and observable; do not claim empirical realism. |
| DATA-04 | Record stockouts separately from genuine zero demand. | YES | [sales_generator.py](../Backend/data_generation/sales_generator.py), `_build_sales_records`; `GroundTruthDemand` | `test_test_profile_has_genuine_zero_demand_days` and `test_test_profile_has_stockout_censored_and_zero_sales_stockouts`; data contains 785 stockout-impacted records, 71 zero-sales stockouts, and 271 genuine zero-demand records. | None identified. |
| DATA-05 | Keep actual demand in `GroundTruthDemand`, isolated from forecast inputs. | YES | [sales_generator.py](../Backend/data_generation/sales_generator.py); [forecast_engine.py](../Backend/forecasting/forecast_engine.py), `generate_forecast_data`; [forecast_evaluator.py](../Backend/evaluation/forecast_evaluator.py), `evaluate_forecasts` | `test_test_profile_contains_promotions_and_no_ground_truth_leakage`, `test_forecast_and_store_evaluation_inputs_remain_separated`, and evaluator tests passed. Sales history has no actual-demand fields; evaluation joins truth after forecast creation. | None identified. |
| DATA-06 | Generate valid supplier MOQ, pack sizes, and lead times. | YES | [master_generator.py](../Backend/data_generation/master_generator.py), `_create_supplier_skus`; [inventory_generator.py](../Backend/data_generation/inventory_generator.py), `_build_lead_time_observations` | `test_generated_relationships_and_constraints` and `test_lead_time_observations_and_reorder_policies_are_valid`; 15 supplier-SKU rows and 15 lead-time observations were generated. | None identified. |
| DATA-07 | Generate labelled fixtures for the five required anomaly scenarios. | YES | [anomaly_detector.py](../Backend/validation/anomaly_detector.py), `run_anomaly_validation` | `test_all_required_anomalies_are_detected` and `test_anomaly_outputs_match_frozen_schema_and_id_formats`; the runner generated all five fixture types with PASS. | The fixtures are controlled test scenarios, not ongoing monitoring or live incidents. |
| DATA-08 | Validate primary/foreign keys, dates, enums, and business rules. | YES | [loader.py](../Backend/database/loader.py), `preflight_dataset`; generation validators | `test_test_profile_preflight_accepts_empty_tables_and_checks_all_rows`; actual preflight of `data/generated/` returned `valid=True`, no issues, and passed profile checks. | None identified for the schema rules exercised by preflight. |
| DATA-09 | Support the configured development profile of 250 SKUs, 20 stores, and 365 days. | PARTIAL | [config.py](../config.py), `PROFILES`; master, sales, and inventory generators | The `dev` profile is configured for 250 SKUs, 20 stores, 30 suppliers; the 365-day window is configured. The audit did not generate that profile. | The full replenishment pipeline and anomaly runner explicitly restrict generation to `test`. Verify/enable a complete `dev` pipeline only if the 250/20 development workflow is expected to run end-to-end. |
| DATA-11 | Export generated data to CSV. | YES | `export_*_data` functions in the data-generation, forecasting, replenishment, evaluation, and validation modules | CSV export tests passed. Temporary full-profile runs emitted schema-aligned table CSVs and the metrics/anomaly export CSVs. | None for the required CSV format. |
| DATA-12 | Generate the configured SKU-store relationship matrix and dependent demand. | YES | [master_generator.py](../Backend/data_generation/master_generator.py), `_create_store_skus`; [sales_generator.py](../Backend/data_generation/sales_generator.py), `_get_eligible_periods` | `test_generated_relationships_and_constraints` and sales lifecycle/FK tests passed. The generated profile contains 17 eligible pairs out of 30 possible SKU-store combinations; the matrix is assortment-based, not a full Cartesian product. | None identified; the requirement does not require every SKU to be carried at every store. |
| DATA-13 | Use deterministic or database-generated identifiers rather than hardcoded IDs. | YES | Generator ID construction in [master_generator.py](../Backend/data_generation/master_generator.py), [sales_generator.py](../Backend/data_generation/sales_generator.py), and downstream generators; [inventory_service.py](../Backend/services/inventory_service.py), event ID generation | Generator tests verify key formats, uniqueness, and reproducibility. Inventory service tests exercise deterministic event IDs and collision retries. | No hardcoded business record IDs were identified in the generation/save paths inspected. |

## Forecasting

| ID | Original requirement | Implemented? | Source and function | Test and execution evidence | Gap or recommended action |
|---|---|---|---|---|---|
| FC-01 | Begin with simple, explainable statistical forecasting methods. | YES | [forecast_engine.py](../Backend/forecasting/forecast_engine.py), `predict_daily_demand` | `test_weekday_seasonal_forecast_uses_matching_weekday_average` and the baseline tests exercise `BASELINE_7D` and `WEEKDAY_SEASONAL_28D`. | The methods are simple statistical baselines, not advanced AI; the application should continue describing them that way. |
| FC-02 | Use chronological train/test or holdout evaluation. | YES | [forecast_evaluator.py](../Backend/evaluation/forecast_evaluator.py), `get_holdout_origins` and `evaluate_forecasts` | `test_holdout_origins_are_seven_days_apart_and_end_at_reference` and `test_evaluation_uses_only_future_holdout_dates`; three chronological holdout origins were executed. | None identified. |
| FC-03 | Prevent future-data leakage. | YES | [forecast_engine.py](../Backend/forecasting/forecast_engine.py), `predict_daily_demand` and `generate_forecast_data` | `test_baseline_uses_only_previous_seven_sales_and_ignores_future_values`; the leakage anomaly included 14 future observations and verified origin cutoff plus rejection of a truth-contaminated input. | None identified for the tested forecast path. |
| FC-04 | Handle stockout-censored sales rather than treating them as zero demand. | YES | [forecast_engine.py](../Backend/forecasting/forecast_engine.py), stockout history policy in `predict_daily_demand` | `test_stockout_censoring_prefers_uncensored_history_and_excludes_zero_stockouts`; the stockout anomaly compared forecasts with and without a censored zero-sales record. | None identified. |
| FC-05 | Record forecast runs and their provenance. | YES | [schema.sql](../Backend/database/schema.sql), `ForecastRun` and `Forecast`; [forecast_engine.py](../Backend/forecasting/forecast_engine.py) | Generated runs include method, version, origin, horizon, seed, dataset version, and feature cutoff; the run/forecast schema and FK tests passed. | None identified. |
| FC-06 | Produce reproducible forecasts. | YES | [forecast_engine.py](../Backend/forecasting/forecast_engine.py), `generate_forecast_data` | `test_forecast_generation_is_deterministic`; two independent temporary end-to-end runs had identical forecast CSV checksums. | None identified for the fixed test profile and seed. |

## Replenishment

| ID | Original requirement | Implemented? | Source and function | Test and execution evidence | Gap or recommended action |
|---|---|---|---|---|---|
| RP-01 | Calculate inventory position. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), recommendation candidate construction | `test_recommendation_calculations_and_lifecycle_are_valid`; live Store Evaluation also produced an inventory position equal to the latest saved snapshot for the checked SKU. | None identified. |
| RP-02 | Calculate lead-time demand, safety stock, reorder point, and target stock. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `_build_recommendation_candidates` | `test_recommendation_calculations_and_lifecycle_are_valid` independently recomputes these values and validates the results. | None identified. |
| RP-03 | Respect minimum order quantities and pack sizes. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `_round_order_quantity` and `validate_replenishment_data` | `test_recommendation_calculations_and_lifecycle_are_valid`; the audit changed a generated order to 93 units with pack size 4 and the validator rejected it. | None identified. |
| RP-04 | Apply store capacity constraints and record exceptions instead of silently exceeding capacity. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `_allocate_store_capacity` | `test_capacity_allocation_blocks_complete_orders_in_urgency_order` exercises a blocked order and its reason. The actual generated run had 16 `WITHIN_CAPACITY` rows and no blocked rows. | The current generated profile does not itself contain a blocked order; the boundary behavior is test-executed. |
| RP-05 | Respect supplier eligibility and discontinued SKU lifecycle. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), supplier candidate filtering; [anomaly_detector.py](../Backend/validation/anomaly_detector.py), `_discontinued_sku_scenario` | Supplier selection/lifecycle tests passed; the anomaly marks an eligible SKU discontinued in an isolated copy and calls `create_recommendations`, which omits the pair. | None identified. |
| RP-06 | Reject negative supplier lead times. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), supplier-term validation | `test_validation_rejects_negative_supplier_lead_time`; the negative-lead-time anomaly changes a supplier lead time to -1 and observes a `ValueError`. | None identified. |
| RP-07 | Record exceptions and recommendation traceability. | YES | [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `create_recommendations`; [schema.sql](../Backend/database/schema.sql), `PurchaseRecommendation` and `ValidationIssue` | Missing supplier/policy and late-arrival tests verify issue records; recommendation tests verify run, supplier, and policy relationships. | None identified for tested conditions. |

## Evaluation

| ID | Original requirement | Implemented? | Source and function | Test and execution evidence | Gap or recommended action |
|---|---|---|---|---|---|
| EV-01 | Report MAE, RMSE, and WAPE against ground truth. | YES | [forecast_evaluator.py](../Backend/evaluation/forecast_evaluator.py), `calculate_forecast_metrics` and `evaluate_forecasts` | `test_mae_rmse_wape_and_bias_calculations`, evaluation export test, and two full temporary runs. Selected `BASELINE_7D`: MAE 1.589649, RMSE 2.067210, WAPE 43.722320%; `WEEKDAY_SEASONAL_28D`: 1.690064, 2.215173, 46.484183%. | Metrics are based on the configured small test profile, not a large or external dataset. |
| EV-02 | Report forecast bias. | YES | [forecast_evaluator.py](../Backend/evaluation/forecast_evaluator.py), `calculate_forecast_metrics` | Bias is included in the exported metrics and verified by `test_mae_rmse_wape_and_bias_calculations`; observed overall bias was -0.418658 for the selected method and -0.332109 for the seasonal method. | Bias is an additional dashboard/evaluation metric beyond the original minimum. |

## Mandatory anomaly scenarios

| ID | Original requirement | Implemented? | Source and function | Test and execution evidence | Gap or recommended action |
|---|---|---|---|---|---|
| AN-01 | Detect `STOCKOUT_AS_ZERO_DEMAND`. | YES | [anomaly_detector.py](../Backend/validation/anomaly_detector.py), `_stockout_scenario` | `test_all_required_anomalies_are_detected` and parametrized `test_each_anomaly_records_the_detected_result`; execution observed `stockout_flag=True`, zero sales, positive evaluation-only demand, and an unchanged forecast after removing the censored row. | Executed against a generated stockout case; truth was used only to confirm positive demand. |
| AN-02 | Detect `PACK_SIZE_IGNORED`. | YES | [anomaly_detector.py](../Backend/validation/anomaly_detector.py), `_pack_size_scenario`; [replenishment_engine.py](../Backend/replenishment/replenishment_engine.py), `validate_replenishment_data` | The stored scenario generated invalid quantity 93 for pack size 4, while normal output 92 met MOQ 12 and pack rules. An additional audit-only in-memory call to `validate_replenishment_data` rejected quantity 93. | The fixture's own detection is a remainder check; the audit separately exercised the actual replenishment validator on the malformed row. |
| AN-03 | Detect `DISCONTINUED_SKU`. | YES | [anomaly_detector.py](../Backend/validation/anomaly_detector.py), `_discontinued_sku_scenario` | The anomaly runner changed an isolated master-data copy and executed the replenishment engine; it reported that the recommendation was prevented. | None identified. |
| AN-04 | Detect `NEGATIVE_LEAD_TIME`. | YES | [anomaly_detector.py](../Backend/validation/anomaly_detector.py), `_negative_lead_time_scenario` | The anomaly runner injected `lead_time_days=-1` into an isolated copy and observed rejection by `create_recommendations`. | None identified. |
| AN-05 | Detect `FORECAST_LEAKAGE`. | YES | [anomaly_detector.py](../Backend/validation/anomaly_detector.py), `_forecast_leakage_scenario` | The anomaly runner included 14 future sales rows and a `GroundTruthDemand`-only field; the origin-cutoff forecast was unchanged and the contaminated input was rejected. | None identified for the tested path. |

All five anomaly fixture records in Supabase were read-only checked and had
`PASS` status. Their five corresponding `ValidationIssue` records were all
resolved. These are controlled validation scenarios, not unresolved operational
incidents.

## Optional scale recommendation

| ID | Requirement or suggestion | Status | Source/evidence | Classification |
|---|---|---|---|---|
| OPT-01 | Support a profile larger than the configured 250-SKU/20-store development profile; 2,000 SKUs × 100 stores × 365 days was suggested. | PARTIAL, OPTIONAL | [config.py](../config.py) defines test and 250/20 development profiles; no larger profile was generated. The user's clarification explicitly says this scale is suggested, not mandatory. | Not counted in the 42 mandatory requirements; not a compliance failure or blocker. |

## Supplemental integration and presentation checks

These are later-phase project expectations, not counted in the 42 original
functional requirements above.

| Check | Result | Evidence |
|---|---|---|
| Live database tables, constraints, FKs, row counts, and inventory consistency | YES, read-only | Supabase contained exactly 16 project base tables. Live columns/types/nullability, 16 PKs, 23 FKs, 8 unique constraints, and 66 named/validated CHECK constraints matched the schema; exact CHECK expressions were not compared. All FK orphan counts were zero. See [test execution report](test_execution_report.md). |
| Current persisted inventory reaches Store Evaluation | YES, read-only | The additional live inventory event was an `ADJUSTMENT_IN` of 5 units on 2026-11-11. The corresponding latest snapshot was on hand 29; a read-only Store Evaluation produced inventory position 29. |
| Read-only and parameterized dashboard data access | YES | [data_access.py](../Backend/dashboard/data_access.py), `_read_only_connection` and filtered query functions; `test_dashboard_connection_uses_read_only_transaction_and_closes`, `test_recommendation_filters_are_parameterized`, and `test_store_evaluation_queries_are_parameterized_and_read_only`. |
| Dashboard page rendering | YES, AppTest | `test_all_seven_dashboard_pages_render_without_data_access_writes` loads seven current pages without exceptions. This is six core dashboard areas plus the later Store Evaluation page. |
| Inventory Preview/Save | YES, unit-test and user-reported manual evidence | Preview is in-memory; Save is transactional and appends `InventoryEvent` plus a current-day `InventorySnapshot`. Inventory service tests cover idempotency, rollback, invalid requests, and capacity. The user reported manual Save and Store Evaluation confirmation; this audit independently verified the persisted rows read-only. |
| Live database loader idempotency | Not re-executed in this audit | Loader unit tests use a fake PostgreSQL connection for idempotent repeat, conflict rollback, and dry-run rollback. No loader write was performed because this audit was read-only. The existing five anomaly rows and five validation issues were present in Supabase. |
| Agreed technology stack | YES | `requirements.txt` and the application use Python, Streamlit, PostgreSQL/psycopg, pandas, NumPy, pytest, SQL, and Plotly. No additional application framework was found. |

## Counts and compliance summary

- **42 mandatory requirements:** 39 `YES`, 3 `PARTIAL`, 0 `NO`.
- The three partial items are exact live CHECK-expression comparison
  (SCH-02), empirical calibration of synthetic realism (DATA-03), and full
  end-to-end support for the configured `dev` profile (DATA-09).
- The 2,000 × 100 scale is optional and is not included in the mandatory
  requirement count.
- No mandatory requirement was classified `NO`.

