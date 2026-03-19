from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.core.config import settings
from app.repositories.job_repository import JobRepository
from app.services.document_parser import DocumentParserService
from app.services.export_service import ExportService
from app.services.job_service import JobService
from app.services.language_service import LanguageService
from app.services.translation_service import TranslationService
from app.services.vocabulary_service import VocabularyService


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="AI-assisted German vocabulary extraction and CEFR filtering.",
    )

    templates = Jinja2Templates(directory=str(settings.base_dir / "templates"))
    repository = JobRepository(settings.database_path)
    translation_service = TranslationService(settings)
    vocabulary_service = VocabularyService(
        data_path=settings.data_dir / "cefr_vocabulary.csv",
        translation_service=translation_service,
    )
    job_service = JobService(
        settings=settings,
        repository=repository,
        parser=DocumentParserService(),
        language_service=LanguageService(),
        vocabulary_service=vocabulary_service,
        export_service=ExportService(),
    )

    app.state.settings = settings
    app.state.templates = templates
    app.state.job_repository = repository
    app.state.job_service = job_service

    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=str(settings.base_dir / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "max_upload_size_mb": settings.max_upload_size_mb,
            },
        )

    return app


app = create_app()
