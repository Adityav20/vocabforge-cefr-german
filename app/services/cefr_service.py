from __future__ import annotations

import json
from pathlib import Path

import requests

from app.core.config import Settings


SUPPORTED_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
STTS_CATEGORY_MAP = {
    "NN": "nouns",
    "V": "verbs",
    "ADJ": "adjectives",
    "ADV": "adverbs",
    "APPR": "prepositions",
    "APPRART": "prepositions",
    "APPO": "prepositions",
    "APZR": "prepositions",
}


class CEFRLevelService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache_path = settings.cefr_cache_path
        self.cache = self._load_cache(self.cache_path)

    def lookup_levels(self, candidates: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
        resolved: dict[tuple[str, str], str] = {}
        pending: list[tuple[str, str]] = []
        seen_pending: set[tuple[str, str]] = set()

        for category, lemma in candidates:
            normalized = self._normalize_lemma(lemma, category)
            if not normalized:
                continue
            key = (category, normalized.casefold())
            cached_level = self.cache.get(f"{category}:{key[1]}")
            if cached_level in SUPPORTED_LEVELS:
                resolved[key] = cached_level
                continue
            if key not in seen_pending:
                seen_pending.add(key)
                pending.append((category, normalized))

        if not pending or not self.settings.cefr_api_enabled:
            return resolved

        fetched = self._fetch_daflex_levels(pending)
        if not fetched:
            return resolved

        for key, level in fetched.items():
            self.cache[f"{key[0]}:{key[1]}"] = level
            resolved[key] = level

        self._write_cache()
        return resolved

    def _fetch_daflex_levels(self, candidates: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
        lookup_text = "\n".join(
            self._format_lookup_term(category, lemma)
            for category, lemma in candidates
            if lemma and " " not in lemma
        )
        if not lookup_text:
            return {}

        response = requests.post(
            self.settings.cefr_api_url,
            json={
                "user_text": lookup_text,
                "resource": "DAFlex",
                "tagger": "TreeTagger - German",
                "version": "First observation",
            },
            timeout=self.settings.cefr_api_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return {}

        levels: dict[tuple[str, str], str] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            level = str(item.get("cefr", "")).upper()
            category = self._map_pos(item.get("pos", ""))
            lemma = self._normalize_lemma(str(item.get("lemma", "")), category)
            if category and lemma and level in SUPPORTED_LEVELS:
                levels[(category, lemma.casefold())] = level
        return levels

    @staticmethod
    def _map_pos(pos: str) -> str | None:
        for prefix, category in STTS_CATEGORY_MAP.items():
            if pos.startswith(prefix):
                return category
        return None

    @staticmethod
    def _normalize_lemma(lemma: str, category: str) -> str:
        cleaned = "".join(char for char in lemma.strip() if char.isalpha() or char in "-ÄÖÜäöüß")
        if not cleaned:
            return ""
        if category == "nouns":
            return cleaned.capitalize()
        return cleaned.casefold()

    @staticmethod
    def _format_lookup_term(category: str, lemma: str) -> str:
        return lemma.capitalize() if category == "nouns" else lemma.casefold()

    @staticmethod
    def _load_cache(path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): str(value).upper()
            for key, value in raw.items()
            if str(value).upper() in SUPPORTED_LEVELS
        }

    def _write_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("w", encoding="utf-8") as handle:
            json.dump(self.cache, handle, ensure_ascii=False, indent=2, sort_keys=True)
