"""Tests for the Postgres connector: type normalisation and query methods."""

import logging
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from obs_tool.connectors.postgres import PostgresConnector, normalise_type


class TestNormaliseType:
    @pytest.mark.parametrize(
        "pg_type,expected",
        [
            ("smallint", "integer"),
            ("bigint", "bigint"),
            ("numeric", "decimal"),
            ("character varying", "varchar"),
            ("timestamp without time zone", "timestamp"),
            ("timestamp with time zone", "timestamp_tz"),
            ("ARRAY", "array"),
            ("jsonb", "jsonb"),
        ],
    )
    def test_known_types_map_to_canonical_name(self, pg_type, expected):
        assert normalise_type(pg_type) == expected

    def test_unmapped_type_falls_back_to_raw_name_and_logs(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert normalise_type("hstore") == "hstore"
        assert "unmapped Postgres type 'hstore'" in caplog.text


def make_connector():
    connector = PostgresConnector.__new__(PostgresConnector)
    connector.engine = MagicMock()
    return connector


def mock_connection(connector):
    conn = MagicMock()
    connector.engine.connect.return_value.__enter__.return_value = conn
    return conn


def make_row(**overrides):
    defaults = {
        "column_name": "id",
        "data_type": "integer",
        "is_nullable": "YES",
        "character_maximum_length": None,
        "numeric_precision": None,
        "numeric_scale": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestInitDriverSteering:
    def test_bare_postgresql_scheme_switches_to_psycopg(self):
        connector = PostgresConnector("postgresql://user:pass@localhost/db")
        assert connector.engine.url.drivername == "postgresql+psycopg"

    def test_explicit_driver_left_untouched(self):
        connector = PostgresConnector("postgresql+psycopg://user:pass@localhost/db")
        assert connector.engine.url.drivername == "postgresql+psycopg"


class TestGetSchema:
    def test_normalises_types_and_splits_schema_table(self):
        connector = make_connector()
        conn = mock_connection(connector)
        conn.execute.return_value.fetchall.return_value = [
            make_row(
                column_name="id",
                data_type="integer",
                is_nullable="NO",
                numeric_precision=32,
                numeric_scale=0,
            )
        ]

        schema = connector.get_schema("public.accounts")

        assert schema == {
            "id": {
                "type": "integer",
                "nullable": False,
                "max_length": None,
                "numeric_precision": 32,
                "numeric_scale": 0,
            }
        }
        params = conn.execute.call_args[0][1]
        assert params == {"schema": "public", "table": "accounts"}

    def test_defaults_to_public_schema_when_unqualified(self):
        connector = make_connector()
        conn = mock_connection(connector)
        conn.execute.return_value.fetchall.return_value = [make_row()]

        connector.get_schema("accounts")

        params = conn.execute.call_args[0][1]
        assert params == {"schema": "public", "table": "accounts"}

    def test_no_rows_raises(self):
        connector = make_connector()
        conn = mock_connection(connector)
        conn.execute.return_value.fetchall.return_value = []

        with pytest.raises(ValueError, match="No columns found for public.missing"):
            connector.get_schema("public.missing")

    def test_unmapped_column_type_falls_back_instead_of_failing_whole_table(self, caplog):
        connector = make_connector()
        conn = mock_connection(connector)
        conn.execute.return_value.fetchall.return_value = [
            make_row(column_name="tags", data_type="hstore"),
            make_row(column_name="id", data_type="integer"),
        ]

        with caplog.at_level(logging.WARNING):
            schema = connector.get_schema("public.t")

        assert schema["tags"]["type"] == "hstore"
        assert schema["id"]["type"] == "integer"
        assert "unmapped Postgres type 'hstore'" in caplog.text


class TestGetRowCount:
    def test_returns_scalar_count(self):
        connector = make_connector()
        conn = mock_connection(connector)
        conn.execute.return_value.scalar_one.return_value = 42

        assert connector.get_row_count("public.accounts") == 42


class TestGetNullCount:
    def test_returns_scalar_count_for_column(self):
        connector = make_connector()
        conn = mock_connection(connector)
        conn.execute.return_value.scalar_one.return_value = 3

        assert connector.get_null_count("public.accounts", "email") == 3


class TestGetLastUpdated:
    def test_returns_max_of_declared_column(self):
        connector = make_connector()
        conn = mock_connection(connector)
        expected = datetime(2024, 1, 1)
        conn.execute.return_value.scalar_one.return_value = expected

        assert connector.get_last_updated("public.accounts", "updated_at") == expected

    def test_returns_none_without_updated_at_column(self):
        connector = make_connector()
        assert connector.get_last_updated("public.accounts", None) is None
