from __future__ import annotations

import csv
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


CATEGORY_LABELS = {
    "nouns": "Nouns",
    "verbs": "Verbs",
    "adjectives": "Adjectives",
    "adverbs": "Adverbs",
    "prepositions": "Prepositions",
    "phrases": "Phrases",
}


class ExportService:
    def generate_pdf(self, result: dict, output_path: Path) -> None:
        styles = self._build_styles()
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=20 * mm,
            bottomMargin=18 * mm,
            title=f"German Vocabulary - Level {result['selected_level']}",
        )

        summary = result["summary"]
        story = [
            Paragraph(f"German Vocabulary - Level {result['selected_level']}", styles["title"]),
            Spacer(1, 4 * mm),
            Paragraph(result["document_name"], styles["subtitle"]),
            Spacer(1, 8 * mm),
            Paragraph(
                f"Detected language: {result['source_language']} &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Entries: {summary['total_entries']} &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Translation mode: {summary['translation_mode']}",
                styles["meta"],
            ),
            Spacer(1, 4 * mm),
        ]

        if summary.get("language_warning"):
            story.extend(
                [
                    Paragraph(summary["language_warning"], styles["warning"]),
                    Spacer(1, 4 * mm),
                ]
            )

        if summary.get("notes"):
            notes_text = " | ".join(summary["notes"])
            story.extend([Paragraph(notes_text, styles["note"]), Spacer(1, 6 * mm)])

        story.extend(self._summary_table(summary, styles))

        for category in ("nouns", "verbs", "adjectives", "adverbs", "prepositions", "phrases"):
            entries = result["sections"].get(category, [])
            if not entries:
                continue
            story.extend(
                [
                    Spacer(1, 6 * mm),
                    Paragraph(CATEGORY_LABELS[category], styles["section"]),
                    Spacer(1, 2 * mm),
                    self._category_table(entries, styles),
                ]
            )

        doc.build(
            story,
            onFirstPage=self._decorate_page,
            onLaterPages=self._decorate_page,
        )

    def generate_csv(self, result: dict, output_path: Path) -> None:
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Category", "German", "English", "CEFR", "Occurrences", "Example"])
            for category in ("nouns", "verbs", "adjectives", "adverbs", "prepositions", "phrases"):
                for entry in result["sections"].get(category, []):
                    writer.writerow(
                        [
                            CATEGORY_LABELS[category],
                            entry["term"],
                            entry["translation"],
                            entry["cefr_level"],
                            entry["occurrences"],
                            entry.get("example") or "",
                        ]
                    )

    def _summary_table(self, summary: dict, styles: dict[str, ParagraphStyle]) -> list:
        table_rows = [["Section", "Items"]]
        for category in ("nouns", "verbs", "adjectives", "adverbs", "prepositions", "phrases"):
            table_rows.append(
                [
                    CATEGORY_LABELS[category],
                    str(summary["section_counts"].get(category, 0)),
                ]
            )

        table = Table(table_rows, colWidths=[72 * mm, 28 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#103f45")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f2f7f7")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7e6e6")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        return [table]

    def _category_table(self, entries: list[dict], styles: dict[str, ParagraphStyle]) -> Table:
        table_rows = [[
            Paragraph("German", styles["table_header"]),
            Paragraph("English", styles["table_header"]),
            Paragraph("CEFR", styles["table_header"]),
            Paragraph("Count", styles["table_header"]),
        ]]
        for entry in entries:
            table_rows.append(
                [
                    Paragraph(entry["term"], styles["table_cell_strong"]),
                    Paragraph(entry["translation"], styles["table_cell"]),
                    Paragraph(entry["cefr_level"], styles["table_cell"]),
                    Paragraph(str(entry["occurrences"]), styles["table_cell"]),
                ]
            )

        table = Table(table_rows, colWidths=[62 * mm, 78 * mm, 18 * mm, 18 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#153b5c")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fbfc")]),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7e6e6")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    @staticmethod
    def _decorate_page(canvas, doc) -> None:  # pragma: no cover - rendering callback
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d9e3e7"))
        canvas.line(18 * mm, 287 * mm, 192 * mm, 287 * mm)
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#5a6a78"))
        canvas.drawString(18 * mm, 11 * mm, "Generated by Ger Translator")
        canvas.drawRightString(192 * mm, 11 * mm, f"Page {doc.page}")
        canvas.restoreState()

    @staticmethod
    def _build_styles() -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "title",
                parent=base["Title"],
                fontName="Helvetica-Bold",
                fontSize=20,
                leading=24,
                textColor=colors.HexColor("#102232"),
                alignment=TA_LEFT,
            ),
            "subtitle": ParagraphStyle(
                "subtitle",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=11,
                leading=15,
                textColor=colors.HexColor("#4e6170"),
            ),
            "meta": ParagraphStyle(
                "meta",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=9.5,
                leading=13,
                textColor=colors.HexColor("#29475a"),
            ),
            "warning": ParagraphStyle(
                "warning",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=9.5,
                leading=13,
                textColor=colors.HexColor("#7c4a03"),
                backColor=colors.HexColor("#fff6df"),
                borderPadding=8,
                borderWidth=0.3,
                borderColor=colors.HexColor("#f1d28c"),
            ),
            "note": ParagraphStyle(
                "note",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=9.5,
                leading=13,
                textColor=colors.HexColor("#425261"),
            ),
            "section": ParagraphStyle(
                "section",
                parent=base["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=13,
                leading=16,
                textColor=colors.HexColor("#153b5c"),
            ),
            "table_header": ParagraphStyle(
                "table_header",
                parent=base["BodyText"],
                fontName="Helvetica-Bold",
                fontSize=9,
                leading=12,
                textColor=colors.white,
            ),
            "table_cell": ParagraphStyle(
                "table_cell",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=9,
                leading=12,
                textColor=colors.HexColor("#20313d"),
            ),
            "table_cell_strong": ParagraphStyle(
                "table_cell_strong",
                parent=base["BodyText"],
                fontName="Helvetica-Bold",
                fontSize=9,
                leading=12,
                textColor=colors.HexColor("#102232"),
            ),
        }

