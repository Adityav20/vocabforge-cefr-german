from __future__ import annotations

from typing import Any

import requests

from app.core.config import Settings


class TranslationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def translate_missing(
        self,
        pending_items: list[dict[str, str]],
        *,
        glossary: dict[str, str],
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        unresolved_terms: list[str] = []
        term_to_cache_key: dict[str, str] = {}

        for item in pending_items:
            candidate = self._lookup_glossary(item["lemma"], item["term"], glossary)
            if candidate:
                resolved[item["cache_key"]] = candidate
            else:
                unresolved_terms.append(item["term"])
                term_to_cache_key[item["term"]] = item["cache_key"]

        if unresolved_terms and self.settings.deepl_api_key:
            try:
                deepl_results = self._translate_with_deepl(unresolved_terms)
                for term, translation in zip(unresolved_terms, deepl_results, strict=False):
                    if translation:
                        resolved[term_to_cache_key[term]] = translation
            except Exception:
                # The offline glossary remains the safe fallback path.
                pass

        return resolved

    @staticmethod
    def _lookup_glossary(lemma: str, term: str, glossary: dict[str, str]) -> str | None:
        for key in (lemma.lower(), term.lower(), term.casefold(), lemma.casefold()):
            if key in glossary:
                return glossary[key]
        return None

    def _translate_with_deepl(self, terms: list[str]) -> list[str]:
        payload: list[tuple[str, Any]] = [
            ("target_lang", "EN-US"),
            ("source_lang", "DE"),
            ("split_sentences", "nonewlines"),
            ("preserve_formatting", "1"),
        ]
        payload.extend(("text", term) for term in terms)
        response = requests.post(
            self.settings.deepl_api_url,
            data=payload,
            headers={"Authorization": f"DeepL-Auth-Key {self.settings.deepl_api_key}"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        return [item.get("text", "").strip() for item in data.get("translations", [])]
