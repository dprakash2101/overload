from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from overload.engine.models import RunProgress

logger = logging.getLogger(__name__)

router = APIRouter()

_connections: dict[str, list[WebSocket]] = {}


async def broadcast_progress(run_id: str, progress: RunProgress) -> None:
    sockets = _connections.get(run_id, [])
    if not sockets:
        return

    message = json.dumps({
        "type": "progress",
        "data": asdict(progress),
    })

    dead: list[WebSocket] = []
    for ws in sockets:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)

    for ws in dead:
        sockets.remove(ws)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    subscribed_run: str | None = None

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            if msg.get("type") == "subscribe":
                run_id = msg.get("run_id", "")
                if subscribed_run and subscribed_run in _connections:
                    conns = _connections[subscribed_run]
                    if ws in conns:
                        conns.remove(ws)

                subscribed_run = run_id
                _connections.setdefault(run_id, []).append(ws)
                await ws.send_text(json.dumps({"type": "subscribed", "run_id": run_id}))
                logger.debug("WebSocket subscribed to run %s", run_id)

            elif msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected")
    except Exception:
        logger.exception("WebSocket error")
    finally:
        if subscribed_run and subscribed_run in _connections:
            conns = _connections[subscribed_run]
            if ws in conns:
                conns.remove(ws)
