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

from obs_tool.config.loader import load_config
from obs_tool.config.startup_validation import validate_config_against_schema
from obs_tool.connectors.postgres import PostgresConnector
from obs_tool.storage.sqlite import SqliteStorage
from obs_tool.checks.schema_drift import check_schema_drift

from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file


def main():
    config, version = load_config("config.yml")
    print(f"Loaded config version {version}.")

    dsn = os.environ[config.source.connection_env]
    connector_required = config.source.type
    if connector_required != "postgres":
        raise ValueError(f"Unsupported connector type: {connector_required}")
    connector = PostgresConnector(dsn)

    validate_config_against_schema(config, get_schema=connector.get_schema)
    storage_path = config.project.storage_path
    storage = SqliteStorage(storage_path)

    for table in config.source.tables:
        current_schema = connector.get_schema(table.name)
        print(f"Current schema for {table.name}: {json.dumps(current_schema, indent=2)}")

        changes = check_schema_drift(table, current_schema, storage, version)

if __name__ == "__main__":
    main()
