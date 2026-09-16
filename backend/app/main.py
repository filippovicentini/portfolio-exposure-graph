from fastapi import FastAPI

from app.api.routes import health, portfolios
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Explainable portfolio exposure graph API.",
)

app.include_router(health.router)
app.include_router(portfolios.router, prefix=settings.api_prefix)
