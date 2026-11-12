# StockLens

**Inventory Intelligence**

SKU-level demand forecasting, inventory visibility, and replenishment decision
support.

## What it does

StockLens brings together SKU and store data, observed sales, inventory events,
supplier terms, forecasts, purchase recommendations, and controlled validation
scenarios. Forecasts use historical `SalesHistory`; `GroundTruthDemand` is kept
for evaluation after forecasts have been generated.

The Streamlit workspace includes:

- Operations Overview
- Demand Forecasting
- Replenishment Recommendations
- Inventory & Suppliers, including an in-memory inventory adjustment simulator
- Validation Scenarios
- Forecast Evaluation & Exports
- Store Evaluation for chronological, location-specific holdouts

Dashboard queries use read-only PostgreSQL transactions. The explicit
inventory `Save` action uses a separate, narrowly scoped transaction for
`InventoryEvent` and `InventorySnapshot`; `Preview` does not write data.

## Project layout

- `Frontend/` contains the Streamlit application and its theme configuration.
- `Backend/dashboard/` contains cached, read-only dashboard data access.
- `Backend/services/` contains inventory simulation and store evaluation
  workflows.
- `Backend/database/` contains the PostgreSQL connection, frozen schema, and
  dataset loader.
- `Backend/data_generation/`, `Backend/forecasting/`,
  `Backend/replenishment/`, `Backend/evaluation/`, and `Backend/validation/`
  contain the existing application logic.
- `data/`, `tests/`, and `docs/` remain at the project root.

## Install dependencies

From the project root, create and activate a virtual environment, then install
the declared packages:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configure Supabase securely

1. Copy `.env.example` to `.env` in the project root:

   ```powershell
   Copy-Item .env.example .env
   ```
2. Replace the placeholder value in your local `.env` with the Supabase
   PostgreSQL connection string, using SSL as required by your Supabase
   configuration.
3. Keep `.env` private. It is ignored by `.gitignore`; do not commit it, paste
   the connection string into source files, or share it in screenshots or logs.
   `.env.example` is a placeholder template and must not contain credentials.
4. For a hosted Streamlit workspace, configure `DATABASE_URL` through that
   workspace's Streamlit secrets instead of committing a secrets file.

The application does not display the connection string. Dashboard reads use
read-only transactions. The explicit inventory Save action writes only the
inventory event and snapshot.

## Start StockLens

From the project root:

```powershell
Set-Location Frontend
python -m streamlit run app.py
```

Open the local URL printed by Streamlit. The dashboard requires a reachable
Supabase PostgreSQL database for its real data.

## Run tests

Run the complete test suite from the project root:

```powershell
python -m pytest -q
```

To run the tests for the five controlled anomaly scenarios specifically:

```powershell
python -m pytest -q tests/test_anomaly_detector.py
```

These are deterministic validation scenarios, not live operational incidents.

## Demonstrate Inventory Preview and Save

1. Start StockLens and open **Inventory & Suppliers**.
2. Select a location and eligible product, choose an adjustment type, enter
   the unit quantity and reason.
3. Select **Preview** to see the in-memory inventory and replenishment effect.
   Preview does not persist data.
4. Select **Save** only when you intend to persist the adjustment. Save writes
   an `InventoryEvent` and the current-day `InventorySnapshot` in one
   transaction. It does not update forecasts or generated CSVs.
5. Open **Store Evaluation** to see the persisted inventory reflected in the
   replenishment result.

Use an authorized database and verify the selected location/product before
selecting Save.

## Run Store Evaluation

Open **Store Evaluation**, select a location, and choose one or more eligible
products. The page reports chronological holdout accuracy and recalculated
replenishment decisions. It displays the configured forecast reference date
and the latest inventory snapshot date. Replenishment uses that latest saved
inventory with the configured forecast baseline; historical forecast inputs
and holdout metrics remain unchanged.

## Reproduce the synthetic test profile

The existing commands use the fixed seed in `config.py` and write CSVs to
`data/generated/` and `data/exports/`. They overwrite files with matching
names. To preserve the current accepted dataset, run these commands from a
disposable copy of the project:

```powershell
python -m Backend.data_generation.master_generator --profile test
python -m Backend.data_generation.sales_generator --profile test
python -m Backend.data_generation.inventory_generator --profile test
python -m Backend.replenishment.replenishment_engine --profile test
python -m Backend.validation.anomaly_detector --profile test
python -m Backend.database.loader --mode preflight
```

The generation commands do not upload data to Supabase. The replenishment
pipeline and anomaly runner currently support the `test` profile only. The
development profile supports master, sales, and inventory generation, but is
not enabled end-to-end for replenishment. Do not use a larger profile for this
workflow.

See [the data dictionary](docs/data_dictionary.md) for the frozen 16-table
database definition, [the final requirements traceability matrix](docs/requirements_traceability_matrix.md)
for the audited status, and [the manual inventory testing guide](docs/manual_testing_guide.md)
for additional Preview/Save checks.
