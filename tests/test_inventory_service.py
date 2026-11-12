from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, time, timezone
import hashlib
import re

import psycopg
import pytest

from Backend.services.inventory_service import (
    InventoryServiceError,
    save_inventory_adjustment,
)


STORE_ID = "STORE-000001"
SKU_ID = "SKU-000001"
TODAY = date(2026, 11, 12)
OLD_DATE = date(2026, 10, 22)
TOKEN = "a" * 24


def _event_id_candidate(store_id, sku_id, token, offset=0):
    digest = hashlib.sha256(
        f"{store_id}|{sku_id}|{token}".encode("utf-8")
    ).digest()
    first_number = int.from_bytes(digest[:8], byteorder="big") % 99_999_999 + 1
    number = ((first_number - 1 + offset) % 99_999_999) + 1
    return f"EVT-{number:08d}"


def _snapshot(snapshot_date, on_hand):
    return {
        "snapshot_id": f"INV-{STORE_ID}-{SKU_ID}-{snapshot_date.isoformat()}",
        "store_id": STORE_ID,
        "sku_id": SKU_ID,
        "snapshot_date": snapshot_date,
        "on_hand": on_hand,
        "on_order": 0,
        "reserved": 0,
        "backorders": 0,
        "created_at": datetime.combine(
            snapshot_date,
            time.min,
            tzinfo=timezone.utc,
        ),
    }


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeInventoryConnection:
    def __init__(self, *, capacity=100, eligible=True, fail_snapshot=False):
        self.today = TODAY
        self.capacity = capacity
        self.eligible = eligible
        self.fail_snapshot = fail_snapshot
        old_snapshot = _snapshot(OLD_DATE, 8)
        self.snapshots = [old_snapshot]
        self.events = [
            {
                "event_id": "EVT-00000001",
                "store_id": STORE_ID,
                "sku_id": SKU_ID,
                "event_date": OLD_DATE,
                "event_type": "RECEIPT",
                "quantity": 8,
                "reference_id": "TEST-OPENING-BALANCE",
            }
        ]
        self.lock_keys = []
        self.savepoints = {}
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False

    @contextmanager
    def transaction(self):
        before = deepcopy((self.snapshots, self.events))
        try:
            yield
        except Exception:
            self.snapshots, self.events = before
            self.rollback_count += 1
            raise
        else:
            self.commit_count += 1

    def close(self):
        self.closed = True

    def execute(self, query, parameters=None):
        query_text = str(query).strip()
        parameters = tuple(parameters or ())
        if "pg_advisory_xact_lock" in query_text:
            self.lock_keys.append(parameters[0])
            return FakeCursor()
        if query_text.startswith("SAVEPOINT "):
            self.savepoints[query_text.split()[-1]] = deepcopy(
                (self.snapshots, self.events)
            )
            return FakeCursor()
        if query_text.startswith("ROLLBACK TO SAVEPOINT "):
            name = query_text.split()[-1]
            self.snapshots, self.events = deepcopy(self.savepoints[name])
            return FakeCursor()
        if query_text.startswith("RELEASE SAVEPOINT "):
            self.savepoints.pop(query_text.split()[-1], None)
            return FakeCursor()
        if query_text.startswith("SELECT CURRENT_DATE"):
            return FakeCursor([(self.today,)])
        if "reference_id LIKE %s" in query_text:
            store_id, sku_id, pattern = parameters
            prefix = pattern[:-1]
            matches = [
                event
                for event in self.events
                if event["store_id"] == store_id
                and event["sku_id"] == sku_id
                and event["reference_id"].startswith(prefix)
            ]
            return FakeCursor(
                [
                    (
                        event["store_id"],
                        event["sku_id"],
                        event["event_id"],
                        event["event_type"],
                        event["quantity"],
                    )
                    for event in matches
                ]
            )
        if "SELECT location.capacity_units" in query_text:
            return (
                FakeCursor([(self.capacity,)])
                if self.eligible
                else FakeCursor()
            )
        if query_text.startswith("SELECT snapshot_id, snapshot_date"):
            store_id, sku_id = parameters
            candidates = [
                snapshot
                for snapshot in self.snapshots
                if snapshot["store_id"] == store_id
                and snapshot["sku_id"] == sku_id
            ]
            if not candidates:
                return FakeCursor()
            snapshot = max(
                candidates,
                key=lambda row: (
                    row["snapshot_date"],
                    row["created_at"],
                    row["snapshot_id"],
                ),
            )
            return FakeCursor(
                [
                    (
                        snapshot["snapshot_id"],
                        snapshot["snapshot_date"],
                        snapshot["on_hand"],
                        snapshot["on_order"],
                        snapshot["reserved"],
                        snapshot["backorders"],
                    )
                ]
            )
        if query_text.startswith("SELECT COALESCE(SUM(quantity), 0)"):
            store_id, sku_id, through_date = parameters
            total = sum(
                event["quantity"]
                for event in self.events
                if event["store_id"] == store_id
                and event["sku_id"] == sku_id
                and event["event_date"] <= through_date
            )
            return FakeCursor([(total,)])
        if "SELECT COALESCE(SUM(latest.on_hand + latest.on_order), 0)" in query_text:
            (store_id,) = parameters
            latest_by_sku = {}
            for snapshot in self.snapshots:
                if snapshot["store_id"] != store_id:
                    continue
                current = latest_by_sku.get(snapshot["sku_id"])
                if current is None or (
                    snapshot["snapshot_date"],
                    snapshot["created_at"],
                    snapshot["snapshot_id"],
                ) > (
                    current["snapshot_date"],
                    current["created_at"],
                    current["snapshot_id"],
                ):
                    latest_by_sku[snapshot["sku_id"]] = snapshot
            total = sum(
                row["on_hand"] + row["on_order"]
                for row in latest_by_sku.values()
            )
            return FakeCursor([(total,)])
        if query_text.startswith('INSERT INTO "InventoryEvent"'):
            (
                event_id,
                store_id,
                sku_id,
                event_date,
                event_type,
                quantity,
                reference_id,
            ) = parameters
            if any(
                event["event_id"] == event_id for event in self.events
            ):
                raise psycopg.errors.UniqueViolation("duplicate event ID")
            self.events.append(
                {
                    "event_id": event_id,
                    "store_id": store_id,
                    "sku_id": sku_id,
                    "event_date": event_date,
                    "event_type": event_type,
                    "quantity": quantity,
                    "reference_id": reference_id,
                }
            )
            return FakeCursor()
        if query_text.startswith('INSERT INTO "InventorySnapshot"'):
            if self.fail_snapshot:
                raise RuntimeError("simulated snapshot write failure")
            (
                snapshot_id,
                store_id,
                sku_id,
                snapshot_date,
                on_hand,
                on_order,
                reserved,
                backorders,
            ) = parameters
            existing = next(
                (
                    snapshot
                    for snapshot in self.snapshots
                    if snapshot["store_id"] == store_id
                    and snapshot["sku_id"] == sku_id
                    and snapshot["snapshot_date"] == snapshot_date
                ),
                None,
            )
            if existing is None:
                existing = _snapshot(snapshot_date, on_hand)
                self.snapshots.append(existing)
            existing.update(
                {
                    "snapshot_id": snapshot_id,
                    "on_hand": on_hand,
                    "on_order": on_order,
                    "reserved": reserved,
                    "backorders": backorders,
                    "created_at": datetime.combine(
                        snapshot_date,
                        time.min,
                        tzinfo=timezone.utc,
                    ),
                }
            )
            return FakeCursor()
        raise AssertionError(f"Unexpected SQL in fake connection: {query_text}")


def _save(connection, **overrides):
    values = {
        "store_id": STORE_ID,
        "sku_id": SKU_ID,
        "adjustment_type": "RECEIVE_STOCK",
        "quantity": 3,
        "idempotency_token": TOKEN,
        "reason": "cycle count",
        "connection_factory": lambda: connection,
    }
    values.update(overrides)
    return save_inventory_adjustment(**values)


def test_save_appends_event_and_current_day_snapshot_in_one_commit():
    connection = FakeInventoryConnection()

    result = _save(connection)

    assert result == {
        "status": "SAVED",
        "duplicate": False,
        "event_id": _event_id_candidate(STORE_ID, SKU_ID, TOKEN),
        "event_type": "ADJUSTMENT_IN",
        "quantity": 3,
        "snapshot_date": TODAY,
        "on_hand": 11,
        "inventory_position": 11,
    }
    assert len(connection.events) == 2
    assert len(connection.snapshots) == 2
    assert connection.snapshots[-1]["snapshot_date"] == TODAY
    assert connection.snapshots[0]["snapshot_date"] == OLD_DATE
    assert connection.commit_count == 1
    assert connection.rollback_count == 0
    assert connection.closed
    assert connection.lock_keys == [
        f"stocklens:inventory-store:{STORE_ID}",
        "stocklens:inventory-event-id",
    ]


def test_repeated_save_is_idempotent_and_same_day_snapshot_is_updated():
    connection = FakeInventoryConnection()
    first = _save(connection)
    second = _save(connection)

    assert first["status"] == "SAVED"
    assert second["status"] == "DUPLICATE"
    assert second["duplicate"] is True
    assert second["event_id"] == first["event_id"]
    assert second["on_hand"] == first["on_hand"]
    assert len(connection.events) == 2
    assert len(connection.snapshots) == 2
    assert connection.snapshots[0]["snapshot_date"] == OLD_DATE
    assert connection.snapshots[1]["on_hand"] == 11
    assert connection.commit_count == 2


def test_reused_token_with_different_adjustment_is_rejected():
    connection = FakeInventoryConnection()
    _save(connection)

    with pytest.raises(InventoryServiceError, match="already used"):
        _save(connection, quantity=4)

    assert len(connection.events) == 2
    assert connection.rollback_count == 1
    assert connection.closed


def test_failed_snapshot_write_rolls_back_inserted_event():
    connection = FakeInventoryConnection(fail_snapshot=True)

    with pytest.raises(RuntimeError, match="snapshot write failure"):
        _save(connection)

    assert len(connection.events) == 1
    assert len(connection.snapshots) == 1
    assert connection.rollback_count == 1
    assert connection.commit_count == 0
    assert connection.closed


def test_event_id_collision_retries_inside_a_savepoint():
    connection = FakeInventoryConnection()
    collision_id = _event_id_candidate(
        STORE_ID,
        SKU_ID,
        TOKEN,
    )
    connection.events.append(
        {
            "event_id": collision_id,
            "store_id": "STORE-000002",
            "sku_id": "SKU-000002",
            "event_date": OLD_DATE,
            "event_type": "RECEIPT",
            "quantity": 1,
            "reference_id": "OTHER-STORE-EVENT",
        }
    )

    result = _save(connection)

    assert result["event_id"] != collision_id
    assert result["event_id"] == _event_id_candidate(
        STORE_ID,
        SKU_ID,
        TOKEN,
        offset=1,
    )
    assert len(connection.events) == 3
    assert connection.commit_count == 1


@pytest.mark.parametrize(
    ("quantity", "capacity", "eligible", "message"),
    [
        (9, 100, True, "on-hand inventory negative"),
        (93, 100, True, "exceed store capacity"),
        (1, 100, False, "not currently eligible"),
    ],
)
def test_invalid_adjustment_is_rejected_without_database_changes(
    quantity,
    capacity,
    eligible,
    message,
):
    connection = FakeInventoryConnection(capacity=capacity, eligible=eligible)
    before = deepcopy((connection.events, connection.snapshots))

    with pytest.raises(InventoryServiceError, match=message):
        _save(
            connection,
            adjustment_type="REMOVE_STOCK" if quantity == 9 else "RECEIVE_STOCK",
            quantity=quantity,
        )

    assert (connection.events, connection.snapshots) == before
    assert connection.rollback_count == 1


def test_invalid_request_does_not_open_a_connection():
    def fail_if_connected():
        pytest.fail("connection should not open for an invalid request")

    with pytest.raises(InventoryServiceError, match="greater than zero"):
        save_inventory_adjustment(
            STORE_ID,
            SKU_ID,
            "RECEIVE_STOCK",
            0,
            TOKEN,
            connection_factory=fail_if_connected,
        )
