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

import os
import sys
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
# Main (Process Manager or Worker)
# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run_worker":
        logger.info("Starting LiveKit agent worker: agent=%s", settings.agent_name)
        # Act purely as the livekit worker process.
        # Ensure Typer CLI sees standard commands (like 'start')
        if sys.argv[-1] not in ("start", "dev", "connect", "download-files", "console"):
            sys.argv.append("start")

        # Strip 'run_worker' from args so cli.run_app doesn't get confused
        sys.argv.remove("run_worker")

        cli.run_app(
            WorkerOptions(
                entrypoint_fnc=_get_entrypoint(),
                agent_name=settings.agent_name,
                port=0,  # Use random port for internal LiveKit healthcheck
            )
        )
    else:
        # Act as the Process Manager
        import subprocess
        port = os.environ.get("PORT", "8081")
        logger.info("==========================================")
        logger.info("🚀 SPAWNING MULTIPROCESS MANAGER")
        logger.info("==========================================")
        logger.info(f"Binding FastAPI Uvicorn to internal port: {port}")

        # Start LiveKit Agent Worker background process
        worker_process = subprocess.Popen(
            [sys.executable, "-m", "app.main", "run_worker", "start"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        # Start Uvicorn FastAPI Server foreground process
        uvicorn_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        logger.info("Successfully spanned both services! Polling health...")

        # Monitor processes
        try:
            while True:
                time.sleep(1)
                if uvicorn_process.poll() is not None:
                    logger.error("🛑 Uvicorn server crashed unexpectedly. Tearing down.")
                    worker_process.terminate()
                    sys.exit(1)
                
                if worker_process.poll() is not None:
                    logger.error("🛑 LiveKit Worker crashed unexpectedly. Tearing down.")
                    uvicorn_process.terminate()
                    sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt. Terminating gracefully...")
            worker_process.terminate()
            uvicorn_process.terminate()
            sys.exit(0)