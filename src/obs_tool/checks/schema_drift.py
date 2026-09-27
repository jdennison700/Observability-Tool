"""Schema drift check (spec §4.1).

Writes one event per detected column addition, removal, type change, or
nullability change. Two modes:

- contract: the table declares `expectations.schema` (spec §4.5). The live
  schema is compared against the declared columns only; undeclared live
  columns are ignored. No cold start — violations fire from the first run.
- snapshot: no declared schema. The live schema is compared to the last
  recorded snapshot. Cold start (no prior snapshot) seeds silently.
"""

import json
from typing import Literal

import logging

from obs_tool.config.config_models import TableConfig
from obs_tool.storage.base import Storage

CHECK_TYPE = "schema_drift"
METRIC_NAME = "schema_snapshot"

ChangeType = Literal["column_added", "column_removed", "type_changed", "nullability_changed"]

logger = logging.getLogger(__name__)

def _type_nullable(column: dict) -> dict:
    return {"type": column["type"], "nullable": column["nullable"]}


def _change(column: str, change_type: ChangeType, old: dict | None, new: dict | None) -> dict:
    return {"column": column, "change_type": change_type, "old": old, "new": new}


def _diff_against_snapshot(previous_schema: dict, current_schema: dict) -> list[dict]:
    """Diff two schema dicts (column -> {type, nullable, ...}), comparing only
    type and nullable. Returns one change record per individual difference —
    a column whose type and nullability both changed produces two records.
    """

    if current_schema is None:
        logger.error("Current schema is None, cannot diff against snapshot.")
        raise ValueError("Current schema is None, cannot diff against snapshot.")

    logger.debug(
        "Diffing schema: %d previous column(s), %d current column(s).",
        len(previous_schema), len(current_schema),
    )

    changes = []
    for column in sorted(previous_schema):
        previous = previous_schema[column]
        current = current_schema.get(column)
        if current is None:
            logger.debug("Column removed: %s", column)
            changes.append(_change(column, "column_removed", old=_type_nullable(previous), new=None))
            continue
        if current["type"] != previous["type"]:
            logger.debug(
                "Column type changed: %s (%s -> %s)", column, previous["type"], current["type"],
            )
            changes.append(_change(column, "type_changed", old=_type_nullable(previous), new=_type_nullable(current)))
        if current["nullable"] != previous["nullable"]:
            logger.debug(
                "Column nullability changed: %s (%s -> %s)", column, previous["nullable"], current["nullable"],
            )
            changes.append(_change(column, "nullability_changed", old=_type_nullable(previous), new=_type_nullable(current)))

    for column in sorted(current_schema):
        if column not in previous_schema:
            logger.debug("Column added: %s", column)
            changes.append(_change(column, "column_added", old=None, new=_type_nullable(current_schema[column])))

    if changes:
        logger.info("Detected %d schema change(s).", len(changes))
    else:
        logger.debug("No schema changes detected.")

    return changes


def _contract_schema(table: TableConfig) -> dict | None:
    if not table.expectations or not table.expectations.schema_:
        return None
    return {e.column: {"type": e.type, "nullable": e.nullable} for e in table.expectations.schema_}


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

    logger.debug("Running schema drift check for table %s.", table.name)

    contract = _contract_schema(table)
    if contract is not None:
        mode = "contract"
        logger.info("Comparing %s against declared schema contract (%d column(s)).", table.name, len(contract))
        declared_live = {c: current_schema[c] for c in contract if c in current_schema}
        changes = _diff_against_snapshot(contract, declared_live)
    else:
        mode = "snapshot"
        previous_row = storage.get_latest_run_snapshot(table.name, METRIC_NAME)
        if previous_row is None:
            logger.info("No prior schema snapshot for %s; seeding baseline silently.", table.name)
            changes = []  # cold start: no prior snapshot -> seed silently, no events
        else:
            logger.debug("Comparing %s against last recorded schema snapshot.", table.name)
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
                "mode": mode,
            },
        }
        logger.warning(
            "Schema drift on %s.%s: %s (severity=%s)",
            table.name, change["column"], change["change_type"], event["severity"],
        )
        storage.write_event(event)
        events.append(event)

    storage.write_run_snapshot({
        "table_name": table.name,
        "column_name": None,
        "metric_name": METRIC_NAME,
        "metric_value": None,
        "metric_json": current_schema,
    })
    logger.info("Wrote schema snapshot for %s (%d columns)", table.name, len(current_schema))

    return events
