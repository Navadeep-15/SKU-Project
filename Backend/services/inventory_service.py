import hashlib
import re
from numbers import Integral

import psycopg


_IDEMPOTENCY_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{24}$")
_ADJUSTMENTS = {
    "RECEIVE_STOCK": ("ADJUSTMENT_IN", 1),
    "REMOVE_STOCK": ("ADJUSTMENT_OUT", -1),
}
_MAX_REASON_LENGTH = 22


class InventoryServiceError(Exception):
    """A safe, user-facing inventory adjustment error."""


def _validate_request(
    store_id,
    sku_id,
    adjustment_type,
    quantity,
    idempotency_token,
    reason,
):
    if not isinstance(store_id, str) or not store_id.strip():
        raise InventoryServiceError("Select a valid store.")
    if not isinstance(sku_id, str) or not sku_id.strip():
        raise InventoryServiceError("Select a valid SKU.")
    if adjustment_type not in _ADJUSTMENTS:
        raise InventoryServiceError("Choose Receive Stock or Remove Stock.")
    if isinstance(quantity, bool) or not isinstance(quantity, Integral):
        raise InventoryServiceError("Quantity must be a whole number of units.")
    if quantity <= 0:
        raise InventoryServiceError("Quantity must be greater than zero.")
    if not isinstance(idempotency_token, str) or not _IDEMPOTENCY_TOKEN_PATTERN.fullmatch(
        idempotency_token
    ):
        raise InventoryServiceError("The save request could not be identified.")
    if not isinstance(reason, str):
        raise InventoryServiceError("Reason must be text.")
    reason = reason.strip()
    if len(reason) > _MAX_REASON_LENGTH or any(
        not character.isprintable() for character in reason
    ):
        raise InventoryServiceError(
            f"Reason must be {_MAX_REASON_LENGTH} printable characters or fewer."
        )
    return int(quantity), reason


def _latest_snapshot(connection, store_id, sku_id, current_date):
    row = connection.execute(
        """
        SELECT snapshot_id, snapshot_date, on_hand, on_order, reserved, backorders
        FROM "InventorySnapshot"
        WHERE store_id = %s AND sku_id = %s
        ORDER BY snapshot_date DESC, created_at DESC, snapshot_id DESC
        LIMIT 1
        FOR UPDATE
        """,
        (store_id, sku_id),
    ).fetchone()
    if row is None:
        raise InventoryServiceError(
            "No inventory snapshot exists for this store and SKU."
        )

    snapshot_id, snapshot_date, on_hand, on_order, reserved, backorders = row
    if snapshot_date > current_date:
        raise InventoryServiceError(
            "The latest inventory snapshot is dated in the future."
        )
    ledger_balance = connection.execute(
        """
        SELECT COALESCE(SUM(quantity), 0)
        FROM "InventoryEvent"
        WHERE store_id = %s AND sku_id = %s AND event_date <= %s
        """,
        (store_id, sku_id, snapshot_date),
    ).fetchone()[0]
    if int(on_hand) != int(ledger_balance):
        raise InventoryServiceError(
            "Inventory history does not reconcile to the latest snapshot; "
            "the adjustment was not saved."
        )
    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date,
        "on_hand": int(on_hand),
        "on_order": int(on_order),
        "reserved": int(reserved),
        "backorders": int(backorders),
    }


def _existing_request(
    connection,
    store_id,
    sku_id,
    reference_prefix,
    expected_event_type,
    expected_quantity,
    current_date,
):
    rows = connection.execute(
        """
        SELECT store_id, sku_id, event_id, event_type, quantity
        FROM "InventoryEvent"
        WHERE store_id = %s
          AND sku_id = %s
          AND reference_id LIKE %s
        """,
        (store_id, sku_id, f"{reference_prefix}%"),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise InventoryServiceError(
            "This save request matches multiple inventory events; no changes "
            "were made."
        )
    existing_store_id, existing_sku_id, event_id, event_type, quantity = rows[0]
    if existing_store_id != store_id or existing_sku_id != sku_id:
        raise InventoryServiceError(
            "This save request was already used for a different store or SKU."
        )
    if event_type != expected_event_type or int(quantity) != expected_quantity:
        raise InventoryServiceError(
            "This save request was already used for a different adjustment."
        )
    snapshot = _latest_snapshot(connection, store_id, sku_id, current_date)
    return {
        "status": "DUPLICATE",
        "duplicate": True,
        "event_id": event_id,
        "event_type": event_type,
        "quantity": int(quantity),
        "snapshot_date": snapshot["snapshot_date"],
        "on_hand": snapshot["on_hand"],
        "inventory_position": (
            snapshot["on_hand"]
            + snapshot["on_order"]
            - snapshot["reserved"]
            - snapshot["backorders"]
        ),
    }


def _save_in_transaction(
    connection,
    store_id,
    sku_id,
    adjustment_type,
    quantity,
    idempotency_token,
    reason,
):
    event_type, sign = _ADJUSTMENTS[adjustment_type]
    signed_quantity = sign * quantity
    reference_prefix = f"UI-{idempotency_token}|"
    reference_id = f"{reference_prefix}{reason}"

    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"stocklens:inventory-store:{store_id}",),
    )
    current_date = connection.execute(
        "SELECT CURRENT_DATE"
    ).fetchone()[0]
    duplicate = _existing_request(
        connection,
        store_id,
        sku_id,
        reference_prefix,
        event_type,
        signed_quantity,
        current_date,
    )
    if duplicate is not None:
        return duplicate

    eligible = connection.execute(
        """
        SELECT location.capacity_units
        FROM "Store" AS location
        JOIN "StoreSKU" AS assortment
          ON assortment.store_id = location.store_id
        JOIN "SKU" AS product
          ON product.sku_id = assortment.sku_id
        WHERE location.store_id = %s
          AND assortment.sku_id = %s
          AND location.active_flag
          AND assortment.assortment_status = 'ACTIVE'
          AND assortment.active_from <= CURRENT_DATE
          AND (assortment.active_to IS NULL OR CURRENT_DATE < assortment.active_to)
          AND product.lifecycle_state <> 'DISCONTINUED'
          AND product.launch_date <= CURRENT_DATE
          AND (
              product.discontinue_date IS NULL
              OR CURRENT_DATE < product.discontinue_date
          )
        """,
        (store_id, sku_id),
    ).fetchone()
    if eligible is None:
        raise InventoryServiceError(
            "This SKU is not currently eligible for the selected store."
        )
    capacity_units = int(eligible[0])

    snapshot = _latest_snapshot(connection, store_id, sku_id, current_date)
    on_hand_after = snapshot["on_hand"] + signed_quantity
    if on_hand_after < 0:
        raise InventoryServiceError(
            "The adjustment would make on-hand inventory negative."
        )

    current_store_units = connection.execute(
        """
        SELECT COALESCE(SUM(latest.on_hand + latest.on_order), 0)
        FROM (
            SELECT DISTINCT ON (sku_id) sku_id, on_hand, on_order
            FROM "InventorySnapshot"
            WHERE store_id = %s
            ORDER BY sku_id, snapshot_date DESC, created_at DESC, snapshot_id DESC
        ) AS latest
        """,
        (store_id,),
    ).fetchone()[0]
    projected_store_units = int(current_store_units) + signed_quantity
    if projected_store_units > capacity_units:
        raise InventoryServiceError(
            f"The adjustment would exceed store capacity "
            f"({projected_store_units} of {capacity_units} units)."
        )

    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ("stocklens:inventory-event-id",),
    )
    request_digest = hashlib.sha256(
        f"{store_id}|{sku_id}|{idempotency_token}".encode("utf-8")
    ).digest()
    first_event_number = (
        int.from_bytes(request_digest[:8], byteorder="big") % 99_999_999
    ) + 1
    event_id = None
    for offset in range(20):
        event_number = ((first_event_number - 1 + offset) % 99_999_999) + 1
        candidate_event_id = f"EVT-{event_number:08d}"
        connection.execute("SAVEPOINT stocklens_inventory_event")
        try:
            connection.execute(
                """
                INSERT INTO "InventoryEvent" (
                    event_id, store_id, sku_id, event_date, event_type,
                    quantity, reference_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    candidate_event_id,
                    store_id,
                    sku_id,
                    current_date,
                    event_type,
                    signed_quantity,
                    reference_id,
                ),
            )
        except psycopg.errors.UniqueViolation:
            connection.execute(
                "ROLLBACK TO SAVEPOINT stocklens_inventory_event"
            )
            connection.execute("RELEASE SAVEPOINT stocklens_inventory_event")
        else:
            connection.execute("RELEASE SAVEPOINT stocklens_inventory_event")
            event_id = candidate_event_id
            break
    if event_id is None:
        raise InventoryServiceError(
            "A unique inventory event ID could not be allocated; "
            "the adjustment was not saved."
        )

    snapshot_id = f"INV-{store_id}-{sku_id}-{current_date.isoformat()}"
    connection.execute(
        """
        INSERT INTO "InventorySnapshot" (
            snapshot_id, store_id, sku_id, snapshot_date, on_hand,
            on_order, reserved, backorders
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (store_id, sku_id, snapshot_date)
        DO UPDATE SET
            snapshot_id = EXCLUDED.snapshot_id,
            on_hand = EXCLUDED.on_hand,
            on_order = EXCLUDED.on_order,
            reserved = EXCLUDED.reserved,
            backorders = EXCLUDED.backorders,
            created_at = NOW()
        """,
        (
            snapshot_id,
            store_id,
            sku_id,
            current_date,
            on_hand_after,
            snapshot["on_order"],
            snapshot["reserved"],
            snapshot["backorders"],
        ),
    )
    return {
        "status": "SAVED",
        "duplicate": False,
        "event_id": event_id,
        "event_type": event_type,
        "quantity": signed_quantity,
        "snapshot_date": current_date,
        "on_hand": on_hand_after,
        "inventory_position": (
            on_hand_after
            + snapshot["on_order"]
            - snapshot["reserved"]
            - snapshot["backorders"]
        ),
    }


def save_inventory_adjustment(
    store_id,
    sku_id,
    adjustment_type,
    quantity,
    idempotency_token,
    reason="",
    connection_factory=None,
):
    """Persist one inventory adjustment in a transaction.

    The caller supplies the configured connection factory so dashboard secrets
    and local environment settings stay outside this service.
    """
    quantity, reason = _validate_request(
        store_id,
        sku_id,
        adjustment_type,
        quantity,
        idempotency_token,
        reason,
    )
    if connection_factory is None:
        raise InventoryServiceError(
            "A configured database connection is required to save inventory."
        )

    connection = connection_factory()
    try:
        with connection.transaction():
            result = _save_in_transaction(
                connection,
                store_id,
                sku_id,
                adjustment_type,
                quantity,
                idempotency_token,
                reason,
            )
        return result
    except InventoryServiceError:
        raise
    except psycopg.Error as error:
        if error.sqlstate == "42501":
            raise InventoryServiceError(
                "The configured database role lacks permission for inventory "
                "adjustments. Grant only the required table access and "
                "row-scoped policies; do not disable row-level security."
            ) from None
        raise InventoryServiceError(
            "Inventory adjustment could not be saved; no changes were committed."
        ) from None
    finally:
        connection.close()
