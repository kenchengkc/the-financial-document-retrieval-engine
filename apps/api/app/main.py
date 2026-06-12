from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import Base, get_engine
from apps.api.app.routes.answer import router as answer_router
from apps.api.app.routes.companies import router as companies_router
from apps.api.app.routes.health import router as health_router
from apps.api.app.routes.operations import router as operations_router
from apps.api.app.routes.research import router as research_router
from apps.api.app.routes.search import router as search_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    settings = get_settings()
    if settings.app_env == "vercel-demo":
        _initialize_demo_database()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Financial Document Retrieval Engine API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(answer_router)
    app.include_router(companies_router)
    app.include_router(health_router)
    app.include_router(operations_router)
    app.include_router(research_router)
    app.include_router(search_router)
    return app


def _initialize_demo_database() -> None:
    from fdre.demo import seed_demo_document

    engine = get_engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_demo_document(session)


app = create_app()
