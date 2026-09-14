"""Startup validation: checks the config against the live source schema."""

from obs_tool.config.config_models import AppConfig, TableConfig
from obs_tool.config.loader import resolve_source_config


class ConfigValidationError(Exception):
    """Raised when a structurally-valid config fails a startup check against live schema."""


def validate_columns_exist(table: TableConfig, schema: dict) -> None:
    """updated_at_column, checks columns, expectations columns must all exist (spec §7)."""
    actual_columns = set(schema.keys())
    referenced = set()
    if table.updated_at_column:
        referenced.add(table.updated_at_column)
    if table.checks and table.checks.null_rate and table.checks.null_rate.exclude:
        referenced.update(table.checks.null_rate.exclude)
    if table.expectations:
        referenced.update(e.column for e in table.expectations.values)
        referenced.update(e.column for e in table.expectations.schema_)

    missing = referenced - actual_columns
    if missing:
        raise ConfigValidationError(
            f"table '{table.name}' references unknown column(s): {', '.join(sorted(missing))}"
        )


def validate_exclude_not_all_columns(table: TableConfig, schema: dict) -> None:
    """exclude covering every column leaves nothing to check (spec §7)."""
    if table.checks and table.checks.null_rate and table.checks.null_rate.exclude:
        if set(table.checks.null_rate.exclude) >= set(schema.keys()):
            raise ConfigValidationError(
                f"table '{table.name}': null_rate.exclude covers every column — nothing left to check"
            )


def validate_at_least_one_enabled_check(table: TableConfig, defaults) -> None:
    """A table with every check disabled (after merge) is a meaningless entry (spec §7)."""
    effective = resolve_source_config(defaults, table.checks)
    if not (effective.volume.enabled or effective.null_rate.enabled or effective.schema_drift.enabled or table.cadence):
        raise ConfigValidationError(f"table '{table.name}' has no enabled checks")


def validate_schema_expectations(table: TableConfig, schema: dict) -> None:
    """Declared expectations.schema entries must match the live column's actual
    type and nullability (spec §6.3) — not just exist, but match.
    """
    if not table.expectations:
        return
    for expectation in table.expectations.schema_:
        actual = schema.get(expectation.column)
        if actual is None:
            continue  # already caught by validate_columns_exist
        if actual["type"] != expectation.type:
            raise ConfigValidationError(
                f"table '{table.name}' column '{expectation.column}': expected type "
                f"'{expectation.type}', found '{actual['type']}'"
            )
        if actual["nullable"] != expectation.nullable:
            raise ConfigValidationError(
                f"table '{table.name}' column '{expectation.column}': expected nullable="
                f"{expectation.nullable}, found {actual['nullable']}"
            )


def validate_config_against_schema(config: AppConfig, get_schema) -> None:
    """Run all startup checks. get_schema(table_name) -> dict is injected so
    this stays testable without a real DB connection. get_schema is expected
    to raise if the table itself doesn't exist (your connector already does this).
    """
    for table in config.source.tables:
        schema = get_schema(table.name)
        validate_columns_exist(table, schema)
        validate_exclude_not_all_columns(table, schema)
        validate_at_least_one_enabled_check(table, config.defaults)
        validate_schema_expectations(table, schema)