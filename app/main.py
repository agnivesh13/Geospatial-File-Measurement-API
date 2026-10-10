"""Application factory. Run with: ``uvicorn app.main:create_app --factory --reload``"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api import problem_response, router
from app.config import Settings, get_settings
from app.db import create_session_factory
from app.errors import GeoFileError


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass their own Settings (for example a temporary database)."""
    settings = settings or get_settings()
    app = FastAPI(
        title="Geospatial File Measurement API",
        version="1.0.0",
        summary="Upload a KML or zipped Shapefile and get the area or length of every feature in metres.",
    )
    app.state.settings = settings
    app.state.session_factory = create_session_factory(settings.database_url)
    app.include_router(router)
    app.add_exception_handler(GeoFileError, problem_response)

    @app.get("/", include_in_schema=False)
    def docs_redirect() -> RedirectResponse:
        return RedirectResponse("/docs")

    return app
