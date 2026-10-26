"""FastAPI application entrypoint.

Run locally:   uvicorn app.main:app --reload   (from the backend/ folder)

If `frontend/dist` exists (after `npm run build`), it is served from `/`,
so the whole app can be deployed as ONE web service (no separate static
host, no CORS in production). In development the Vite dev server serves the
frontend and proxies /api to this process instead.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .ecourts.errors import EcourtsError
from .routers import drafts, ecourts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Lawyer Toolkit API",
    description="eCourts district court case scraper + legal draft template generator.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(EcourtsError)
def ecourts_error(_: Request, exc: EcourtsError):
    # One consistent error shape for every scraper failure:
    # {"detail": {"code", "message", "hint"}} -- same envelope as HTTPException.
    return JSONResponse(status_code=exc.http_status, content={"detail": exc.to_dict()})


app.include_router(ecourts.router)
app.include_router(drafts.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------- built frontend (optional)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # Serve real files (favicon etc.), otherwise index.html so client-side
        # routes like /drafts survive a page refresh.
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
