# StockLens test execution report

**Audit date:** 2026-11-12  
**Audit mode:** Read-only for repository data and Supabase. No application code,
generated dataset, schema, or database record was modified.

## Automated test suite

The existing full suite was run during this audit:

```text
python -m pytest -q
113 passed in 153.12s
```

The suite includes generation, data validation, forecasting, replenishment,
evaluation, database loader, anomaly, dashboard data-access, Store Evaluation,
inventory simulation, and inventory Save tests. In particular,
`test_all_seven_dashboard_pages_render_without_data_access_writes` uses
Streamlit AppTest to load each current page without exceptions. The app currently
has seven pages: six core dashboard areas and the later Store Evaluation page.

The current tests do not constitute a live database write test. Loader
idempotency and rollback tests use a fake PostgreSQL connection; this audit did
not perform any database writes.

## Requirement count reconciliation

The earlier 38/41 tally omitted `DATA-13`, the original requirement to avoid
hardcoded IDs where deterministic or database-generated IDs are required.
The final matrix retains all 41 earlier rows and adds this satisfied
requirement: **39/42 fully satisfied, 3 partial, 0 missing**. This is the
authoritative final tally.

## Existing generated data and preflight

`preflight_dataset(data/generated, verify_test_profile=True)` was run against
the existing files. It returned `valid=True`, no issues, and passed the
test-profile SKU/store/supplier and ForecastRun seed/version/reference-date
checks.

| Logical table | Existing generated CSV rows |
|---|---:|
| SKU | 10 |
| Store | 3 |
| Supplier | 5 |
| StoreSKU | 17 |
| SupplierSKU | 15 |
| SalesHistory | 4,805 |
| InventorySnapshot | 172 |
| InventoryEvent | 7,687 |
| LeadTimeObservation | 15 |
| ReorderPolicy | 17 |
| ForecastRun | 8 |
| Forecast | 1,298 |
| PurchaseRecommendation | 16 |
| GroundTruthDemand | 4,805 |
| AnomalyFixture | 0 |
| ValidationIssue | 0 |
| **Total** | **18,873** |

The five anomaly fixtures and five corresponding validation issues are separate
CSV exports in `data/exports/`; they are not included in the 18,873-row
`data/generated/` count. The evaluation export contains eight rows (six
holdout-origin rows and two overall method rows).

### Representative data coverage

Observed in the existing test-profile CSVs:

- Configuration: seed `20261022`, reference date `2026-10-22`, 365 calendar
  demand dates; 10 SKUs, 3 stores, and 5 suppliers in the generated test data.
- SKU lifecycle: 8 `ACTIVE`, 1 `LAUNCHED`, and 1 `DISCONTINUED`.
- Assortment: 17 eligible SKU-store relationships out of 30 possible pairs.
- Promotions: 323 rows; stockouts: 785 rows, including 71 zero-sales stockouts.
- Genuine zero-demand rows: 271. Thirteen of 17 SKU-store series had at least
  one genuine zero-demand day. Positive-demand-day coverage ranged from 71.78%
  to 100%; the generator does not define a separate named intermittent-demand
  mode.
- Lead-time observations: 15; 7 `SUPPLIER_DELAY`, 7 `EARLY_DELIVERY`, and
  1 `NORMAL`; observed lead times ranged from 1 to 28 days.
- Inventory events: 7,687 (`SALE` 4,463, `RECEIPT` 2,874,
  `ADJUSTMENT_OUT` 350). The generated snapshots reconciled to their event
  ledger with zero mismatches.
- Replenishment output: 16 rows; 15 positive quantities and one zero quantity.
  All 16 were `WITHIN_CAPACITY`; the generated sample had no blocked row.

The generator implements weekday and annual seasonal factors and a promotion
multiplier. The sample demonstrates promotions, genuine zeros, stockouts,
supplier delays, a launch, and a discontinued SKU. It is not calibrated against
external retail data, and the small sample should not be described as empirical
validation of realism.

## Reproducibility and exports

Two complete test-profile packages were generated in separate temporary
directories. Each included all 16 logical table CSVs, evaluation metrics, and
the dedicated anomaly exports. Each temporary table set passed schema preflight.

| Comparison | Result |
|---|---|
| Total logical-table rows per run | 18,883 (18,873 operational rows plus 5 anomaly fixtures and 5 validation issues) |
| Per-table row counts | Identical |
| Primary keys across all 16 tables | Identical; no duplicate keys |
| CSV files hashed | 19 per run |
| SHA-256 checksums | All 19 matched |
| Temporary directory cleanup | Completed automatically |
| `data/generated/` or Supabase writes | None |

CSV generation and export are supported and tested. JSON export, SQL seed
export, and a source manifest/checksum artifact are not provided by the project.
The SHA-256 comparison above was performed only as an audit check.

## Forecast evaluation execution

The temporary test-profile evaluation selected `BASELINE_7D` by pooled holdout
WAPE. Each method had 313 holdout predictions.

| Method | MAE | RMSE | WAPE | Bias | Selected |
|---|---:|---:|---:|---:|---|
| BASELINE_7D | 1.589649 | 2.067210 | 43.722320% | -0.418658 | Yes |
| WEEKDAY_SEASONAL_28D | 1.690064 | 2.215173 | 46.484183% | -0.332109 | No |

Tests verified the three chronological holdout origins, future target dates,
the feature cutoff, stockout censoring, and separation of `GroundTruthDemand`
from forecast inputs. The values above are for the small configured test
profile and are not performance guarantees for other data.

## Mandatory anomaly execution

`run_anomaly_validation("test")` was run and generated five PASS fixtures and
five resolved validation issues. The anomaly tests also verified schema,
deterministic output, and that running the scenarios did not change the clean
generated CSVs.

| Scenario | Injected/tested condition | Observed behavior | Execution status |
|---|---|---|---|
| STOCKOUT_AS_ZERO_DEMAND | Zero units sold with `stockout_flag=True`; evaluation-only actual demand was 3. | The prediction was unchanged when the censored zero was removed from uncensored history. | Executed by `_stockout_scenario`; PASS. |
| PACK_SIZE_IGNORED | Deliberately malformed order quantity 93 with pack size 4 and MOQ 12. | The fixture detected remainder 1; regular generated quantity 92 was MOQ/pack compliant. An audit-only in-memory call to `validate_replenishment_data` rejected the malformed 93-unit order. | Scenario executed and validator separately exercised; PASS. |
| DISCONTINUED_SKU | Marked a previously eligible SKU discontinued on the reference date in an isolated copy. | `create_recommendations` omitted the SKU-store pair. | Executed by `_discontinued_sku_scenario`; PASS. |
| NEGATIVE_LEAD_TIME | Set a supplier lead time to -1 in an isolated copy. | `create_recommendations` rejected it with a nonnegative-lead-time `ValueError`. | Executed by `_negative_lead_time_scenario`; PASS. |
| FORECAST_LEAKAGE | Supplied 14 future-dated sales rows and a `GroundTruthDemand`-only field. | Forecast stayed unchanged after origin cutoff; contaminated input was rejected. | Executed by `_forecast_leakage_scenario`; PASS. |

The five fixture records and five resolved issue records were also confirmed in
Supabase with read-only SELECT queries.

## Read-only Supabase verification

All queries ran in transactions started with `SET TRANSACTION READ ONLY`. The
transactions were rolled back on close. No insert, update, delete, DDL, RLS
change, or policy change was performed.

### Schema and integrity

- Exactly 16 project base tables were present; no missing or extra base tables
  were found in the current schema.
- Column order/types/nullability matched the frozen schema.
- All 16 primary keys, 23 foreign keys, and 8 unique constraints matched.
- All 66 expected CHECK constraint names were present and validated. Exact
  CHECK-expression text was not compared because the repository's schema
  comparator normalizes expressions by creating and dropping temporary tables,
  which was not used in this read-only audit.
- All 23 foreign-key relationships were validated; aggregate orphan count was
  zero.
- For the latest inventory snapshot per 17 store/SKU pairs, event-ledger
  balances matched `on_hand` (0 mismatches).

### Current database row counts

| Logical table | Generated CSV baseline | Current Supabase |
|---|---:|---:|
| SKU | 10 | 10 |
| Store | 3 | 3 |
| Supplier | 5 | 5 |
| StoreSKU | 17 | 17 |
| SupplierSKU | 15 | 15 |
| SalesHistory | 4,805 | 4,805 |
| InventorySnapshot | 172 | 173 |
| InventoryEvent | 7,687 | 7,688 |
| LeadTimeObservation | 15 | 15 |
| ReorderPolicy | 17 | 17 |
| ForecastRun | 8 | 8 |
| Forecast | 1,298 | 1,298 |
| PurchaseRecommendation | 16 | 16 |
| GroundTruthDemand | 4,805 | 4,805 |
| AnomalyFixture | 0 | 5 |
| ValidationIssue | 0 | 5 |
| **Total** | **18,873** | **18,885** |

The 18,873 generated operational rows plus the five fixtures and five issues
make 18,883 rows. Supabase currently has two additional inventory rows: one
`ADJUSTMENT_IN` event of 5 units and one snapshot dated 2026-11-11. This is
consistent with the inventory Save workflow the user reported testing. A
read-only Store Evaluation using that saved SKU read the latest snapshot
(`on_hand=29`) and produced inventory position 29. The two rows were preserved;
the audit did not write them.

The 18,885 current total therefore does not mean the original generated
operational CSVs were overwritten: all table counts match their generated
baseline except the one saved inventory event and one saved inventory
snapshot, and the anomaly tables contain the five expected rows each.

## Limitations

- No browser screenshot review was performed in this audit. UI evidence is the
  passing Streamlit AppTest plus the user's prior report that the site and
  inventory Preview/Save workflow work manually.
- Live schema CHECK expressions were not compared; names and validation state
  were checked read-only.
- No live database write/idempotency test was run, as required by the
  read-only audit scope.
- No 2,000-SKU/100-store dataset was generated. That scale is optional under
  the user's clarification and is not a compliance failure.

