CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE "SKU" (
    sku_id VARCHAR(20) NOT NULL,
    sku_name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    brand VARCHAR(100) NOT NULL,
    unit_cost NUMERIC(10,2) NOT NULL DEFAULT 0,
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,
    lifecycle_state VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    launch_date DATE NOT NULL,
    discontinue_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT sku_pk PRIMARY KEY (sku_id),
    CONSTRAINT sku_id_format_ck CHECK (sku_id ~ '^SKU-[0-9]{6}$'),
    CONSTRAINT sku_name_nonempty_ck CHECK (BTRIM(sku_name) <> ''),
    CONSTRAINT sku_brand_nonempty_ck CHECK (BTRIM(brand) <> ''),
    CONSTRAINT sku_unit_cost_ck CHECK (unit_cost >= 0),
    CONSTRAINT sku_unit_price_ck CHECK (unit_price >= unit_cost),
    CONSTRAINT sku_lifecycle_state_ck
        CHECK (lifecycle_state IN ('ACTIVE', 'LAUNCHED', 'DISCONTINUED')),
    CONSTRAINT sku_discontinue_date_ck
        CHECK (discontinue_date IS NULL OR discontinue_date > launch_date),
    CONSTRAINT sku_discontinued_date_required_ck
        CHECK (lifecycle_state <> 'DISCONTINUED' OR discontinue_date IS NOT NULL)
);

CREATE TABLE "Store" (
    store_id VARCHAR(20) NOT NULL,
    store_name VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    region VARCHAR(100) NOT NULL,
    store_type VARCHAR(50) NOT NULL,
    capacity_units INTEGER NOT NULL,
    active_flag BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT store_pk PRIMARY KEY (store_id),
    CONSTRAINT store_id_format_ck CHECK (store_id ~ '^STORE-[0-9]{6}$'),
    CONSTRAINT store_name_nonempty_ck CHECK (BTRIM(store_name) <> ''),
    CONSTRAINT store_city_nonempty_ck CHECK (BTRIM(city) <> ''),
    CONSTRAINT store_region_nonempty_ck CHECK (BTRIM(region) <> ''),
    CONSTRAINT store_type_ck
        CHECK (store_type IN ('URBAN', 'SUBURBAN', 'EXPRESS')),
    CONSTRAINT store_capacity_ck CHECK (capacity_units > 0)
);

CREATE TABLE "Supplier" (
    supplier_id VARCHAR(20) NOT NULL,
    supplier_name VARCHAR(255) NOT NULL,
    supplier_type VARCHAR(50) NOT NULL,
    active_flag BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT supplier_pk PRIMARY KEY (supplier_id),
    CONSTRAINT supplier_id_format_ck CHECK (supplier_id ~ '^SUP-[0-9]{6}$'),
    CONSTRAINT supplier_type_ck
        CHECK (supplier_type IN ('MANUFACTURER', 'DISTRIBUTOR', 'WHOLESALER'))
);

CREATE TABLE "StoreSKU" (
    store_sku_id VARCHAR(20) NOT NULL,
    store_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    active_from DATE NOT NULL,
    active_to DATE,
    assortment_status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT storesku_pk PRIMARY KEY (store_sku_id),
    CONSTRAINT storesku_id_format_ck CHECK (store_sku_id ~ '^SSK-[0-9]{6}$'),
    CONSTRAINT storesku_store_fk
        FOREIGN KEY (store_id) REFERENCES "Store" (store_id),
    CONSTRAINT storesku_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT storesku_store_sku_start_uq
        UNIQUE (store_id, sku_id, active_from),
    CONSTRAINT storesku_status_ck
        CHECK (assortment_status IN ('ACTIVE', 'INACTIVE', 'DISCONTINUED')),
    CONSTRAINT storesku_period_ck
        CHECK (active_to IS NULL OR active_to > active_from)
);

CREATE TABLE "SupplierSKU" (
    supplier_sku_id VARCHAR(20) NOT NULL,
    supplier_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    lead_time_days INTEGER NOT NULL,
    min_order_qty INTEGER NOT NULL,
    pack_size INTEGER NOT NULL,
    contract_cost NUMERIC(10,2) NOT NULL,
    supplier_priority INTEGER NOT NULL,
    is_preferred_supplier BOOLEAN NOT NULL,
    active_from DATE NOT NULL,
    active_to DATE,

    CONSTRAINT suppliersku_pk PRIMARY KEY (supplier_sku_id),
    CONSTRAINT suppliersku_id_format_ck CHECK (supplier_sku_id ~ '^PSK-[0-9]{6}$'),
    CONSTRAINT suppliersku_supplier_fk
        FOREIGN KEY (supplier_id) REFERENCES "Supplier" (supplier_id),
    CONSTRAINT suppliersku_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT suppliersku_supplier_sku_start_uq
        UNIQUE (supplier_id, sku_id, active_from),
    CONSTRAINT suppliersku_id_sku_uq
        UNIQUE (supplier_sku_id, sku_id),
    CONSTRAINT suppliersku_lead_time_ck CHECK (lead_time_days >= 0),
    CONSTRAINT suppliersku_min_order_qty_ck CHECK (min_order_qty > 0),
    CONSTRAINT suppliersku_pack_size_ck CHECK (pack_size > 0),
    CONSTRAINT suppliersku_contract_cost_ck CHECK (contract_cost >= 0),
    CONSTRAINT suppliersku_period_ck
        CHECK (active_to IS NULL OR active_to > active_from)
);

CREATE TABLE "SalesHistory" (
    sales_id VARCHAR(80) NOT NULL,
    store_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    sales_date DATE NOT NULL,
    units_sold INTEGER NOT NULL,
    sales_amount NUMERIC(12,2) NOT NULL,
    promotion_flag BOOLEAN NOT NULL,
    stockout_flag BOOLEAN NOT NULL,
    promotion_id VARCHAR(30),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT saleshistory_pk PRIMARY KEY (sales_id),
    CONSTRAINT saleshistory_id_format_ck CHECK (
        sales_id ~ '^SALE-STORE-[0-9]{6}-SKU-[0-9]{6}-[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    ),
    CONSTRAINT saleshistory_store_fk
        FOREIGN KEY (store_id) REFERENCES "Store" (store_id),
    CONSTRAINT saleshistory_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT saleshistory_store_sku_date_uq
        UNIQUE (store_id, sku_id, sales_date),
    CONSTRAINT saleshistory_units_ck CHECK (units_sold >= 0),
    CONSTRAINT saleshistory_amount_ck CHECK (sales_amount >= 0)
);

CREATE TABLE "InventorySnapshot" (
    snapshot_id VARCHAR(80) NOT NULL,
    store_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    snapshot_date DATE NOT NULL,
    on_hand INTEGER NOT NULL,
    on_order INTEGER NOT NULL,
    reserved INTEGER NOT NULL,
    backorders INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT inventorysnapshot_pk PRIMARY KEY (snapshot_id),
    CONSTRAINT inventorysnapshot_id_format_ck CHECK (
        snapshot_id ~ '^INV-STORE-[0-9]{6}-SKU-[0-9]{6}-[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    ),
    CONSTRAINT inventorysnapshot_store_fk
        FOREIGN KEY (store_id) REFERENCES "Store" (store_id),
    CONSTRAINT inventorysnapshot_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT inventorysnapshot_store_sku_date_uq
        UNIQUE (store_id, sku_id, snapshot_date),
    CONSTRAINT inventorysnapshot_quantities_ck
        CHECK (on_hand >= 0 AND on_order >= 0 AND reserved >= 0 AND backorders >= 0)
);

CREATE TABLE "InventoryEvent" (
    event_id VARCHAR(24) NOT NULL,
    store_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    event_date DATE NOT NULL,
    event_type VARCHAR(30) NOT NULL,
    quantity INTEGER NOT NULL,
    reference_id VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT inventoryevent_pk PRIMARY KEY (event_id),
    CONSTRAINT inventoryevent_id_format_ck CHECK (event_id ~ '^EVT-[0-9]{8}$'),
    CONSTRAINT inventoryevent_store_fk
        FOREIGN KEY (store_id) REFERENCES "Store" (store_id),
    CONSTRAINT inventoryevent_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT inventoryevent_type_ck
        CHECK (event_type IN (
            'RECEIPT',
            'ADJUSTMENT_IN',
            'TRANSFER_IN',
            'SALE',
            'ADJUSTMENT_OUT',
            'SCRAP',
            'TRANSFER_OUT'
        )),
    CONSTRAINT inventoryevent_sign_ck CHECK (
        (event_type IN ('RECEIPT', 'ADJUSTMENT_IN', 'TRANSFER_IN') AND quantity > 0)
        OR
        (event_type IN ('SALE', 'ADJUSTMENT_OUT', 'SCRAP', 'TRANSFER_OUT')
            AND quantity < 0)
    ),
    CONSTRAINT inventoryevent_nonzero_quantity_ck CHECK (quantity <> 0)
);

CREATE TABLE "LeadTimeObservation" (
    observation_id VARCHAR(20) NOT NULL,
    supplier_sku_id VARCHAR(20) NOT NULL,
    order_date DATE NOT NULL,
    receipt_date DATE NOT NULL,
    lead_time_days INTEGER NOT NULL,
    issue_type VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT leadtimeobservation_pk PRIMARY KEY (observation_id),
    CONSTRAINT leadtimeobservation_id_format_ck
        CHECK (observation_id ~ '^LTO-[0-9]{6}$'),
    CONSTRAINT leadtimeobservation_supplier_sku_fk
        FOREIGN KEY (supplier_sku_id) REFERENCES "SupplierSKU" (supplier_sku_id),
    CONSTRAINT leadtimeobservation_issue_type_ck
        CHECK (issue_type IN ('NORMAL', 'SUPPLIER_DELAY', 'EARLY_DELIVERY')),
    CONSTRAINT leadtimeobservation_lead_time_ck
        CHECK (lead_time_days >= 0 AND lead_time_days = receipt_date - order_date)
);

CREATE TABLE "ReorderPolicy" (
    policy_id VARCHAR(20) NOT NULL,
    store_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    review_period_days INTEGER NOT NULL,
    service_level NUMERIC(5,4) NOT NULL,
    safety_stock INTEGER NOT NULL,
    reorder_method VARCHAR(30) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT reorderpolicy_pk PRIMARY KEY (policy_id),
    CONSTRAINT reorderpolicy_id_format_ck CHECK (policy_id ~ '^POL-[0-9]{6}$'),
    CONSTRAINT reorderpolicy_store_fk
        FOREIGN KEY (store_id) REFERENCES "Store" (store_id),
    CONSTRAINT reorderpolicy_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT reorderpolicy_id_store_sku_uq
        UNIQUE (policy_id, store_id, sku_id),
    CONSTRAINT reorderpolicy_review_period_ck CHECK (review_period_days > 0),
    CONSTRAINT reorderpolicy_service_level_ck
        CHECK (service_level > 0 AND service_level < 1),
    CONSTRAINT reorderpolicy_safety_stock_ck CHECK (safety_stock >= 0),
    CONSTRAINT reorderpolicy_period_ck
        CHECK (effective_to IS NULL OR effective_to > effective_from),
    CONSTRAINT reorderpolicy_no_overlap_excl
        EXCLUDE USING gist (
            store_id WITH =,
            sku_id WITH =,
            daterange(effective_from, effective_to, '[)') WITH &&
        )
);

CREATE TABLE "ForecastRun" (
    run_id VARCHAR(20) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    forecast_origin DATE NOT NULL,
    horizon_days INTEGER NOT NULL,
    random_seed INTEGER NOT NULL,
    dataset_version VARCHAR(50) NOT NULL,
    feature_cutoff_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT forecastrun_pk PRIMARY KEY (run_id),
    CONSTRAINT forecastrun_id_format_ck CHECK (run_id ~ '^RUN-[0-9]{6}$'),
    CONSTRAINT forecastrun_horizon_ck CHECK (horizon_days > 0),
    CONSTRAINT forecastrun_feature_cutoff_ck
        CHECK (feature_cutoff_date <= forecast_origin)
);

CREATE TABLE "Forecast" (
    forecast_id VARCHAR(100) NOT NULL,
    run_id VARCHAR(20) NOT NULL,
    store_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    target_date DATE NOT NULL,
    forecast_units NUMERIC(12,2) NOT NULL,
    lower_bound NUMERIC(12,2) NOT NULL,
    upper_bound NUMERIC(12,2) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    forecast_method VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT forecast_pk PRIMARY KEY (forecast_id),
    CONSTRAINT forecast_id_format_ck CHECK (
        forecast_id ~ '^FC-RUN-[0-9]{6}-STORE-[0-9]{6}-SKU-[0-9]{6}-[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    ),
    CONSTRAINT forecast_run_fk
        FOREIGN KEY (run_id) REFERENCES "ForecastRun" (run_id),
    CONSTRAINT forecast_store_fk
        FOREIGN KEY (store_id) REFERENCES "Store" (store_id),
    CONSTRAINT forecast_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT forecast_run_store_sku_date_uq
        UNIQUE (run_id, store_id, sku_id, target_date),
    CONSTRAINT forecast_bounds_ck
        CHECK (lower_bound <= forecast_units AND forecast_units <= upper_bound),
    CONSTRAINT forecast_units_ck CHECK (forecast_units >= 0)
);

CREATE TABLE "PurchaseRecommendation" (
    recommendation_id VARCHAR(30) NOT NULL,
    run_id VARCHAR(20) NOT NULL,
    store_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    supplier_sku_id VARCHAR(20) NOT NULL,
    policy_id VARCHAR(20) NOT NULL,
    inventory_position INTEGER NOT NULL,
    lead_time_demand NUMERIC(12,2) NOT NULL,
    safety_stock INTEGER NOT NULL,
    reorder_point NUMERIC(12,2) NOT NULL,
    target_stock NUMERIC(12,2) NOT NULL,
    recommended_qty INTEGER NOT NULL,
    pack_size INTEGER NOT NULL,
    minimum_order_qty INTEGER NOT NULL,
    capacity_constraint_status VARCHAR(30) NOT NULL,
    reason_code VARCHAR(40) NOT NULL,
    exception_reason VARCHAR(255),
    recommended_order_date DATE NOT NULL,
    expected_delivery_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT purchaserecommendation_pk PRIMARY KEY (recommendation_id),
    CONSTRAINT purchaserecommendation_id_format_ck
        CHECK (recommendation_id ~ '^PO-[0-9]{4}-[0-9]{6}$'),
    CONSTRAINT purchaserecommendation_run_fk
        FOREIGN KEY (run_id) REFERENCES "ForecastRun" (run_id),
    CONSTRAINT purchaserecommendation_store_fk
        FOREIGN KEY (store_id) REFERENCES "Store" (store_id),
    CONSTRAINT purchaserecommendation_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT purchaserecommendation_supplier_sku_fk
        FOREIGN KEY (supplier_sku_id, sku_id)
        REFERENCES "SupplierSKU" (supplier_sku_id, sku_id),
    CONSTRAINT purchaserecommendation_policy_fk
        FOREIGN KEY (policy_id, store_id, sku_id)
        REFERENCES "ReorderPolicy" (policy_id, store_id, sku_id),
    CONSTRAINT purchaserecommendation_capacity_status_ck
        CHECK (capacity_constraint_status IN (
            'WITHIN_CAPACITY', 'CAPACITY_EXCEEDED', 'BLOCKED'
        )),
    CONSTRAINT purchaserecommendation_status_ck
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CONSTRAINT purchaserecommendation_blocked_exception_ck
        CHECK (
            capacity_constraint_status <> 'BLOCKED'
            OR NULLIF(BTRIM(exception_reason), '') IS NOT NULL
        ),
    CONSTRAINT purchaserecommendation_lead_time_demand_ck
        CHECK (lead_time_demand >= 0),
    CONSTRAINT purchaserecommendation_safety_stock_ck
        CHECK (safety_stock >= 0),
    CONSTRAINT purchaserecommendation_reorder_point_ck
        CHECK (reorder_point >= 0),
    CONSTRAINT purchaserecommendation_target_stock_ck
        CHECK (target_stock >= 0),
    CONSTRAINT purchaserecommendation_order_qty_ck
        CHECK (
            pack_size > 0
            AND minimum_order_qty > 0
            AND recommended_qty >= 0
            AND CASE
                WHEN recommended_qty = 0 THEN TRUE
                WHEN pack_size > 0 AND minimum_order_qty > 0 THEN
                    recommended_qty >= minimum_order_qty
                    AND MOD(recommended_qty, pack_size) = 0
                ELSE FALSE
            END
        )
);

CREATE TABLE "GroundTruthDemand" (
    truth_id VARCHAR(24) NOT NULL,
    store_id VARCHAR(20) NOT NULL,
    sku_id VARCHAR(20) NOT NULL,
    demand_date DATE NOT NULL,
    actual_demand INTEGER NOT NULL,
    observed_sales INTEGER NOT NULL,
    stockout_impact INTEGER NOT NULL,
    stockout_flag BOOLEAN NOT NULL,
    generation_scenario VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT groundtruthdemand_pk PRIMARY KEY (truth_id),
    CONSTRAINT groundtruthdemand_id_format_ck CHECK (truth_id ~ '^GT-[0-9]{8}$'),
    CONSTRAINT groundtruthdemand_store_fk
        FOREIGN KEY (store_id) REFERENCES "Store" (store_id),
    CONSTRAINT groundtruthdemand_sku_fk
        FOREIGN KEY (sku_id) REFERENCES "SKU" (sku_id),
    CONSTRAINT groundtruthdemand_store_sku_date_uq
        UNIQUE (store_id, sku_id, demand_date),
    CONSTRAINT groundtruthdemand_observed_sales_ck
        CHECK (observed_sales >= 0),
    CONSTRAINT groundtruthdemand_stockout_impact_ck
        CHECK (stockout_impact >= 0),
    CONSTRAINT groundtruthdemand_actual_demand_ck
        CHECK (actual_demand = observed_sales + stockout_impact)
);

CREATE TABLE "AnomalyFixture" (
    anomaly_id VARCHAR(20) NOT NULL,
    issue_type VARCHAR(50) NOT NULL,
    scenario TEXT NOT NULL,
    affected_entity VARCHAR(50) NOT NULL,
    affected_record_key VARCHAR(100) NOT NULL,
    expected_result TEXT NOT NULL,
    detected_result TEXT NOT NULL,
    test_status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT anomalyfixture_pk PRIMARY KEY (anomaly_id),
    CONSTRAINT anomalyfixture_id_format_ck CHECK (anomaly_id ~ '^ANM-[0-9]{6}$'),
    CONSTRAINT anomalyfixture_issue_type_ck
        CHECK (issue_type IN (
            'STOCKOUT_AS_ZERO_DEMAND',
            'PACK_SIZE_IGNORED',
            'DISCONTINUED_SKU',
            'NEGATIVE_LEAD_TIME',
            'FORECAST_LEAKAGE'
        )),
    CONSTRAINT anomalyfixture_test_status_ck
        CHECK (test_status IN ('PASS', 'FAIL', 'PENDING'))
);

CREATE TABLE "ValidationIssue" (
    validation_id VARCHAR(20) NOT NULL,
    table_name VARCHAR(100) NOT NULL,
    rule_name VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    record_key VARCHAR(100) NOT NULL,
    issue_description TEXT NOT NULL,
    resolved_flag BOOLEAN NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT validationissue_pk PRIMARY KEY (validation_id),
    CONSTRAINT validationissue_id_format_ck CHECK (validation_id ~ '^VAL-[0-9]{6}$'),
    CONSTRAINT validationissue_severity_ck
        CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))
);

CREATE OR REPLACE FUNCTION enforce_forecast_target_horizon()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_forecast_origin DATE;
    v_horizon_days INTEGER;
BEGIN
    SELECT forecast_origin, horizon_days
    INTO v_forecast_origin, v_horizon_days
    FROM "ForecastRun"
    WHERE run_id = NEW.run_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'ForecastRun % does not exist', NEW.run_id;
    END IF;

    IF NEW.target_date <= v_forecast_origin
       OR NEW.target_date > v_forecast_origin + v_horizon_days THEN
        RAISE EXCEPTION
            'Forecast target_date % must be after origin % and within % days',
            NEW.target_date, v_forecast_origin, v_horizon_days;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER forecast_target_horizon_trg
BEFORE INSERT OR UPDATE ON "Forecast"
FOR EACH ROW
EXECUTE FUNCTION enforce_forecast_target_horizon();

CREATE OR REPLACE FUNCTION preserve_existing_forecast_horizon()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM "Forecast" f
        WHERE f.run_id = OLD.run_id
          AND (
              f.target_date <= NEW.forecast_origin
              OR f.target_date > NEW.forecast_origin + NEW.horizon_days
          )
    ) THEN
        RAISE EXCEPTION
            'ForecastRun origin/horizon update would invalidate existing forecasts';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER forecastrun_horizon_update_trg
BEFORE UPDATE OF forecast_origin, horizon_days ON "ForecastRun"
FOR EACH ROW
EXECUTE FUNCTION preserve_existing_forecast_horizon();

CREATE OR REPLACE FUNCTION prevent_primary_key_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF (to_jsonb(NEW) ->> TG_ARGV[0])
       IS DISTINCT FROM
       (to_jsonb(OLD) ->> TG_ARGV[0]) THEN
        RAISE EXCEPTION 'Primary key % is immutable', TG_ARGV[0];
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER sku_id_immutable_trg
BEFORE UPDATE ON "SKU" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('sku_id');

CREATE TRIGGER store_id_immutable_trg
BEFORE UPDATE ON "Store" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('store_id');

CREATE TRIGGER supplier_id_immutable_trg
BEFORE UPDATE ON "Supplier" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('supplier_id');

CREATE TRIGGER storesku_id_immutable_trg
BEFORE UPDATE ON "StoreSKU" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('store_sku_id');

CREATE TRIGGER suppliersku_id_immutable_trg
BEFORE UPDATE ON "SupplierSKU" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('supplier_sku_id');

CREATE TRIGGER saleshistory_id_immutable_trg
BEFORE UPDATE ON "SalesHistory" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('sales_id');

CREATE TRIGGER inventorysnapshot_id_immutable_trg
BEFORE UPDATE ON "InventorySnapshot" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('snapshot_id');

CREATE TRIGGER inventoryevent_id_immutable_trg
BEFORE UPDATE ON "InventoryEvent" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('event_id');

CREATE TRIGGER leadtimeobservation_id_immutable_trg
BEFORE UPDATE ON "LeadTimeObservation" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('observation_id');

CREATE TRIGGER reorderpolicy_id_immutable_trg
BEFORE UPDATE ON "ReorderPolicy" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('policy_id');

CREATE TRIGGER forecastrun_id_immutable_trg
BEFORE UPDATE ON "ForecastRun" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('run_id');

CREATE TRIGGER forecast_id_immutable_trg
BEFORE UPDATE ON "Forecast" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('forecast_id');

CREATE TRIGGER purchaserecommendation_id_immutable_trg
BEFORE UPDATE ON "PurchaseRecommendation" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('recommendation_id');

CREATE TRIGGER groundtruthdemand_id_immutable_trg
BEFORE UPDATE ON "GroundTruthDemand" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('truth_id');

CREATE TRIGGER anomalyfixture_id_immutable_trg
BEFORE UPDATE ON "AnomalyFixture" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('anomaly_id');

CREATE TRIGGER validationissue_id_immutable_trg
BEFORE UPDATE ON "ValidationIssue" FOR EACH ROW
EXECUTE FUNCTION prevent_primary_key_change('validation_id');

CREATE INDEX storesku_sku_idx ON "StoreSKU" (sku_id);
CREATE INDEX suppliersku_sku_idx ON "SupplierSKU" (sku_id);

CREATE INDEX saleshistory_sku_date_idx ON "SalesHistory" (sku_id, sales_date);
CREATE INDEX saleshistory_date_idx ON "SalesHistory" (sales_date);

CREATE INDEX inventorysnapshot_sku_date_idx
    ON "InventorySnapshot" (sku_id, snapshot_date);

CREATE INDEX inventoryevent_sku_date_idx
    ON "InventoryEvent" (sku_id, event_date);
CREATE INDEX inventoryevent_store_date_idx
    ON "InventoryEvent" (store_id, event_date);

CREATE INDEX leadtimeobservation_order_date_idx
    ON "LeadTimeObservation" (supplier_sku_id, order_date);
CREATE INDEX leadtimeobservation_receipt_date_idx
    ON "LeadTimeObservation" (receipt_date);

CREATE INDEX reorderpolicy_sku_idx ON "ReorderPolicy" (sku_id);

CREATE INDEX forecast_store_target_date_idx ON "Forecast" (store_id, target_date);
CREATE INDEX forecast_sku_target_date_idx ON "Forecast" (sku_id, target_date);

CREATE INDEX purchaserecommendation_run_idx
    ON "PurchaseRecommendation" (run_id);
CREATE INDEX purchaserecommendation_store_idx
    ON "PurchaseRecommendation" (store_id);
CREATE INDEX purchaserecommendation_sku_idx
    ON "PurchaseRecommendation" (sku_id);
