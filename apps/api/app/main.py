from fastapi import FastAPI

from apps.api.app.config import get_settings
from apps.api.app.routes.health import router as health_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Financial Document Retrieval Engine API",
        version="0.1.0",
    )
    app.include_router(health_router)
    return app


app = create_app()
