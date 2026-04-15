"""
FastAPI application factory + main entry point.

This module:
1. Creates the FastAPI app with middleware and error handling
2. Mounts all API routes
3. Starts the FastAPI server in a background thread
4. Starts the LiveKit agent worker as the main process

Run with:
    python -m app.main dev
"""

from __future__ import annotations

import threading
import time
import traceback

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from livekit.agents import cli, WorkerOptions

from app.config import settings
from app.api.routes import router
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# FastAPI application
# ────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""

    app = FastAPI(
        title="Horizon Realty Voice Agent API",
        description="Outbound AI voice agent for real estate lead qualification",
        version="2.0.0",
    )

    # ── CORS (for frontend later) ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],      # Restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Global error handler ──
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception on %s %s: %s\n%s",
            request.method,
            request.url.path,
            exc,
            traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error_code": "INTERNAL_ERROR"},
        )

    # ── Request logging middleware ──
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000
        logger.info(
            "%s %s → %d (%.0fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # ── Mount routes ──
    app.include_router(router)

    return app


# Create the app instance (importable by uvicorn or tests)
app = create_app()


# ────────────────────────────────────────────────────────────────────
# Background API server
# ────────────────────────────────────────────────────────────────────

def start_api_server() -> None:
    """Run the FastAPI server (blocking — intended for a daemon thread)."""
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )


# ────────────────────────────────────────────────────────────────────
# Worker entrypoint import (deferred to avoid circular imports)
# ────────────────────────────────────────────────────────────────────

def _get_entrypoint():
    """Lazy import to break the config → agent_service → worker cycle."""
    from worker.agent_worker import entrypoint
    return entrypoint


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 1. Start FastAPI in a background daemon thread
    api_thread = threading.Thread(target=start_api_server, daemon=True)
    api_thread.start()
    logger.info("🌐 FastAPI server started on %s:%d", settings.api_host, settings.api_port)

    # 2. Start the LiveKit agent worker (main blocking call)
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=_get_entrypoint(),
            agent_name=settings.agent_name,
            http_server=False,   # ✅ THIS FIXES YOUR ISSUE
        )
    )
