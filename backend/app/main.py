from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import enrichment, health, portfolios
from app.core.config import settings
from app.dependencies import enrichment_service
from app.services.enrichment_worker import EnrichmentWorker


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker = None
    if settings.enrichment_worker_interval_seconds > 0:
        worker = EnrichmentWorker(
            enrichment_service,
            interval_seconds=settings.enrichment_worker_interval_seconds,
            batch_size=settings.enrichment_worker_batch_size,
        )
        worker.start()
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Explainable portfolio exposure graph API.",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(portfolios.router, prefix=settings.api_prefix)
app.include_router(enrichment.router, prefix=settings.api_prefix)

web_dir = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=web_dir), name="static")


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    return FileResponse(web_dir / "index.html")
