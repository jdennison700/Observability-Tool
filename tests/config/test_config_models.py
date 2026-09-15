"""Tests for pydantic config models and validation rules."""

import pytest
from pydantic import ValidationError

from obs_tool.config.config_models import (
    AppConfig,
    ExpectationConfig,
    ProjectConfig,
    SourceConfig,
    TableConfig,
    parse_duration_hours,
)


def make_source(**overrides):
    data = {
        "name": "warehouse",
        "type": "postgres",
        "connection_env": "WAREHOUSE_DSN",
        "tables": [{"name": "public.some_table"}],
    }
    data.update(overrides)
    return data


def make_app_config(**overrides):
    data = {
        "project": {"owner_email": "me@example.com", "scan_interval": 6},
        "source": make_source(),
    }
    data.update(overrides)
    return data


class TestParseDurationHours:
    def test_hours(self):
        assert parse_duration_hours("20h") == 20

    def test_days(self):
        assert parse_duration_hours("2d") == 48

    @pytest.mark.parametrize("value", ["20", "h20", "20m", "-5h", "", "20 h", "1.5h"])
    def test_invalid_formats_raise(self, value):
        with pytest.raises(ValueError):
            parse_duration_hours(value)


class TestProjectConfig:
    def test_accepts_int_and_string_intervals(self):
        p = ProjectConfig(owner_email="me@example.com", scan_interval="6h")
        assert p.scan_interval == 6

    def test_heartbeat_defaults_to_scan_plus_one_day(self):
        p = ProjectConfig(owner_email="me@example.com", scan_interval=6)
        assert p.heartbeat_interval == 30

    def test_heartbeat_can_be_overridden_above_scan(self):
        p = ProjectConfig(owner_email="me@example.com", scan_interval=6, heartbeat_interval=12)
        assert p.heartbeat_interval == 12

    def test_heartbeat_equal_to_scan_rejected(self):
        with pytest.raises(ValidationError, match="heartbeat_interval"):
            ProjectConfig(owner_email="me@example.com", scan_interval=6, heartbeat_interval=6)

    def test_heartbeat_less_than_scan_rejected(self):
        with pytest.raises(ValidationError, match="heartbeat_interval"):
            ProjectConfig(owner_email="me@example.com", scan_interval=12, heartbeat_interval=6)

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            ProjectConfig(owner_email="not-an-email", scan_interval=6)

    def test_scan_interval_must_be_positive(self):
        with pytest.raises(ValidationError):
            ProjectConfig(owner_email="me@example.com", scan_interval=0)

    def test_default_storage_path(self):
        p = ProjectConfig(owner_email="me@example.com", scan_interval=6)
        assert str(p.storage_path) == "observability.db"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ProjectConfig(owner_email="me@example.com", scan_interval=6, bogus="x")


class TestBaselineRuns:
    def test_min_baseline_runs_exceeds_baseline_runs_rejected(self):
        with pytest.raises(ValidationError, match="min_baseline_runs"):
            AppConfig.model_validate(
                make_app_config(
                    defaults={
                        "volume": {"baseline_runs": 5, "min_baseline_runs": 10},
                    }
                )
            )

    def test_min_baseline_runs_equal_allowed(self):
        cfg = AppConfig.model_validate(
            make_app_config(
                defaults={"volume": {"baseline_runs": 5, "min_baseline_runs": 5}}
            )
        )
        assert cfg.defaults.volume.min_baseline_runs == 5

    def test_override_with_only_one_field_set_is_not_compared(self):
        cfg = AppConfig.model_validate(
            make_app_config(
                source=make_source(
                    tables=[
                        {
                            "name": "public.t",
                            "checks": {"volume": {"min_baseline_runs": 999}},
                        }
                    ]
                )
            )
        )
        assert cfg.source.tables[0].checks.volume.min_baseline_runs == 999


class TestExpectationConfig:
    def test_not_null_rejects_value(self):
        with pytest.raises(ValidationError, match="not_null"):
            ExpectationConfig(column="c", op="not_null", value=1)

    def test_not_null_rejects_agg(self):
        with pytest.raises(ValidationError, match="not_null"):
            ExpectationConfig(column="c", op="not_null", agg="count")

    def test_not_null_valid(self):
        e = ExpectationConfig(column="c", op="not_null")
        assert e.value is None

    def test_non_not_null_requires_value(self):
        with pytest.raises(ValidationError, match="requires a value"):
            ExpectationConfig(column="c", op="gt")

    @pytest.mark.parametrize("op", ["gt", "gte", "lt", "lte"])
    def test_numeric_ops_reject_bool(self, op):
        with pytest.raises(ValidationError, match="numeric value"):
            ExpectationConfig(column="c", op=op, value=True)

    @pytest.mark.parametrize("op", ["gt", "gte", "lt", "lte"])
    def test_numeric_ops_reject_string(self, op):
        with pytest.raises(ValidationError, match="numeric value"):
            ExpectationConfig(column="c", op=op, value="5")

    @pytest.mark.parametrize("op", ["gt", "gte", "lt", "lte"])
    def test_numeric_ops_accept_int_and_float(self, op):
        e1 = ExpectationConfig(column="c", op=op, value=5)
        e2 = ExpectationConfig(column="c", op=op, value=5.5)
        assert e1.value == 5
        assert e2.value == 5.5

    def test_in_requires_list(self):
        with pytest.raises(ValidationError, match="requires a list value"):
            ExpectationConfig(column="c", op="in", value=5)

    def test_in_accepts_list(self):
        e = ExpectationConfig(column="c", op="in", value=[1, 2, 3])
        assert e.value == [1, 2, 3]

    def test_in_rejects_agg(self):
        with pytest.raises(ValidationError, match="'in' cannot be combined with 'agg'"):
            ExpectationConfig(column="c", op="in", value=[1], agg="count")

    def test_eq_accepts_string(self):
        e = ExpectationConfig(column="c", op="eq", value="active")
        assert e.value == "active"

    @pytest.mark.parametrize("agg", ["count", "count_distinct", "null_count"])
    def test_count_aggs_reject_float_value(self, agg):
        with pytest.raises(ValidationError, match="requires an integer value"):
            ExpectationConfig(column="c", op="eq", value=1.5, agg=agg)

    @pytest.mark.parametrize("agg", ["count", "count_distinct", "null_count"])
    def test_count_aggs_accept_int_value(self, agg):
        e = ExpectationConfig(column="c", op="eq", value=5, agg=agg)
        assert e.agg == agg

    @pytest.mark.parametrize("agg", ["sum", "avg"])
    def test_sum_avg_accept_numeric_value(self, agg):
        e = ExpectationConfig(column="c", op="eq", value=5.5, agg=agg)
        assert e.agg == agg

    def test_unknown_op_rejected(self):
        with pytest.raises(ValidationError):
            ExpectationConfig(column="c", op="startswith", value="x")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ExpectationConfig(column="c", op="not_null", bogus=True)


class TestTableConfig:
    def test_cadence_parses_duration_string(self):
        t = TableConfig(name="t", cadence="24h")
        assert t.cadence == 24

    def test_cadence_optional(self):
        t = TableConfig(name="t")
        assert t.cadence is None

    def test_cadence_must_be_positive(self):
        with pytest.raises(ValidationError):
            TableConfig(name="t", cadence=0)

    def test_invalid_alert_recipient_email(self):
        with pytest.raises(ValidationError):
            TableConfig(name="t", alert_recipients=["not-an-email"])


class TestSourceConfig:
    def test_duplicate_table_names_rejected(self):
        with pytest.raises(ValidationError, match="duplicate table name"):
            SourceConfig.model_validate(
                make_source(tables=[{"name": "t"}, {"name": "t"}])
            )

    def test_requires_at_least_one_table(self):
        with pytest.raises(ValidationError):
            SourceConfig.model_validate(make_source(tables=[]))

    def test_unknown_source_type_rejected(self):
        with pytest.raises(ValidationError):
            SourceConfig.model_validate(make_source(type="mysql"))


class TestAppConfig:
    def test_minimal_valid_config(self):
        cfg = AppConfig.model_validate(make_app_config())
        assert cfg.project.owner_email == "me@example.com"
        assert cfg.defaults.volume.enabled is True

    def test_extra_top_level_fields_forbidden(self):
        with pytest.raises(ValidationError):
            AppConfig.model_validate(make_app_config(bogus="x"))

    def test_schema_alias_populates_schema_field(self):
        cfg = AppConfig.model_validate(
            make_app_config(
                source=make_source(
                    tables=[
                        {
                            "name": "t",
                            "expectations": {
                                "schema": [{"column": "id", "type": "integer"}]
                            },
                        }
                    ]
                )
            )
        )
        assert cfg.source.tables[0].expectations.schema_[0].column == "id"
