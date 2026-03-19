from __future__ import annotations

import unittest
from pathlib import Path

from app.core.config import settings
from app.services.language_service import LanguageService
from app.services.translation_service import TranslationService
from app.services.vocabulary_service import VocabularyService


class StubCEFRService:
    def __init__(self, mapping: dict[tuple[str, str], str] | None = None) -> None:
        self.mapping = mapping or {}

    def lookup_levels(self, candidates: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
        resolved: dict[tuple[str, str], str] = {}
        for category, lemma in candidates:
            for variant in {lemma.casefold(), lemma.casefold().replace("ß", "ss"), lemma.casefold().replace("ss", "ß")}:
                level = self.mapping.get((category, variant))
                if level:
                    resolved[(category, lemma.casefold())] = level
                    break
        return resolved


class LanguageAndVocabularyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.language_service = LanguageService()
        cls.vocabulary_service = VocabularyService(
            data_path=Path(settings.data_dir / "cefr_vocabulary.csv"),
            translation_service=TranslationService(settings),
            cefr_service=StubCEFRService(
                {
                    ("nouns", "auge"): "A1",
                    ("nouns", "auto"): "A1",
                    ("nouns", "kind"): "A1",
                    ("nouns", "schloss"): "A1",
                    ("verbs", "schließen"): "A1",
                    ("verbs", "schliessen"): "A1",
                }
            ),
        )

    def test_detects_german_text(self) -> None:
        assessment = self.language_service.assess(
            "Die Entscheidung ist wichtig. Wir analysieren die Entwicklung und beschreiben die Ergebnisse."
        )
        self.assertTrue(assessment.is_german)

    def test_accepts_mixed_language_text_with_german_sections(self) -> None:
        assessment = self.language_service.assess(
            "Learn German with Stories. About the author and answer key. "
            "Die Wohngemeinschaft ist nicht einfach. Ich spreche mit meiner Familie und lerne Deutsch. "
            "More notes in English. Auf Wiedersehen und bis morgen."
        )
        self.assertTrue(assessment.is_german)

    def test_extracts_structured_vocabulary(self) -> None:
        result = self.vocabulary_service.analyze(
            text=(
                "Die Entscheidung ist wichtig. Im Vergleich zu früher ist die Entwicklung deutlich. "
                "Wir analysieren die Strategie und beschreiben die Ergebnisse Schritt für Schritt."
            ),
            selected_level="B2",
            document_name="sample.pdf",
            language_warning=None,
            document_units=3,
            source_type="PDF",
        )
        nouns = [entry["term"] for entry in result["sections"]["nouns"]]
        verbs = [entry["term"] for entry in result["sections"]["verbs"]]
        phrases = [entry["term"] for entry in result["sections"]["phrases"]]

        self.assertIn("die Entscheidung", nouns)
        self.assertIn("analysieren", verbs)
        self.assertIn("Im Vergleich zu", phrases)

    def test_mixed_text_ignores_obvious_english_only_tokens(self) -> None:
        result = self.vocabulary_service.analyze(
            text=(
                "She is after short breaks. Learn German with stories. "
                "Die Entscheidung ist wichtig und ich spreche mit meiner Familie."
            ),
            selected_level="B1",
            document_name="sample.pdf",
            language_warning="Mixed language",
            document_units=1,
            source_type="PDF",
        )
        all_terms = {
            entry["term"].casefold()
            for entries in result["sections"].values()
            for entry in entries
        }
        self.assertIn("die entscheidung", all_terms)
        self.assertNotIn("short", all_terms)
        self.assertNotIn("she", all_terms)
        self.assertNotIn("after", all_terms)

    def test_ambiguous_inflected_verb_surfaces_multiple_meanings_without_prefix(self) -> None:
        result = self.vocabulary_service.analyze(
            text="Ich schloss meine Augen.",
            selected_level="B2",
            document_name="sample.pdf",
            language_warning=None,
            document_units=1,
            source_type="PDF",
        )
        verb_translations = " ".join(entry["translation"] for entry in result["sections"]["verbs"]).casefold()
        self.assertIn("to close", verb_translations)
        self.assertIn("to lock", verb_translations)
        self.assertNotIn("possible meanings", verb_translations)
        self.assertNotIn("palace", verb_translations)

    def test_corrects_articles_and_cefr_for_common_nouns(self) -> None:
        result = self.vocabulary_service.analyze(
            text="Das Auge sieht das Schloss. Das Kind repariert das Auto.",
            selected_level="A1",
            document_name="sample.pdf",
            language_warning=None,
            document_units=1,
            source_type="PDF",
        )
        nouns = {entry["term"] for entry in result["sections"]["nouns"]}
        self.assertIn("das Auge", nouns)
        self.assertIn("das Schloss", nouns)
        self.assertIn("das Kind", nouns)
        self.assertIn("das Auto", nouns)


if __name__ == "__main__":
    unittest.main()
