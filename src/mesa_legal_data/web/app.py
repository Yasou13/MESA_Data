import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from mesa_legal_data.web.api import router as api_router

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings_override: Optional[Dict[str, Any]] = None) -> FastAPI:
    """
    FastAPI application factory for MESA Legal Data Web Management Panel.
    """
    if settings_override:
        for k, v in settings_override.items():
            os.environ[f"MESA_DATA_{k.upper()}"] = str(v)

    app = FastAPI(
        title="MESA Legal Data Web Admin",
        version="0.1.0",
        docs_url=None,  # Disabled in production MVP
        redoc_url=None,
    )

    # Global Exception Handler for consistent API Error schema
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        details_dict: Dict[str, Any] = {}
        if isinstance(detail, dict):
            code = detail.get("code", "ERROR")
            message = detail.get("message", str(detail))
            details_dict = detail.get("details", {})
        else:
            code = "HTTP_ERROR"
            message = str(detail)

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "error": {
                    "code": code,
                    "message": message,
                    "details": details_dict,
                },
            },
        )

    # Include API router
    app.include_router(api_router)

    # Mount Static Files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Serve Root index.html
    @app.get("/", response_class=HTMLResponse)
    def read_root():
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>MESA Legal Data Web Admin</h1>")

    return app
