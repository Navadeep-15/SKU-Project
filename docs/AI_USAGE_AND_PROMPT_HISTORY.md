# StockLens — Project Ownership, Technical Contributions & AI-Assisted Development Record

**Project:** SKU-Location Demand Forecasting & Replenishment (StockLens)  
**Development approach:** AI-assisted engineering with requirements-led technical direction, iterative review and validation  
**Source of prompt history:** Curated, verbatim excerpts from the GitHub Copilot conversation

## Executive summary

StockLens is an end-to-end demonstration application that models SKU-store demand, generates explainable demand forecasts, recommends replenishment subject to ordering and inventory constraints, identifies invalid business scenarios, and exposes results through a Streamlit dashboard. Its supporting stack includes Python, pandas, NumPy, Supabase PostgreSQL, SQL and pytest.

I drove the project from requirements interpretation and data-model design through implementation planning, decision review, integration, test-oriented refinement and evaluator preparation. I established the application scope and the 16-table data model, specified operational business rules, selected practical forecasting and replenishment approaches, and made explicit decisions on traceability, exception handling and database safety. I used ChatGPT and GitHub Copilot to accelerate development and support implementation across the project.

The prompt history records a sequence of technical decisions, reviews, and refinements. The repository, test execution report, and application walkthrough provide the associated implementation and validation evidence.

## My role and contributions

### 1. Requirements engineering and solution design

I translated the project brief into an implementation plan covering master data, related business transactions, synthetic demand, stockout handling, forecasting, replenishment, validation and an evaluator-facing dashboard. I deliberately scoped the application as a functional, understandable demonstration, with one reproducible demonstration dataset.

I established a frozen 16-table design with separate operational, forecasting, replenishment, validation and ground-truth entities. I required consistent keys and relationships, lifecycle and effective-date controls, preservation of historical events and traceable forecast runs and purchase recommendations.

### 2. Database modeling and data integrity

I reviewed and refined the PostgreSQL schema over multiple iterations. My decisions addressed valid table constraints, cross-table rules that cannot be enforced by ordinary CHECK constraints, date-range handling, schema-supported identifiers, nonnegative quantities and supplier or policy matching. I also specified the distinction between controlled invalid test fixtures and valid operational database records.

For data generation, I defined deterministic master and dependent records, realistic sales seasonality and promotions, explicit stockout censoring, and consistency between observed sales and separately stored ground-truth demand. I directed inventory-ledger reconciliation, event sequencing, store-level capacity checks and snapshot matching without rewriting sales history.

### 3. Forecasting and evaluation decisions

I selected two transparent statistical approaches—a recent seven-day baseline and a weekday-seasonal 28-day method—and required chronological holdout evaluation. I specified that forecasting use eligible historical observed sales only, while GroundTruthDemand remain isolated for evaluation. I required treatment of stockout-censored observations, cold-start behavior, forecast-origin cutoffs and measurable MAE, RMSE, WAPE and bias.

### 4. Replenishment logic and operational constraints

I specified calculations for inventory position, lead-time demand, reorder points and target stock, as well as supplier eligibility and deterministic supplier selection. I directed MOQ and pack-size rounding, safety-stock usage, eligibility windows, capacity allocation across multiple SKUs and explicit BLOCKED outcomes when an order could not satisfy constraints. I also required each recommendation to remain traceable to its forecast run, inventory state and applicable policy.

### 5. Quality, database integration and risk controls

I worked in reviewable phases and required focused tests, full-suite regression checks, schema-aligned CSV validation and explicit exception coverage. Before permanent database loading, I directed preflight checks, foreign-key-aware insertion order, rollback-only dry runs, idempotency controls, batching improvements and database constraint verification. These safeguards were intended to make loading repeatable and to detect inconsistencies before committed changes.

I also specified five controlled anomaly demonstrations: stockout-as-zero-demand, ignored pack size, discontinued SKU, negative lead time and forecast leakage. The scenarios were designed to test invalid inputs in isolation, without contaminating operational data.

### 6. Application experience and delivery

I directed the Streamlit dashboard presentation, product naming and evaluator journey. My documented manual checks included reviewing the running interface and testing Inventory Preview and Save. I also directed repository preparation, README setup options, dependency and environment configuration, test reporting, and restricted database access for evaluation. These activities are supported by the development record and validation report.

## How AI contributed to development

I used ChatGPT and GitHub Copilot as development tools while directing the project requirements, technical design, implementation priorities, review cycles, and validation approach. The recorded prompts illustrate my decisions about architecture, business rules, database integrity, interface design, and evaluator preparation.

The project was intentionally implemented in an explainable, modular style. This supported straightforward testing, traceability and demonstration of each business rule. The selected original requests below illustrate the technical decisions and refinements made during the Copilot session.

## Evidence and project outcomes

StockLens includes a frozen 16-table PostgreSQL schema, linked synthetic operational data, explainable forecasting, replenishment recommendations, five passing anomaly scenarios, and a seven-page Streamlit interface. The final recorded validation includes **120 passing automated tests**, **seven passing Streamlit AppTest page checks**, **five passing anomaly scenarios**, and matching checksums across **19 CSV files** in two independent generation runs. The [test execution report](test_execution_report.md) documents these results.

## Prompt history

The following selected requests are reproduced verbatim and in chronological order. They illustrate my technical direction across schema design, implementation, anomaly coverage, interface design, and evaluation preparation.

---

## Selected original GitHub Copilot prompts

### 1. Create project structure

*Recorded: 2026-11-11 16:26 UTC*

````text
Based on our agreed project requirements, create the initial folder structure for the SKU-Location Demand Forecasting & Replenishment System.

Create only the following:

- app.py
- config.py
- requirements.txt
- .gitignore
- database/schema.sql
- database/connection.py
- src/data_generation/
- src/forecasting/
- src/replenishment/
- src/validation/
- src/evaluation/
- data/generated/
- data/exports/
- tests/
- docs/
Add appropriate **init**.py files where required.

Do not implement business logic yet. Do not add unnecessary folders or technologies.

After creating the structure, show me the folder tree and explain the purpose of each major folder.
````
### 2. Approve schema decisions

*Recorded: 2026-11-11 16:37 UTC*

````text
Your review of docs/data_dictionary.md is correct.

Before drafting SQL, use the following approved implementation decisions to resolve the identified ambiguities.

1. Nullability:

- Treat columns as NOT NULL unless the Data Dictionary explicitly identifies them as nullable.
- Apply defaults only when explicitly documented.
- Use DEFAULT NOW() for created_at fields documented as automatic.
- Do not invent additional defaults.
2. Negative lead time:

- Valid LeadTimeObservation records must have lead_time_days >= 0.
- The NEGATIVE_LEAD_TIME anomaly must be tested using AnomalyFixture.
- Do not insert invalid negative lead-time records into valid operational tables.
3. Effective-date intervals:

- Use half-open date intervals [effective_from, effective_to).
- NULL effective_to means there is no end date.
- Prevent overlapping ReorderPolicy periods for the same store_id and sku_id.
- Validate active_from/active_to and effective_from/effective_to date ordering.
4. Forecast horizon:

- horizon_days must be greater than zero.
- Valid target dates must be greater than forecast_origin and less than or equal to forecast_origin + horizon_days.
5. Store capacity:

- Capacity must be checked at store level across all SKUs.
- If projected inventory exceeds capacity, mark the recommendation BLOCKED and record an exception.
- Never silently violate MOQ or pack-size requirements.
6. Cross-table matching:

- Validate that supplier_sku_id refers to a SupplierSKU belonging to the recommendation's sku_id.
- Validate that policy_id refers to a ReorderPolicy belonging to the recommendation's store_id and sku_id.
- Do not add supplier_id to PurchaseRecommendation because it is not in the Data Dictionary.
7. Preserve the exact 16-table design and all specified columns.
Now prepare the proposed PostgreSQL schema.

Before creating schema.sql:

- Show all CREATE TABLE statements.
- Show primary keys, foreign keys, unique constraints and CHECK constraints.
- Show any extensions, triggers or exclusion constraints required.
- Identify which business rules will remain in Python validation.
- Explain how the constraints enforce the approved decisions.
Do not execute SQL against Supabase.
Do not modify other files.
Wait for my approval before writing schema.sql.
````
### 3. Final schema corrections

*Recorded: 2026-11-11 16:44 UTC*

````text
Make only these three final corrections to the proposed PostgreSQL schema:

1. In GroundTruthDemand, replace the existing actual_demand >= observed_sales constraint with:

- observed_sales >= 0
- stockout_impact >= 0
- actual_demand = observed_sales + stockout_impact
2. In SupplierSKU, add:
CHECK (contract_cost >= 0)
3. In InventoryEvent, add:
CHECK (quantity <> 0)
Preserve all existing tables, columns, keys, constraints, triggers, indexes, ID formats, and approved design decisions.

Return the complete final SQL, including all functions, triggers, and indexes.

Do not modify any project files.
Do not execute SQL against Supabase.
Wait for my approval.
````
### 4. Approve SQL with ID correction

*Recorded: 2026-11-11 16:48 UTC*

````text
The final PostgreSQL schema proposal has been reviewed and approved, subject to one ID-format correction.

Please make the following changes:

1. In the `InventoryEvent` table:

- Change `event_id` from `VARCHAR(20)` to `VARCHAR(24)`.
- Change its ID format constraint to `^EVT-[0-9]{8}$`.
- Example ID: `EVT-00000001`.
2. In the `GroundTruthDemand` table:

- Change `truth_id` from `VARCHAR(20)` to `VARCHAR(24)`.
- Change its ID format constraint to `^GT-[0-9]{8}$`.
- Example ID: `GT-00000001`.
3. Do not change the other ID formats, table names, columns, constraints, triggers, or indexes.
4. Save the complete finalized SQL schema to:
`E:\Yottaflex\database\schema.sql`
5. Ensure the file contains:

- All 16 tables
- All primary keys, foreign keys, and constraints
- Forecast horizon triggers
- Primary-key immutability triggers
- All indexes
- The three previously approved corrections for GroundTruthDemand reconciliation, SupplierSKU contract_cost, and InventoryEvent nonzero quantity
6. Check the SQL file for syntax and dependency-order issues. Do not claim that the SQL has been successfully executed unless it has actually been tested.
7. Do not execute any SQL, connect to Supabase, create tables, or modify any other project files.
After saving, confirm the file path and summarize exactly what you changed.
````
### 5. Review master generator

*Recorded: 2026-11-11 17:27 UTC*

````text
Review the existing Phase 4A implementation in config.py, src/data_generation/master_generator.py, and tests/test_master_generator.py.

Make only these targeted improvements:

1. In config.py, define SALES_HISTORY_DAYS = 365 and SALES_START_DATE = REFERENCE_DATE - timedelta(days=364), so the sales window includes exactly 365 calendar dates ending on REFERENCE_DATE.
2. Preserve the existing master-data generation logic, IDs, row counts, and deterministic behavior.
3. Add focused pytest cases that verify validate_master_data() rejects:

- Duplicate primary keys
- Invalid foreign keys
- Overlapping effective periods
- An active StoreSKU without an eligible active SupplierSKU
- Negative supplier lead times
- Invalid discontinued SKU dates
4. Ensure tests use copies of generated DataFrames so they do not modify shared test data.
5. Run the complete tests/test_master_generator.py suite and report the actual results.
Do not change database/schema.sql, database/connection.py, or any generated CSV files.

Do not implement daily sales, inventory, forecasting, or replenishment yet.

Keep changes minimal and beginner-friendly.
````
### 6. Integrate anomaly results

*Recorded: 2026-11-11 20:14 UTC*

````text
Continue with Phase 8B: Supabase Anomaly Results Integration.

Phase 8A has been reviewed and accepted. Five anomaly fixtures and five validation issues were generated, with 83 tests passing.

Objective: Store the five verified anomaly demonstrations in Supabase so the Streamlit dashboard can display them.

Requirements:

1. Use the existing data/exports/anomaly_fixtures.csv and anomaly_validation_issues.csv.
2. Verify both files against the frozen AnomalyFixture and ValidationIssue schema.
3. Confirm that all five anomaly types have PASS status.
4. Confirm that the existing 18,873 operational rows remain unchanged.
5. Inspect the current Supabase row counts for AnomalyFixture and ValidationIssue before writing.
6. Stop if either table contains unexpected or conflicting records.
7. Use a transaction and existing safe, idempotent insertion logic where practical.
8. Insert only the five AnomalyFixture and five ValidationIssue rows.
9. Verify the final database counts are 5 and 5.
10. Re-run the insertion and confirm no duplicate records are created.
11. Run the full pytest suite.
Important:

- Do not regenerate data.
- Do not modify the existing forecasting or replenishment results.
- Do not modify the frozen 16-table schema.
- Do not disable RLS or create public Data API policies.
- Do not build Streamlit yet.
- Do not modify other database tables.
- Stop if any validation or database integrity check fails.
Report the inserted/skipped counts, final table counts, and test results. Stop after Phase 8B.
````
### 7. Apply StockLens branding

*Recorded: 2026-11-11 21:44 UTC*

````text
Update the existing Streamlit frontend branding and user-facing terminology.

Selected product name: StockLens
Product subtitle: Inventory Intelligence
Primary page heading: Operations Overview
Product description: SKU-level demand forecasting, inventory visibility, and replenishment decision support.

Requirements:

1. Replace all user-facing references to DemandIQ and SKU Intelligence branding with StockLens.
2. Update the browser page title to "StockLens | Inventory Intelligence".
3. Replace "DEMO WORKSPACE" with "OPERATIONS WORKSPACE".
4. Remove user-facing references to "demo", "demonstration", "sample project", "student project", "assessment", and "production".
5. Use professional product-oriented terminology throughout all six Streamlit pages.
6. Describe anomaly fixtures accurately as controlled validation test scenarios, not live operational incidents.
7. Do not claim real-time monitoring, advanced AI, or capabilities that the application does not implement.
8. Preserve the light workspace, dark green sidebar, and existing design.
9. Preserve all forecasting, replenishment, inventory, evaluation, and CSV export functionality.
10. Do not modify the database schema, generated datasets, backend algorithms, or Supabase records.
11. Do not rename database columns, model identifiers, or internal schema fields.
12. Run the existing tests and verify all six dashboard pages load correctly.
Keep changes limited to frontend branding, labels, headings, descriptions, and related presentation styling. Report modified files and test results.
````
### 8. Review final evaluator changes

*Recorded: 2026-11-12 01:22 UTC*

````text
The latest StockLens evaluator preparation changes have passed 120 automated tests.

1. Run git status and review the five changed files.
2. Run python -m pytest -q.
3. Verify that no credentials, .env, .venv, or secrets are staged.
4. Stage only the intended evaluator preparation files.
5. Commit with message:
"Prepare StockLens for YottaFlex evaluator setup"
6. Push to origin/master without force-pushing.
7. Confirm the remote commit and report the commit hash.
Do not modify application logic, database schema, or datasets.

Do not claim live PostgreSQL initialization was tested, because it has not been performed.
````
### 9. Document two database options

*Recorded: 2026-11-12 13:43 UTC*

````text
Modify the readme Update the existing StockLens README.md to provide two database setup options for evaluators.

**Option A: Supabase PostgreSQL — Recommended Quick Start**

- Explain that the project has an existing Supabase PostgreSQL database containing the 16 tables and preloaded synthetic data.
- Make this the first and recommended setup method.
- Provide exact commands to clone the repository, install Python dependencies, configure DATABASE_URL, and launch Streamlit.
- Do not require schema creation, database initialization, or data loading for this option.
- Keep the existing .env.example configuration approach.
- Do not commit the existing .env file or insert actual database credentials into the README. Use a placeholder for DATABASE_URL until I explicitly provide the evaluation connection details.
- Explain that this cloud database is temporary and will be deleted after evaluation.
**Option B: Local PostgreSQL — Backup Setup**

- Preserve the complete existing local PostgreSQL setup instructions.
- Include PostgreSQL installation guidance for Windows and a link to the official PostgreSQL download page.
- Include commands for database creation, schema initialization, synthetic data preflight, data loading, and verification.
- Ensure this method works independently of the Supabase database.
**Additional requirements**

- Add a short Quick Start section near the beginning of README.md.
- Clearly distinguish commands required for Supabase from commands required for local PostgreSQL.
- Preserve the existing application documentation, testing instructions, anomaly scenarios, architecture, and AI disclosure links.
- Do not modify Python code, database schema, forecasting logic, replenishment logic, or dependencies.
- Do not stage, commit, or push changes.
- Show the README diff after editing.
````
### 10. Update README setup wording

*Recorded: 2026-11-12 13:47 UTC*

````text
Update only README.md for StockLens.

Keep the two database setup methods:

Option A — Preloaded Supabase PostgreSQL (Recommended)
Option B — Local PostgreSQL (Backup)

Make these corrections:

1. Clearly explain that Option A uses the existing, preloaded evaluation database and requires no schema creation or data loading.
2. Remove references to obtaining credentials through a separate private submission channel, because the evaluation submission only accepts a public GitHub repository link.
3. Keep DATABASE_URL as a placeholder for now. Do not insert, print, or commit actual credentials.
4. Make Section 10 consistent with both options rather than describing only a new database.
5. Add a short note that Option A requires valid evaluation database credentials and cannot work with the placeholder alone.
6. Preserve all existing local PostgreSQL backup instructions.
7. Do not modify application code, tests, schema, or dependencies.
8. Do not stage, commit, or push changes.
9. Show the exact README diff.
````
