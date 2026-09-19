"""Schema drift check (spec §4.1).

Compares a table's current live schema to the last schema this tool recorded,
and writes one event per detected column addition, removal, type change, or
nullability change.

Cold start (no prior snapshot) seeds silently — no events on the first run.

TODO(PERS-228 follow-up): contract-mode comparison (comparing against a
declared `table.expectations.schema` instead of the last recorded snapshot,
per spec §4.5) is not implemented yet.
"""

import json
from typing import Literal

from obs_tool.config.config_models import TableConfig
from obs_tool.storage.base import Storage

CHECK_TYPE = "schema_drift"
METRIC_NAME = "schema_snapshot"

ChangeType = Literal["column_added", "column_removed", "type_changed", "nullability_changed"]


def _type_nullable(column: dict) -> dict:
    return {"type": column["type"], "nullable": column["nullable"]}


def _change(column: str, change_type: ChangeType, old: dict | None, new: dict | None) -> dict:
    return {"column": column, "change_type": change_type, "old": old, "new": new}


def _diff_against_snapshot(previous_schema: dict, current_schema: dict) -> list[dict]:
    """Diff two schema dicts (column -> {type, nullable, ...}), comparing only
    type and nullable. Returns one change record per individual difference —
    a column whose type and nullability both changed produces two records.
    """
    #TODO Check current schema is not none
    changes = []
    for column in sorted(previous_schema):
        previous = previous_schema[column]
        current = current_schema.get(column)
        if current is None:
            changes.append(_change(column, "column_removed", old=_type_nullable(previous), new=None))
            continue
        if current["type"] != previous["type"]:
            changes.append(_change(column, "type_changed", old=_type_nullable(previous), new=_type_nullable(current)))
        if current["nullable"] != previous["nullable"]:
            changes.append(_change(column, "nullability_changed", old=_type_nullable(previous), new=_type_nullable(current)))

    for column in sorted(current_schema):
        if column not in previous_schema:
            changes.append(_change(column, "column_added", old=None, new=_type_nullable(current_schema[column])))

    return changes


def _severity_for(change_type: ChangeType) -> Literal["critical", "warn"]:
    if change_type in ("column_removed", "type_changed"):
        return "critical"
    return "warn"  # column_added, nullability_changed (loosened or tightened)


def check_schema_drift(
    table: TableConfig,
    current_schema: dict,
    storage: Storage,
    config_version: str,
) -> list[dict]:
    """Detect schema drift for one table and write one event per change.

    Always writes the current schema as a new run_snapshot afterwards, so the
    next run's baseline reflects what was just observed, not what was last
    seen before drift started.

    `table.checks.schema_drift.enabled` is not consulted here — callers are
    responsible for resolving effective per-table config and deciding whether
    to invoke this check at all.
    """

    previous_row = storage.get_latest_run_snapshot(table.name, METRIC_NAME)
    if previous_row is None:
        changes = []  # cold start: no prior snapshot -> seed silently, no events
    else:
        previous_schema = json.loads(previous_row["metric_json"])
        changes = _diff_against_snapshot(previous_schema, current_schema)

    events = []
    for change in changes:
        event = {
            "table_name": table.name,
            "check_type": CHECK_TYPE,
            "severity": _severity_for(change["change_type"]),
            "config_version": config_version,
            "payload": {
                "column": change["column"],
                "change_type": change["change_type"],
                "old": change["old"],
                "new": change["new"],
            },
        }
        storage.write_event(event)
        events.append(event)

    storage.write_run_snapshot({
        "table_name": table.name,
        "column_name": None,
        "metric_name": METRIC_NAME,
        "metric_value": None,
        "metric_json": current_schema,
    })

    return events
