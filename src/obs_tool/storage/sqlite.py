from .base import Storage

import json
import sqlite3
from pathlib import Path

_SCHEMA = """
create table if not exists events (
    id integer primary key autoincrement,
    created_at text not null default (datetime('now')),
    table_name text not null,
    check_type text not null,
    severity text not null,
    payload text not null,
    config_version text not null
);

create index if not exists idx_events_lookup
    on events (table_name, check_type, created_at);

create table if not exists run_snapshots (
    id integer primary key autoincrement,
    created_at text not null default (datetime('now')),
    table_name text not null,
    column_name text,
    metric_name text not null,
    metric_value real,
    metric_json text
);

create index if not exists idx_run_snapshots_lookup
    on run_snapshots (table_name, column_name, metric_name, created_at);
"""


class SqliteStorage(Storage):
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        """Close the underlying connection. Safe to call more than once."""
        self.conn.close()

    def __enter__(self) -> "SqliteStorage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def write_event(self, event: dict) -> None:
        self.conn.execute(
            "insert into events (table_name, check_type, severity, payload, config_version) "
            "values (?, ?, ?, ?, ?)",
            (
                event["table_name"],
                event["check_type"],
                event["severity"],
                json.dumps(event.get("payload", {})),
                event["config_version"],
            ),
        )
        self.conn.commit()

    def get_events(self, table_name: str | None = None) -> list[dict]:
        if table_name is not None:
            rows = self.conn.execute(
                "select * from events where table_name = ? order by id", (table_name,)
            ).fetchall()
        else:
            rows = self.conn.execute("select * from events order by id").fetchall()
        return [dict(row) for row in rows]

    def write_run_snapshot(self, snapshots: dict) -> None:
        metric_json = snapshots.get("metric_json")
        self.conn.execute(
            "insert into run_snapshots (table_name, column_name, metric_name, metric_value, metric_json) "
            "values (?, ?, ?, ?, ?)",
            (
                snapshots["table_name"],
                snapshots.get("column_name"),  # None if not applicable
                snapshots["metric_name"],
                snapshots.get("metric_value"),  # .get is needed for optional keys
                json.dumps(metric_json) if metric_json is not None else None,
            ),
        )
        self.conn.commit()

    def get_run_snapshots(self, table_name: str | None = None) -> list[dict]:
        if table_name is not None:
            rows = self.conn.execute(
                "select * from run_snapshots where table_name = ? order by id", (table_name,)
            ).fetchall()
        else:
            rows = self.conn.execute("select * from run_snapshots order by id").fetchall()
        return [dict(row) for row in rows]

    def get_latest_run_snapshot(self, table_name: str, metric_name: str, column_name: str | None = None) -> dict | None:
        row = self.conn.execute(
            "select * from run_snapshots "
            "where table_name = ? and metric_name = ? and column_name is ? "
            "order by id desc limit 1",
            (table_name, metric_name, column_name),
        ).fetchone()
        return dict(row) if row else None

    def get_recent_run_snapshots(self, table_name: str, metric_name: str, column_name: str | None = None, n: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "select * from run_snapshots "
            "where table_name = ? and metric_name = ? and column_name is ? "
            "order by id desc limit ?",
            (table_name, metric_name, column_name, n),
        ).fetchall()
        return [dict(row) for row in rows]
