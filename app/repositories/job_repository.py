from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL,
                    message TEXT,
                    error TEXT,
                    source_language TEXT,
                    warning TEXT,
                    result_json TEXT,
                    pdf_path TEXT,
                    csv_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create_job(
        self,
        *,
        job_id: str,
        original_filename: str,
        stored_filename: str,
        level: str,
    ) -> None:
        timestamp = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, original_filename, stored_filename, level, status, progress,
                    stage, message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    original_filename,
                    stored_filename,
                    level,
                    "queued",
                    5,
                    "Queued",
                    "Document received and waiting to be processed.",
                    timestamp,
                    timestamp,
                ),
            )

    def update_job(self, job_id: str, **updates: Any) -> None:
        if not updates:
            return
        updates["updated_at"] = _utc_now()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        values = list(updates.values()) + [job_id]
        with self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                values,
            )

    def complete_job(
        self,
        job_id: str,
        *,
        result: dict[str, Any],
        pdf_path: str,
        csv_path: str,
        source_language: str,
        warning: str | None,
    ) -> None:
        self.update_job(
            job_id,
            status="completed",
            progress=100,
            stage="Completed",
            message="Your vocabulary pack is ready to preview and download.",
            source_language=source_language,
            warning=warning,
            result_json=json.dumps(result),
            pdf_path=pdf_path,
            csv_path=csv_path,
        )

    def fail_job(self, job_id: str, error: str) -> None:
        self.update_job(
            job_id,
            status="failed",
            progress=100,
            stage="Failed",
            error=error,
            message="We could not produce a vocabulary pack from this document.",
        )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def list_recent_jobs(self, limit: int = 8) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = dict(row)
        if payload.get("result_json"):
            payload["result"] = json.loads(payload.pop("result_json"))
        else:
            payload.pop("result_json", None)
            payload["result"] = None
        return payload

