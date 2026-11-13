# StockLens Test Execution Report

## 1. Executive Validation Summary

**120 automated tests passed successfully.**

The recorded validation includes:

- All seven Streamlit pages passing automated AppTest checks.
- All five mandatory anomaly scenarios passing.
- Matching row counts, primary keys, and all 19 CSV checksums across two
  independent demonstration generations.
- Read-only Supabase verification of the database schema, relationships, and
  inventory-ledger integrity.
- Manual review of the running application, successful Inventory Preview and
  Save checks, and successful evaluator-account application access.

The following sections document the automated, database, and manual validation evidence.

## 2. Automated Test Results

The full test suite completed with:

```text
python -m pytest -q
120 passed in 168.10s
```

The suite covers data generation and validation, forecasting, replenishment,
evaluation, database loading, anomaly detection, dashboard data access, Store
Evaluation, inventory simulation, and inventory Save behavior.

Recorded focused test groups:

| Test group | Result |
|---|---:|
| Forecast generation and evaluation | 19 passed |
| Replenishment | 11 passed |
| Database loader and dashboard data access | 25 passed |
| Anomaly scenarios | 10 passed |

The offline dataset preflight also passed. It validated the 16 logical tables
and 18,883 expected integrated rows: 18,873 generated rows plus five anomaly
fixtures and five resolved validation issues. Preflight validates CSV and
schema compatibility without connecting to PostgreSQL.

## 3. Streamlit Application Validation

The automated test
`test_all_seven_dashboard_pages_render_without_data_access_writes` uses
Streamlit AppTest to load all seven pages without exceptions or database
writes. The app includes the six core dashboard areas and Store Evaluation.
Related AppTest coverage verifies that Preview does not persist data and that
Save invokes the persistence service.

## 4. Manual UI and Inventory Workflow Verification

I manually opened and reviewed the running application, successfully tested
Inventory Preview and Save, and confirmed application reads and inventory
operations using the restricted Supabase evaluator account. These hands-on
checks complement the automated and database verification results.

## 5. Supabase Database Integrity Verification

Read-only Supabase queries were run in transactions set to `READ ONLY` and
rolled back when complete. The verification made no database writes or schema
changes.

Checks confirmed:

- Exactly 16 project base tables, with column order, types, and nullability
  matching the frozen schema.
- 16 primary keys, 23 foreign keys, and 8 unique constraints matching the
  expected schema.
- All 66 expected CHECK constraint names present and validated.
- All 23 foreign-key relationships had zero orphan rows.
- Latest inventory snapshots for 17 store/SKU pairs reconciled to the event
  ledger with zero mismatches.

The integrated generated baseline is 18,883 rows. Supabase contained 18,885
rows: the same baseline plus one five-unit `ADJUSTMENT_IN` inventory event
dated 2026-11-11 and its snapshot, consistent with the reported Save workflow.
Read-only Store Evaluation read the saved snapshot (`on_hand=29`) and
calculated inventory position 29. The saved rows were preserved during
verification.

The 18,883-row integrated baseline consists of 18,873 rows in the committed
generated CSV set plus the five fixture rows and five resolved issue rows in
the dedicated anomaly exports.

## 6. Five Mandatory Anomaly Scenarios

`run_anomaly_validation("test")` generated five PASS fixtures and five
resolved validation issues. The automated tests also checked output schema,
deterministic results, and that scenario execution did not alter the clean
generated CSVs.

| Scenario | Condition tested | Verified behavior |
|---|---|---|
| `STOCKOUT_AS_ZERO_DEMAND` | Zero observed sales with a stockout flag | Censored zero sales are not treated as ordinary zero demand; removing the censored observation did not change the prediction. |
| `PACK_SIZE_IGNORED` | Malformed order quantity 93 with pack size 4 and MOQ 12 | The fixture detected a noncompliant quantity; an in-memory validator rejected it. Generated order quantities remained MOQ/pack compliant. |
| `DISCONTINUED_SKU` | Previously eligible SKU marked discontinued | Replenishment omitted the discontinued SKU/store pair. |
| `NEGATIVE_LEAD_TIME` | Supplier lead time set to -1 | Replenishment rejected the negative lead time. |
| `FORECAST_LEAKAGE` | Future-dated sales and a ground-truth-only field supplied | Forecast inputs respected the origin cutoff, and the contaminated input was rejected. |

The five fixture and five issue records were also confirmed in Supabase using
read-only queries.

## 7. Deterministic Data Reproducibility

Two complete demonstration packages were generated in separate temporary
directories. Each included all 16 logical table CSVs, evaluation metrics, and
the dedicated anomaly exports. Both packages passed schema preflight.

| Comparison | Result |
|---|---|
| Integrated logical-table rows per run | 18,883 |
| Per-table row counts | Identical |
| Primary keys across all 16 tables | Identical; no duplicate keys |
| CSV files compared | 19 per run |
| SHA-256 checksums | All 19 matched |
| Persistent generated data or Supabase writes | None |

The demonstration configuration uses seed `20261022`, reference date
`2026-10-22`, and 365 calendar demand dates. The generated CSV exports support deterministic comparison, with matching
SHA-256 checksums across both independent runs.

## 8. Forecast Evaluation Results

The demonstration chronological holdout evaluation selected `BASELINE_7D` by
pooled holdout WAPE. Each method had 313 holdout predictions.

| Method | MAE | RMSE | WAPE | Bias | Selected |
|---|---:|---:|---:|---:|---|
| `BASELINE_7D` | 1.589649 | 2.067210 | 43.722320% | -0.418658 | Yes |
| `WEEKDAY_SEASONAL_28D` | 1.690064 | 2.215173 | 46.484183% | -0.332109 | No |

Automated checks verified three chronological holdout origins, future target
dates, feature cutoff, stockout censoring, and separation of `GroundTruthDemand`
from forecast inputs. These results quantify forecast accuracy on the reproducible demonstration
dataset and provide a transparent basis for comparing the two methods.

## 9. Validation Conclusion

StockLens successfully completed the recorded automated validation suite with
**120 tests passed**. All seven Streamlit pages passed AppTest
checks; all five mandatory anomaly scenarios passed; and two independently
generated datasets produced identical primary keys, row counts, and 19 CSV
checksums. Read-only Supabase verification confirmed the expected schema,
relationships, and inventory-ledger consistency. I also completed manual Inventory Preview, Save, and evaluator-role checks.

The evidence establishes a repeatable, tested demonstration of the selected
SKU-location forecasting and replenishment workflow. The [README](../README.md) provides the complete evaluator setup and
demonstration walkthrough.
