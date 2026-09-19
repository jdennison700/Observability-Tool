"""Connector interface — one implementation per source type (postgres, sqlserver).

Per scope §7, every connector needs to support:
  - schema introspection
  - row counts
  - column-level null / value stats
  - a "last updated" signal (declared column, or system-table fallback)
"""

from abc import ABC, abstractmethod
from datetime import datetime


class Connector(ABC):
    @abstractmethod
    def get_schema(self, table_name: str) -> dict:
        """Return column name -> {type, nullable, max_length, numeric_precision, numeric_scale} for the given table."""

    @abstractmethod
    def get_row_count(self, table_name: str) -> int:
        ...

    @abstractmethod
    def get_null_count(self, table_name: str, column: str) -> int:
        ...

    @abstractmethod
    def get_last_updated(self, table_name: str, updated_at_column: str | None) -> datetime | None:
        """Falls back to system-table heuristics if updated_at_column is None (scope §4.2)."""
