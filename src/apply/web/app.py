"""The dashboard. Server-rendered, bound to localhost, no build step.

State changes are plain form POSTs followed by a redirect. There is no client
framework and no CDN script tag: a tool that has to work offline in five years
should not depend on a URL staying up, and at four routes the interactivity a
JS library would buy is not worth the dependency.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import router

BASE = Path(__file__).resolve().parents[3]

app = FastAPI(
    title="apply",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(router)
