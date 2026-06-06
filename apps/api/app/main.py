from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.config import get_settings
from apps.api.app.routes.answer import router as answer_router
from apps.api.app.routes.health import router as health_router
from apps.api.app.routes.search import router as search_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Financial Document Retrieval Engine API",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(answer_router)
    app.include_router(health_router)
    app.include_router(search_router)
    return app


app = create_app()
