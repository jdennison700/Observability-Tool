"""Tests for startup validation checks against a (fake) live schema."""

import os

import pytest

from obs_tool.config.config_models import AppConfig, DefaultConfig, TableConfig
from obs_tool.config.startup_validation import (
    ConfigValidationError,
    validate_at_least_one_enabled_check,
    validate_columns_exist,
    validate_config_against_schema,
    validate_env_vars,
    validate_exclude_not_all_columns,
    validate_schema_expectations,
    validate_storage_path,
)


def make_app_config(tmp_path, **table_overrides):
    table = {"name": "public.t", **table_overrides}
    return AppConfig.model_validate(
        {
            "project": {
                "owner_email": "me@example.com",
                "scan_interval": 6,
                "storage_path": str(tmp_path),
            },
            "source": {
                "name": "warehouse",
                "type": "postgres",
                "connection_env": "WAREHOUSE_DSN",
                "tables": [table],
            },
        }
    )


COLUMN_SCHEMA = {
    "id": {"type": "integer", "nullable": False},
    "updated_at": {"type": "timestamp", "nullable": False},
    "status": {"type": "string", "nullable": True},
}


class TestValidateEnvVars:
    def test_missing_env_var_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("WAREHOUSE_DSN", raising=False)
        config = make_app_config(tmp_path)
        with pytest.raises(ConfigValidationError, match="WAREHOUSE_DSN"):
            validate_env_vars(config)

    def test_present_env_var_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WAREHOUSE_DSN", "postgres://x")
        config = make_app_config(tmp_path)
        validate_env_vars(config)

    def test_missing_connection_env_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WAREHOUSE_DSN", "postgres://x")
        config = make_app_config(tmp_path)
        config.source.connection_env = ""
        with pytest.raises(ConfigValidationError, match="Warehouse configuration"):
            validate_env_vars(config)


class TestValidateStoragePath:
    def test_nonexistent_path_raises(self, tmp_path):
        config = make_app_config(tmp_path)
        config.project.storage_path = tmp_path / "does_not_exist"
        with pytest.raises(ConfigValidationError, match="does not exist"):
            validate_storage_path(config)

    def test_existing_writable_path_passes(self, tmp_path):
        config = make_app_config(tmp_path)
        validate_storage_path(config)

    def test_unwritable_path_raises(self, tmp_path, monkeypatch):
        # os.chmod does not reliably restrict directory write access on
        # Windows, so simulate the unwritable case directly via os.access.
        config = make_app_config(tmp_path)
        monkeypatch.setattr(os, "access", lambda path, mode: False)
        with pytest.raises(ConfigValidationError, match="not writable"):
            validate_storage_path(config)


class TestValidateColumnsExist:
    def test_unknown_updated_at_column_raises(self):
        table = TableConfig(name="t", updated_at_column="bogus")
        with pytest.raises(ConfigValidationError, match="bogus"):
            validate_columns_exist(table, COLUMN_SCHEMA)

    def test_known_updated_at_column_passes(self):
        table = TableConfig(name="t", updated_at_column="updated_at")
        validate_columns_exist(table, COLUMN_SCHEMA)

    def test_unknown_exclude_column_raises(self):
        table = TableConfig(
            name="t", checks={"null_rate": {"exclude": ["bogus"]}}
        )
        with pytest.raises(ConfigValidationError, match="bogus"):
            validate_columns_exist(table, COLUMN_SCHEMA)

    def test_unknown_expectation_value_column_raises(self):
        table = TableConfig(
            name="t",
            expectations={"values": [{"column": "bogus", "op": "not_null"}]},
        )
        with pytest.raises(ConfigValidationError, match="bogus"):
            validate_columns_exist(table, COLUMN_SCHEMA)

    def test_unknown_expectation_schema_column_raises(self):
        table = TableConfig(
            name="t",
            expectations={"schema": [{"column": "bogus", "type": "integer"}]},
        )
        with pytest.raises(ConfigValidationError, match="bogus"):
            validate_columns_exist(table, COLUMN_SCHEMA)

    def test_all_known_columns_passes(self):
        table = TableConfig(
            name="t",
            updated_at_column="updated_at",
            checks={"null_rate": {"exclude": ["status"]}},
            expectations={
                "schema": [{"column": "id", "type": "integer", "nullable": False}],
                "values": [{"column": "status", "op": "not_null"}],
            },
        )
        validate_columns_exist(table, COLUMN_SCHEMA)


class TestValidateExcludeNotAllColumns:
    def test_exclude_covering_all_columns_raises(self):
        table = TableConfig(
            name="t",
            checks={"null_rate": {"exclude": list(COLUMN_SCHEMA.keys())}},
        )
        with pytest.raises(ConfigValidationError, match="nothing left to check"):
            validate_exclude_not_all_columns(table, COLUMN_SCHEMA)

    def test_exclude_covering_some_columns_passes(self):
        table = TableConfig(name="t", checks={"null_rate": {"exclude": ["status"]}})
        validate_exclude_not_all_columns(table, COLUMN_SCHEMA)

    def test_no_exclude_passes(self):
        table = TableConfig(name="t")
        validate_exclude_not_all_columns(table, COLUMN_SCHEMA)


class TestValidateAtLeastOneEnabledCheck:
    def test_all_checks_disabled_no_cadence_raises(self):
        table = TableConfig(
            name="t",
            checks={
                "volume": {"enabled": False},
                "null_rate": {"enabled": False},
                "schema_drift": {"enabled": False},
            },
        )
        with pytest.raises(ConfigValidationError, match="no enabled checks"):
            validate_at_least_one_enabled_check(table, DefaultConfig())

    def test_cadence_alone_counts_as_enabled(self):
        table = TableConfig(
            name="t",
            cadence=24,
            checks={
                "volume": {"enabled": False},
                "null_rate": {"enabled": False},
                "schema_drift": {"enabled": False},
            },
        )
        validate_at_least_one_enabled_check(table, DefaultConfig())

    def test_default_checks_enabled_passes(self):
        table = TableConfig(name="t")
        validate_at_least_one_enabled_check(table, DefaultConfig())

    def test_one_check_enabled_passes(self):
        table = TableConfig(
            name="t",
            checks={
                "volume": {"enabled": False},
                "null_rate": {"enabled": False},
                "schema_drift": {"enabled": True},
            },
        )
        validate_at_least_one_enabled_check(table, DefaultConfig())


class TestValidateSchemaExpectations:
    def test_no_expectations_passes(self):
        table = TableConfig(name="t")
        validate_schema_expectations(table, COLUMN_SCHEMA)

    def test_type_mismatch_raises(self):
        table = TableConfig(
            name="t",
            expectations={"schema": [{"column": "id", "type": "string"}]},
        )
        with pytest.raises(ConfigValidationError, match="expected type"):
            validate_schema_expectations(table, COLUMN_SCHEMA)

    def test_nullable_mismatch_raises(self):
        table = TableConfig(
            name="t",
            expectations={
                "schema": [{"column": "id", "type": "integer", "nullable": True}]
            },
        )
        with pytest.raises(ConfigValidationError, match="nullable"):
            validate_schema_expectations(table, COLUMN_SCHEMA)

    def test_matching_expectation_passes(self):
        table = TableConfig(
            name="t",
            expectations={
                "schema": [{"column": "id", "type": "integer", "nullable": False}]
            },
        )
        validate_schema_expectations(table, COLUMN_SCHEMA)

    def test_unknown_column_skipped_already_caught_elsewhere(self):
        table = TableConfig(
            name="t",
            expectations={"schema": [{"column": "bogus", "type": "integer"}]},
        )
        # Should not raise here — validate_columns_exist is responsible for this case.
        validate_schema_expectations(table, COLUMN_SCHEMA)


class TestValidateConfigAgainstSchema:
    def test_full_valid_config_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WAREHOUSE_DSN", "postgres://x")
        config = make_app_config(
            tmp_path, updated_at_column="updated_at", cadence=24
        )

        def get_schema(name):
            return COLUMN_SCHEMA

        validate_config_against_schema(config, get_schema)

    def test_env_var_checked_before_touching_schema(self, tmp_path, monkeypatch):
        monkeypatch.delenv("WAREHOUSE_DSN", raising=False)
        config = make_app_config(tmp_path)

        def get_schema(name):
            raise AssertionError("get_schema should not be called before env check")

        with pytest.raises(ConfigValidationError, match="WAREHOUSE_DSN"):
            validate_config_against_schema(config, get_schema)

    def test_bad_column_reference_propagates(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WAREHOUSE_DSN", "postgres://x")
        config = make_app_config(tmp_path, updated_at_column="bogus")

        def get_schema(name):
            return COLUMN_SCHEMA

        with pytest.raises(ConfigValidationError, match="bogus"):
            validate_config_against_schema(config, get_schema)
