from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from overload.web.routes.api import router as api_router, _state
from overload.web.routes.ws import router as ws_router

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(working_dir: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Overload",
        description="Load testing tool for Postman collections",
        version="0.1.0",
    )

    _state["working_dir"] = working_dir or os.getcwd()

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)

    @app.get("/")
    async def index():
        from fastapi.responses import FileResponse
        return FileResponse(str(TEMPLATES_DIR / "index.html"))

    return app
