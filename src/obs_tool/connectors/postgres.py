import logging
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from .base import Connector

logger = logging.getLogger(__name__)

_PG_TYPE_MAPPING = {
    "smallint": "integer",
    "integer": "integer",
    "bigint": "bigint",
    "decimal": "decimal",
    "numeric": "decimal",
    "real": "float",
    "double precision": "float",
    "boolean": "boolean",
    "character varying": "string",
    "varchar": "string",
    "character": "string",
    "char": "string",
    "text": "string",
    "date": "date",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamp_tz",
    "time without time zone": "time",
    "time with time zone": "time_tz",
    "interval": "interval",
    "bytea": "bytea",
    "uuid": "uuid",
    "json": "json",
    "jsonb": "jsonb",
    "ARRAY": "array",
    "inet": "inet",
    "cidr": "cidr",
    "macaddr": "macaddr",
    "point": "point",
    "line": "line",
    "lseg": "lseg",
    "box": "box",
    "path": "path",
    "polygon": "polygon",
    "circle": "circle",
    "money": "money",
    "int4range": "int4range",
    "int8range": "int8range",
    "numrange": "numrange",
    "tsrange": "tsrange",
    "tstzrange": "tstzrange",
    "daterange": "daterange",
    "xml": "xml",
    "bit varying": "varbit",
    "bit": "bit",
    "tsvector": "vector",
    "tsquery": "tsquery",
    "oid": "oid",
}

def normalise_type(pg_type: str) -> str:
    """Convert a Postgres type to a canonical type.

    Falls back to the raw Postgres type name for anything not in the
    mapping, so one unmapped column doesn't fail schema introspection
    for the whole table.
    """
    try:
        return _PG_TYPE_MAPPING[pg_type]
    except KeyError:
        logger.warning(
            "unmapped Postgres type '%s' — add it to _PG_TYPE_MAPPING; using raw type name",
            pg_type,
        )
        return pg_type
class PostgresConnector(Connector):
    def __init__(self, dsn: str):
        # The project ships psycopg 3 (psycopg[binary]), but SQLAlchemy's
        # default driver for a bare "postgresql://" URL is psycopg2. Steer
        # it to psycopg 3 so the DSN doesn't have to spell out the driver.
        url = make_url(dsn)
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        self.engine = create_engine(url)

    def get_schema(self, table_name: str) -> dict:
        schema, _, table = table_name.partition(".")
        if not table:
            schema, table = "public", schema

        query = text("""
            select column_name, data_type, is_nullable, character_maximum_length, numeric_precision, numeric_scale
            from information_schema.columns
            where table_schema = :schema and table_name = :table
            order by ordinal_position
        """)
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"schema": schema, "table": table}).fetchall()

        if not rows:
            raise ValueError(f"No columns found for {table_name} — does it exist?")

        return {
            row.column_name: {"type": normalise_type(row.data_type), "nullable": row.is_nullable == "YES", "max_length": row.character_maximum_length, "numeric_precision": row.numeric_precision, "numeric_scale": row.numeric_scale}
            for row in rows
        }

    def get_row_count(self, table_name: str) -> int:
        # NB: table_name is only ever sourced from our own validated config,
        # never user input at request time — safe to interpolate as an identifier.
        with self.engine.connect() as conn:
            result = conn.execute(text(f"select count(*) from {table_name}"))
            return result.scalar_one()

    def get_null_count(self, table_name: str, column: str) -> int:
        with self.engine.connect() as conn:
            result = conn.execute(
                text(f"select count(*) from {table_name} where {column} is null")
            )
            return result.scalar_one()

    def get_last_updated(self, table_name: str, updated_at_column: str | None) -> datetime | None:
        if updated_at_column:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(f"select max({updated_at_column}) from {table_name}")
                )
                return result.scalar_one()
        # TODO: system-table fallback (pg_stat_user_tables) — best-effort,
        # see the caveat in the scope doc §4.2.
        return None
