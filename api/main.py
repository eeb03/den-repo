from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from database.session import init_db
from api.routes import datasets, fusion, benchmark, sources, training
from utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Subterra Data Platform API — initializing database...")
    init_db()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router, prefix="/api/datasets", tags=["datasets"])
app.include_router(fusion.router, prefix="/api/fusion", tags=["fusion"])
app.include_router(benchmark.router, prefix="/api/benchmark", tags=["benchmark"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(training.router, prefix="/api/training", tags=["training"])


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
