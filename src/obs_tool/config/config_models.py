"""Config models for the observability tool config validation."""

from pathlib import Path
import re
from typing import Optional, Literal

from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator, ConfigDict

CanonicalType = Literal["integer", "bigint", "float", "decimal", "boolean",
    "string", "date", "timestamp", "json"]

_DURATION_RE = re.compile(r"^(\d+)(h|d)$")

def parse_duration_hours(value: str) -> int:
    """Parse a duration string like '20h' or '1d' into whole hours."""
    match = _DURATION_RE.match(value.strip())
    if not match:
        raise ValueError(f"invalid duration '{value}' — expected a format like '20h' or '2d'")
    amount, unit = match.groups()
    return int(amount) * (24 if unit == "d" else 1)


def check_min_baseline_runs(min_baseline_runs: int | None, baseline_runs: int | None) -> None:
    """Shared rule: min_baseline_runs must not exceed baseline_runs.

    Only enforced when both values are present — a partial override with just
    one of the two fields set has nothing to compare against yet.
    """
    if min_baseline_runs is not None and baseline_runs is not None:
        if min_baseline_runs > baseline_runs:
            raise ValueError(
                f"min_baseline_runs ({min_baseline_runs}) must be <= "
                f"baseline_runs ({baseline_runs})"
            )

class ProjectConfig(BaseModel):
    """Config for project-level settings."""
    model_config = ConfigDict(extra="forbid")

    owner_email: EmailStr = Field(..., description="Email address of the project owner.")
    scan_interval: int = Field(..., gt=0, description="Interval in hours between scans.")
    heartbeat_interval: Optional[int] = Field(None, gt=0, description="Interval in hours between heartbeat email events. Defaults to scan_interval + 1 day.")
    storage_path: Path = Field(Path("./observability.db"), description="Path to the storage location.")

    @field_validator("scan_interval", "heartbeat_interval", mode="before")
    @classmethod
    def parse_interval(cls, value):
        if isinstance(value, str):
            return parse_duration_hours(value)
        return value

    @model_validator(mode="after")
    def heartbeat_must_exceed_scan_interval(self):
        """Default heartbeat_interval to scan_interval + 1 day, and ensure it exceeds scan_interval."""
        if self.heartbeat_interval is None:
            self.heartbeat_interval = self.scan_interval + 24
        if self.heartbeat_interval <= self.scan_interval:
            raise ValueError(
                f"heartbeat_interval ({self.heartbeat_interval}) must be greater than "
                f"scan_interval ({self.scan_interval})"
            )
        return self


class BaselineRuns(BaseModel):
    """Shared shape/rule for checks that compare against a rolling baseline."""
    model_config = ConfigDict(extra="forbid")

    baseline_runs: int = Field(10, gt=0, description="Number of runs to use for baseline comparison.")
    min_baseline_runs: int = Field(5, gt=0, description="Minimum number of runs to use for baseline comparison.")

    @model_validator(mode="after")
    def min_baseline_runs_le_baseline_runs(self):
        check_min_baseline_runs(self.min_baseline_runs, self.baseline_runs)
        return self


class VolumeDefaultConfig(BaselineRuns):
    """Default config for volume checks."""
    enabled: bool = Field(True, description="Whether to enable volume checks.")
    sigma: float = Field(3.0, gt=0, description="Number of standard deviations for volume check threshold.")


class NullRateDefaultConfig(BaselineRuns):
    """Default config for null rate checks."""
    enabled: bool = Field(True, description="Whether to enable null rate checks.")
    delta: float = Field(0.10, gt=0, le=1, description="Maximum allowed change in null rate between runs.")
    fire_on_zero_baseline: bool = Field(True, description="Whether to fire an alert if the normal null rate is zero.")
    exclude: list[str] = Field(default_factory=list, description="Columns to skip'.")


class SchemaDriftDefaultConfig(BaseModel):
    """Default config for schema checks."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(True, description="Whether to enable schema checks.")


class DefaultConfig(BaseModel):
    """Default config for all checks."""
    model_config = ConfigDict(extra="forbid")

    volume: VolumeDefaultConfig = Field(default_factory=VolumeDefaultConfig, description="Default config for volume checks.")
    null_rate: NullRateDefaultConfig = Field(default_factory=NullRateDefaultConfig, description="Default config for null rate checks.")
    schema_drift: SchemaDriftDefaultConfig = Field(default_factory=SchemaDriftDefaultConfig, description="Default config for schema checks.")


class BaselineRunsOverride(BaseModel):
    """Override shape for checks that compare against a rolling baseline.

    All fields optional — None means 'inherit from default'.
    """
    model_config = ConfigDict(extra="forbid")

    baseline_runs: Optional[int] = Field(None, gt=0, description="Number of runs to use for baseline comparison.")
    min_baseline_runs: Optional[int] = Field(None, gt=0, description="Minimum number of runs to use for baseline comparison.")

    @model_validator(mode="after")
    def min_baseline_runs_le_baseline_runs(self):
        check_min_baseline_runs(self.min_baseline_runs, self.baseline_runs)
        return self


class VolumeOverrideConfig(BaselineRunsOverride):
    """Per-table override for volume checks."""
    enabled: Optional[bool] = Field(None, description="Whether to enable volume checks.")
    sigma: Optional[float] = Field(None, gt=0, description="Number of standard deviations for volume check threshold.")


class NullRateOverrideConfig(BaselineRunsOverride):
    """Per-table override for null rate checks."""
    enabled: Optional[bool] = Field(None, description="Whether to enable null rate checks.")
    delta: Optional[float] = Field(None, gt=0, le=1, description="Maximum allowed change in null rate between runs.")
    fire_on_zero_baseline: Optional[bool] = Field(None, description="Whether to fire an alert if the normal null rate is zero.")
    exclude: Optional[list[str]] = Field(None, description="Columns to skip..")

class SchemaDriftOverrideConfig(BaseModel):
    """Per-table override for schema checks."""
    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = Field(None, description="Whether to enable schema checks.")


class TableCheckOverrides(BaseModel):
    """Per-table overrides layered on top of DefaultConfig."""
    model_config = ConfigDict(extra="forbid")

    volume: Optional[VolumeOverrideConfig] = None
    null_rate: Optional[NullRateOverrideConfig] = None
    schema_drift: Optional[SchemaDriftOverrideConfig] = None


class SchemaExpectationConfig(BaseModel):
    """A single declared schema expectation (spec §6.3)."""
    model_config = ConfigDict(extra="forbid")

    column: str
    type: CanonicalType
    nullable: bool = True


class ExpectationConfig(BaseModel):
    """A single user-declared value expectation for a column (spec §6.3)."""
    model_config = ConfigDict(extra="forbid")

    column: str
    op: Literal["gt", "gte", "lt", "lte", "eq", "not_null", "in","ne"]
    value: Optional[int | float | str | list[int | float | str]] = None
    agg: Optional[Literal["min", "max", "sum", "avg", "count", "count_distinct", "null_count"]] = None

    @field_validator("value", mode="before")
    @classmethod
    def reject_bool_for_numeric_ops(cls, value, info):
        op = info.data.get("op")
        if op in ("gt", "gte", "lt", "lte") and isinstance(value, bool):
            raise ValueError(f"op '{op}' requires a numeric value")
        return value

    @model_validator(mode="after")
    def validate_expectation(self):
        if self.op == "not_null":
            if self.value is not None:
                raise ValueError("'not_null' does not take a value")
            if self.agg is not None:
                raise ValueError("'not_null' cannot be combined with 'agg' — it is inherently per-row")
        else:
            if self.value is None:
                raise ValueError(f"op '{self.op}' requires a value")

        if self.op =='gt' or self.op =='lt' or self.op =='gte' or self.op =='lte':
            if not isinstance(self.value, (int, float)):
                raise ValueError(f"op '{self.op}' requires a numeric value")

        if self.op == "in":
            if not isinstance(self.value, list):
                raise ValueError("op 'in' requires a list value")
            if self.agg is not None:
                raise ValueError("op 'in' cannot be combined with 'agg' — it is per-row only in v1")

        if self.agg in {"count", "count_distinct", "null_count"} and self.value is not None:
            if not isinstance(self.value, int):
                raise ValueError(f"agg '{self.agg}' requires an integer value")
        if self.agg in {"sum", "avg"} and self.value is not None:
            if not isinstance(self.value, (int, float)):
                raise ValueError(f"agg '{self.agg}' requires a numeric value")
        return self


class TableExpectations(BaseModel):
    """Declared contracts for a table (spec §6.3)."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: list[SchemaExpectationConfig] = Field(default_factory=list, alias="schema")
    values: list[ExpectationConfig] = Field(default_factory=list)


class TableConfig(BaseModel):
    """Config for a single monitored table within a source."""
    model_config = ConfigDict(extra="forbid")

    name: str
    cadence: Optional[int] = Field(None, gt=0, description="Omit to disable freshness for this table.")
    updated_at_column: Optional[str] = None
    alert_recipients: list[EmailStr] = Field(default_factory=list)
    checks: Optional[TableCheckOverrides] = None
    expectations: Optional[TableExpectations] = None

    @field_validator("cadence", mode="before")
    @classmethod
    def parse_cadence(cls, value):
        if isinstance(value, str):
            return parse_duration_hours(value)
        return value


class SourceConfig(BaseModel):
    """Config for the single monitored data source (spec §6)."""
    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["postgres", "sqlserver"]
    connection_env: str
    tables: list[TableConfig] = Field(..., min_length=1)

    @model_validator(mode="after")
    def table_names_must_be_unique(self):
        names = [t.name for t in self.tables]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate table name(s) in source '{self.name}': {', '.join(dupes)}")
        return self


class AppConfig(BaseModel):
    """Root model for a single observability config file — one file, one source."""
    model_config = ConfigDict(extra="forbid")

    project: ProjectConfig
    defaults: DefaultConfig = Field(default_factory=DefaultConfig)
    source: SourceConfig