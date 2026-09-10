"""Storage interface — built so SQLite (v1) can later be swapped for Postgres.

Two tables live behind this interface (see the data-model discussion):
  - events: one row per detected event (schema drift, freshness, etc.)
  - run_snapshots: per-run, per-table/column stats that baselines are computed from

"""

from abc import ABC, abstractmethod


class Storage(ABC):

    @abstractmethod
    def __enter__(self) -> "Storage":
        """Context manager entry point. Implementations may open a connection or
        perform other setup here.
        """

    @abstractmethod
    def __exit__(self, *exc: object) -> None:
        """Context manager exit point. Implementations may close a connection or
        perform other teardown here.
        """

    @abstractmethod
    def close(self) -> None:
        """Close the underlying connection. Safe to call more than once."""

    @abstractmethod
    def write_event(self, event: dict) -> None:
        """Persist a single detected event.

        Args:
            event: The event to store. Required keys: ``table_name`` (str),
                ``check_type`` (str), ``severity`` (str), and
                ``config_version`` (str). Optional key ``payload`` (dict) holds
                check-specific detail and defaults to an empty dict.
                Implementations set the creation timestamp themselves.
        """

    @abstractmethod
    def get_events(self, table_name: str | None = None) -> list[dict]:
        """Return stored events in insertion order (oldest first).

        Args:
            table_name: If given, return only events for this table; otherwise
                return events for all tables.

        Returns:
            A list of row dicts containing the stored columns (``id``,
            ``created_at``, ``table_name``, ``check_type``, ``severity``,
            ``payload``, ``config_version``). ``payload`` is returned as its
            serialized (JSON) string, not a dict. Empty list if nothing matches.
        """

    @abstractmethod
    def write_run_snapshot(self, snapshots: dict) -> None:
        """Persist a single per-run metric observation.

        A snapshot is one metric for one table (and optionally one column) from
        one run; baselines are computed by reading these back.

        Args:
            snapshots: The observation to store. Required keys: ``table_name``
                (str) and ``metric_name`` (str). Optional keys:
                ``column_name`` (str, ``None`` for table-level metrics),
                ``metric_value`` (float, for scalar metrics), and
                ``metric_json`` (JSON-serializable, for structured metrics).
                Implementations set the creation timestamp themselves.
        """

    @abstractmethod
    def get_run_snapshots(self, table_name: str | None = None) -> list[dict]:
        """Return stored run snapshots in insertion order (oldest first).

        Args:
            table_name: If given, return only snapshots for this table;
                otherwise return snapshots for all tables.

        Returns:
            A list of row dicts containing the stored columns (``id``,
            ``created_at``, ``table_name``, ``column_name``, ``metric_name``,
            ``metric_value``, ``metric_json``). Empty list if nothing matches.
        """

    @abstractmethod
    def get_latest_run_snapshot(self, table_name: str, metric_name: str, column_name: str | None = None) -> dict | None:
        """Return the most recently written snapshot matching the given key.

        Args:
            table_name: Table to match.
            metric_name: Metric to match.
            column_name: Column to match. ``None`` matches rows stored with no
                column (table-level metrics), not "any column".

        Returns:
            The newest matching row dict, or ``None`` if there is no match.
        """

    @abstractmethod
    def get_recent_run_snapshots(self, table_name: str, metric_name: str, column_name: str | None = None, n: int = 10) -> list[dict]:
        """Return the most recent snapshots matching the given key, newest first.

        Args:
            table_name: Table to match.
            metric_name: Metric to match.
            column_name: Column to match. ``None`` matches rows stored with no
                column (table-level metrics), not "any column".
            n: Maximum number of rows to return.

        Returns:
            Up to ``n`` matching row dicts ordered newest to oldest. Empty list
            if nothing matches.
        """
