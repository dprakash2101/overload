from __future__ import annotations

import pytest

from overload.config_file import (
    extract_config,
    extract_test_type,
    extract_thresholds,
    load_config,
    save_config,
)
from overload.engine.models import Threshold


class TestLoadConfig:
    def test_loads_valid_yaml(self, tmp_path) -> None:
        cfg = tmp_path / "test.yaml"
        cfg.write_text(
            "test_type: load\n"
            "config:\n"
            "  target_rps: 100\n"
            "  hold_duration_seconds: 60\n"
            "thresholds:\n"
            "  - metric: p95_latency_ms\n"
            "    operator: '<'\n"
            "    value: 500\n"
        )
        raw = load_config(cfg)
        assert raw["test_type"] == "load"
        assert raw["config"]["target_rps"] == 100

    def test_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_content_raises(self, tmp_path) -> None:
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("- just\n- a\n- list\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_config(cfg)


class TestSaveConfig:
    def test_roundtrip(self, tmp_path) -> None:
        path = tmp_path / "out.yaml"
        thresholds = [
            Threshold("p95_latency_ms", "<", 500.0),
            Threshold("error_rate_pct", "<", 1.0),
        ]
        save_config(
            path,
            test_type="load",
            config={"target_rps": 100, "hold_duration_seconds": 60},
            thresholds=thresholds,
        )

        raw = load_config(path)
        assert raw["test_type"] == "load"
        assert raw["config"]["target_rps"] == 100

        loaded_thresholds = extract_thresholds(raw)
        assert len(loaded_thresholds) == 2
        assert loaded_thresholds[0].metric == "p95_latency_ms"
        assert loaded_thresholds[0].value == 500.0
        assert loaded_thresholds[1].metric == "error_rate_pct"

    def test_save_without_thresholds(self, tmp_path) -> None:
        path = tmp_path / "out.yaml"
        save_config(path, test_type="burst", config={"total_requests": 200})
        raw = load_config(path)
        assert "thresholds" not in raw
        assert extract_thresholds(raw) == []


class TestExtractors:
    def test_extract_test_type(self) -> None:
        assert extract_test_type({"test_type": "stress"}) == "stress"
        assert extract_test_type({}) is None

    def test_extract_config(self) -> None:
        assert extract_config({"config": {"rps": 50}}) == {"rps": 50}
        assert extract_config({}) == {}

    def test_extract_thresholds(self) -> None:
        raw = {
            "thresholds": [
                {"metric": "avg_rps", "operator": ">", "value": 100},
            ]
        }
        ts = extract_thresholds(raw)
        assert len(ts) == 1
        assert ts[0].metric == "avg_rps"
        assert ts[0].operator == ">"
        assert ts[0].value == 100.0

    def test_extract_thresholds_skips_invalid(self) -> None:
        raw = {"thresholds": ["not a dict", {"metric": "avg_rps", "operator": ">", "value": 10}]}
        ts = extract_thresholds(raw)
        assert len(ts) == 1
