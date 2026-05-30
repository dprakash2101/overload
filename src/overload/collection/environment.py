from __future__ import annotations

import json
from pathlib import Path


def parse_environment(source: str | Path | dict) -> dict[str, str]:
    if isinstance(source, dict):
        data = source
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Environment file not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

    variables: dict[str, str] = {}

    for entry in data.get("values", []):
        if entry.get("enabled", True) and "key" in entry:
            variables[entry["key"]] = entry.get("value", "")

    return variables
