# Manual Inventory Testing Guide

This guide covers inventory adjustment Preview and Save behavior. Run any
database-backed checks only against a dedicated test database or isolated test
schema, never against the primary Supabase project.

## Dashboard checks

1. Configure the local `.env` or Streamlit secret with the connection for the
   intended test database. Confirm the database and schema before saving.
2. Open **Inventory & Suppliers**, select a location and an eligible SKU, and
   note its latest on-hand quantity and recent event history.
3. Choose **Receive Stock** or **Remove Stock**, enter a positive whole-number
   quantity, and select **Preview**. Confirm that the projected quantity,
   capacity outcome, and replenishment explanation are shown. Verify that no
   `InventoryEvent` or `InventorySnapshot` row was written.
4. Preview a removal larger than on-hand and a receipt that would exceed store
   capacity. Both should be rejected without a database change.
5. Save a small valid adjustment. Confirm the success notice appears only after
   the transaction completes, the activity history includes the event, the
   current stock view refreshes, and Store Evaluation recalculates its
   replenishment result.
6. Confirm the new event has an `ADJUSTMENT_IN` positive quantity or an
   `ADJUSTMENT_OUT` negative quantity. The previous dated snapshots remain
   unchanged. The first adjustment on a date inserts that day's snapshot;
   further adjustments that day update only that current-day row while adding
   separate inventory events.
7. Try an inactive or discontinued SKU in an isolated test schema. The
   transaction should reject it. A database permission or row-policy failure
   should be reported without falling back to a privileged role.
8. In the isolated target, repeat Save with unchanged form fields and submit
   two different adjustments to the same location from separate sessions at
   nearly the same time. Confirm the identical request creates one event, both
   distinct requests are recorded, the snapshot reconciles to the event ledger,
   and total store stock never exceeds capacity.

Automated unit tests cover transaction rollback, retries with the same
idempotency token, store-level lock acquisition, capacity, and eligibility.
The UI retains the token while the submitted fields are unchanged; changing a
field creates a new save request.

## Optional isolated PostgreSQL integration workflow

This workflow is optional and was not run as part of implementation.

1. Provision a disposable PostgreSQL database or a dedicated schema whose name
   starts with `stocklens_test_`. Apply the unchanged
   `Backend/database/schema.sql` and load only the existing test-profile CSVs
   into that isolated target.
2. Use a dedicated non-owner database role that does not have `BYPASSRLS`.
   Grant `SELECT` only on the required master, event, and snapshot tables;
   grant `INSERT` only on the event columns written by the service; and grant
   `SELECT`/`INSERT` plus `UPDATE` only on the snapshot fields the service
   changes (`snapshot_id`, quantities, and `created_at`). Configure only the
   row-scoped policies required by the test. Do not disable RLS, broaden
   existing policies, use a service-role key, or grant updates to master or
   event tables. Read policies must expose the authorized store's event
   references for idempotency checks and all current snapshots for that store
   needed for capacity checks. Event-ID collisions are retried safely inside a
   savepoint without reading event rows from other stores.
3. Verify `SELECT current_database(), current_schema()` and inspect the
   existing counts in the isolated target before opening the dashboard.
4. Temporarily point the local process to the isolated database URL, then
   launch the dashboard from `Frontend/`. Do not copy the isolated URL into the
   primary `.env` or deployed Streamlit secrets.
5. Exercise the Preview, Save, same-token retry, capacity, inactive-SKU, and
   concurrent-request cases above. Verify counts and history only in the
   isolated target.
6. When resetting the workflow, discard the disposable database/schema or
   remove only the known test records there. Never run cleanup against the
   primary Supabase database.

The application schema is not changed for this workflow. The isolated target
uses the same frozen 16-table schema.
