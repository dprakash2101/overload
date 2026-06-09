from __future__ import annotations

import json
import logging
import os

from overload.engine.models import Stats

logger = logging.getLogger(__name__)

RESPONSES_FILENAME = "responses.json"


def write_responses_json(run_dir: str, stats: Stats, run_id: str) -> str:
    """Write captured response bodies to ``{run_dir}/responses.json``.

    Returns the file path, or ``""`` when no response bodies were captured
    (i.e. the run was started without ``save_responses``).
    """
    entries = []
    if stats.results:
        t0 = stats.results[0].timestamp
        for i, r in enumerate(stats.results):
            if r.response_body is None:
                continue
            entries.append({
                "index": i,
                "request_name": r.request_name,
                "method": r.method,
                "url": r.url,
                "status": r.status_code,
                "latency_ms": round(r.latency_ms, 1),
                "timestamp": round(r.timestamp - t0, 3),
                "response_body": r.response_body,
            })

    if not entries:
        return ""

    payload = {"run_id": run_id, "count": len(entries), "responses": entries}
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, RESPONSES_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))

    logger.info("Responses written: %s (%d entries)", os.path.abspath(path), len(entries))
    return path
