from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from overload.collection.data_source import DataSource
from overload.collection.environment import parse_environment
from overload.collection.models import ParsedCollection
from overload.collection.parser import parse_collection
from overload.collection.variables import VariableContext, discover_placeholders
from overload.config_file import extract_config, extract_test_type, extract_thresholds, load_config, save_config
from overload.engine import service as _engine_service
from overload.engine.models import PatternConfig, RunProgress, Threshold
from overload.utils.naming import generate_run_id

logger = logging.getLogger(__name__)

router = APIRouter()

_state: dict[str, Any] = {
    "collection": None,
    "environment": None,
    "variables": None,
    "data_source": None,
    "current_task": None,
    "cancel_event": None,
    "current_run_id": None,
    "working_dir": os.getcwd(),
}


def _detect_postman_files(directory: str) -> dict[str, list[dict]]:
    collections: list[dict] = []
    environments: list[dict] = []
    csv_files: list[dict] = []

    dir_path = Path(directory)
    if not dir_path.is_dir():
        return {"collections": collections, "environments": environments, "csv_files": csv_files}

    for f in sorted(dir_path.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)

            if isinstance(data, dict):
                info = data.get("info", {})
                schema = info.get("schema", "")
                if "postman" in schema.lower() or (info.get("name") and "item" in data):
                    collections.append({
                        "name": info.get("name", f.stem),
                        "filename": f.name,
                        "path": str(f),
                        "request_count": _count_requests(data.get("item", [])),
                    })
                elif "values" in data and isinstance(data.get("values"), list):
                    environments.append({
                        "name": data.get("name", f.stem),
                        "filename": f.name,
                        "path": str(f),
                        "variable_count": len(data.get("values", [])),
                    })
        except (json.JSONDecodeError, OSError):
            continue

    for f in sorted(dir_path.glob("*.csv")):
        try:
            ds = DataSource.from_csv(str(f))
            csv_files.append({
                "filename": f.name,
                "path": str(f),
                "row_count": len(ds.rows),
                "columns": ds.columns,
            })
        except OSError:
            continue

    return {"collections": collections, "environments": environments, "csv_files": csv_files}


def _count_requests(items: list) -> int:
    count = 0
    for item in items:
        if "request" in item:
            count += 1
        if "item" in item:
            count += _count_requests(item["item"])
    return count


@router.get("/detect")
async def detect_files() -> JSONResponse:
    working_dir = _state.get("working_dir", os.getcwd())
    detected = _detect_postman_files(working_dir)
    return JSONResponse({
        "status": "ok",
        "working_dir": working_dir,
        **detected,
    })


@router.post("/collection/load-local")
async def load_local_collection(body: dict) -> JSONResponse:
    filepath = body.get("path", "")
    if not filepath or not os.path.isfile(filepath):
        return JSONResponse({"status": "error", "message": "File not found"}, status_code=400)
    try:
        collection = parse_collection(filepath)
        _state["collection"] = collection

        env_vars = _state["environment"] or {}
        _state["variables"] = VariableContext(
            collection_vars=collection.variables,
            environment_vars=env_vars,
        )

        logger.info("Collection loaded from disk: %s (%d requests)", collection.name, len(collection.requests))
        return JSONResponse({"status": "ok", "collection": collection.to_dict()})
    except Exception as exc:
        logger.exception("Error parsing collection")
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)


@router.post("/environment/load-local")
async def load_local_environment(body: dict) -> JSONResponse:
    filepath = body.get("path", "")
    if not filepath or not os.path.isfile(filepath):
        return JSONResponse({"status": "error", "message": "File not found"}, status_code=400)
    try:
        env_vars = parse_environment(filepath)
        _state["environment"] = env_vars

        if _state["collection"]:
            _state["variables"] = VariableContext(
                collection_vars=_state["collection"].variables,
                environment_vars=env_vars,
            )

        logger.info("Environment loaded from disk: %d variables", len(env_vars))
        return JSONResponse({"status": "ok", "variables": env_vars})
    except Exception as exc:
        logger.exception("Error parsing environment")
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)


@router.post("/collection/upload")
async def upload_collection(file: UploadFile = File(...)) -> JSONResponse:
    try:
        content = await file.read()
        data = json.loads(content)
        collection = parse_collection(data)
        _state["collection"] = collection

        env_vars = _state["environment"] or {}
        _state["variables"] = VariableContext(
            collection_vars=collection.variables,
            environment_vars=env_vars,
        )

        logger.info("Collection loaded: %s (%d requests)", collection.name, len(collection.requests))
        return JSONResponse({"status": "ok", "collection": collection.to_dict()})
    except json.JSONDecodeError:
        return JSONResponse({"status": "error", "message": "Invalid JSON file"}, status_code=400)
    except Exception as exc:
        logger.exception("Error parsing collection")
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)


@router.post("/environment/upload")
async def upload_environment(file: UploadFile = File(...)) -> JSONResponse:
    try:
        content = await file.read()
        data = json.loads(content)
        env_vars = parse_environment(data)
        _state["environment"] = env_vars

        if _state["collection"]:
            _state["variables"] = VariableContext(
                collection_vars=_state["collection"].variables,
                environment_vars=env_vars,
            )

        logger.info("Environment loaded: %d variables", len(env_vars))
        return JSONResponse({"status": "ok", "variables": env_vars})
    except Exception as exc:
        logger.exception("Error parsing environment")
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)


@router.post("/data/upload")
async def upload_data(file: UploadFile = File(...)) -> JSONResponse:
    try:
        content = await file.read()
        ds = DataSource.from_csv(io.BytesIO(content))
        _state["data_source"] = ds
        collection: ParsedCollection | None = _state.get("collection")
        matched: list[str] = []
        unmatched: list[str] = []
        if collection:
            placeholders = discover_placeholders(collection)
            col_set = set(ds.columns)
            matched = sorted(placeholders & col_set)
            unmatched = sorted(placeholders - col_set)
        logger.info("CSV data loaded: %d rows, %d columns", len(ds.rows), len(ds.columns))
        return JSONResponse({
            "status": "ok",
            "row_count": len(ds.rows),
            "columns": ds.columns,
            "matched_placeholders": matched,
            "unmatched_placeholders": unmatched,
        })
    except Exception as exc:
        logger.exception("Error loading CSV")
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)


@router.post("/data/load-local")
async def load_local_data(body: dict) -> JSONResponse:
    filepath = body.get("path", "")
    if not filepath or not os.path.isfile(filepath):
        return JSONResponse({"status": "error", "message": "File not found"}, status_code=400)
    try:
        ds = DataSource.from_csv(filepath)
        _state["data_source"] = ds
        collection: ParsedCollection | None = _state.get("collection")
        matched: list[str] = []
        unmatched: list[str] = []
        if collection:
            placeholders = discover_placeholders(collection)
            col_set = set(ds.columns)
            matched = sorted(placeholders & col_set)
            unmatched = sorted(placeholders - col_set)
        logger.info("CSV data loaded from disk: %s (%d rows)", filepath, len(ds.rows))
        return JSONResponse({
            "status": "ok",
            "row_count": len(ds.rows),
            "columns": ds.columns,
            "matched_placeholders": matched,
            "unmatched_placeholders": unmatched,
        })
    except Exception as exc:
        logger.exception("Error loading CSV from disk")
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)


@router.post("/data/clear")
async def clear_data() -> JSONResponse:
    _state["data_source"] = None
    logger.info("Data source cleared")
    return JSONResponse({"status": "ok"})


@router.get("/data/status")
async def data_status() -> JSONResponse:
    ds: DataSource | None = _state.get("data_source")
    if ds is None:
        return JSONResponse({"attached": False})
    return JSONResponse({
        "attached": True,
        "row_count": len(ds.rows),
        "columns": ds.columns,
    })


@router.post("/variables/update")
async def update_variables(body: dict) -> JSONResponse:
    overrides = body.get("variables", {})
    if _state["variables"]:
        for key, value in overrides.items():
            _state["variables"].set_variable(key, value)
    else:
        collection = _state.get("collection")
        _state["variables"] = VariableContext(
            collection_vars=collection.variables if collection else [],
            runtime_vars=overrides,
        )
    return JSONResponse({"status": "ok"})


@router.post("/test/start")
async def start_test(body: dict) -> JSONResponse:
    collection: ParsedCollection | None = _state.get("collection")
    if not collection or not collection.requests:
        return JSONResponse(
            {"status": "error", "message": "No collection loaded"},
            status_code=400,
        )

    if _state.get("current_task") and not _state["current_task"].done():
        return JSONResponse(
            {"status": "error", "message": "A test is already running"},
            status_code=409,
        )

    test_type = body.get("test_type", "burst")
    config_dict = body.get("config", {})
    selected_indices = body.get("selected_requests")

    if selected_indices is not None:
        if len(selected_indices) == 0:
            return JSONResponse(
                {"status": "error", "message": "No requests selected"},
                status_code=400,
            )
        n = len(collection.requests)
        invalid = [i for i in selected_indices if not isinstance(i, int) or i < 0 or i >= n]
        if invalid:
            return JSONResponse(
                {"status": "error", "message": f"Invalid request indices (must be 0–{n - 1}): {invalid}"},
                status_code=400,
            )

    thresholds: list[Threshold] = []
    for entry in body.get("thresholds", []):
        if isinstance(entry, dict) and "metric" in entry:
            thresholds.append(Threshold(
                metric=entry["metric"],
                operator=entry.get("operator", "<"),
                value=float(entry.get("value", 0)),
            ))

    run_id = generate_run_id()
    cancel_event = asyncio.Event()
    _state["cancel_event"] = cancel_event

    config = PatternConfig(**{k: v for k, v in config_dict.items() if hasattr(PatternConfig, k)})

    requests = collection.requests
    if selected_indices is not None:
        requests = [collection.requests[i] for i in selected_indices]

    variables = _state.get("variables") or VariableContext(collection_vars=collection.variables)
    data_source = _state.get("data_source")
    output_dir = os.path.join(_state.get("working_dir", os.getcwd()), "reports")

    from overload.web.routes.ws import broadcast_progress

    async def on_progress(progress: RunProgress) -> None:
        await broadcast_progress(run_id, progress)

    async def _run_test() -> None:
        result = await _engine_service.run_test(
            collection, test_type, config,
            variables=variables,
            requests=requests,
            thresholds=thresholds,
            data_source=data_source,
            output_dir=output_dir,
            run_id=run_id,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
        logger.info("Test %s: %s", result.status, run_id)

    task = asyncio.create_task(_run_test())
    _state["current_task"] = task
    _state["current_run_id"] = run_id

    return JSONResponse({"status": "ok", "run_id": run_id})


@router.post("/test/stop")
async def stop_test() -> JSONResponse:
    cancel_event = _state.get("cancel_event")
    if cancel_event:
        cancel_event.set()
        logger.info("Stop signal sent — waiting for graceful shutdown")
    task = _state.get("current_task")
    if task and not task.done():
        async def _watchdog(t: asyncio.Task) -> None:  # type: ignore[type-arg]
            await asyncio.sleep(10)
            if not t.done():
                t.cancel()
                logger.info("Watchdog: hard-cancelled task after grace window")
        asyncio.create_task(_watchdog(task))
    return JSONResponse({"status": "ok"})


@router.get("/runs")
async def list_runs() -> JSONResponse:
    reports_dir = os.path.join(_state.get("working_dir", os.getcwd()), "reports")
    _engine_service.load_run_history(reports_dir)
    runs = []
    for run_id, run_data in _engine_service._runs.items():
        summary = {
            "run_id": run_id,
            "test_type": run_data.get("test_type", ""),
            "status": run_data.get("status", ""),
        }
        stats = run_data.get("stats")
        if stats:
            summary["total"] = stats.get("total", 0)
            summary["ok"] = stats.get("ok", 0)
            summary["errors"] = stats.get("errors", 0)
            summary["avg_rps"] = stats.get("avg_rps", 0)
            summary["duration"] = stats.get("duration_seconds", 0)
        verdict = run_data.get("verdict")
        if verdict is not None:
            summary["verdict"] = verdict["passed"]
        runs.append(summary)
    return JSONResponse({"runs": runs})


@router.get("/runs/{run_id}/data")
async def get_run_data(run_id: str) -> JSONResponse:
    run_data = _engine_service.get_run(run_id)
    if not run_data:
        return JSONResponse({"status": "error", "message": "Run not found"}, status_code=404)
    return JSONResponse(run_data)


@router.get("/runs/{run_id}/report")
async def get_run_report(run_id: str) -> FileResponse:
    run_data = _engine_service.get_run(run_id)
    if not run_data or not run_data.get("report_path"):
        return JSONResponse({"status": "error", "message": "Report not found"}, status_code=404)
    return FileResponse(run_data["report_path"], media_type="text/html")


@router.get("/runs/{run_id}/export/csv")
async def export_run_csv(run_id: str) -> JSONResponse:
    run_data = _engine_service.get_run(run_id)
    if not run_data:
        return JSONResponse({"status": "error", "message": "Run not found"}, status_code=404)
    return JSONResponse({"status": "error", "message": "CSV export requires stored results"}, status_code=501)


@router.get("/runs/{run_id}/export/json")
async def export_run_json(run_id: str) -> JSONResponse:
    run_data = _engine_service.get_run(run_id)
    if not run_data:
        return JSONResponse({"status": "error", "message": "Run not found"}, status_code=404)
    return JSONResponse(run_data)


@router.get("/test/status")
async def test_status() -> JSONResponse:
    task = _state.get("current_task")
    if task and not task.done():
        return JSONResponse({"status": "running"})
    return JSONResponse({"status": "idle"})


@router.post("/config/save")
async def save_config_endpoint(body: dict) -> JSONResponse:
    working_dir = _state.get("working_dir", os.getcwd())
    test_type = body.get("test_type", "burst")
    config_dict = body.get("config", {})
    threshold_list: list[Threshold] = []
    for entry in body.get("thresholds", []):
        if isinstance(entry, dict) and "metric" in entry:
            threshold_list.append(Threshold(
                metric=entry["metric"],
                operator=entry.get("operator", "<"),
                value=float(entry.get("value", 0)),
            ))
    path = os.path.join(working_dir, "overload.config.yaml")
    save_config(path, test_type, config_dict, threshold_list if threshold_list else None)
    return JSONResponse({"status": "ok", "path": path})


@router.get("/config/load")
async def load_config_endpoint() -> JSONResponse:
    working_dir = _state.get("working_dir", os.getcwd())
    path = os.path.join(working_dir, "overload.config.yaml")
    if not os.path.isfile(path):
        return JSONResponse({"status": "error", "message": "No overload.config.yaml found"}, status_code=404)
    raw = load_config(path)
    return JSONResponse({"status": "ok", "config": raw})
