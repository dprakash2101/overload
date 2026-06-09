from __future__ import annotations

import os
import random
import string
from datetime import datetime


def generate_run_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{ts}_{suffix}"


def generate_correlation_id(length: int = 20) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def stamped_filename(base_name: str, run_id: str, extension: str = ".html") -> str:
    return f"{base_name}_{run_id}{extension}"


def make_output_dir(base_dir: str, run_id: str) -> str:
    path = os.path.join(base_dir, "overload_runs", run_id)
    os.makedirs(path, exist_ok=True)
    return path


def run_dir_name(run_id: str) -> str:
    """Folder name for a single run. The run_id already embeds the datetime."""
    return f"run_{run_id}"


def make_run_dir(base_dir: str, run_id: str) -> str:
    """Create and return the per-run output folder: ``{base_dir}/run_{run_id}``."""
    path = os.path.join(base_dir, run_dir_name(run_id))
    os.makedirs(path, exist_ok=True)
    return path
