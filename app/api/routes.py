from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.models.schemas import CEFRLevel, CreateJobResponse, JobStatusModel


router = APIRouter(prefix="/api/v1", tags=["vocabulary"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/jobs", response_model=CreateJobResponse, status_code=202)
async def create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    level: CEFRLevel = Form(...),
) -> CreateJobResponse:
    job_service = request.app.state.job_service
    job = await job_service.create_job(upload=file, level=level.value, background_tasks=background_tasks)
    return CreateJobResponse(
        id=job["id"],
        status=job["status"],
        poll_url=f"/api/v1/jobs/{job['id']}",
        message="Upload accepted. Processing has started.",
    )


@router.get("/jobs", response_model=list[JobStatusModel])
def list_jobs(request: Request) -> list[dict]:
    repository = request.app.state.job_repository
    return repository.list_recent_jobs(limit=request.app.state.settings.history_limit)


@router.get("/jobs/{job_id}", response_model=JobStatusModel)
def get_job(job_id: str, request: Request) -> dict:
    repository = request.app.state.job_repository
    job = repository.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.get("/jobs/{job_id}/download/{fmt}")
def download_file(job_id: str, fmt: str, request: Request) -> FileResponse:
    repository = request.app.state.job_repository
    job = repository.get_job(job_id)
    if not job or job["status"] != "completed":
        raise HTTPException(status_code=404, detail="The requested export is not available.")

    if fmt not in {"pdf", "csv"}:
        raise HTTPException(status_code=404, detail="Unsupported download format.")

    file_path = Path(job[f"{fmt}_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="The requested file could not be found.")

    media_type = "application/pdf" if fmt == "pdf" else "text/csv"
    filename = f"german-vocabulary-{job['level'].lower()}.{fmt}"
    return FileResponse(file_path, media_type=media_type, filename=filename)

