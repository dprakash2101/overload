from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from overload.engine.models import Threshold

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "overload.config.yaml"


def load_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a YAML mapping, got {type(raw).__name__}")

    return raw


def save_config(
    path: str | Path,
    test_type: str,
    config: dict[str, Any],
    thresholds: list[Threshold] | None = None,
) -> str:
    data: dict[str, Any] = {
        "test_type": test_type,
        "config": config,
    }

    if thresholds:
        data["thresholds"] = [
            {"metric": t.metric, "operator": t.operator, "value": t.value}
            for t in thresholds
        ]

    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    logger.info("Config saved to %s", path)
    return str(path)


def extract_thresholds(raw: dict[str, Any]) -> list[Threshold]:
    thresholds: list[Threshold] = []
    for entry in raw.get("thresholds", []):
        if not isinstance(entry, dict):
            continue
        thresholds.append(Threshold(
            metric=entry["metric"],
            operator=entry["operator"],
            value=float(entry["value"]),
        ))
    return thresholds


def extract_config(raw: dict[str, Any]) -> dict[str, Any]:
    return raw.get("config", {})


def extract_test_type(raw: dict[str, Any]) -> str | None:
    return raw.get("test_type")
