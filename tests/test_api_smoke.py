from __future__ import annotations

from io import BytesIO
import unittest

from docx import Document
from fastapi.testclient import TestClient

from app.main import app


class ApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_create_job_and_download_exports(self) -> None:
        buffer = BytesIO()
        document = Document()
        document.add_paragraph(
            "Die Entscheidung ist wichtig. Im Vergleich zu früher analysieren wir die Strategie "
            "und beschreiben die Entwicklung Schritt für Schritt."
        )
        document.save(buffer)
        buffer.seek(0)

        response = self.client.post(
            "/api/v1/jobs",
            files={
                "file": (
                    "sample.docx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            data={"level": "B2"},
        )
        self.assertEqual(response.status_code, 202)

        payload = response.json()
        status_response = self.client.get(payload["poll_url"])
        self.assertEqual(status_response.status_code, 200)
        job = status_response.json()
        self.assertEqual(job["status"], "completed")
        self.assertGreater(job["result"]["summary"]["total_entries"], 0)

        pdf_response = self.client.get(job["result"]["available_downloads"]["pdf"])
        csv_response = self.client.get(job["result"]["available_downloads"]["csv"])
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("application/pdf", pdf_response.headers["content-type"])
        self.assertIn("text/csv", csv_response.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
