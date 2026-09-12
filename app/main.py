from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.deps import UiBasicAuthMiddleware
from app.api.integrations import router as integrations_router
from app.api.routes import router
from app.core.config import get_settings
from app.db.session import init_db
from app.web.pages import (
    catalog_page,
    home_page,
    logs_page,
    progress_page,
    queue_page,
    race_page,
    reading_page,
)
from app.workers.scheduler import start_scheduler, stop_scheduler

_STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


def _media_cache_dir() -> Path:
    docker = Path("/app/data/media_cache")
    if docker.parent.is_dir():
        docker.mkdir(parents=True, exist_ok=True)
        return docker
    local = Path("data/media_cache")
    local.mkdir(parents=True, exist_ok=True)
    return local

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    # Ensure data dirs exist for sqlite / exports
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        # handle sqlite:////absolute
        if settings.database_url.startswith("sqlite:////"):
            db_path = "/" + settings.database_url[len("sqlite:////") :]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("data/tadoku_export").mkdir(parents=True, exist_ok=True)
    _media_cache_dir()

    init_db()
    start_scheduler()
    logger.info("immersion-tracker %s ready", __version__)
    yield
    stop_scheduler()


app = FastAPI(
    title="Immersion Tracker",
    version=__version__,
    description="Japanese immersion logging, Google Sheets sync, Tadoku queue",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Outer auth gate (runs after CORS on the way in — added last = outermost)
app.add_middleware(UiBasicAuthMiddleware)

app.include_router(router, prefix="/api")
app.include_router(integrations_router, prefix="/api")

if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.mount(
    "/media-cache",
    StaticFiles(directory=str(_media_cache_dir())),
    name="media-cache",
)


@app.get("/", response_class=HTMLResponse)
def index():
    return home_page()


@app.get("/queue", response_class=HTMLResponse)
@app.get("/inbox", response_class=HTMLResponse)
def queue_ui():
    """Inbox (primary ops) — /queue kept as stable URL alias."""
    return queue_page()


@app.get("/catalog", response_class=HTMLResponse)
def catalog_ui():
    return catalog_page()


@app.get("/logs", response_class=HTMLResponse)
def logs_ui():
    return logs_page()


@app.get("/progress", response_class=HTMLResponse)
def progress_ui():
    return progress_page()


@app.get("/reading", response_class=HTMLResponse)
def reading_ui():
    return reading_page()


@app.get("/race", response_class=HTMLResponse)
def race_ui():
    return race_page()


