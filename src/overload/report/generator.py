from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from overload.engine.models import Stats
from overload.utils.naming import generate_run_id, stamped_filename

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _create_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )


def generate_report(
    stats: Stats,
    test_type: str,
    config: dict,
    run_id: str | None = None,
    ramp_rows: list[dict] | None = None,
    output_dir: str = "reports",
    verdict: dict | None = None,
) -> str:
    run_id = run_id or generate_run_id()
    computed = stats.compute()
    if not computed:
        logger.warning("No results to generate report from")
        return ""

    payload: dict = {
        "meta": {
            "run_id": run_id,
            "test_type": test_type,
            "config": config,
        },
        "stats": computed,
        "ramp_rows": ramp_rows or [],
    }
    if verdict is not None:
        payload["verdict"] = verdict

    data_json = json.dumps(payload, separators=(",", ":"))
    data_json = data_json.replace("</", "<\\/")

    env = _create_jinja_env()
    template = env.get_template("report.html")
    html = template.render(
        run_id=run_id,
        test_type=test_type,
        data_json=data_json,
    )

    filename = stamped_filename("overload_report", run_id, ".html")
    filepath = os.path.join(output_dir, filename)
    os.makedirs(output_dir, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report generated: %s", os.path.abspath(filepath))
    return filepath
