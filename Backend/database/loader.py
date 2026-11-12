import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import uuid

import psycopg
from psycopg import sql

from config import (
    DATASET_VERSION,
    PROFILES,
    RANDOM_SEED,
    REFERENCE_DATE,
    SALES_START_DATE,
)
from Backend.database.connection import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = PROJECT_ROOT / "Backend" / "database" / "schema.sql"
GENERATED_DATA_DIRECTORY = PROJECT_ROOT / "data" / "generated"
HOLDOUT_ORIGIN_OFFSETS = (21, 14, 7)
EXPECTED_TABLE_COUNT = 16
INSERT_BATCH_SIZE = 250


@dataclass(frozen=True)
class ColumnDefinition:
    name: str
    sql_type: str
    nullable: bool
    length: int = None
    precision: int = None
    scale: int = None


@dataclass(frozen=True)
class ForeignKeyDefinition:
    columns: tuple
    referenced_table: str
    referenced_columns: tuple


@dataclass(frozen=True)
class CheckConstraintDefinition:
    name: str
    expression: str


@dataclass
class TableDefinition:
    name: str
    columns: list
    primary_key: tuple
    foreign_keys: list
    unique_keys: list
    check_constraints: list


@dataclass
class PreflightReport:
    schema: dict
    dependency_order: list
    rows: dict
    source_row_counts: dict
    issues: list
    profile_checks: list

    @property
    def valid(self):
        return not self.issues

    @property
    def total_rows(self):
        return sum(self.source_row_counts.values())


class LoaderError(Exception):
    pass


class DatabaseSchemaError(LoaderError):
    pass


class RowInsertError(LoaderError):
    def __init__(self, table_name, csv_row_number, primary_key, detail):
        self.table_name = table_name
        self.csv_row_number = csv_row_number
        self.primary_key = primary_key
        self.detail = detail
        super().__init__(
            f"{table_name}.csv row {csv_row_number}, primary key "
            f"{primary_key!r}: {detail}"
        )


def _split_sql_items(body):
    items = []
    start = 0
    depth = 0
    single_quoted = False
    double_quoted = False
    index = 0

    while index < len(body):
        character = body[index]
        if character == "'" and not double_quoted:
            if single_quoted and index + 1 < len(body) and body[index + 1] == "'":
                index += 2
                continue
            single_quoted = not single_quoted
        elif character == '"' and not single_quoted:
            double_quoted = not double_quoted
        elif not single_quoted and not double_quoted:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif character == "," and depth == 0:
                items.append(body[start:index].strip())
                start = index + 1
        index += 1

    final_item = body[start:].strip()
    if final_item:
        items.append(final_item)
    return items


def _parse_column_definition(item):
    match = re.match(
        r"^([A-Za-z_][A-Za-z_0-9]*)\s+"
        r"([A-Za-z]+(?:\s*\([^)]*\))?)\s*(.*)$",
        item,
        flags=re.DOTALL,
    )
    if not match:
        raise LoaderError(f"Unable to parse schema column definition: {item}")

    name = match.group(1)
    sql_type = re.sub(r"\s+", "", match.group(2)).upper()
    rest = match.group(3).upper()
    nullable = "NOT NULL" not in rest
    length = None
    precision = None
    scale = None

    type_parameters = re.search(r"\((\d+)(?:,(\d+))?\)", sql_type)
    if type_parameters:
        first = int(type_parameters.group(1))
        second = type_parameters.group(2)
        if sql_type.startswith("VARCHAR"):
            length = first
        elif sql_type.startswith("NUMERIC"):
            precision = first
            scale = int(second or 0)

    return ColumnDefinition(
        name=name,
        sql_type=sql_type,
        nullable=nullable,
        length=length,
        precision=precision,
        scale=scale,
    )


def parse_schema(schema_file=SCHEMA_FILE):
    schema_text = Path(schema_file).read_text(encoding="utf-8")
    table_pattern = re.compile(
        r'CREATE\s+TABLE\s+"(?P<name>[^"]+)"\s*'
        r"\((?P<body>.*?)\n\);",
        flags=re.IGNORECASE | re.DOTALL,
    )
    schema = {}

    for match in table_pattern.finditer(schema_text):
        table_name = match.group("name")
        columns = []
        primary_key = ()
        foreign_keys = []
        unique_keys = []
        check_constraints = []

        for item in _split_sql_items(match.group("body")):
            if item.upper().startswith("CONSTRAINT"):
                check_match = re.match(
                    r'CONSTRAINT\s+"?(?P<name>[A-Za-z_][A-Za-z_0-9]*)"?\s+'
                    r"CHECK\s*\((?P<expression>.*)\)\s*$",
                    item,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if check_match:
                    check_constraints.append(
                        CheckConstraintDefinition(
                            name=check_match.group("name"),
                            expression=check_match.group("expression").strip(),
                        )
                    )

                primary_match = re.search(
                    r"PRIMARY\s+KEY\s*\(([^)]*)\)",
                    item,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if primary_match:
                    primary_key = tuple(
                        value.strip().strip('"')
                        for value in primary_match.group(1).split(",")
                    )

                unique_match = re.search(
                    r"\bUNIQUE\s*\(([^)]*)\)",
                    item,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if unique_match:
                    unique_keys.append(
                        tuple(
                            value.strip().strip('"')
                            for value in unique_match.group(1).split(",")
                        )
                    )

                foreign_match = re.search(
                    r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*"
                    r"REFERENCES\s+\"(?P<table>[^\"]+)\"\s*"
                    r"\((?P<referenced>[^)]*)\)",
                    item,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if foreign_match:
                    foreign_keys.append(
                        ForeignKeyDefinition(
                            columns=tuple(
                                value.strip().strip('"')
                                for value in foreign_match.group(1).split(",")
                            ),
                            referenced_table=foreign_match.group("table"),
                            referenced_columns=tuple(
                                value.strip().strip('"')
                                for value in foreign_match.group(
                                    "referenced"
                                ).split(",")
                            ),
                        )
                    )
                continue

            columns.append(_parse_column_definition(item))

        if not primary_key:
            raise LoaderError(f"Schema table {table_name} has no primary key.")
        schema[table_name] = TableDefinition(
            name=table_name,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
            unique_keys=unique_keys,
            check_constraints=check_constraints,
        )

    if len(schema) != EXPECTED_TABLE_COUNT:
        raise LoaderError(
            f"Expected {EXPECTED_TABLE_COUNT} schema tables; parsed {len(schema)}."
        )

    for table in schema.values():
        column_names = {column.name for column in table.columns}
        if not set(table.primary_key).issubset(column_names):
            raise LoaderError(f"Invalid primary key definition for {table.name}.")
        for foreign_key in table.foreign_keys:
            if not set(foreign_key.columns).issubset(column_names):
                raise LoaderError(f"Invalid foreign key columns for {table.name}.")
            parent = schema.get(foreign_key.referenced_table)
            if parent is None:
                raise LoaderError(
                    f"{table.name} references unknown table "
                    f"{foreign_key.referenced_table}."
                )
            parent_key = (
                parent.primary_key,
                *parent.unique_keys,
            )
            if foreign_key.referenced_columns not in parent_key:
                raise LoaderError(
                    f"{table.name} references a non-unique key in "
                    f"{parent.name}: {foreign_key.referenced_columns}."
                )

    return schema


def get_insertion_order(schema):
    declaration_order = list(schema)
    dependencies = {
        table_name: {
            foreign_key.referenced_table
            for foreign_key in table.foreign_keys
            if foreign_key.referenced_table != table_name
        }
        for table_name, table in schema.items()
    }
    insertion_order = []
    inserted = set()

    while len(inserted) < len(schema):
        ready = [
            table_name
            for table_name in declaration_order
            if table_name not in inserted
            and dependencies[table_name].issubset(inserted)
        ]
        if not ready:
            unresolved = sorted(set(schema) - inserted)
            raise LoaderError(
                "Foreign-key dependency cycle or unresolved dependency: "
                + ", ".join(unresolved)
            )
        table_name = ready[0]
        insertion_order.append(table_name)
        inserted.add(table_name)

    return insertion_order


def _convert_value(raw_value, column):
    if raw_value == "":
        if column.nullable:
            return None
        raise ValueError("blank value is not allowed for a NOT NULL column")

    if column.sql_type.startswith("VARCHAR"):
        if column.length is not None and len(raw_value) > column.length:
            raise ValueError(
                f"value length {len(raw_value)} exceeds VARCHAR({column.length})"
            )
        return raw_value
    if column.sql_type == "TEXT":
        return raw_value
    if column.sql_type == "INTEGER":
        value = int(raw_value)
        if not -2_147_483_648 <= value <= 2_147_483_647:
            raise ValueError("integer is outside PostgreSQL INTEGER range")
        return value
    if column.sql_type.startswith("NUMERIC"):
        try:
            value = Decimal(raw_value)
        except InvalidOperation as error:
            raise ValueError("invalid numeric value") from error
        if not value.is_finite():
            raise ValueError("numeric value must be finite")
        decimal_places = max(-value.as_tuple().exponent, 0)
        integer_digits = max(value.copy_abs().adjusted() + 1, 0) if value else 0
        if column.scale is not None and decimal_places > column.scale:
            raise ValueError(
                f"numeric value has more than {column.scale} decimal places"
            )
        if (
            column.precision is not None
            and column.scale is not None
            and integer_digits > column.precision - column.scale
        ):
            raise ValueError(
                f"numeric value exceeds NUMERIC({column.precision},{column.scale})"
            )
        return value
    if column.sql_type == "BOOLEAN":
        normalized = raw_value.strip().lower()
        if normalized in {"true", "t", "1"}:
            return True
        if normalized in {"false", "f", "0"}:
            return False
        raise ValueError("boolean value must be true or false")
    if column.sql_type == "DATE":
        try:
            value = date.fromisoformat(raw_value)
        except ValueError as error:
            raise ValueError("date must use YYYY-MM-DD format") from error
        if value.isoformat() != raw_value:
            raise ValueError("date must use YYYY-MM-DD format")
        return value
    if column.sql_type == "TIMESTAMPTZ":
        normalized = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError as error:
            raise ValueError("invalid timestamp with time zone") from error
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a time zone")
        return value

    raise LoaderError(f"Unsupported schema data type: {column.sql_type}")


def _read_table_csv(csv_path, table):
    rows = []
    line_numbers = []
    with Path(csv_path).open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(csv_file)
        expected_columns = [column.name for column in table.columns]
        if reader.fieldnames != expected_columns:
            raise LoaderError(
                "header does not match schema; expected "
                + ", ".join(expected_columns)
            )

        for line_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise LoaderError(f"row {line_number} has extra CSV fields")
            converted = {}
            try:
                for column in table.columns:
                    converted[column.name] = _convert_value(
                        raw_row[column.name],
                        column,
                    )
            except (TypeError, ValueError) as error:
                raise LoaderError(f"row {line_number}: {error}") from error
            rows.append(converted)
            line_numbers.append(line_number)
    return rows, line_numbers


def _check_duplicate_keys(table, rows, line_numbers, key_columns, key_name, issues):
    seen = {}
    for row, line_number in zip(rows, line_numbers):
        key = tuple(row[column] for column in key_columns)
        if any(value is None for value in key):
            continue
        if key in seen:
            issues.append(
                f"{table.name}.csv rows {seen[key]} and {line_number} have "
                f"duplicate {key_name} {key!r}."
            )
        else:
            seen[key] = line_number


def _validate_keys(schema, rows_by_table, line_numbers_by_table, issues):
    for table_name, table in schema.items():
        rows = rows_by_table.get(table_name, [])
        line_numbers = line_numbers_by_table.get(table_name, [])
        _check_duplicate_keys(
            table,
            rows,
            line_numbers,
            table.primary_key,
            "primary key",
            issues,
        )
        for unique_key in table.unique_keys:
            _check_duplicate_keys(
                table,
                rows,
                line_numbers,
                unique_key,
                "unique key",
                issues,
            )

    for table_name, table in schema.items():
        for foreign_key in table.foreign_keys:
            parent_rows = rows_by_table.get(foreign_key.referenced_table, [])
            parent_keys = {
                tuple(row[column] for column in foreign_key.referenced_columns)
                for row in parent_rows
            }
            child_rows = rows_by_table.get(table_name, [])
            child_lines = line_numbers_by_table.get(table_name, [])
            for row, line_number in zip(child_rows, child_lines):
                key = tuple(row[column] for column in foreign_key.columns)
                if any(value is None for value in key):
                    continue
                if key not in parent_keys:
                    issues.append(
                        f"{table_name}.csv row {line_number} has invalid foreign "
                        f"key {foreign_key.columns}={key!r}; expected "
                        f"{foreign_key.referenced_table}"
                        f"{foreign_key.referenced_columns}."
                    )


def _check_profile_metadata(rows_by_table, issues, profile_checks):
    expected_profile = PROFILES["test"]
    expected_counts = {
        "SKU": expected_profile["sku_count"],
        "Store": expected_profile["store_count"],
        "Supplier": expected_profile["supplier_count"],
    }
    for table_name, expected_count in expected_counts.items():
        actual_count = len(rows_by_table.get(table_name, []))
        passed = actual_count == expected_count
        profile_checks.append(
            f"{table_name} test-profile count: {actual_count}/{expected_count}"
        )
        if not passed:
            issues.append(
                f"{table_name}.csv has {actual_count} rows; test profile requires "
                f"{expected_count}."
            )

    for table_name, rows in rows_by_table.items():
        if not rows or "created_at" not in rows[0]:
            continue
        mismatched_dates = [
            row["created_at"].date()
            for row in rows
            if row["created_at"].date() != REFERENCE_DATE
        ]
        if mismatched_dates:
            issues.append(
                f"{table_name}.csv created_at values do not all match "
                f"REFERENCE_DATE {REFERENCE_DATE}."
            )

    forecast_runs = rows_by_table.get("ForecastRun", [])
    if forecast_runs:
        seeds = {row["random_seed"] for row in forecast_runs}
        versions = {row["dataset_version"] for row in forecast_runs}
        expected_origins = {
            REFERENCE_DATE - timedelta(days=offset)
            for offset in HOLDOUT_ORIGIN_OFFSETS
        } | {REFERENCE_DATE}
        actual_origins = {row["forecast_origin"] for row in forecast_runs}
        if seeds != {RANDOM_SEED}:
            issues.append(
                f"ForecastRun.csv random_seed does not match configured test seed "
                f"{RANDOM_SEED}."
            )
        if versions != {DATASET_VERSION}:
            issues.append(
                "ForecastRun.csv dataset_version does not match config.py."
            )
        if actual_origins != expected_origins:
            issues.append(
                "ForecastRun.csv origins do not match the three holdouts and "
                "configured reference date."
            )
        profile_checks.append(
            f"ForecastRun seed/version/reference-date checks: "
            f"{'passed' if seeds == {RANDOM_SEED} and versions == {DATASET_VERSION} and actual_origins == expected_origins else 'failed'}"
        )

    sales_rows = rows_by_table.get("SalesHistory", [])
    for row in sales_rows:
        if not SALES_START_DATE <= row["sales_date"] <= REFERENCE_DATE:
            issues.append(
                "SalesHistory.csv contains a sales_date outside the configured "
                "test sales window."
            )
            break
    truth_rows = rows_by_table.get("GroundTruthDemand", [])
    for row in truth_rows:
        if not SALES_START_DATE <= row["demand_date"] <= REFERENCE_DATE:
            issues.append(
                "GroundTruthDemand.csv contains a demand_date outside the "
                "configured test sales window."
            )
            break


def preflight_dataset(
    csv_directory=GENERATED_DATA_DIRECTORY,
    schema_file=SCHEMA_FILE,
    verify_test_profile=True,
):
    schema = parse_schema(schema_file)
    dependency_order = get_insertion_order(schema)
    csv_directory = Path(csv_directory)
    issues = []
    profile_checks = []
    rows_by_table = {}
    line_numbers_by_table = {}
    source_row_counts = {}

    actual_csv_names = {
        path.stem
        for path in csv_directory.glob("*.csv")
        if path.is_file()
    }
    expected_csv_names = set(schema)
    for missing in sorted(expected_csv_names - actual_csv_names):
        issues.append(f"Missing required file: {missing}.csv")
    for extra in sorted(actual_csv_names - expected_csv_names):
        issues.append(f"Unrecognized CSV file: {extra}.csv")

    for table_name, table in schema.items():
        csv_path = csv_directory / f"{table_name}.csv"
        rows_by_table[table_name] = []
        line_numbers_by_table[table_name] = []
        source_row_counts[table_name] = 0
        if not csv_path.is_file():
            continue
        try:
            rows, line_numbers = _read_table_csv(csv_path, table)
        except (OSError, UnicodeError, csv.Error, LoaderError) as error:
            issues.append(f"{table_name}.csv: {error}")
            continue
        rows_by_table[table_name] = rows
        line_numbers_by_table[table_name] = line_numbers
        source_row_counts[table_name] = len(rows)

    _validate_keys(
        schema,
        rows_by_table,
        line_numbers_by_table,
        issues,
    )
    if verify_test_profile:
        _check_profile_metadata(rows_by_table, issues, profile_checks)

    return PreflightReport(
        schema=schema,
        dependency_order=dependency_order,
        rows=rows_by_table,
        source_row_counts=source_row_counts,
        issues=issues,
        profile_checks=profile_checks,
    )


def _database_type_matches(column, database_column):
    expected_types = {
        "VARCHAR": "character varying",
        "TEXT": "text",
        "INTEGER": "integer",
        "NUMERIC": "numeric",
        "BOOLEAN": "boolean",
        "DATE": "date",
        "TIMESTAMPTZ": "timestamp with time zone",
    }
    base_type = column.sql_type.split("(", 1)[0]
    return (
        database_column["data_type"] == expected_types.get(base_type)
        and database_column["is_nullable"] == column.nullable
        and (
            column.length is None
            or database_column["character_maximum_length"] == column.length
        )
        and (
            column.precision is None
            or (
                database_column["numeric_precision"] == column.precision
                and database_column["numeric_scale"] == column.scale
            )
        )
    )


def _expected_primary_keys(schema):
    return {
        (table.name, table.primary_key)
        for table in schema.values()
    }


def _expected_foreign_keys(schema):
    return {
        (
            table.name,
            foreign_key.columns,
            foreign_key.referenced_table,
            foreign_key.referenced_columns,
        )
        for table in schema.values()
        for foreign_key in table.foreign_keys
    }


def _expected_unique_keys(schema):
    return {
        (table.name, unique_key)
        for table in schema.values()
        for unique_key in table.unique_keys
    }


def _report_unique_constraint_differences(schema, actual_unique_keys, issues):
    expected_unique_keys = _expected_unique_keys(schema)
    for table_name, columns in sorted(expected_unique_keys - actual_unique_keys):
        issues.append(
            f"Missing UNIQUE constraint on {table_name}({', '.join(columns)})."
        )
    for table_name, columns in sorted(actual_unique_keys - expected_unique_keys):
        issues.append(
            f"Unexpected UNIQUE constraint on {table_name}({', '.join(columns)})."
        )


def _report_check_constraint_differences(
    schema,
    expected_definitions,
    actual_definitions,
    issues,
):
    expected_keys = {
        (table.name, check.name)
        for table in schema.values()
        for check in table.check_constraints
    }
    actual_keys = set(actual_definitions)
    for table_name, constraint_name in sorted(expected_keys - actual_keys):
        issues.append(
            f"Missing CHECK constraint {table_name}.{constraint_name}."
        )
    for table_name, constraint_name in sorted(actual_keys - expected_keys):
        issues.append(
            f"Unexpected CHECK constraint {table_name}.{constraint_name}."
        )

    for key in sorted(expected_keys & actual_keys):
        expected_definition = expected_definitions[key]
        actual_definition, validated = actual_definitions[key]
        if expected_definition != actual_definition:
            issues.append(
                f"Mismatched CHECK constraint {key[0]}.{key[1]}: "
                "definition differs from Backend/database/schema.sql."
            )
        if not validated:
            issues.append(
                f"CHECK constraint {key[0]}.{key[1]} is not validated."
            )


def _normalized_expected_check_definitions(connection, schema):
    expected_definitions = {}
    for table in schema.values():
        if not table.check_constraints:
            continue

        temp_table_name = (
            f"loader_check_{table.name.lower()}_{uuid.uuid4().hex[:8]}"
        )
        column_definitions = [
            sql.SQL("{} {}").format(
                sql.Identifier(column.name),
                sql.SQL(column.sql_type),
            )
            for column in table.columns
        ]
        check_definitions = [
            sql.SQL("CONSTRAINT {} CHECK ({})").format(
                sql.Identifier(check.name),
                sql.SQL(check.expression),
            )
            for check in table.check_constraints
        ]
        table_definition = sql.SQL(", ").join(
            column_definitions + check_definitions
        )
        connection.execute(
            sql.SQL("CREATE TEMP TABLE {} ({})").format(
                sql.Identifier(temp_table_name),
                table_definition,
            )
        )
        normalized_rows = connection.execute(
            """
            SELECT constraint_row.conname,
                   pg_get_constraintdef(constraint_row.oid, true)
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS table_class
              ON table_class.oid = constraint_row.conrelid
            JOIN pg_namespace AS table_namespace
              ON table_namespace.oid = table_class.relnamespace
            WHERE table_namespace.oid = pg_my_temp_schema()
              AND table_class.relname = %s
              AND constraint_row.contype = 'c'
            """,
            (temp_table_name,),
        ).fetchall()
        for constraint_name, definition in normalized_rows:
            expected_definitions[(table.name, constraint_name)] = definition
        connection.execute(
            sql.SQL("DROP TABLE IF EXISTS {}").format(
                sql.Identifier("pg_temp", temp_table_name)
            )
        )
    return expected_definitions


def inspect_database_schema(connection, expected_schema, schema_name=None):
    if schema_name is None:
        schema_name = connection.execute(
            "SELECT current_schema()"
        ).fetchone()[0]
    if not schema_name:
        raise DatabaseSchemaError("PostgreSQL did not report a current schema.")

    table_rows = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        """,
        (schema_name,),
    ).fetchall()
    actual_tables = {row[0] for row in table_rows}
    missing_tables = set(expected_schema) - actual_tables
    if missing_tables:
        raise DatabaseSchemaError(
            f"Database schema {schema_name!r} is missing project tables: "
            + ", ".join(sorted(missing_tables))
        )

    column_rows = connection.execute(
        """
        SELECT table_name, column_name, data_type, is_nullable,
               character_maximum_length, numeric_precision, numeric_scale,
               ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
        """,
        (schema_name,),
    ).fetchall()
    actual_columns = {}
    for row in column_rows:
        table_name, column_name, data_type, is_nullable = row[:4]
        actual_columns.setdefault(table_name, []).append(
            {
                "column_name": column_name,
                "data_type": data_type,
                "is_nullable": is_nullable == "YES",
                "character_maximum_length": row[4],
                "numeric_precision": row[5],
                "numeric_scale": row[6],
            }
        )

    schema_issues = []
    for table_name, table in expected_schema.items():
        actual = actual_columns.get(table_name, [])
        expected_names = [column.name for column in table.columns]
        actual_names = [column["column_name"] for column in actual]
        if actual_names != expected_names:
            schema_issues.append(
                f"{table_name} columns differ: expected {expected_names}, "
                f"found {actual_names}."
            )
            continue
        for expected_column, database_column in zip(table.columns, actual):
            if not _database_type_matches(expected_column, database_column):
                schema_issues.append(
                    f"{table_name}.{expected_column.name} type/nullability "
                    "differs from Backend/database/schema.sql."
                )

    primary_key_rows = connection.execute(
        """
        SELECT table_class.relname,
               array_agg(attribute.attname ORDER BY key_column.ordinality)
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS table_class
          ON table_class.oid = constraint_row.conrelid
        JOIN pg_namespace AS table_namespace
          ON table_namespace.oid = table_class.relnamespace
        CROSS JOIN LATERAL
          unnest(constraint_row.conkey) WITH ORDINALITY
          AS key_column(attribute_number, ordinality)
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = table_class.oid
         AND attribute.attnum = key_column.attribute_number
        WHERE constraint_row.contype = 'p'
          AND table_namespace.nspname = %s
        GROUP BY table_class.relname, constraint_row.conname
        """,
        (schema_name,),
    ).fetchall()
    actual_primary_keys = {
        (table_name, tuple(columns))
        for table_name, columns in primary_key_rows
        if table_name in expected_schema
    }
    missing_primary_keys = _expected_primary_keys(expected_schema) - actual_primary_keys
    if missing_primary_keys:
        schema_issues.append(
            "Database primary keys differ from Backend/database/schema.sql: "
            + repr(sorted(missing_primary_keys))
        )

    foreign_key_rows = connection.execute(
        """
        SELECT child_class.relname,
               constraint_row.conname,
               parent_class.relname,
               child_attribute.attname,
               parent_attribute.attname,
               child_key.ordinality
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS child_class
          ON child_class.oid = constraint_row.conrelid
        JOIN pg_namespace AS child_namespace
          ON child_namespace.oid = child_class.relnamespace
        JOIN pg_class AS parent_class
          ON parent_class.oid = constraint_row.confrelid
        CROSS JOIN LATERAL
          unnest(constraint_row.conkey) WITH ORDINALITY
          AS child_key(attribute_number, ordinality)
        JOIN LATERAL
          unnest(constraint_row.confkey) WITH ORDINALITY
          AS parent_key(attribute_number, ordinality)
          ON parent_key.ordinality = child_key.ordinality
        JOIN pg_attribute AS child_attribute
          ON child_attribute.attrelid = child_class.oid
         AND child_attribute.attnum = child_key.attribute_number
        JOIN pg_attribute AS parent_attribute
          ON parent_attribute.attrelid = parent_class.oid
         AND parent_attribute.attnum = parent_key.attribute_number
        WHERE constraint_row.contype = 'f'
          AND child_namespace.nspname = %s
        ORDER BY child_class.relname, constraint_row.conname,
                 child_key.ordinality
        """,
        (schema_name,),
    ).fetchall()
    grouped_foreign_keys = {}
    for table_name, constraint_name, parent_name, child_column, parent_column, _ in foreign_key_rows:
        if table_name not in expected_schema:
            continue
        key = (table_name, constraint_name, parent_name)
        grouped_foreign_keys.setdefault(key, ([], []))
        grouped_foreign_keys[key][0].append(child_column)
        grouped_foreign_keys[key][1].append(parent_column)
    actual_foreign_keys = {
        (
            table_name,
            tuple(child_columns),
            parent_name,
            tuple(parent_columns),
        )
        for (table_name, _, parent_name), (
            child_columns,
            parent_columns,
        ) in grouped_foreign_keys.items()
    }
    missing_foreign_keys = (
        _expected_foreign_keys(expected_schema) - actual_foreign_keys
    )
    if missing_foreign_keys:
        schema_issues.append(
            "Database foreign keys differ from Backend/database/schema.sql: "
            + repr(sorted(missing_foreign_keys))
        )

    unique_rows = connection.execute(
        """
        SELECT table_class.relname,
               array_agg(attribute.attname ORDER BY key_column.ordinality)
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS table_class
          ON table_class.oid = constraint_row.conrelid
        JOIN pg_namespace AS table_namespace
          ON table_namespace.oid = table_class.relnamespace
        CROSS JOIN LATERAL
          unnest(constraint_row.conkey) WITH ORDINALITY
          AS key_column(attribute_number, ordinality)
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = table_class.oid
         AND attribute.attnum = key_column.attribute_number
        WHERE constraint_row.contype = 'u'
          AND table_namespace.nspname = %s
        GROUP BY table_class.relname, constraint_row.conname
        """,
        (schema_name,),
    ).fetchall()
    actual_unique_keys = {
        (table_name, tuple(columns))
        for table_name, columns in unique_rows
        if table_name in expected_schema
    }
    _report_unique_constraint_differences(
        expected_schema,
        actual_unique_keys,
        schema_issues,
    )

    actual_check_rows = connection.execute(
        """
        SELECT table_class.relname, constraint_row.conname,
               pg_get_constraintdef(constraint_row.oid, true),
               constraint_row.convalidated
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS table_class
          ON table_class.oid = constraint_row.conrelid
        JOIN pg_namespace AS table_namespace
          ON table_namespace.oid = table_class.relnamespace
        WHERE constraint_row.contype = 'c'
          AND table_namespace.nspname = %s
        """,
        (schema_name,),
    ).fetchall()
    actual_check_definitions = {
        (table_name, constraint_name): (definition, validated)
        for table_name, constraint_name, definition, validated
        in actual_check_rows
        if table_name in expected_schema
    }
    expected_check_definitions = _normalized_expected_check_definitions(
        connection,
        expected_schema,
    )
    _report_check_constraint_differences(
        expected_schema,
        expected_check_definitions,
        actual_check_definitions,
        schema_issues,
    )

    if schema_issues:
        raise DatabaseSchemaError(" ".join(schema_issues))
    return schema_name


def _insert_statement(schema_name, table):
    column_sql = sql.SQL(", ").join(
        sql.Identifier(column.name) for column in table.columns
    )
    placeholders = sql.SQL(", ").join(
        sql.Placeholder() for _ in table.columns
    )
    return sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(schema_name, table.name),
        column_sql,
        placeholders,
    )


def _insert_batch_statement(schema_name, table, row_count):
    column_sql = sql.SQL(", ").join(
        sql.Identifier(column.name) for column in table.columns
    )
    row_placeholders = sql.SQL("({})").format(
        sql.SQL(", ").join(sql.Placeholder() for _ in table.columns)
    )
    values_sql = sql.SQL(", ").join(
        row_placeholders for _ in range(row_count)
    )
    return sql.SQL("INSERT INTO {} ({}) VALUES {}").format(
        sql.Identifier(schema_name, table.name),
        column_sql,
        values_sql,
    )


def _select_rows_by_primary_keys(schema_name, table, row_count):
    columns = sql.SQL(", ").join(
        sql.Identifier(column.name) for column in table.columns
    )
    primary_key_columns = sql.SQL(", ").join(
        sql.Identifier(column) for column in table.primary_key
    )
    key_placeholders = sql.SQL("({})").format(
        sql.SQL(", ").join(
            sql.Placeholder() for _ in table.primary_key
        )
    )
    keys_sql = sql.SQL(", ").join(
        key_placeholders for _ in range(row_count)
    )
    return sql.SQL("SELECT {} FROM {} WHERE ({}) IN ({})").format(
        columns,
        sql.Identifier(schema_name, table.name),
        primary_key_columns,
        keys_sql,
    )


def _insert_idempotent_batch(
    connection,
    schema_name,
    table,
    rows,
    csv_row_start,
):
    columns = [column.name for column in table.columns]
    insert = _insert_batch_statement(schema_name, table, len(rows))
    conflict_columns = sql.SQL(", ").join(
        sql.Identifier(column) for column in table.primary_key
    )
    insert = insert + sql.SQL(" ON CONFLICT ({}) DO NOTHING").format(
        conflict_columns
    )
    insert = insert + sql.SQL(" RETURNING {}").format(
        sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    )
    values = tuple(
        row[column]
        for row in rows
        for column in columns
    )
    inserted_rows = connection.execute(insert, values).fetchall()
    inserted_keys = {
        tuple(inserted_row[columns.index(column)] for column in table.primary_key)
        for inserted_row in inserted_rows
    }

    skipped_candidates = [
        (row, offset)
        for offset, row in enumerate(rows)
        if tuple(row[column] for column in table.primary_key) not in inserted_keys
    ]
    if not skipped_candidates:
        return len(inserted_rows), 0

    key_values = tuple(
        row[column]
        for row, _ in skipped_candidates
        for column in table.primary_key
    )
    existing_rows = connection.execute(
        _select_rows_by_primary_keys(
            schema_name,
            table,
            len(skipped_candidates),
        ),
        key_values,
    ).fetchall()
    existing_by_key = {
        tuple(
            existing_row[columns.index(column)]
            for column in table.primary_key
        ): existing_row
        for existing_row in existing_rows
    }
    for row, offset in skipped_candidates:
        key = tuple(row[column] for column in table.primary_key)
        expected = tuple(row[column] for column in columns)
        if existing_by_key.get(key) != expected:
            raise RowInsertError(
                table.name,
                csv_row_start + offset,
                _primary_key_value(row, table),
                "existing primary key contains different data",
            )
    return len(inserted_rows), len(skipped_candidates)


def _insert_idempotent_row(
    connection,
    schema_name,
    table,
    row,
    csv_row_number,
):
    columns = [column.name for column in table.columns]
    insert = _insert_statement(schema_name, table)
    conflict_columns = sql.SQL(", ").join(
        sql.Identifier(column) for column in table.primary_key
    )
    insert = insert + sql.SQL(" ON CONFLICT ({}) DO NOTHING").format(
        conflict_columns
    )
    insert = insert + sql.SQL(" RETURNING {}").format(
        sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    )
    values = tuple(row[column] for column in columns)
    if connection.execute(insert, values).fetchone() is not None:
        return 1, 0

    key_values = tuple(row[column] for column in table.primary_key)
    existing = connection.execute(
        _select_rows_by_primary_keys(schema_name, table, 1),
        key_values,
    ).fetchone()
    if existing != values:
        raise RowInsertError(
            table.name,
            csv_row_number,
            _primary_key_value(row, table),
            "existing primary key contains different data",
        )
    return 0, 1


def _primary_key_value(row, table):
    values = tuple(row[column] for column in table.primary_key)
    return values[0] if len(values) == 1 else values


def _safe_database_error(error):
    sqlstate = getattr(error, "sqlstate", None)
    diagnostic = getattr(error, "diag", None)
    message = getattr(diagnostic, "message_primary", None)
    if not message:
        message = "database rejected the row"
    if sqlstate:
        return f"SQLSTATE {sqlstate}: {message}"
    return message


def _insert_dataset_rows(
    connection,
    report,
    schema_name,
    idempotent=False,
):
    inserted_rows = 0
    skipped_rows = 0
    for table_name in report.dependency_order:
        table = report.schema[table_name]
        columns = [column.name for column in table.columns]
        insert = _insert_statement(schema_name, table)
        rows = report.rows[table_name]
        if not idempotent:
            for start in range(0, len(rows), INSERT_BATCH_SIZE):
                batch = rows[start:start + INSERT_BATCH_SIZE]
                csv_row_start = start + 2
                batch_values = tuple(
                    row[column]
                    for row in batch
                    for column in columns
                )
                connection.execute("SAVEPOINT loader_insert_batch")
                try:
                    connection.execute(
                        _insert_batch_statement(
                            schema_name,
                            table,
                            len(batch),
                        ),
                        batch_values,
                    )
                except psycopg.Error:
                    connection.execute(
                        "ROLLBACK TO SAVEPOINT loader_insert_batch"
                    )
                    for offset, row in enumerate(batch):
                        values = tuple(row[column] for column in columns)
                        try:
                            connection.execute(insert, values)
                        except psycopg.Error as error:
                            raise RowInsertError(
                                table_name,
                                csv_row_start + offset,
                                _primary_key_value(row, table),
                                _safe_database_error(error),
                            ) from None
                    connection.execute(
                        "RELEASE SAVEPOINT loader_insert_batch"
                    )
                else:
                    connection.execute(
                        "RELEASE SAVEPOINT loader_insert_batch"
                    )
                inserted_rows += len(batch)
            continue

        for start in range(0, len(rows), INSERT_BATCH_SIZE):
            batch = rows[start:start + INSERT_BATCH_SIZE]
            csv_row_start = start + 2
            connection.execute("SAVEPOINT loader_insert_batch")
            try:
                batch_inserted, batch_skipped = _insert_idempotent_batch(
                    connection,
                    schema_name,
                    table,
                    batch,
                    csv_row_start,
                )
            except psycopg.Error:
                connection.execute("ROLLBACK TO SAVEPOINT loader_insert_batch")
                for offset, row in enumerate(batch):
                    try:
                        row_inserted, row_skipped = _insert_idempotent_row(
                            connection,
                            schema_name,
                            table,
                            row,
                            csv_row_start + offset,
                        )
                    except RowInsertError:
                        raise
                    except psycopg.Error as error:
                        raise RowInsertError(
                            table_name,
                            csv_row_start + offset,
                            _primary_key_value(row, table),
                            _safe_database_error(error),
                        ) from None
                    inserted_rows += row_inserted
                    skipped_rows += row_skipped
                connection.execute("RELEASE SAVEPOINT loader_insert_batch")
            else:
                connection.execute("RELEASE SAVEPOINT loader_insert_batch")
                inserted_rows += batch_inserted
                skipped_rows += batch_skipped
    return inserted_rows, skipped_rows


def run_database_dry_run(
    report,
    connection_factory=get_connection,
):
    if not report.valid:
        raise LoaderError(
            "Preflight failed; database dry run was not started."
        )
    connection = connection_factory()
    inserted_rows = 0
    try:
        connection.execute("BEGIN")
        schema_name = inspect_database_schema(connection, report.schema)
        inserted_rows, _ = _insert_dataset_rows(
            connection,
            report,
            schema_name,
            idempotent=False,
        )
        connection.rollback()
        return {
            "inserted_rows_tested": inserted_rows,
            "rolled_back": True,
            "schema_name": schema_name,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_dataset_idempotently(
    report,
    confirm_commit=False,
    connection_factory=get_connection,
):
    if not confirm_commit:
        raise LoaderError(
            "Permanent loading requires explicit approval via confirm_commit=True."
        )
    if not report.valid:
        raise LoaderError("Preflight failed; permanent loading was not started.")

    connection = connection_factory()
    try:
        connection.execute("BEGIN")
        schema_name = inspect_database_schema(connection, report.schema)
        inserted_rows, skipped_rows = _insert_dataset_rows(
            connection,
            report,
            schema_name,
            idempotent=True,
        )
        connection.commit()
        return {
            "inserted_rows": inserted_rows,
            "identical_rows_skipped": skipped_rows,
            "schema_name": schema_name,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def print_preflight_report(report):
    print(f"Schema tables: {len(report.schema)}")
    print("Foreign-key insertion order:")
    print(" -> ".join(report.dependency_order))
    print("Expected rows per table:")
    for table_name in report.dependency_order:
        print(f"  {table_name}: {report.source_row_counts[table_name]}")
    print(f"Total expected rows: {report.total_rows}")
    for check in report.profile_checks:
        print(f"Profile check: {check}")
    if report.issues:
        print("Preflight issues:")
        for issue in report.issues:
            print(f"  - {issue}")
    else:
        print("Preflight result: PASS")
        print(
            "Seed provenance is explicit in ForecastRun.csv; other tables are "
            "cross-checked by test-profile counts, dates, IDs, and foreign keys."
        )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Preflight or rollback-test the generated test-profile CSVs."
    )
    parser.add_argument(
        "--mode",
        choices=["preflight", "dry-run"],
        required=True,
    )
    parser.add_argument(
        "--csv-directory",
        default=str(GENERATED_DATA_DIRECTORY),
    )
    parser.add_argument(
        "--schema-file",
        default=str(SCHEMA_FILE),
    )
    args = parser.parse_args(argv)

    try:
        report = preflight_dataset(
            args.csv_directory,
            args.schema_file,
            verify_test_profile=True,
        )
        print_preflight_report(report)
        if not report.valid:
            return 1
        if args.mode == "dry-run":
            result = run_database_dry_run(report)
            print(
                "Database dry run: PASS; "
                f"{result['inserted_rows_tested']} rows inserted inside "
                f"{result['schema_name']!r} and rolled back."
            )
            print("Permanent data changes: none.")
        return 0
    except RowInsertError as error:
        print(f"Database dry run: FAILED; {error}")
        print("The transaction was rolled back; permanent data changes: none.")
        return 1
    except (LoaderError, psycopg.Error, ConnectionError, ValueError) as error:
        print(f"Database loader: FAILED; {error}")
        print("Permanent data changes: none.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
