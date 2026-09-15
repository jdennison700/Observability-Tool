"""Load and validate config.yml."""

import hashlib
from pathlib import Path

from pydantic import BaseModel
import yaml

from obs_tool.config.config_models import AppConfig, DefaultConfig, TableCheckOverrides


def merge_config(default: BaseModel, override: BaseModel | None) -> BaseModel:
    """Layer a validated override onto a validated default, re-validating the result.

    Only fields the user actually set in the override (exclude_unset) replace
    the default's values; everything else is inherited.
    """
    if override is None:
        return default

    merged_data = {**default.model_dump(), **override.model_dump(exclude_unset=True, exclude_none=True)}
    return type(default).model_validate(merged_data)


def resolve_source_config(default: DefaultConfig, override: TableCheckOverrides | None) -> DefaultConfig:
    """Produce the effective config for one source by layering its overrides onto the global defaults."""
    if override is None:
        return default

    return DefaultConfig(
        volume=merge_config(default.volume, override.volume),
        null_rate=merge_config(default.null_rate, override.null_rate),
        schema_drift=merge_config(default.schema_drift, override.schema_drift),
    )


def load_config(path: str = "config.yml") -> tuple[AppConfig, str]:
    """Load, validate, and version a config file.

    Returns the validated AppConfig and a version hash of the raw file
    contents (spec §2), for stamping into events so old events can be
    interpreted against the config that produced them.
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw_text = Path(path).read_text(encoding="utf-8")
    if not raw_text.strip():
        raise ValueError(f"Config file is empty: {path}")
    version = hashlib.sha256(raw_text.encode()).hexdigest()[:12]
    config = AppConfig.model_validate(yaml.safe_load(raw_text))
    return config, version