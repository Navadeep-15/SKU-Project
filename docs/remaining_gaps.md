# StockLens remaining gaps and submission notes

**Audit date:** 2026-11-12  
**Audit mode:** Findings only. No application code, generated data, database
schema, or Supabase records were changed.

## Requirement count reconciliation

The earlier 38/41 tally omitted `DATA-13`, the original requirement to avoid
hardcoded IDs where deterministic or database-generated IDs are required.
That satisfied requirement has been added without removing any of the earlier
41 rows. The final count is **39/42 satisfied, 3 partial, 0 missing**; this
reconciled count is authoritative.

## Priority findings

### 1. End-to-end development-profile support is partial

`config.py` defines a development profile of 250 SKUs, 20 stores, and 30
suppliers, with a 365-day sales-history window. Master, sales, and inventory
generation accept that profile. However, the replenishment pipeline and
anomaly validation runner explicitly restrict generation to the `test`
profile. The audit did not generate the development profile.

**Assessment:** Partial support for the configured 250/20 development profile;
this is distinct from the optional 2,000/100 scale recommendation.  
**Suggested follow-up:** If the 250/20 profile must represent a complete
end-to-end workflow, review the profile restrictions and generation cost
before enabling it. This audit did not change them.

### 2. Synthetic “realism” is not externally calibrated

The demand generator includes weekday and annual seasonal factors and a
promotion multiplier. The existing generated test data has 323 promotion
rows, 271 genuine zero-demand records, and 785 stockout-impacted records.
However, no comparison to actual retail demand or calibration target is
provided.

There are zero-demand days in 13 of 17 SKU-store series, but positive-demand
coverage is 71.78%–100%. The code does not define a separate named
intermittent-demand process. This demonstrates true zeros but gives limited
evidence for strongly intermittent demand.

**Assessment:** Sufficient to demonstrate the synthetic workflows and
stockout/zero distinction; not evidence of empirical demand realism or broad
intermittent-demand coverage. This is a demo-quality limitation, not a failure
of a separately stated mandatory original requirement.

### 3. Exact live CHECK-expression parity remains unverified

Read-only Supabase checks matched the 16 tables, columns/types/nullability,
16 primary keys, 23 foreign keys, 8 unique constraints, and all 66 named and
validated CHECK constraints. Exact live CHECK-expression text was not
compared. The repository's existing comparator creates and drops temporary
tables to normalize expressions, so it was not used under the required
read-only audit.

**Suggested follow-up:** If exact expression parity is required, add or run a
read-only-safe catalog comparison. No database changes are recommended based
on the evidence collected.

### 4. Live write/idempotency was intentionally not retested

The database loader tests cover first insert, identical repeat, conflict
rollback, and dry-run rollback using a fake PostgreSQL connection. The audit
made no live writes. Supabase currently contains the expected five anomaly
fixtures and five resolved issues, but this read-only check does not itself
prove that a fresh live repeated insert would skip them.

**Assessment:** Not a submission blocker under the requested audit scope. The
prior Phase 8B integration was accepted in project history; do not rerun
insertion without separate authorization.

## Data and database interpretation

- The existing generated CSV baseline is 18,873 rows across 16 logical
  tables. `AnomalyFixture.csv` and `ValidationIssue.csv` in
  `data/generated/` each contain zero rows; their five rows each are in the
  dedicated anomaly exports.
- The integrated dataset with the five fixtures and five issues has 18,883
  logical rows.
- Supabase currently has 18,885 rows. Compared with the generated baseline,
  all tables match except for one additional `InventoryEvent` and one
  additional `InventorySnapshot`, consistent with the user's inventory Save
  test. The additional event is a 5-unit `ADJUSTMENT_IN` dated 2026-11-11.
- All 23 live FK relationships had zero orphan rows. Latest snapshots for 17
  store/SKU pairs reconciled to the event ledger with zero mismatches.
- A read-only Store Evaluation using the saved SKU read its latest snapshot
  (`on_hand=29`) and calculated inventory position 29.
- The application has a fixed `REFERENCE_DATE` of 2026-10-22 while the saved
  snapshot is dated 2026-11-11. Store Evaluation intentionally uses the latest
  persisted inventory with the configured forecast origin. Its generated
  forecast holdouts remain historical and are not changed by inventory
  updates, but the replenishment result should be understood as current
  inventory combined with the configured reference-date forecast, not as a
  strictly historical inventory backtest.

## Optional capabilities and scope clarifications

- **2,000 SKUs × 100 stores × 365 days:** Optional scalability enhancement per
  the user's clarification. It was not generated and is not a missing
  mandatory requirement or blocker.
- **JSON and SQL seed exports:** Not present. CSV exports, including
  `GroundTruthDemand`, are present and tested. JSON/SQL exports were requested
  as audit questions, not as original mandatory deliverables.
- **Source manifest and built-in checksums:** No manifest/checksum export is
  present. The audit computed SHA-256 externally for two temporary runs; all
  19 CSV files matched. Deterministic generation is tested, but checksums are
  not a persisted project artifact.
- **Validation summaries:** The project exports anomaly fixtures, validation
  issues, and evaluation metrics as separate CSVs; no single combined
  validation-summary export was found.
- **Anomaly detection scope:** The five PASS records are controlled,
  deterministic validation scenarios. They are not live production incidents
  or a continuous anomaly-monitoring service.
- **Browser verification:** AppTest covered all seven current pages. No
  browser screenshot automation was run during this audit; visual review
  remains based on the user's prior manual review.

## Documentation discrepancy

The existing [implementation compliance audit](implementation_compliance.md)
describes the inventory Save workflow as using “store/request locks.” The
current implementation and unit tests show a store-level advisory lock and an
inventory-event-ID advisory lock. No code change was made; update that wording
only in a separately authorized documentation pass.

## Overall disposition

The audit found **39 of 42 mandatory requirements fully satisfied**, **3
partially satisfied**, and **0 classified as missing**. The partial items are
the end-to-end development profile, empirical validation of synthetic
realism, and exact live CHECK-expression comparison. There are no
scale-related blockers under the user's clarification.

The full pytest suite passed (113 tests). Two independent temporary
test-profile generations matched row counts, primary keys, and all 19 CSV
SHA-256 checksums. Supabase was reachable and its read-only schema,
foreign-key, row-count, anomaly, inventory-ledger, and Store Evaluation checks
passed. No database writes were made during this audit.

