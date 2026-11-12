from copy import deepcopy
import re

import pytest

from Backend.database import loader


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakePostgresConnection:
    def __init__(self, schema, initial_rows=None):
        self.schema = schema
        self.rows = deepcopy(initial_rows or {})
        self.transaction_start = deepcopy(self.rows)
        self.savepoints = {}
        self.committed = False
        self.rollback_count = 0
        self.closed = False

    def execute(self, query, parameters=None):
        query_text = (
            query.as_string(None)
            if hasattr(query, "as_string")
            else query
        )
        parameters = tuple(parameters or ())
        if query_text == "BEGIN":
            self.transaction_start = deepcopy(self.rows)
            return FakeCursor()
        if query_text.startswith("SAVEPOINT "):
            name = query_text.split()[-1]
            self.savepoints[name] = deepcopy(self.rows)
            return FakeCursor()
        if query_text.startswith("ROLLBACK TO SAVEPOINT "):
            name = query_text.split()[-1]
            self.rows = deepcopy(self.savepoints[name])
            return FakeCursor()
        if query_text.startswith("RELEASE SAVEPOINT "):
            self.savepoints.pop(query_text.split()[-1], None)
            return FakeCursor()
        if query_text.startswith("INSERT INTO "):
            table_name = re.search(r'INSERT INTO "[^"]+"\."([^"]+)"', query_text).group(1)
            column_text = re.search(r'\((.*?)\) VALUES', query_text).group(1)
            columns = re.findall(r'"([^"]+)"', column_text)
            table = self.schema[table_name]
            row_width = len(columns)
            inserted = []
            for start in range(0, len(parameters), row_width):
                values = parameters[start:start + row_width]
                row = dict(zip(columns, values))
                key = tuple(row[column] for column in table.primary_key)
                existing = self.rows.setdefault(table_name, {}).get(key)
                if existing is None:
                    self.rows[table_name][key] = row
                    inserted.append(tuple(row[column] for column in columns))
                elif "ON CONFLICT" not in query_text:
                    raise loader.psycopg.IntegrityError("duplicate key")
            return FakeCursor(inserted)
        if query_text.startswith("SELECT "):
            selected = re.search(r'SELECT (.*?) FROM', query_text).group(1)
            columns = re.findall(r'"([^"]+)"', selected)
            table_name = re.search(r'FROM "[^"]+"\."([^"]+)"', query_text).group(1)
            table = self.schema[table_name]
            key_width = len(table.primary_key)
            matching_rows = []
            table_rows = self.rows.get(table_name, {})
            for start in range(0, len(parameters), key_width):
                key = tuple(parameters[start:start + key_width])
                row = table_rows.get(key)
                if row is not None:
                    matching_rows.append(tuple(row[column] for column in columns))
            return FakeCursor(matching_rows)
        return FakeCursor()

    def commit(self):
        self.committed = True
        self.transaction_start = deepcopy(self.rows)

    def rollback(self):
        self.rows = deepcopy(self.transaction_start)
        self.rollback_count += 1

    def close(self):
        self.closed = True


def _sku_only_report():
    report = loader.preflight_dataset()
    report.rows = {"SKU": report.rows["SKU"][:2]}
    report.source_row_counts = {"SKU": 2}
    report.schema = {"SKU": report.schema["SKU"]}
    report.dependency_order = ["SKU"]
    return report


def test_schema_order_includes_composite_foreign_key_dependencies():
    schema = loader.parse_schema()
    insertion_order = loader.get_insertion_order(schema)
    recommendation_foreign_keys = schema["PurchaseRecommendation"].foreign_keys

    assert len(schema) == 16
    assert insertion_order.index("SKU") < insertion_order.index("StoreSKU")
    assert insertion_order.index("StoreSKU") < insertion_order.index("PurchaseRecommendation")
    assert insertion_order.index("SupplierSKU") < insertion_order.index(
        "PurchaseRecommendation"
    )
    assert insertion_order.index("ReorderPolicy") < insertion_order.index(
        "PurchaseRecommendation"
    )
    assert any(
        key.columns == ("supplier_sku_id", "sku_id")
        and key.referenced_table == "SupplierSKU"
        for key in recommendation_foreign_keys
    )
    assert any(
        key.columns == ("policy_id", "store_id", "sku_id")
        and key.referenced_table == "ReorderPolicy"
        for key in recommendation_foreign_keys
    )


def test_constraint_comparison_reports_missing_unique_constraint():
    schema = loader.parse_schema()
    expected_unique_keys = loader._expected_unique_keys(schema)
    missing_key = sorted(expected_unique_keys)[0]
    actual_unique_keys = expected_unique_keys - {missing_key}
    issues = []

    loader._report_unique_constraint_differences(
        schema,
        actual_unique_keys,
        issues,
    )

    assert len(issues) == 1
    assert "Missing UNIQUE constraint" in issues[0]
    assert missing_key[0] in issues[0]


def test_constraint_comparison_reports_missing_check_constraint():
    schema = loader.parse_schema()
    expected_definitions = {
        (table.name, check.name): f"CHECK ({check.expression})"
        for table in schema.values()
        for check in table.check_constraints
    }
    missing_key = sorted(expected_definitions)[0]
    actual_definitions = {
        key: (definition, True)
        for key, definition in expected_definitions.items()
        if key != missing_key
    }
    issues = []

    loader._report_check_constraint_differences(
        schema,
        expected_definitions,
        actual_definitions,
        issues,
    )

    assert issues == [f"Missing CHECK constraint {missing_key[0]}.{missing_key[1]}."]


def test_constraint_comparison_reports_mismatched_check_definition():
    schema = loader.parse_schema()
    expected_definitions = {
        (table.name, check.name): f"CHECK ({check.expression})"
        for table in schema.values()
        for check in table.check_constraints
    }
    key = sorted(expected_definitions)[0]
    actual_definitions = {
        constraint_key: (definition, True)
        for constraint_key, definition in expected_definitions.items()
    }
    actual_definitions[key] = ("CHECK (false)", True)
    issues = []

    loader._report_check_constraint_differences(
        schema,
        expected_definitions,
        actual_definitions,
        issues,
    )

    assert len(issues) == 1
    assert f"Mismatched CHECK constraint {key[0]}.{key[1]}" in issues[0]


def test_test_profile_preflight_accepts_empty_tables_and_checks_all_rows():
    report = loader.preflight_dataset()

    assert report.valid, report.issues
    assert report.source_row_counts["AnomalyFixture"] == 0
    assert report.source_row_counts["ValidationIssue"] == 0
    assert report.total_rows == 18873


def test_csv_header_must_match_schema(tmp_path):
    schema = loader.parse_schema()
    csv_path = tmp_path / "SKU.csv"
    csv_path.write_text("wrong_header\n", encoding="utf-8")

    with pytest.raises(loader.LoaderError, match="header does not match schema"):
        loader._read_table_csv(csv_path, schema["SKU"])


def test_database_dry_run_rolls_back_after_success(monkeypatch):
    report = loader.preflight_dataset()

    class FakeConnection:
        def __init__(self):
            self.rollback_count = 0
            self.closed = False

        def execute(self, query, parameters=None):
            return None

        def rollback(self):
            self.rollback_count += 1

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(
        loader,
        "inspect_database_schema",
        lambda connection, schema: "public",
    )
    monkeypatch.setattr(
        loader,
        "_insert_dataset_rows",
        lambda connection, report, schema_name, idempotent=False: (
            report.total_rows,
            0,
        ),
    )

    result = loader.run_database_dry_run(
        report,
        connection_factory=lambda: connection,
    )

    assert result == {
        "inserted_rows_tested": report.total_rows,
        "rolled_back": True,
        "schema_name": "public",
    }
    assert connection.rollback_count == 1
    assert connection.closed


def test_database_dry_run_rolls_back_and_preserves_failed_row(monkeypatch):
    report = loader.preflight_dataset()

    class FakeConnection:
        def __init__(self):
            self.rollback_count = 0
            self.closed = False

        def execute(self, query, parameters=None):
            return None

        def rollback(self):
            self.rollback_count += 1

        def close(self):
            self.closed = True

    connection = FakeConnection()
    failure = loader.RowInsertError(
        "SalesHistory",
        42,
        "SALE-000041",
        "SQLSTATE 23503: database rejected the row",
    )
    monkeypatch.setattr(
        loader,
        "inspect_database_schema",
        lambda connection, schema: "public",
    )

    def fail_insert(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        loader,
        "_insert_dataset_rows",
        fail_insert,
    )

    with pytest.raises(loader.RowInsertError) as error:
        loader.run_database_dry_run(
            report,
            connection_factory=lambda: connection,
        )

    assert error.value.table_name == "SalesHistory"
    assert error.value.csv_row_number == 42
    assert error.value.primary_key == "SALE-000041"
    assert connection.rollback_count == 1
    assert connection.closed


def test_batch_insert_fallback_reports_the_exact_failed_csv_row():
    report = loader.preflight_dataset()
    sku_rows = report.rows["SKU"][:2]
    for table_name in report.rows:
        report.rows[table_name] = []
        report.source_row_counts[table_name] = 0
    report.rows["SKU"] = sku_rows
    report.source_row_counts["SKU"] = 2
    failed_sku_id = sku_rows[1]["sku_id"]

    class FakeConnection:
        def execute(self, query, parameters=None):
            if parameters and len(parameters) > len(report.schema["SKU"].columns):
                raise loader.psycopg.IntegrityError("batch rejected")
            if parameters and parameters[0] == failed_sku_id:
                raise loader.psycopg.IntegrityError("row rejected")
            return None

    with pytest.raises(loader.RowInsertError) as error:
        loader._insert_dataset_rows(
            FakeConnection(),
            report,
            "public",
        )

    assert error.value.table_name == "SKU"
    assert error.value.csv_row_number == 3
    assert error.value.primary_key == failed_sku_id


def test_idempotent_batch_inserts_rows_on_first_load():
    report = _sku_only_report()
    connection = FakePostgresConnection(report.schema)

    inserted, skipped = loader._insert_dataset_rows(
        connection,
        report,
        "public",
        idempotent=True,
    )

    assert (inserted, skipped) == (2, 0)
    assert len(connection.rows["SKU"]) == 2


def test_idempotent_batch_skips_identical_rows_on_repeated_load():
    report = _sku_only_report()
    connection = FakePostgresConnection(report.schema)

    first_result = loader._insert_dataset_rows(
        connection,
        report,
        "public",
        idempotent=True,
    )
    second_result = loader._insert_dataset_rows(
        connection,
        report,
        "public",
        idempotent=True,
    )

    assert first_result == (2, 0)
    assert second_result == (0, 2)
    assert len(connection.rows["SKU"]) == 2


def test_conflicting_existing_data_reports_key_and_rolls_back(monkeypatch):
    report = _sku_only_report()
    first_row = dict(report.rows["SKU"][0])
    first_row["unit_price"] += 1
    initial_rows = {
        "SKU": {
            (first_row["sku_id"],): first_row,
        }
    }
    connection = FakePostgresConnection(report.schema, initial_rows)
    monkeypatch.setattr(
        loader,
        "inspect_database_schema",
        lambda connection, schema: "public",
    )

    with pytest.raises(loader.RowInsertError) as error:
        loader.load_dataset_idempotently(
            report,
            confirm_commit=True,
            connection_factory=lambda: connection,
        )

    assert error.value.table_name == "SKU"
    assert error.value.csv_row_number == 2
    assert error.value.primary_key == first_row["sku_id"]
    assert connection.rollback_count == 1
    assert not connection.committed
    assert connection.rows == initial_rows
    assert connection.closed


def test_invalid_preflight_does_not_open_database_connection():
    report = loader.preflight_dataset()
    report.issues.append("test issue")

    def fail_if_connected():
        pytest.fail("database connection must not be opened")

    with pytest.raises(loader.LoaderError, match="Preflight failed"):
        loader.run_database_dry_run(report, connection_factory=fail_if_connected)
