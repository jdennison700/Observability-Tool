"""Tests for config loading, versioning, and default/override merging."""

import pytest
from pydantic import ValidationError

from obs_tool.config.config_models import (
    DefaultConfig,
    NullRateOverrideConfig,
    TableCheckOverrides,
    VolumeOverrideConfig,
)
from obs_tool.config.loader import load_config, merge_config, resolve_source_config

VALID_YAML = """
project:
  owner_email: me@example.com
  scan_interval: 6h
  storage_path: ./observability.db

source:
  name: warehouse
  type: postgres
  connection_env: WAREHOUSE_DSN
  tables:
    - name: public.some_table
      cadence: 24h
"""


class TestLoadConfig:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "does_not_exist.yml"))

    def test_empty_file_raises(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            load_config(str(path))

    def test_whitespace_only_file_raises(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text("   \n\n  ", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            load_config(str(path))

    def test_invalid_config_raises_validation_error(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text("project:\n  owner_email: not-an-email\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_config(str(path))

    def test_valid_config_loads_and_returns_version(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text(VALID_YAML, encoding="utf-8")
        config, version = load_config(str(path))
        assert config.project.owner_email == "me@example.com"
        assert config.source.tables[0].cadence == 24
        assert isinstance(version, str)
        assert len(version) == 12

    def test_version_is_stable_for_same_content(self, tmp_path):
        path1 = tmp_path / "a.yml"
        path2 = tmp_path / "b.yml"
        path1.write_text(VALID_YAML, encoding="utf-8")
        path2.write_text(VALID_YAML, encoding="utf-8")
        _, v1 = load_config(str(path1))
        _, v2 = load_config(str(path2))
        assert v1 == v2

    def test_version_changes_with_content(self, tmp_path):
        path1 = tmp_path / "a.yml"
        path2 = tmp_path / "b.yml"
        path1.write_text(VALID_YAML, encoding="utf-8")
        path2.write_text(VALID_YAML + "\n# comment\n", encoding="utf-8")
        _, v1 = load_config(str(path1))
        _, v2 = load_config(str(path2))
        assert v1 != v2


class TestMergeConfig:
    def test_none_override_returns_default_unchanged(self):
        default = DefaultConfig().volume
        assert merge_config(default, None) is default

    def test_override_replaces_only_set_fields(self):
        default = DefaultConfig().volume
        override = VolumeOverrideConfig(sigma=5.0)
        merged = merge_config(default, override)
        assert merged.sigma == 5.0
        assert merged.enabled is True
        assert merged.baseline_runs == 10

    def test_override_with_none_values_does_not_clobber_default(self):
        default = DefaultConfig().volume
        override = VolumeOverrideConfig(enabled=False, sigma=None)
        merged = merge_config(default, override)
        assert merged.enabled is False
        assert merged.sigma == 3.0

    def test_merged_result_is_revalidated(self):
        default = DefaultConfig().null_rate  # baseline_runs=10
        override = NullRateOverrideConfig(min_baseline_runs=999)
        with pytest.raises(ValidationError, match="min_baseline_runs"):
            merge_config(default, override)


class TestResolveSourceConfig:
    def test_none_override_returns_default(self):
        default = DefaultConfig()
        assert resolve_source_config(default, None) is default

    def test_partial_override_only_affects_targeted_check(self):
        default = DefaultConfig()
        override = TableCheckOverrides(volume=VolumeOverrideConfig(enabled=False))
        resolved = resolve_source_config(default, override)
        assert resolved.volume.enabled is False
        assert resolved.null_rate.enabled is True
        assert resolved.schema_drift.enabled is True

    def test_override_with_all_none_subfields_keeps_defaults(self):
        default = DefaultConfig()
        override = TableCheckOverrides()
        resolved = resolve_source_config(default, override)
        assert resolved.volume.enabled is True
        assert resolved.null_rate.enabled is True
        assert resolved.schema_drift.enabled is True
