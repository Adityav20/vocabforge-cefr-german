from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CEFRLevel(str, Enum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VocabularyEntryModel(BaseModel):
    term: str
    translation: str
    category: str
    cefr_level: CEFRLevel
    lemma: str
    occurrences: int = Field(default=1, ge=1)
    article: str | None = None
    example: str | None = None


class JobSummaryModel(BaseModel):
    total_entries: int
    section_counts: dict[str, int]
    detected_level_mix: dict[str, int]
    translation_mode: str
    language_warning: str | None = None
    notes: list[str] = Field(default_factory=list)


class JobResultModel(BaseModel):
    document_name: str
    selected_level: CEFRLevel
    source_language: str
    generated_at: str
    summary: JobSummaryModel
    sections: dict[str, list[VocabularyEntryModel]]
    available_downloads: dict[str, str]


class JobStatusModel(BaseModel):
    id: str
    original_filename: str
    level: CEFRLevel
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    stage: str
    message: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    source_language: str | None = None
    warning: str | None = None
    result: JobResultModel | None = None


class CreateJobResponse(BaseModel):
    id: str
    status: JobStatus
    poll_url: str
    message: str

