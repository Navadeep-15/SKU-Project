StockLens | Data Dictionary v1.0 (Revised)
SKU-Location Demand Forecasting & Replenishment System

This revised version freezes the 16-table design and includes:

Complete column definitions
PK/FK definitions
Allowed values
Database constraints
Application-level validations
Lifecycle rules
MOQ/Pack-size rules
Capacity rules
Ground-truth isolation requirements
Global ID Standards
Entity	FormatSKU	SKU-000001
Store	STORE-000001
Supplier	SUP-000001
StoreSKU	SSK-000001
SupplierSKU	PSK-000001
Sale	SALE-STORE-000001-SKU-000001-2026-01-01
Snapshot	INV-STORE-000001-SKU-000001-2026-01-01
Event	EVT-000001
Lead Time Observation	LTO-000001
Policy	POL-000001
Forecast Run	RUN-000001
Forecast	FC-RUN-000001-STORE-000001-SKU-000001-2026-01-01
Recommendation	PO-2026-000001
Ground Truth	GT-000001
Anomaly	ANM-000001
Validation Issue	VAL-000001

All IDs are deterministic and immutable.

1. SKU
Purpose

Product master.

Column	Type	Null	PK	FK	Default	Allowed Values / Validationsku_id	VARCHAR(20)	No	Yes	No	None	SKU-######
sku_name	VARCHAR(255)	No	No	No	None	Non-empty
category	VARCHAR(100)	No	No	No	None	Configurable category list
brand	VARCHAR(100)	No	No	No	None	Non-empty
unit_cost	NUMERIC(10,2)	No	No	No	0	>=0
unit_price	NUMERIC(10,2)	No	No	No	0	>= unit_cost
lifecycle_state	VARCHAR(20)	No	No	No	ACTIVE	ACTIVE, LAUNCHED, DISCONTINUED
launch_date	DATE	No	No	No	None	Valid date
discontinue_date	DATE	Yes	No	No	NULL	> launch_date
created_at	TIMESTAMPTZ	No	No	No	NOW()	Auto
Lifecycle Rules
ACTIVE:
launch_date <= current_date

DISCONTINUED:
discontinue_date must exist

LAUNCHED:
New product within configurable launch window

2. Store
Column	Type	Null	PK	Validationstore_id	VARCHAR(20)	No	Yes	STORE format
store_name	VARCHAR(255)	No	No	Non-empty
city	VARCHAR(100)	No	No	Non-empty
region	VARCHAR(100)	No	No	Valid region
store_type	VARCHAR(50)	No	No	URBAN, SUBURBAN, EXPRESS
capacity_units	INTEGER	No	No	>0
active_flag	BOOLEAN	No	No	True/False
created_at	TIMESTAMPTZ	No	No	Auto
Capacity Definition
Maximum inventory units a store may hold.

3. Supplier
Column	Typesupplier_id	VARCHAR(20) PK
supplier_name	VARCHAR(255)
supplier_type	VARCHAR(50)
active_flag	BOOLEAN
created_at	TIMESTAMPTZ

Allowed Types:

MANUFACTURER
DISTRIBUTOR
WHOLESALER

4. StoreSKU

Store assortment bridge.

Cardinality
Store 1:N StoreSKU
SKU   1:N StoreSKU

Unique Constraint
(store_id, sku_id, active_from)

Column	Typestore_sku_id	VARCHAR(20) PK
store_id	VARCHAR(20) FK Store
sku_id	VARCHAR(20) FK SKU
active_from	DATE
active_to	DATE NULL
assortment_status	VARCHAR(20)
created_at	TIMESTAMPTZ

Status:

ACTIVE
INACTIVE
DISCONTINUED

5. SupplierSKU
Purpose

Supplier-specific purchasing conditions.

Unique
(supplier_id, sku_id, active_from)

Column	Typesupplier_sku_id	VARCHAR(20) PK
supplier_id	VARCHAR(20) FK
sku_id	VARCHAR(20) FK
lead_time_days	INTEGER
min_order_qty	INTEGER
pack_size	INTEGER
contract_cost	NUMERIC(10,2)
supplier_priority	INTEGER
is_preferred_supplier	BOOLEAN
active_from	DATE
active_to	DATE NULL

Validation:

lead_time_days >= 0
min_order_qty > 0
pack_size > 0

6. SalesHistory
Purpose

Observed sales only.

Ground truth never stored here.

Unique
(store_id, sku_id, sales_date)

Column	Typesales_id	VARCHAR(80) PK
store_id	VARCHAR(20) FK
sku_id	VARCHAR(20) FK
sales_date	DATE
units_sold	INTEGER
sales_amount	NUMERIC(12,2)
promotion_flag	BOOLEAN
stockout_flag	BOOLEAN
promotion_id	VARCHAR(30) NULL
created_at	TIMESTAMPTZ

Validation:

units_sold >= 0
sales_amount >= 0

7. InventorySnapshot
Unique
(store_id, sku_id, snapshot_date)

Column	Typesnapshot_id	VARCHAR(80) PK
store_id	FK
sku_id	FK
snapshot_date	DATE
on_hand	INTEGER
on_order	INTEGER
reserved	INTEGER
backorders	INTEGER
created_at	TIMESTAMPTZ

Validation:

All quantities >=0

Inventory Position Formula
Inventory Position
=
On Hand
+ On Order
- Reserved
- Backorders

8. InventoryEvent
Purpose

Historical transaction log.

Column	Typeevent_id	VARCHAR(20) PK
store_id	FK
sku_id	FK
event_date	DATE
event_type	VARCHAR(30)
quantity	INTEGER
reference_id	VARCHAR(50)
created_at	TIMESTAMPTZ
Quantity Sign Convention
Event	SignRECEIPT	+
ADJUSTMENT_IN	+
TRANSFER_IN	+
SALE	-
ADJUSTMENT_OUT	-
SCRAP	-
TRANSFER_OUT	-
9. LeadTimeObservation
Purpose

Lead-time distribution tracking.

Column	Typeobservation_id	VARCHAR(20) PK
supplier_sku_id	FK SupplierSKU
order_date	DATE
receipt_date	DATE
lead_time_days	INTEGER
issue_type	VARCHAR(30)
created_at	TIMESTAMPTZ

Allowed Issue Types:

NORMAL
SUPPLIER_DELAY
EARLY_DELIVERY
NEGATIVE_LEAD_TIME


Validation:

lead_time_days
=
receipt_date - order_date

must be >=0

10. ReorderPolicy
Purpose

Store-SKU replenishment configuration.

Column	Typepolicy_id	VARCHAR(20) PK
store_id	FK
sku_id	FK
review_period_days	INTEGER
service_level	NUMERIC(5,4)
safety_stock	INTEGER
reorder_method	VARCHAR(30)
effective_from	DATE
effective_to	DATE NULL
created_at	TIMESTAMPTZ

Validation:

0 < service_level < 1
review_period_days > 0

Policy Overlap Rule

No overlapping active policy periods allowed.

11. ForecastRun
Purpose

Forecast reproducibility.

Column	Typerun_id	VARCHAR(20) PK
model_name	VARCHAR(100)
model_version	VARCHAR(50)
forecast_origin	DATE
horizon_days	INTEGER
random_seed	INTEGER
dataset_version	VARCHAR(50)
feature_cutoff_date	DATE
created_at	TIMESTAMPTZ

Validation:

feature_cutoff_date
<=
forecast_origin

12. Forecast
Purpose

Forecast outputs.

Unique
(run_id, store_id, sku_id, target_date)

Column	Typeforecast_id	VARCHAR(100) PK
run_id	FK ForecastRun
store_id	FK
sku_id	FK
target_date	DATE
forecast_units	NUMERIC(12,2)
lower_bound	NUMERIC(12,2)
upper_bound	NUMERIC(12,2)
model_name	VARCHAR(100)
forecast_method	VARCHAR(50)
created_at	TIMESTAMPTZ

Validation:

lower_bound <= forecast_units <= upper_bound

forecast_units >=0

target_date > forecast_origin

13. PurchaseRecommendation
Purpose

Replenishment recommendations.

Column	Typerecommendation_id	VARCHAR(30) PK
run_id	FK ForecastRun
store_id	FK
sku_id	FK
supplier_sku_id	FK SupplierSKU
policy_id	FK ReorderPolicy
inventory_position	INTEGER
lead_time_demand	NUMERIC(12,2)
safety_stock	INTEGER
reorder_point	NUMERIC(12,2)
target_stock	NUMERIC(12,2)
recommended_qty	INTEGER
pack_size	INTEGER
minimum_order_qty	INTEGER
capacity_constraint_status	VARCHAR(30)
reason_code	VARCHAR(40)
exception_reason	VARCHAR(255) NULL
recommended_order_date	DATE
expected_delivery_date	DATE
status	VARCHAR(20)
created_at	TIMESTAMPTZ

Capacity Status:

WITHIN_CAPACITY
CAPACITY_EXCEEDED
BLOCKED


Status:

PENDING
APPROVED
REJECTED

Replenishment Formula
Lead Time Demand
=
Forecast Demand During Lead Time

Reorder Point
=
Lead Time Demand
+
Safety Stock

Target Stock
=
Forecast Demand During
(Lead Time + Review Period)
+
Safety Stock

MOQ / Pack Size Rule
Q
=
CEILING(
MAX(StockGap, MOQ)
/ PackSize
)
× PackSize

Capacity Validation
Projected Inventory

=
OnHand
+
OnOrder
+
RecommendedQty

Must not exceed Store Capacity

14. GroundTruthDemand
Purpose

Evaluation only.

Not available to forecasting features.

Unique
(store_id, sku_id, demand_date)

Column	Typetruth_id	VARCHAR(20) PK
store_id	FK
sku_id	FK
demand_date	DATE
actual_demand	INTEGER
observed_sales	INTEGER
stockout_impact	INTEGER
stockout_flag	BOOLEAN
generation_scenario	VARCHAR(50)
created_at	TIMESTAMPTZ

Validation:

actual_demand
>=
observed_sales

15. AnomalyFixture
Purpose

Controlled negative test scenarios.

Column	Typeanomaly_id	VARCHAR(20) PK
issue_type	VARCHAR(50)
scenario	TEXT
affected_entity	VARCHAR(50)
affected_record_key	VARCHAR(100)
expected_result	TEXT
detected_result	TEXT
test_status	VARCHAR(20)
created_at	TIMESTAMPTZ

Issue Types:

STOCKOUT_AS_ZERO_DEMAND
PACK_SIZE_IGNORED
DISCONTINUED_SKU
NEGATIVE_LEAD_TIME
FORECAST_LEAKAGE


Test Status:

PASS
FAIL
PENDING

16. ValidationIssue
Purpose

Validation findings.

Column	Typevalidation_id	VARCHAR(20) PK
table_name	VARCHAR(100)
rule_name	VARCHAR(100)
severity	VARCHAR(20)
record_key	VARCHAR(100)
issue_description	TEXT
resolved_flag	BOOLEAN
detected_at	TIMESTAMPTZ

Severity:

LOW
MEDIUM
HIGH
CRITICAL

Required Anomaly Test Coverage
Edge Case	Expected BehaviourStockout mistaken for zero demand	Detect censored demand
Reorder ignores pack size	Reject or correct quantity
Discontinued SKU recommended	Block recommendation
Negative lead time	Fail validation
Forecast uses future sales	Leakage detection failure
Database Constraints vs Business Logic
Database Constraints
PK/FK integrity
Uniqueness
Enums
Non-negative quantities
Date relationships
Policy overlap prevention

Python Business Logic
Forecast generation
Stockout handling
Safety stock calculation
Reorder point calculation
MOQ rounding
Pack-size rounding
Capacity checking
Recommendation creation
Forecast evaluation
Leakage detection

Requirement Coverage Summary
Requirement	Table(s)	Business LogicSKU Master	SKU	Generator
Store Master	Store	Generator
Supplier Terms	SupplierSKU	Generator
Lead-Time Distribution	LeadTimeObservation	Generator + Replenishment
Promotions	SalesHistory	Generator
Stockout Separation	SalesHistory + GroundTruthDemand	Forecast Evaluation
Forecasting	ForecastRun + Forecast	forecasting.py
Reorder Policies	ReorderPolicy	replenishment.py
MOQ Enforcement	SupplierSKU	replenishment.py
Pack Size Enforcement	SupplierSKU	replenishment.py
Capacity Constraints	Store + PurchaseRecommendation	replenishment.py
Event History	InventoryEvent	inventory.py
Ground Truth Isolation	GroundTruthDemand	validation.py
Edge Cases	AnomalyFixture	tests/
Validation Reporting	ValidationIssue	validation.py
Reproducibility	ForecastRun	generator.py

This revised data dictionary is complete enough to serve as the authoritative specification for the ERD, SQL schema, ORM models, synthetic data generator, validation framework, and application implementation.