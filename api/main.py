import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from database.session import init_db
from auth.mailer import configure_from_environment
from jobs.runner import mark_orphaned_jobs_failed
from api.routes import (datasets, fusion, benchmark, sources, training,
                        provenance, labels, overlays, objects, views,
                        exports, imports, auth, spatial, devices, candidates)
from utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Subterra Data Platform API — initializing database...")
    init_db()
    # An import that was running when the process died must not stay RUNNING
    # for ever; reconcile it to FAILED with a stated reason so the API can
    # always represent what actually happened.
    configure_from_environment()
    orphaned = mark_orphaned_jobs_failed()
    if orphaned:
        logger.info("Reconciled %d interrupted import job(s)", orphaned)
    yield
    logger.info("Shutting down Subterra Data Platform API")


app = FastAPI(
    title="Subterra Data Platform",
    description="Underground sensing data ingestion, validation, fusion, and serving API.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS. `allow_origins=["*"]` WITH `allow_credentials=True` is rejected by every
# browser -- the spec forbids a wildcard on a credentialed request -- so the
# previous configuration could never have carried a session cookie from the
# Next.js dev server on :3000. Origins are therefore explicit. Override with
# SUBTERRA_ALLOWED_ORIGINS (comma-separated) for any other deployment.
_origins = [
    o.strip()
    for o in os.environ.get(
        "SUBTERRA_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router, prefix="/api/datasets", tags=["datasets"])
app.include_router(provenance.router, prefix="/api/provenance", tags=["provenance"])
app.include_router(labels.router, prefix="/api/labels", tags=["labels"])
app.include_router(overlays.router, prefix="/api/overlays", tags=["overlays"])
app.include_router(objects.router, prefix="/api/objects", tags=["objects"])
app.include_router(views.router, prefix="/api/views", tags=["views"])
app.include_router(exports.router, prefix="/api/exports", tags=["exports"])
app.include_router(fusion.router, prefix="/api/fusion", tags=["fusion"])
app.include_router(benchmark.router, prefix="/api/benchmark", tags=["benchmark"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(training.router, prefix="/api/training", tags=["training"])
app.include_router(imports.router, prefix="/api/imports", tags=["imports"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(spatial.router, prefix="/api/spatial", tags=["spatial"])
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(devices.sessions_router, prefix="/api/sessions", tags=["devices"])
app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "service": "subterra-data-platform"}


@app.get("/viewer", response_class=HTMLResponse, tags=["system"])
def viewer():
    """
    Interactive 3D viewer. Open http://localhost:8000/viewer?datasets=ID1,ID2
    to auto-load and overlay one or more ingested datasets — combine a GPR
    dataset with a DEM-aligned elevation dataset to see a real fused 3D
    subsurface view.
    """
    html_path = Path(__file__).resolve().parent.parent / "visualization" / "viewer.html"
    return html_path.read_text()


@app.get("/client", response_class=HTMLResponse, tags=["system"])
def thin_client():
    """
    Thin client over the Subterra APIs: map, radargram, selection resolution,
    labels, objects and overlay composition.

    Deliberately thin -- it holds no identity logic and no spatial maths. Which
    views can show a selection is answered by /api/views/resolve, and anything
    the API cannot place is listed rather than plotted. See docs/thin-client.md.
    """
    html_path = (Path(__file__).resolve().parent.parent
                 / "visualization" / "thin_client.html")
    return html_path.read_text()
