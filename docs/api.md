# API Overview

Base URL: `http://127.0.0.1:8000`

## Endpoints

`GET /`
- Returns the server-rendered web application.

`GET /api/v1/health`
- Basic health probe.

`POST /api/v1/jobs`
- Accepts multipart form data:
- `file`: PDF, DOCX, or PPTX upload
- `level`: one of `A1`, `A2`, `B1`, `B2`, `C1`, `C2`
- Returns `202 Accepted` with:
- `id`
- `status`
- `poll_url`

`GET /api/v1/jobs`
- Returns the most recent jobs for the UI history panel.

`GET /api/v1/jobs/{job_id}`
- Returns full job status, progress, metadata, and the finished result payload.

`GET /api/v1/jobs/{job_id}/download/pdf`
- Downloads the generated PDF pack.

`GET /api/v1/jobs/{job_id}/download/csv`
- Downloads the CSV export.

## Result Shape

Completed jobs include:

- `summary.total_entries`
- `summary.section_counts`
- `summary.detected_level_mix`
- `summary.translation_mode`
- `summary.language_warning`
- `summary.notes`
- `sections.nouns`
- `sections.verbs`
- `sections.adjectives`
- `sections.adverbs`
- `sections.prepositions`
- `sections.phrases`

Each vocabulary entry includes:

- `term`
- `translation`
- `cefr_level`
- `lemma`
- `occurrences`
- `article`
- `example`

