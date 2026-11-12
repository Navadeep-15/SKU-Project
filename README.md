# StockLens

**Inventory Intelligence**

SKU-level demand forecasting, inventory visibility, and replenishment decision
support.

## 1. Project Overview

StockLens is a seven-page Streamlit application backed by PostgreSQL. It brings
together synthetic product, store, supplier, sales, inventory, forecast,
replenishment, evaluation, and controlled validation data. The repository
contains the frozen 16-table schema, an accepted test-profile dataset, automated
tests, and supporting documentation.

The application reads operational tables from PostgreSQL. Inventory **Preview**
is an in-memory calculation; the explicit **Save** workflow writes an inventory
event and the current-day inventory snapshot.

## 2. Business Problem

Retail teams need to estimate demand for each SKU at each store, see whether
inventory is likely to cover supplier lead time, and decide what to order
without violating supplier or store constraints. StockLens demonstrates this
workflow with traceable forecasts, recommendations, exceptions, and
ground-truth evaluation.

## 3. Features

- SKU, store, supplier, assortment, sales, inventory, and lead-time views.
- Two explainable forecast methods and chronological holdout evaluation.
- Replenishment recommendations with supplier MOQ, pack-size, lead-time, and
  store-capacity checks.
- Explicit inventory Preview and transactional Save.
- Five controlled anomaly validation scenarios.
- MAE, RMSE, WAPE, and bias evaluation, plus CSV downloads.
- Store-specific chronological evaluation using the latest persisted
  inventory snapshot.

## 4. Technology Stack

- Python, pandas, NumPy
- Streamlit and Plotly
- PostgreSQL, including PostgreSQL-compatible Supabase databases
- psycopg 3 and python-dotenv
- pytest

Python is used across generation, forecasting, replenishment, validation, and
the application so those workflows share the same data structures and
libraries. Streamlit provides a small Python-native interface for this
interview-scale application. PostgreSQL represents the relational entities and
enforces the frozen keys, relationships, and business constraints. Supabase is
an optional hosted PostgreSQL service; a local PostgreSQL database also works.
These are project-fit explanations, not recovered meeting notes.

## 5. Architecture and Project Structure

```text
Backend/
  dashboard/       Read-only dashboard data access
  data_generation/ Synthetic master, sales, and inventory generation
  database/        Connection, frozen SQL schema, and dataset loader
  evaluation/      Forecast holdout metrics and method selection
  forecasting/     Forecast generation
  replenishment/   Purchase recommendations and constraints
  services/        Inventory Preview/Save and Store Evaluation workflows
  validation/      Controlled anomaly scenarios
Frontend/
  app.py           Seven-page Streamlit application
  .streamlit/      Streamlit theme configuration
data/
  generated/       Committed test-profile rows for the 16 tables
  exports/         Evaluation metrics and five anomaly fixtures/issues
docs/              Data dictionary, audits, testing notes, and AI disclosure
tests/              Automated unit and Streamlit AppTest coverage
```

The schema is defined in
[`Backend/database/schema.sql`](Backend/database/schema.sql). The schema-aware
CSV preflight, transactional loader, and database verification are in
[`Backend/database/loader.py`](Backend/database/loader.py).

## 6. Prerequisites

- Python 3.11 or a compatible version supported by the installed dependencies.
- PostgreSQL, or a separate PostgreSQL database hosted by Supabase.
- PostgreSQL client tools (`psql`) to apply the schema from the command line.
- A new, empty application database/schema for initial setup.

The schema script creates the tables and triggers without `IF NOT EXISTS`.
Apply it only to an empty target, not to an existing StockLens or personal
database. The script also requests the PostgreSQL `btree_gist` extension.

## 7. Clone Repository

Windows PowerShell:

```powershell
git clone https://github.com/Navadeep-15/SKU-Project.git
Set-Location SKU-Project
```

macOS/Linux:

```bash
git clone https://github.com/Navadeep-15/SKU-Project.git
cd SKU-Project
```

## 8. Create Python Virtual Environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

If PowerShell blocks activation, use the Python executable in `.venv` directly
or follow the machine's approved PowerShell execution policy. Do not change
system policy just for this project.

## 9. Install Dependencies

Run from the repository root.

Windows PowerShell:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS/Linux:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The declared packages are listed in [`requirements.txt`](requirements.txt).
`psql` is a PostgreSQL client tool and is not installed by this Python
requirements file.

## 10. Configure Environment Variables

The database connection uses `DATABASE_URL`. The committed
[`.env.example`](.env.example) contains placeholders only.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

macOS/Linux:

```bash
cp .env.example .env
${EDITOR:-vi} .env
```

Replace the placeholder URL with the connection string for **your own new
database**. For Supabase, use its PostgreSQL connection details and SSL
requirement, for example the structure
`postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require`. This is a
format example, not a working credential. URL-encode reserved characters in
usernames or passwords as required by PostgreSQL URL syntax. For local
PostgreSQL, remove `?sslmode=require` unless the local server is configured for
SSL.

Keep `.env` local. It is ignored by Git. Never paste the connection string into
source code, a public issue, screenshots, or chat. `python-dotenv` loads the
root `.env` for Python database utilities; environment variables take
precedence. Streamlit deployment secrets are not required for local evaluation.

## 11. Set Up PostgreSQL or Supabase

Use either:

- A local PostgreSQL server and a newly created empty database, or
- A new/separate Supabase PostgreSQL project/database that you control.

Do not use the project author's Supabase credentials or point setup commands at
someone else's database. A PostgreSQL role with permission to create the
extension, tables, functions, triggers, and indexes is needed for schema
initialization. Use an appropriately authorized database role for subsequent
loading and verification.

Create a local database, if needed:

```powershell
createdb -U postgres stocklens
```

The equivalent command is available in macOS/Linux terminals when PostgreSQL
client tools are installed:

```bash
createdb -U postgres stocklens
```

For Supabase, provision a separate project/database through Supabase and use
its connection details. Do not run the schema against an existing application
database.

## 12. Create Database Schema

Apply the committed schema to the empty target. The following commands prompt
for the database password rather than putting it in the command line.

Local PostgreSQL, Windows PowerShell:

```powershell
psql -h localhost -p 5432 -U postgres -d stocklens -W -v ON_ERROR_STOP=1 -f Backend/database/schema.sql
```

Local PostgreSQL, macOS/Linux:

```bash
psql -h localhost -p 5432 -U postgres -d stocklens -W -v ON_ERROR_STOP=1 -f Backend/database/schema.sql
```

For a Supabase target, use the host, port, user, and database from your own
project; set `PGSSLMODE=require` for the `psql` process if required by that
connection:

```powershell
$env:PGSSLMODE = "require"
psql -h "<your-host>" -p 5432 -U "<your-user>" -d "<your-database>" -W -v ON_ERROR_STOP=1 -f Backend/database/schema.sql
```

```bash
PGSSLMODE=require psql -h "<your-host>" -p 5432 -U "<your-user>" -d "<your-database>" -W -v ON_ERROR_STOP=1 -f Backend/database/schema.sql
```

The schema is frozen at 16 logical tables. The command above applies the
existing SQL file; it does not create or alter any additional project tables.
If schema application fails, stop and inspect the error rather than repeatedly
rerunning a partially applied script.

## 13. Load Synthetic Dataset

The committed dataset is loaded as-is; normal setup does not regenerate it.
The loader preflights all 16 generated CSVs and adds the separate five-row
`AnomalyFixture` and five-row `ValidationIssue` exports. The expected baseline
is 18,883 rows total.

First perform the offline preflight:

```powershell
python -m Backend.database.loader --mode preflight
```

Then, only after confirming `DATABASE_URL` points to your newly initialized
target, load the data in one transaction:

```powershell
python -m Backend.database.loader --mode load --confirm-commit
```

The Python loader reads `DATABASE_URL` from the process environment or root
`.env`. The same commands work in macOS/Linux terminals. `--confirm-commit` is
required because this mode permanently writes rows. Inserts are ordered by
foreign-key dependencies. Repeating the load skips rows that are identical and
fails with transaction rollback if an existing primary key has different data.
For a clean first setup, use an empty schema.

The existing files in `data/generated/` contain 18,873 rows; the two anomaly
exports contribute the remaining ten. The zero-row anomaly files in
`data/generated/` are not regenerated or overwritten by setup.

## 14. Verify Database Setup

After loading the new target, run:

```powershell
python -m Backend.database.loader --mode verify
```

This checks the frozen schema, exactly 16 base tables, and per-table row counts
against the committed dataset. It uses `DATABASE_URL`, performs no persistent
data writes, and rolls back its verification transaction. It is a baseline
check for the freshly loaded dataset; later Inventory Save activity changes
inventory table counts, so verify before changing inventory.

The simpler connectivity check is also available:

```powershell
python -m Backend.database.test_db_connection
```

It runs `SELECT 1`; it does not verify the schema or dataset counts.

## 15. Run Streamlit Application

From the repository root:

```powershell
python -m streamlit run Frontend/app.py
```

macOS/Linux:

```bash
python -m streamlit run Frontend/app.py
```

Open the local URL printed by Streamlit. The database must be reachable and
contain the StockLens schema and data. A database connection failure is
reported in the application; do not expose `DATABASE_URL` in the UI or logs.

## 16. Application Pages and How to Test Them

1. **Operations Overview** — review the configured forecast method, accuracy,
   recommendations, and validation summary.
2. **Demand Forecasting** — select a store/SKU and compare historical sales
   with model forecasts.
3. **Replenishment Recommendations** — filter recommendations and inspect
   inventory position, order constraints, capacity status, and explanations.
4. **Inventory & Suppliers** — review snapshots, supplier terms, and inventory
   events. Preview an adjustment before saving. Save writes to the configured
   database, so use only a database you control.
5. **Validation Scenarios** — inspect the five controlled anomaly fixtures and
   corresponding validation issues. These are test scenarios, not live
   operational alerts.
6. **Forecast Evaluation & Exports** — compare the stored metrics and download
   forecasts, recommendations, anomaly results, and evaluation data.
7. **Store Evaluation** — select a store/product subset and inspect chronological
   holdouts and replenishment using the latest saved inventory snapshot.

The Streamlit AppTest suite loads all seven pages without requiring a live
database. Interactive database workflows require the evaluator's configured
PostgreSQL database.

## 17. Run Automated Tests

Run all repository tests:

```powershell
python -m pytest -q
```

Focused suites:

```powershell
# Forecast generation and evaluation
python -m pytest -q tests/test_forecast_engine.py tests/test_forecast_evaluator.py

# Replenishment
python -m pytest -q tests/test_replenishment_engine.py

# Database loader and dashboard database access
python -m pytest -q tests/test_database_loader.py tests/test_dashboard_data_access.py

# Five anomaly scenarios
python -m pytest -q tests/test_anomaly_detector.py
```

These are the test paths configured by `pytest.ini`. Tests use generated
in-memory/test-profile inputs and mocked database connections where applicable;
they do not require or modify the evaluator's live database.

## 18. Run Five Mandatory Anomaly Scenarios

Run the anomaly scenario suite:

```powershell
python -m pytest -q tests/test_anomaly_detector.py
```

The tests call `run_anomaly_validation("test")`, which executes the
scenario-specific checks and verifies the generated results and output
contracts:

1. `STOCKOUT_AS_ZERO_DEMAND` — checks that a stockout-censored zero is not
   treated as ordinary zero demand.
2. `PACK_SIZE_IGNORED` — injects an invalid order quantity and checks that the
   MOQ/pack-size validator rejects it while the generated order remains valid.
3. `DISCONTINUED_SKU` — checks that replenishment omits a discontinued
   SKU/store pair.
4. `NEGATIVE_LEAD_TIME` — checks that a negative supplier lead time is rejected.
5. `FORECAST_LEAKAGE` — checks forecast-origin cutoff and rejection of
   `GroundTruthDemand`-only fields from forecast inputs.

The validated PASS fixtures and resolved issue records are committed separately
in `data/exports/` and are included when loading the database.

## 19. Forecasting and Replenishment Logic

### Forecasts and evaluation

- `BASELINE_7D` uses recent observed sales from the previous seven days.
- `WEEKDAY_SEASONAL_28D` uses recent observed sales from the previous 28 days
  and prefers matching weekdays when there is enough history.
- The pair makes a readable comparison between a recent-level baseline and a
  weekday-aware baseline without adding model infrastructure.
- Both methods use only `SalesHistory` up to the forecast origin. Forecast
  generation rejects ground-truth-only fields. Stockout-censored zero sales are
  excluded when there are enough uncensored observations; sparse-history
  fallbacks are identified in forecast metadata.
- Method selection uses pooled chronological holdout WAPE; ties are broken by
  lower MAE and then alphabetic method name.
- MAE, RMSE, WAPE, and bias are calculated against `GroundTruthDemand` only
  after forecasts are produced. WAPE is undefined when total actual demand is
  zero.

### Replenishment decisions

- Inventory position is on-hand plus on-order, less reserved and backordered
  units.
- Lead-time demand is summed from forecast rows over the supplier's configured
  lead-time horizon. The reorder point is lead-time demand plus policy safety
  stock.
- Target stock is forecast demand over lead time plus review period, plus safety
  stock. A positive order is considered when inventory position is below the
  reorder point and target stock exceeds inventory position.
- The order gap is rounded upward to a supplier pack-size multiple and must be
  at least the MOQ.
- Store capacity allocation accounts for projected on-hand and on-order
  inventory, then processes positive candidates by urgency. An order that does
  not fit is blocked and recorded rather than silently reduced.
- Only active SKU/store relationships and eligible, non-discontinued products
  are considered. Supplier terms must be eligible, and negative lead times are
  rejected.
- `ForecastRun`, `Forecast`, and `PurchaseRecommendation` identifiers and
  foreign keys retain run provenance. `InventoryEvent` records persisted
  adjustments separately from snapshots.

These are simple statistical baselines and rule-based replenishment decisions;
the project does not claim advanced AI or guaranteed business performance.

## 20. Assumptions and Design Decisions

- The committed test profile has 10 SKUs, 3 stores, 5 suppliers, and a
  365-day sales history; the configured seed is `20261022`.
- `config.py` also defines a 250-SKU/20-store development profile, but the
  replenishment pipeline and anomaly runner currently restrict generation to
  the test profile. The larger profile is not needed for this evaluator setup.
- Synthetic data is deterministic and is committed to make setup repeatable.
  The dataset is not calibrated to a real retailer.
- Ground truth is held apart from forecast features and is used for evaluation.
- Supplier lead time in the replenishment calculation comes from the eligible
  `SupplierSKU` record; `LeadTimeObservation` is stored as data but is not used
  as a live learned lead-time estimator by this calculation.
- PostgreSQL stores the relational dataset and enforces the frozen constraints;
  Streamlit/Python keeps the demo workflows visible and straightforward.
- The loader is deliberately idempotent for identical primary-key rows, but
  schema creation is intended for a new empty database.

## 21. Limitations

- Demand is synthetic; it does not establish accuracy on real retailer data.
- The development profile is not supported end-to-end by replenishment and
  anomaly generation.
- The database loader and verification are unit-tested with mocked connections,
  but fresh PostgreSQL initialization and live loading were not run in this
  environment.
- Database access and interactive Save depend on the evaluator's own
  PostgreSQL configuration and permissions.
- Database verification compares exact baseline row counts. Run it immediately
  after loading, before using Inventory Save or otherwise changing rows.
- This repository does not include deployment instructions or a cloud
  deployment; deployment is not required for evaluation.

## 22. AI Assistance Disclosure

AI assistance was used extensively during planning, implementation, debugging,
testing, and documentation. The project owner's contribution statement and the
available prompt excerpts, including clearly identified gaps in the prompt
record, are in
[`docs/AI_USAGE_AND_PROMPT_HISTORY.md`](docs/AI_USAGE_AND_PROMPT_HISTORY.md).

## 23. Troubleshooting

- **`DATABASE_URL is not set`:** create a root `.env` from `.env.example`, or
  set `DATABASE_URL` in the process environment. Never publish the value.
- **Connection timeout/refused:** check that your own database is running,
  reachable, and that its host, port, SSL mode, and network allow-list are
  correct.
- **Schema table missing:** apply `Backend/database/schema.sql` to the intended
  empty target, then rerun the offline preflight and database load.
- **Extension permission error:** use a database role permitted to create
  `btree_gist`, or ask the owner of your new database to enable the supported
  extension. Do not alter the schema to bypass constraints.
- **Preflight fails:** do not load. Review the reported CSV/schema issue and
  restore the committed dataset rather than regenerating or editing it during
  evaluator setup.
- **Load reports conflicting primary-key data:** the target is not an empty
  baseline or contains different records. Stop and use a separate new database;
  do not delete or overwrite records to force a load.
- **`psql` is not recognized:** install PostgreSQL client tools or initialize
  the schema through the SQL interface of your own Supabase project. This
  project does not bundle `psql`.
- **Streamlit opens but has no data:** confirm the app process uses the same
  `DATABASE_URL` whose schema and data were verified.
- **PowerShell activation is blocked:** use `.venv\Scripts\python.exe -m pip`
  and `.venv\Scripts\python.exe -m streamlit ...`, or use the system-approved
  activation configuration.

## Supporting Documentation

- [Data Dictionary v1.0](docs/data_dictionary.md)
- [Implementation Compliance](docs/implementation_compliance.md)
- [Requirements Traceability Matrix](docs/requirements_traceability_matrix.md)
- [Test Execution Report](docs/test_execution_report.md)
- [Remaining Gaps](docs/remaining_gaps.md)
- [Manual Inventory Testing Guide](docs/manual_testing_guide.md)
- [AI Usage and Prompt History](docs/AI_USAGE_AND_PROMPT_HISTORY.md)
