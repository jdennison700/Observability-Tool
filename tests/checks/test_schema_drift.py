"""Tests for the schema drift check (snapshot-vs-snapshot comparison)."""

import json

import pytest

from obs_tool.checks.schema_drift import METRIC_NAME, _severity_for, check_schema_drift
from obs_tool.config.config_models import TableConfig
from obs_tool.storage.sqlite import SqliteStorage


def col(type_: str, nullable: bool) -> dict:
    return {"type": type_, "nullable": nullable}


def make_table(name: str = "t", contract: list | None = None) -> TableConfig:
    return TableConfig(
        name=name,
        expectations={"schema": contract} if contract else None,
    )


def make_storage(tmp_path, filename: str = "test.db") -> SqliteStorage:
    return SqliteStorage(tmp_path / filename)


def seed_snapshot(storage: SqliteStorage, table_name: str, schema: dict) -> None:
    storage.write_run_snapshot(
        {
            "table_name": table_name,
            "column_name": None,
            "metric_name": METRIC_NAME,
            "metric_value": None,
            "metric_json": schema,
        }
    )


def payloads(events: list[dict]) -> list[dict]:
    return [e["payload"] for e in events]


class TestColdStart:
    def test_no_snapshot_no_contract_seeds_silently_no_events(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        schema = {"id": col("integer", False)}

        events = check_schema_drift(table, schema, storage, "v1")

        assert events == []
        assert storage.get_events(table.name) == []
        snapshots = storage.get_run_snapshots(table.name)
        assert len(snapshots) == 1
        assert snapshots[0]["metric_name"] == METRIC_NAME
        assert json.loads(snapshots[0]["metric_json"]) == schema


class TestSnapshotModeDrift:
    def test_identical_schema_emits_no_events(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        schema = {"id": col("integer", False)}
        seed_snapshot(storage, table.name, schema)

        events = check_schema_drift(table, schema, storage, "v1")

        assert events == []

    def test_column_added_emits_warn_event(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {"id": col("integer", False)})
        current = {"id": col("integer", False), "email": col("string", True)}

        events = check_schema_drift(table, current, storage, "v1")

        assert len(events) == 1
        event = events[0]
        assert event["severity"] == "warn"
        assert event["payload"] == {
            "column": "email",
            "change_type": "column_added",
            "old": None,
            "new": {"type": "string", "nullable": True},
        }

    def test_column_removed_emits_critical_event(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {"id": col("integer", False), "email": col("string", True)})
        current = {"id": col("integer", False)}

        events = check_schema_drift(table, current, storage, "v1")

        assert len(events) == 1
        event = events[0]
        assert event["severity"] == "critical"
        assert event["payload"] == {
            "column": "email",
            "change_type": "column_removed",
            "old": {"type": "string", "nullable": True},
            "new": None,
        }

    def test_type_changed_emits_critical_event(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {"amount": col("integer", False)})
        current = {"amount": col("decimal", False)}

        events = check_schema_drift(table, current, storage, "v1")

        assert len(events) == 1
        event = events[0]
        assert event["severity"] == "critical"
        assert event["payload"] == {
            "column": "amount",
            "change_type": "type_changed",
            "old": {"type": "integer", "nullable": False},
            "new": {"type": "decimal", "nullable": False},
        }

    def test_nullability_loosened_emits_warn_event(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {"status": col("string", False)})
        current = {"status": col("string", True)}

        events = check_schema_drift(table, current, storage, "v1")

        assert len(events) == 1
        assert events[0]["severity"] == "warn"
        assert events[0]["payload"]["change_type"] == "nullability_changed"

    def test_nullability_tightened_emits_warn_event(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {"status": col("string", True)})
        current = {"status": col("string", False)}

        events = check_schema_drift(table, current, storage, "v1")

        assert len(events) == 1
        assert events[0]["severity"] == "warn"
        assert events[0]["payload"]["change_type"] == "nullability_changed"

    def test_multiple_changes_produce_multiple_event_rows(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(
            storage,
            table.name,
            {
                "id": col("integer", False),
                "legacy": col("string", True),
                "amount": col("integer", False),
            },
        )
        current = {
            "id": col("integer", False),
            "amount": col("decimal", False),
            "new_col": col("boolean", True),
        }

        events = check_schema_drift(table, current, storage, "v1")

        change_types = sorted(e["payload"]["change_type"] for e in events)
        assert change_types == ["column_added", "column_removed", "type_changed"]

    def test_type_and_nullability_both_changed_on_same_column_emits_two_events(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {"amount": col("integer", False)})
        current = {"amount": col("decimal", True)}

        events = check_schema_drift(table, current, storage, "v1")

        assert len(events) == 2
        change_types = sorted(e["payload"]["change_type"] for e in events)
        assert change_types == ["nullability_changed", "type_changed"]
        assert all(e["payload"]["column"] == "amount" for e in events)

class TestSeverityHelper:
    @pytest.mark.parametrize("change_type", ["column_removed", "type_changed"])
    def test_critical_change_types(self, change_type):
        assert _severity_for(change_type) == "critical"

    @pytest.mark.parametrize("change_type", ["column_added", "nullability_changed"])
    def test_warn_change_types(self, change_type):
        assert _severity_for(change_type) == "warn"


class TestAlwaysPersistsSnapshot:
    def test_writes_new_snapshot_on_clean_run(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        schema = {"id": col("integer", False)}
        seed_snapshot(storage, table.name, schema)

        check_schema_drift(table, schema, storage, "v1")

        assert len(storage.get_run_snapshots(table.name)) == 2

    def test_writes_new_snapshot_when_drift_detected(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {"id": col("integer", False)})
        current = {"id": col("integer", False), "email": col("string", True)}

        check_schema_drift(table, current, storage, "v1")

        snapshots = storage.get_run_snapshots(table.name)
        assert len(snapshots) == 2
        assert json.loads(snapshots[-1]["metric_json"]) == current


class TestEventPayloadShape:
    def test_column_added_payload_shape(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {})
        events = check_schema_drift(table, {"id": col("integer", False)}, storage, "v1")

        assert events[0]["payload"]["old"] is None
        assert events[0]["payload"]["new"] == {"type": "integer", "nullable": False}

    def test_column_removed_payload_shape(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table()
        seed_snapshot(storage, table.name, {"id": col("integer", False)})
        events = check_schema_drift(table, {}, storage, "v1")

        assert events[0]["payload"]["old"] == {"type": "integer", "nullable": False}
        assert events[0]["payload"]["new"] is None

    def test_event_carries_config_version_and_check_type(self, tmp_path):
        storage = make_storage(tmp_path)
        table = make_table(name="public.accounts")
        seed_snapshot(storage, table.name, {"id": col("integer", False)})
        events = check_schema_drift(table, {}, storage, "config-hash-123")

        assert events[0]["check_type"] == "schema_drift"
        assert events[0]["config_version"] == "config-hash-123"
        assert events[0]["table_name"] == "public.accounts"
