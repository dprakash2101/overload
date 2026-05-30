from __future__ import annotations

import csv
import json
import logging
import os

from overload.engine.models import Stats
from overload.utils.naming import stamped_filename

logger = logging.getLogger(__name__)


def export_json(
    stats: Stats,
    test_type: str,
    run_id: str,
    output_dir: str = ".",
    ramp_rows: list[dict] | None = None,
) -> str:
    computed = stats.compute()
    if not computed:
        logger.warning("No results to export")
        return ""

    payload = {
        "meta": {"run_id": run_id, "test_type": test_type},
        "stats": computed,
        "ramp_rows": ramp_rows or [],
    }

    filename = stamped_filename("overload_results", run_id, ".json")
    filepath = os.path.join(output_dir, filename)
    os.makedirs(output_dir, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    logger.info("JSON export: %s", os.path.abspath(filepath))
    return filepath


def export_csv(
    stats: Stats,
    run_id: str,
    output_dir: str = ".",
) -> str:
    if not stats.results:
        logger.warning("No results to export")
        return ""

    filename = stamped_filename("overload_results", run_id, ".csv")
    filepath = os.path.join(output_dir, filename)
    os.makedirs(output_dir, exist_ok=True)

    fieldnames = [
        "timestamp", "request_name", "method", "url",
        "status_code", "latency_ms", "error", "body_size_bytes",
    ]

    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in stats.results:
            writer.writerow({
                "timestamp": r.timestamp,
                "request_name": r.request_name,
                "method": r.method,
                "url": r.url,
                "status_code": r.status_code,
                "latency_ms": round(r.latency_ms, 1),
                "error": r.error or "",
                "body_size_bytes": r.body_size_bytes,
            })

    logger.info("CSV export: %s", os.path.abspath(filepath))
    return filepath
