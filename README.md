# StockLens

**Inventory Intelligence**

SKU-level demand forecasting, inventory visibility, and replenishment decision
support.

## Project Validation Highlights

- **120 automated tests passed successfully.**
- All seven Streamlit pages passed automated AppTest checks.
- All five mandatory anomaly scenarios passed.
- Two independent demonstration generations matched in row counts, primary
  keys, and all 19 CSV checksums.
- Read-only Supabase checks verified the schema, foreign-key relationships,
  and inventory-ledger reconciliation.
- I manually opened and reviewed the application,
  successfully testing Inventory Preview and Save, and testing application
  reads and inventory operations with the restricted Supabase evaluator
  account.

Automated test results, read-only database checks, and user-reported manual
verification are distinguished in the
[test execution report](docs/test_execution_report.md).

## Quick Start

For the hosted evaluation option, place the temporary database URL supplied
through a secure channel in your local `.env` before launching.

### Option A — Preloaded Supabase PostgreSQL (Recommended)

The evaluator setup uses a preloaded Supabase PostgreSQL database with the frozen
16-table schema and the synthetic dataset already loaded. Use this option for
the quickest evaluation; **do not create a schema or load data** when using
that database. The `.env.eval` file is the temporary evaluation
configuration template. The evaluator database role uses scoped permissions and row-level security. Option A requires no schema creation, data
regeneration, CSV preflight, loading, or database verification. 

Windows PowerShell:

```powershell
git clone https://github.com/Navadeep-15/SKU-Project.git
Set-Location SKU-Project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set DATABASE_URL in .env to the evaluation URL provided securely
python -m streamlit run Frontend/app.py
```

macOS/Linux:

```bash
git clone https://github.com/Navadeep-15/SKU-Project.git
cd SKU-Project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Set DATABASE_URL in .env to the evaluation URL provided securely
python -m streamlit run Frontend/app.py
```

Use the temporary evaluation database URL provided for review in `.env` to launch StockLens against the preloaded Supabase database. Keep `.env` local and ignored by Git.

### Option B — Local PostgreSQL (Backup)

Use this independent setup if you do not have access to the shared Supabase
database, or prefer to run your own database. Install PostgreSQL, configure
`DATABASE_URL` for the local database, and follow
[Option B: Local PostgreSQL Setup](#11-option-b-local-postgresql-backup-setup).
This option applies the schema and loads the committed CSV data into your own
empty database.

## 1. Project Overview

StockLens is a seven-page Streamlit application backed by PostgreSQL. It brings
together synthetic product, store, supplier, sales, inventory, forecast,
replenishment, evaluation, and controlled validation data. The repository
contains the frozen 16-table schema, an accepted demonstration dataset, automated
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
the hosted PostgreSQL service for the recommended evaluator setup; the README
also documents a local PostgreSQL alternative setup.

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
  generated/       Committed demonstration rows for the 16 tables
  exports/         Evaluation metrics and five anomaly fixtures/issues
docs/              Data dictionary, test reports, testing notes, and AI disclosure
tests/              Automated unit and Streamlit AppTest coverage
```

The schema is defined in
[`Backend/database/schema.sql`](Backend/database/schema.sql). The schema-aware
CSV preflight, transactional loader, and database verification are in
[`Backend/database/loader.py`](Backend/database/loader.py).

## 6. Prerequisites

- Python 3.11 or a compatible version supported by the installed dependencies.
- A `DATABASE_URL` for either the existing evaluation Supabase database
  (Option A) or your own PostgreSQL database (Option B).
- PostgreSQL and its client tools (`psql` and `createdb`) are required only for
  Option B.

The existing Supabase database is already initialized. The local schema script
creates tables and triggers without `IF NOT EXISTS`; apply it only to your own
new, empty database. It also requests the PostgreSQL `btree_gist` extension.

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

Both database options use `DATABASE_URL`. For Option A, copy `.env.example` to the ignored local `.env` and set
`DATABASE_URL` to the evaluation URL supplied securely. Configure the provided temporary evaluator URL before connecting. For Option B, use [`.env.example`](.env.example)
as the template for your own local PostgreSQL connection.

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

For Option A, populate the local `.env` with the temporary Supabase evaluation URL provided securely to the evaluator. For Option B, replace the
`.env.example` placeholder with your own local database URL. A Supabase URL
typically uses SSL, for example the structure
`postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require`. This is a
format example, not a working credential. URL-encode reserved characters in
usernames or passwords as required by PostgreSQL URL syntax. For local
PostgreSQL, remove `?sslmode=require` unless the local server is configured for
SSL.

Keep `.env` local; it is ignored by Git. Keep any real database credentials out of committed files and public Git history. `python-dotenv` loads the root `.env` for Python database
utilities; environment variables take precedence. Streamlit deployment secrets
are not required for local evaluation.

## 11. Option B: Local PostgreSQL Backup Setup

### Install PostgreSQL

For Windows, download and install PostgreSQL from the
[official PostgreSQL Windows downloads page](https://www.postgresql.org/download/windows/).
The installer includes the PostgreSQL server and command-line tools; ensure
`psql` and `createdb` are available in your terminal (or use their installed
full paths).

On macOS/Linux, install PostgreSQL and its client tools using the official
[PostgreSQL download page](https://www.postgresql.org/download/) or your
operating system's package instructions.

Create a new, empty local database. The command prompts for authentication as
configured by your local PostgreSQL installation:

Windows PowerShell:

```powershell
createdb -U postgres stocklens
```

macOS/Linux:

```bash
createdb -U postgres stocklens
```

Set the root `.env` `DATABASE_URL` to your own local database, for example:

```text
DATABASE_URL=postgresql://postgres:<YOUR_LOCAL_PASSWORD>@localhost:5432/stocklens
```

This is a placeholder format, not a working password. For local PostgreSQL,
omit `sslmode=require` unless your server is configured to require SSL.

## 12. Create Database Schema

**Option B only.** Apply the committed schema to the new, empty local target.
These commands prompt for the PostgreSQL password rather than putting it in
the command line.

Windows PowerShell:

```powershell
psql -h localhost -p 5432 -U postgres -d stocklens -W -v ON_ERROR_STOP=1 -f Backend/database/schema.sql
```

macOS/Linux:

```bash
psql -h localhost -p 5432 -U postgres -d stocklens -W -v ON_ERROR_STOP=1 -f Backend/database/schema.sql
```

The schema remains the frozen 16-table definition. If schema application
fails, stop and inspect the error rather than repeatedly rerunning a partially
applied script.

## 13. Load Synthetic Dataset

**Option B only.** Supabase Option A already has this committed dataset loaded;
skip this section when using the shared evaluation database.

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

### Dataset Scale and Design Rationale

The original project brief suggested 2,000 SKUs across 100 stores. For this time-limited demonstration, I selected **one reproducible dataset of 10 SKUs, 3 stores, 5 suppliers, and 365 days of history**, with 17 eligible store–SKU combinations. This choice supports complete workflow coverage, efficient testing, straightforward evaluator setup, and practical use of Supabase free-tier resources.

The dataset is generated with fixed seed `20261022` and reference date `2026-10-22`. The committed records support the forecasting, replenishment, inventory, evaluation, and five anomaly-validation workflows.

## 14. Verify Database Setup

**Option B only.** Run this after the local load and before using Inventory
Save. For Supabase Option A, the schema and dataset are already initialized.

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
contain the StockLens schema and data. Keep `DATABASE_URL` in the local environment or approved secrets configuration.

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

All seven Streamlit pages passed the automated AppTest suite. Inventory workflows use the configured PostgreSQL database.

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
in-memory/demonstration inputs and mocked database connections where applicable;
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
- `LeadTimeObservation` records supplier delivery variability.
  Replenishment uses configured lead times from eligible
  `SupplierSKU` records, making each recommendation consistent with the active
  supplier agreement.
- `ForecastRun`, `Forecast`, and `PurchaseRecommendation` identifiers and
  foreign keys retain run provenance. `InventoryEvent` records persisted
  adjustments separately from snapshots.

These explainable statistical forecasts and rule-based replenishment decisions
make each recommendation understandable and traceable.

## 20. Assumptions and Design Decisions

- The committed demonstration dataset uses seed `20261022` and the scale described in
  [Dataset Scale and Design Rationale](#dataset-scale-and-design-rationale).
- Synthetic data is deterministic and is committed to make setup repeatable.
  It includes controlled business scenarios for repeatable evaluation.
- Ground truth is held apart from forecast features and is used for evaluation.
- PostgreSQL stores the relational dataset and enforces the frozen constraints;
  Streamlit/Python keeps the demo workflows visible and straightforward.
- The loader is deliberately idempotent for identical primary-key rows, but
  schema creation is intended for a new empty database.

## 21. AI-Assisted Development and Project Ownership

I directed requirements analysis, technical decisions, iterative review, manual
verification, and evaluation preparation while using ChatGPT and GitHub
Copilot as development tools. The [project contributions and authentic Copilot prompt
history](docs/AI_USAGE_AND_PROMPT_HISTORY.md) documents this workflow.

## Supporting Documentation

- [Data Dictionary v1.0](docs/data_dictionary.md)
- [Test Execution Report](docs/test_execution_report.md)
- [Manual Testing Guide](docs/manual_testing_guide.md)
- [Project Contributions and AI Prompt History](docs/AI_USAGE_AND_PROMPT_HISTORY.md)
