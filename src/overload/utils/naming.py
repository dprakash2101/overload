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
