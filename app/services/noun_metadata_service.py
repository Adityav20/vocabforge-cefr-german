from __future__ import annotations

import csv
import re
from functools import lru_cache

try:
    from german_nouns.config import CSV_FILE_PATH
except ImportError:  # pragma: no cover - optional dependency fallback
    CSV_FILE_PATH = None


GENUS_TO_ARTICLE = {
    "m": "der",
    "f": "die",
    "n": "das",
}
FLEXION_COLUMNS = (
    "lemma",
    "nominativ singular",
    "nominativ singular*",
    "nominativ plural",
    "nominativ plural*",
    "genitiv singular",
    "genitiv singular*",
    "genitiv plural",
    "genitiv plural*",
    "dativ singular",
    "dativ singular*",
    "dativ plural",
    "dativ plural*",
    "akkusativ singular",
    "akkusativ singular*",
    "akkusativ plural",
    "akkusativ plural*",
)


class NounMetadataService:
    def __init__(self) -> None:
        self.lookup_table = self._load_lookup_table()

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"[^A-Za-zÄÖÜäöüß-]", "", (text or "").strip())

    def _load_lookup_table(self) -> dict[str, tuple[str, str]]:
        if not CSV_FILE_PATH:
            return {}

        lookup: dict[str, tuple[str, str]] = {}
        try:
            with open(CSV_FILE_PATH, encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    article = self._extract_article(row)
                    lemma = self._clean(row.get("lemma", "")).capitalize()
                    if not article or not lemma:
                        continue
                    for column in FLEXION_COLUMNS:
                        value = self._clean(row.get(column, ""))
                        if value:
                            lookup.setdefault(value.casefold(), (lemma, article))
        except OSError:  # pragma: no cover - external dataset guard
            return {}

        return lookup

    @staticmethod
    def _extract_article(row: dict[str, str]) -> str | None:
        for key in ("genus", "genus 1", "genus 2", "genus 3", "genus 4"):
            article = GENUS_TO_ARTICLE.get((row.get(key) or "").strip())
            if article:
                return article
        return None

    @lru_cache(maxsize=4096)
    def lookup(self, noun: str) -> tuple[str, str] | None:
        cleaned = self._clean(noun)
        if not cleaned:
            return None
        return self.lookup_table.get(cleaned.casefold())
