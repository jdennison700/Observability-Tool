"""
Vertical slice: connect -> introspect schema -> write one event to SQLite.

Run with:
    uv run scripts/slice.py

Deliberately skips the scheduler, alerting, and the full check suite —
this exists to prove the connector -> event -> storage path works before
any of that gets built.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from obs_tool.config.loader import load_raw_config
from obs_tool.connectors.postgres import PostgresConnector
from obs_tool.storage.sqlite import SqliteStorage

from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file


def main():
    config = load_raw_config("config.yml")

    source = config["source"]
    dsn = os.environ[source["connection_env"]]
    connector = PostgresConnector(dsn)

    storage_path = config["project"]["storage_path"]
    storage = SqliteStorage(storage_path)

    table = source["tables"][0]
    table_name = table["name"]

    print(f"Introspecting {table_name}...")
    schema = connector.get_schema(table_name)

    print(f"Found {len(schema)} columns:")

    storage.write_run_snapshot({
        "table_name": table_name,
        "column_name": None,
        "metric_name": "schema_snapshot",
        "metric_value": None,
        "metric_json": schema,
    })

    print(f"Wrote 1 run metric to {storage_path}.")

    row_count = connector.get_row_count(table_name)

    print(f"Found {row_count} rows.")

    storage.write_run_snapshot({
        "table_name": table_name,
        "column_name": None,
        "metric_name": "row_count",
        "metric_value": row_count,
        "metric_json": None,
    })

    
    print(f"Wrote 1 run metric to {storage_path}.")

if __name__ == "__main__":
    main()
