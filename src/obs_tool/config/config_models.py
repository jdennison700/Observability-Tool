"""Config models for the observability tool config validation."""

from pathlib import Path

from pydantic import BaseModel, Field, EmailStr, model_validator


class ProjectConfig(BaseModel):
    """Config for project-level settings."""
    owner_email: EmailStr = Field(..., description="Email address of the project owner.")
    scan_interval: int = Field(..., gt=0, description="Interval in hours between scans.")
    heartbeat_interval: int = Field(..., gt=0, description="Interval in hours between heartbeat email events.")
    storage_path: Path = Field(..., description="Path to the storage location.")

    @model_validator(mode="after")
    def heartbeat_must_exceed_scan_interval(self):
        """Ensure that heartbeat_interval is greater than scan_interval."""
        if self.heartbeat_interval <= self.scan_interval:
            raise ValueError(
                f"heartbeat_interval ({self.heartbeat_interval}) must be greater than "
                f"scan_interval ({self.scan_interval})"
            )
        return self

class BaselineRuns(BaseModel):
    """Shared shape/rule for checks that compare against a rolling baseline."""
    baseline_runs: int = Field(10, gt=0, description="Number of runs to use for baseline comparison.")
    min_baseline_runs: int = Field(5, gt=0, description="Minimum number of runs to use for baseline comparison.")

    @model_validator(mode="after")
    def min_baseline_runs_le_baseline_runs(self):
        """Ensure that min_baseline_runs is less than or equal to baseline_runs."""
        if self.min_baseline_runs > self.baseline_runs:
            raise ValueError(
                f"min_baseline_runs ({self.min_baseline_runs}) must be <= "
                f"baseline_runs ({self.baseline_runs})"
            )
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
    exclude: list[str] = Field(default_factory=list, description="List of columns to exclude from null rate checks.")

class SchemaDriftDefaultConfig(BaseModel):
    """Default config for schema checks."""
    enabled: bool = Field(True, description="Whether to enable schema checks.")

class DefaultConfig(BaseModel):
    """Default config for all checks."""
    volume: VolumeDefaultConfig = Field(default_factory=VolumeDefaultConfig, description="Default config for volume checks.")
    null_rate: NullRateDefaultConfig = Field(default_factory=NullRateDefaultConfig, description="Default config for null rate checks.")
    schema_drift: SchemaDriftDefaultConfig = Field(default_factory=SchemaDriftDefaultConfig, description="Default config for schema checks.")
