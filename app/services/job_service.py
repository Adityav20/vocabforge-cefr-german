from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException, UploadFile

from app.core.config import Settings
from app.repositories.job_repository import JobRepository
from app.services.document_parser import DocumentParseError, DocumentParserService
from app.services.export_service import ExportService
from app.services.language_service import LanguageService
from app.services.vocabulary_service import VocabularyService


class JobService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: JobRepository,
        parser: DocumentParserService,
        language_service: LanguageService,
        vocabulary_service: VocabularyService,
        export_service: ExportService,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.parser = parser
        self.language_service = language_service
        self.vocabulary_service = vocabulary_service
        self.export_service = export_service

    async def create_job(
        self,
        *,
        upload: UploadFile,
        level: str,
        background_tasks: BackgroundTasks,
    ) -> dict:
        safe_name = self._sanitize_filename(upload.filename or "document")
        extension = Path(safe_name).suffix.lower()
        if extension not in self.settings.supported_extensions:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Upload a PDF, Word document, or PowerPoint presentation.",
            )

        job_id = uuid.uuid4().hex
        stored_filename = f"{job_id}{extension}"
        destination = self.settings.upload_dir / stored_filename

        file_size = 0
        with destination.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > self.settings.max_upload_size_bytes:
                    handle.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=400,
                        detail=f"Files larger than {self.settings.max_upload_size_mb} MB are not supported yet.",
                    )
                handle.write(chunk)

        self.repository.create_job(
            job_id=job_id,
            original_filename=safe_name,
            stored_filename=stored_filename,
            level=level,
        )
        background_tasks.add_task(self.process_job, job_id, destination)
        return self.repository.get_job(job_id)

    def process_job(self, job_id: str, source_path: Path) -> None:
        job = self.repository.get_job(job_id)
        if not job:
            return

        try:
            self.repository.update_job(
                job_id,
                status="processing",
                progress=18,
                stage="Extracting text",
                message="Reading the document and preparing its text content.",
            )
            parsed_document = self.parser.extract_text(source_path)

            self.repository.update_job(
                job_id,
                progress=36,
                stage="Checking language",
                message="Checking whether the document contains enough German text.",
            )
            language = self.language_service.assess(parsed_document.text)
            if not language.is_german:
                raise ValueError(language.warning or "The uploaded document does not appear to contain enough German text.")

            self.repository.update_job(
                job_id,
                progress=64,
                stage="Extracting vocabulary",
                message="Identifying vocabulary, CEFR levels, and English translations.",
                source_language=language.primary_language,
                warning=language.warning,
            )
            result = self.vocabulary_service.analyze(
                text=parsed_document.text,
                selected_level=job["level"],
                document_name=job["original_filename"],
                language_warning=language.warning,
                document_units=parsed_document.unit_count,
                source_type=parsed_document.source_type,
            )
            result["source_language"] = language.primary_language

            self.repository.update_job(
                job_id,
                progress=86,
                stage="Building downloads",
                message="Formatting your printable PDF and CSV export.",
            )
            pdf_path = self.settings.generated_dir / f"{job_id}.pdf"
            csv_path = self.settings.generated_dir / f"{job_id}.csv"
            result["generated_at"] = datetime.now(timezone.utc).isoformat()
            result["available_downloads"] = {
                "pdf": f"/api/v1/jobs/{job_id}/download/pdf",
                "csv": f"/api/v1/jobs/{job_id}/download/csv",
            }
            self.export_service.generate_pdf(result, pdf_path)
            self.export_service.generate_csv(result, csv_path)

            self.repository.complete_job(
                job_id,
                result=result,
                pdf_path=str(pdf_path),
                csv_path=str(csv_path),
                source_language=language.primary_language,
                warning=language.warning,
            )
        except (DocumentParseError, ValueError) as exc:
            self.repository.fail_job(job_id, str(exc))
        except Exception:
            self.repository.fail_job(
                job_id,
                "Something went wrong while processing the file. Please try again or use a cleaner export of the document.",
            )

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        cleaned = Path(filename).name
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned).strip("-")
        return cleaned or "document"
