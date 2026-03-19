from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import spacy

from app.services.cefr_service import CEFRLevelService
from app.services.noun_metadata_service import NounMetadataService
from app.services.translation_service import TranslationService

try:
    from wordfreq import zipf_frequency
except ImportError:  # pragma: no cover - optional dependency fallback
    zipf_frequency = None

try:
    import simplemma
except ImportError:  # pragma: no cover - optional dependency fallback
    simplemma = None


LEVEL_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
CATEGORY_ORDER = ("nouns", "verbs", "adjectives", "adverbs", "prepositions", "phrases")
POS_CATEGORY_MAP = {
    "NOUN": "nouns",
    "VERB": "verbs",
    "AUX": "verbs",
    "ADJ": "adjectives",
    "ADV": "adverbs",
    "ADP": "prepositions",
}
GERMAN_HINT_WORDS = {
    "aber",
    "als",
    "auch",
    "auf",
    "aus",
    "bei",
    "bin",
    "bist",
    "das",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "doch",
    "ein",
    "eine",
    "einer",
    "einem",
    "einen",
    "er",
    "es",
    "für",
    "habe",
    "haben",
    "hat",
    "ich",
    "ihm",
    "im",
    "ist",
    "mit",
    "nach",
    "nicht",
    "noch",
    "schon",
    "sie",
    "und",
    "von",
    "war",
    "wir",
    "zu",
}
ENGLISH_HINT_WORDS = {
    "a",
    "about",
    "after",
    "all",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "get",
    "have",
    "he",
    "her",
    "his",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "read",
    "she",
    "short",
    "stories",
    "that",
    "the",
    "their",
    "there",
    "they",
    "this",
    "to",
    "was",
    "we",
    "with",
    "you",
}


@dataclass(frozen=True)
class LexiconEntry:
    cefr_level: str
    category: str
    lemma: str
    term: str
    translation: str
    article: str | None
    aliases: tuple[str, ...]


class VocabularyService:
    def __init__(
        self,
        *,
        data_path: Path,
        translation_service: TranslationService,
        cefr_service: CEFRLevelService | None = None,
    ) -> None:
        self.translation_service = translation_service
        self.cefr_service = cefr_service
        self.noun_metadata_service = NounMetadataService()
        self.lexicon = [self._normalize_lexicon_entry(entry) for entry in self._load_lexicon(data_path)]
        self.trusted_seed_categories = self._load_trusted_seed_categories(data_path.parent / "cefr_vocabulary_seed.csv")
        self.translation_candidates = self._load_translation_candidates(data_path.parent / "translation_candidates.json")
        self.glossary = self._build_glossary()
        self.phrase_entries = [entry for entry in self.lexicon if entry.category == "phrases"]
        self.entry_index = self._build_entry_index()
        self.nlp = self._load_nlp()
        self.stopwords = set(self.nlp.Defaults.stop_words) if self.nlp else set()
        self._ensure_sentence_boundaries()

    def analyze(
        self,
        *,
        text: str,
        selected_level: str,
        document_name: str,
        language_warning: str | None,
        document_units: int,
        source_type: str,
    ) -> dict[str, Any]:
        selected_rank = LEVEL_ORDER[selected_level]
        prepared_text = self._prepare_text(text)
        sections: dict[str, dict[str, dict[str, Any]]] = {
            category: {} for category in CATEGORY_ORDER
        }

        self._extract_phrase_entries(prepared_text, selected_rank, sections)

        if self._has_full_spacy_pipeline():
            doc = self.nlp(prepared_text)
            try:
                cefr_hints = self.cefr_service.lookup_levels(self._collect_cefr_candidates(doc)) if self.cefr_service else {}
            except Exception:
                cefr_hints = {}
            self._extract_token_entries(doc, selected_rank, sections, cefr_hints)
        else:
            self._extract_with_regex(prepared_text, selected_rank, sections)

        unresolved = [
            {
                "cache_key": f"{category}:{key}",
                "term": entry["term"],
                "lemma": entry["lemma"],
            }
            for category, group in sections.items()
            for key, entry in group.items()
            if not entry.get("translation")
        ]
        resolved = self.translation_service.translate_missing(unresolved, glossary=self.glossary)
        for category, group in sections.items():
            for key, entry in list(group.items()):
                translation = resolved.get(f"{category}:{key}")
                if translation:
                    entry["translation"] = translation
                entry["translation"] = self._resolve_display_translation(entry)
                if not entry.get("translation"):
                    del group[key]

        serialized_sections = {
            category: self._sort_entries(list(group.values()))
            for category, group in sections.items()
        }

        section_counts = {
            category: len(serialized_sections[category])
            for category in CATEGORY_ORDER
        }
        level_mix = defaultdict(int)
        total_entries = 0
        for category in CATEGORY_ORDER:
            for entry in serialized_sections[category]:
                total_entries += 1
                level_mix[entry["cefr_level"]] += 1

        notes = [
            f"Processed {document_units} {source_type} unit(s).",
            f"Vocabulary includes items at or below {selected_level}.",
        ]
        if not self.translation_service.settings.deepl_api_key:
            notes.append("Offline glossary mode is active; connect DeepL for broader translation coverage.")

        return {
            "document_name": document_name,
            "selected_level": selected_level,
            "source_language": "de",
            "generated_at": "",
            "summary": {
                "total_entries": total_entries,
                "section_counts": section_counts,
                "detected_level_mix": dict(level_mix),
                "translation_mode": (
                    "DeepL + curated glossary"
                    if self.translation_service.settings.deepl_api_key
                    else "Curated glossary"
                ),
                "language_warning": language_warning,
                "notes": notes,
            },
            "sections": serialized_sections,
            "available_downloads": {},
        }

    def _extract_phrase_entries(
        self,
        text: str,
        selected_rank: int,
        sections: dict[str, dict[str, dict[str, Any]]],
    ) -> None:
        lowered = text.lower()
        for entry in self.phrase_entries:
            if LEVEL_ORDER[entry.cefr_level] > selected_rank:
                continue
            pattern = r"(?<!\w)" + re.escape(entry.term.lower()) + r"(?!\w)"
            matches = list(re.finditer(pattern, lowered))
            if not matches:
                continue
            self._upsert_entry(
                sections["phrases"],
                key=entry.lemma.lower(),
                payload=self._payload_from_entry(
                    entry,
                    occurrences=len(matches),
                    example=self._snippet(text, matches[0].start(), matches[0].end()),
                ),
            )

    def _extract_token_entries(
        self,
        doc,
        selected_rank: int,
        sections: dict[str, dict[str, dict[str, Any]]],
        cefr_hints: dict[tuple[str, str], str] | None = None,
    ) -> None:
        cefr_hints = cefr_hints or {}
        for token in doc:
            if token.is_space or token.is_punct or token.like_num:
                continue
            category = POS_CATEGORY_MAP.get(token.pos_)
            if not category:
                continue
            if category == "nouns" and token.pos_ == "PROPN":
                continue
            lemma = self._derive_lemma(token, category)
            article = None
            if category == "nouns":
                lemma, article = self._resolve_noun_metadata(lemma, token.text)

            matched_entry = self._match_entry(category, lemma, token.text)
            example = token.sent.text.strip() if token.sent is not None else None
            if not self._should_keep_candidate(
                token_text=token.text,
                lemma=lemma,
                category=category,
                sentence_text=example or token.text,
                matched_entry=matched_entry,
            ):
                continue

            if matched_entry:
                effective_level = self._lookup_cefr_level(cefr_hints, matched_entry.category, matched_entry.lemma) or matched_entry.cefr_level
                if LEVEL_ORDER[effective_level] > selected_rank:
                    continue
                payload = self._payload_from_entry(
                    matched_entry,
                    occurrences=1,
                    example=example,
                )
                payload["cefr_level"] = effective_level
                self._upsert_entry(
                    sections[matched_entry.category],
                    key=matched_entry.lemma.lower(),
                    payload=payload,
                )
                continue

            if not self._should_keep_token(lemma, category):
                continue

            estimated_level = self._lookup_cefr_level(cefr_hints, category, lemma) or self._estimate_level(lemma, category, frequency_hint=1)
            if LEVEL_ORDER[estimated_level] > selected_rank:
                continue

            term = f"{article} {lemma}" if article else lemma
            key = lemma.lower()
            self._upsert_entry(
                sections[category],
                key=key,
                payload={
                    "term": term,
                    "translation": "",
                    "category": category,
                    "cefr_level": estimated_level,
                    "lemma": lemma,
                    "occurrences": 1,
                    "article": article,
                    "example": example,
                },
            )

    def _collect_cefr_candidates(self, doc) -> list[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        candidates: list[tuple[str, str]] = []
        for token in doc:
            if token.is_space or token.is_punct or token.like_num:
                continue
            category = POS_CATEGORY_MAP.get(token.pos_)
            if not category:
                continue
            lemma = self._derive_lemma(token, category)
            if category == "nouns":
                lemma, _ = self._resolve_noun_metadata(lemma, token.text)
            if not self._should_keep_token(lemma, category) or " " in lemma:
                continue
            key = (category, lemma.casefold())
            if key in seen:
                continue
            seen.add(key)
            candidates.append((category, lemma))
        return candidates

    def _extract_with_regex(self, text: str, selected_rank: int, sections: dict[str, dict[str, dict[str, Any]]]) -> None:
        for raw_token in re.findall(r"[A-Za-zÄÖÜäöüß-]{3,}", text):
            lemma = raw_token.lower()
            entry = self._match_entry(None, lemma, raw_token)
            if not self._should_keep_candidate(
                token_text=raw_token,
                lemma=lemma,
                category=entry.category if entry else "nouns",
                sentence_text=raw_token,
                matched_entry=entry,
            ):
                continue
            if not entry or LEVEL_ORDER[entry.cefr_level] > selected_rank:
                continue
            self._upsert_entry(
                sections[entry.category],
                key=entry.lemma.lower(),
                payload=self._payload_from_entry(entry, occurrences=1, example=None),
            )

    def _match_entry(self, category: str | None, lemma: str, surface: str) -> LexiconEntry | None:
        search_keys = self._entry_search_keys(lemma, surface)
        categories = (category,) if category else CATEGORY_ORDER
        for candidate_category in categories:
            if candidate_category is None:
                continue
            for key in search_keys:
                entry = self.entry_index.get((candidate_category, key))
                if entry:
                    return entry
        if category:
            for key in search_keys:
                entry = self.entry_index.get(("all", key))
                if entry and entry.category == category:
                    return entry
        return None

    def _entry_search_keys(self, lemma: str, surface: str) -> list[str]:
        search_keys: list[str] = []
        for candidate in (lemma, surface):
            if not candidate:
                continue
            for variant in self._orthography_variants(candidate):
                lowered = variant.lower()
                casefolded = variant.casefold()
                if lowered not in search_keys:
                    search_keys.append(lowered)
                if casefolded not in search_keys:
                    search_keys.append(casefolded)
        return search_keys

    @staticmethod
    def _upsert_entry(group: dict[str, dict[str, Any]], *, key: str, payload: dict[str, Any]) -> None:
        existing = group.get(key)
        if not existing:
            group[key] = payload
            return
        existing["occurrences"] += payload["occurrences"]
        if not existing.get("example") and payload.get("example"):
            existing["example"] = payload["example"]

    @staticmethod
    def _normalize_lemma(lemma: str, category: str) -> str:
        cleaned = re.sub(r"^[^A-Za-zÄÖÜäöüß]+|[^A-Za-zÄÖÜäöüß-]+$", "", lemma.strip())
        if category == "nouns":
            return cleaned.capitalize()
        return cleaned.lower()

    def _derive_lemma(self, token, category: str) -> str:
        normalized = self._normalize_lemma(token.lemma_ or token.text, category)
        if simplemma is None or category not in {"nouns", "verbs", "adjectives", "adverbs"}:
            return normalized

        try:
            fallback = simplemma.lemmatize(token.text, lang="de")
        except Exception:  # pragma: no cover - external library guard
            fallback = token.text

        fallback_normalized = self._normalize_lemma(fallback or token.text, category)
        if not fallback_normalized:
            return normalized
        if category == "verbs" and fallback_normalized != normalized:
            return fallback_normalized
        if category == "nouns" and fallback_normalized != normalized and token.text[:1].isupper():
            return fallback_normalized
        if category in {"adjectives", "adverbs"} and len(fallback_normalized) >= len(normalized):
            return fallback_normalized
        return normalized

    def _resolve_noun_metadata(self, lemma: str, surface: str | None = None) -> tuple[str, str]:
        for candidate in (lemma, surface or ""):
            if not candidate:
                continue
            resolved = self.noun_metadata_service.lookup(candidate)
            if resolved:
                return resolved
        normalized = self._normalize_lemma(lemma, "nouns")
        return normalized, self._guess_article(normalized)

    def _lookup_cefr_level(
        self,
        cefr_hints: dict[tuple[str, str], str],
        category: str,
        lemma: str,
    ) -> str | None:
        for variant in self._orthography_variants(lemma):
            level = cefr_hints.get((category, variant.casefold()))
            if level:
                return level
        return None

    def _should_keep_token(self, lemma: str, category: str) -> bool:
        if not lemma or len(lemma) < 3:
            return False
        if category != "nouns" and lemma.lower() in self.stopwords:
            return False
        return True

    def _should_keep_candidate(
        self,
        *,
        token_text: str,
        lemma: str,
        category: str,
        sentence_text: str,
        matched_entry: LexiconEntry | None,
    ) -> bool:
        if not self._should_keep_token(lemma, category):
            return False
        if matched_entry and not self._matches_trusted_category(matched_entry.lemma, matched_entry.category):
            return False
        if self._looks_english_only(
            token_text=token_text,
            lemma=lemma,
            category=category,
            sentence_text=sentence_text,
            matched_entry=matched_entry,
        ):
            return False
        return True

    def _looks_english_only(
        self,
        *,
        token_text: str,
        lemma: str,
        category: str,
        sentence_text: str,
        matched_entry: LexiconEntry | None,
    ) -> bool:
        probe = matched_entry.lemma if matched_entry else lemma
        normalized_probe = probe.lower()
        if re.search(r"[äöüß]", probe.lower()):
            return False
        if normalized_probe in GERMAN_HINT_WORDS:
            return False

        german_hint_count, english_hint_count = self._sentence_hint_counts(sentence_text)
        german_frequency = self._zipf(probe, "de")
        english_frequency = max(
            self._zipf(probe, "en"),
            self._zipf(token_text, "en"),
        )
        trusted_seed_entry = normalized_probe in self.trusted_seed_categories

        if german_frequency >= 3.0:
            if not (english_hint_count >= german_hint_count + 2 and english_hint_count >= 2):
                return False
        if category == "nouns" and probe[:1].isupper() and german_hint_count >= english_hint_count:
            return False
        if german_hint_count >= english_hint_count + 1:
            return False
        if english_hint_count >= german_hint_count + 2 and english_hint_count >= 2:
            return german_frequency < 5.5 and normalized_probe not in GERMAN_HINT_WORDS and not trusted_seed_entry
        if english_hint_count >= german_hint_count + 2 and german_frequency < 2.8:
            return True
        if not trusted_seed_entry and english_frequency >= german_frequency + 1.0 and german_frequency < 5.0:
            return True
        if english_frequency >= german_frequency + 1.25 and german_frequency < 2.3:
            return True
        return normalized_probe in ENGLISH_HINT_WORDS and german_frequency < 2.5

    def _matches_trusted_category(self, lemma: str, category: str) -> bool:
        trusted_categories = self.trusted_seed_categories.get(lemma.casefold())
        if not trusted_categories:
            return True
        return category in trusted_categories

    def _prepare_text(self, text: str) -> str:
        parts = re.split(r"([,\n;])", text)
        cleaned_parts: list[str] = []
        for part in parts:
            if part in {",", "\n", ";"}:
                cleaned_parts.append(part)
                continue
            cleaned_parts.append(self._strip_inline_translation(part))
        return "".join(cleaned_parts)

    def _strip_inline_translation(self, fragment: str) -> str:
        if ":" not in fragment:
            return fragment

        left, right = fragment.split(":", 1)
        if self._looks_like_inline_translation(right):
            return left
        return fragment

    def _looks_like_inline_translation(self, text: str) -> bool:
        tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+", text.lower())
        if not tokens or len(tokens) > 8:
            return False
        if re.search(r"[äöüß]", text.lower()):
            return False

        german_hits, english_hits = self._sentence_hint_counts(text)
        if english_hits >= german_hits + 1:
            return True

        english_leaning = 0
        for token in tokens:
            if self._zipf(token, "en") >= self._zipf(token, "de") + 0.9:
                english_leaning += 1
        return english_leaning >= max(1, len(tokens) // 2)

    @lru_cache(maxsize=4096)
    def _sentence_hint_counts(self, sentence_text: str) -> tuple[int, int]:
        tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+", sentence_text.lower())
        german_hits = sum(1 for token in tokens if token in GERMAN_HINT_WORDS)
        english_hits = sum(1 for token in tokens if token in ENGLISH_HINT_WORDS)
        return german_hits, english_hits

    @staticmethod
    def _zipf(term: str, language: str) -> float:
        if zipf_frequency is None:
            return 0.0
        try:
            return float(zipf_frequency(term, language))
        except Exception:  # pragma: no cover - external library guard
            return 0.0

    def _estimate_level(self, lemma: str, category: str, frequency_hint: int) -> str:
        lower_lemma = lemma.lower()
        if category == "prepositions":
            return "A2" if lower_lemma in {"zwischen", "gegen", "seit", "während"} else "B1"
        if category == "adverbs":
            return "A2" if len(lower_lemma) <= 6 else "B1"
        if any(lower_lemma.endswith(suffix) for suffix in ("keit", "heit", "ung", "schaft")):
            return "B1"
        if any(lower_lemma.endswith(suffix) for suffix in ("tion", "tät", "ismus", "logie", "enz", "anz")):
            return "C1"
        if any(lower_lemma.endswith(suffix) for suffix in ("ieren", "isieren", "ifizieren")):
            return "B2"
        if frequency_hint >= 4 and len(lower_lemma) <= 6:
            return "A2"
        if len(lower_lemma) <= 5:
            return "A1"
        if len(lower_lemma) <= 8:
            return "B1"
        if len(lower_lemma) <= 11:
            return "B2"
        if len(lower_lemma) <= 14:
            return "C1"
        return "C2"

    @staticmethod
    def _guess_article(noun: str) -> str:
        lower_noun = noun.lower()
        if lower_noun.endswith(("ung", "heit", "keit", "schaft", "tion", "ik", "ie", "ur", "tät")):
            return "die"
        if lower_noun.endswith(("chen", "lein", "ment", "um", "ma")):
            return "das"
        if lower_noun.endswith(("er", "ig", "ich", "ismus", "ling")):
            return "der"
        return "die" if lower_noun.endswith("e") else "der"

    @staticmethod
    def _orthography_variants(term: str) -> tuple[str, ...]:
        variants: list[str] = []
        if term:
            variants.append(term)
        if "ß" in term:
            variants.append(term.replace("ß", "ss"))
        if "ss" in term:
            variants.append(term.replace("ss", "ß"))
        deduped: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            if variant in seen:
                continue
            seen.add(variant)
            deduped.append(variant)
        return tuple(deduped)

    @staticmethod
    def _snippet(text: str, start: int, end: int) -> str:
        before = max(0, start - 40)
        after = min(len(text), end + 40)
        snippet = text[before:after].strip()
        return re.sub(r"\s+", " ", snippet)

    def _payload_from_entry(self, entry: LexiconEntry, *, occurrences: int, example: str | None) -> dict[str, Any]:
        term = entry.term
        if entry.category == "nouns" and entry.article and not term.startswith(entry.article):
            term = f"{entry.article} {entry.term}"
        return {
            "term": term,
            "translation": entry.translation,
            "category": entry.category,
            "cefr_level": entry.cefr_level,
            "lemma": entry.lemma,
            "occurrences": occurrences,
            "article": entry.article,
            "example": example,
        }

    @staticmethod
    def _sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            entries,
            key=lambda item: (
                LEVEL_ORDER[item["cefr_level"]],
                -item["occurrences"],
                item["term"].lower(),
            ),
        )

    def _build_entry_index(self) -> dict[tuple[str, str], LexiconEntry]:
        index: dict[tuple[str, str], LexiconEntry] = {}
        for entry in self.lexicon:
            keys = {
                entry.lemma.lower(),
                entry.term.lower(),
                entry.term.casefold(),
                entry.lemma.casefold(),
            }
            if entry.article:
                keys.add(f"{entry.article} {entry.lemma}".lower())
            keys.update(alias.lower() for alias in entry.aliases if alias)
            for key in keys:
                index[(entry.category, key)] = entry
                index[("all", key)] = entry
        return index

    def _build_glossary(self) -> dict[str, str]:
        glossary: dict[str, str] = {}
        for entry in self.lexicon:
            glossary[entry.lemma.lower()] = entry.translation
            glossary[entry.term.lower()] = entry.translation
            if entry.article:
                glossary[f"{entry.article} {entry.lemma}".lower()] = entry.translation
            for alias in entry.aliases:
                if alias:
                    glossary[alias.lower()] = entry.translation
        return glossary

    def _normalize_lexicon_entry(self, entry: LexiconEntry) -> LexiconEntry:
        if entry.category != "nouns":
            return entry

        lemma, article = self._resolve_noun_metadata(entry.lemma, entry.term)
        aliases = list(entry.aliases)
        for alias_candidate in (entry.term, entry.lemma):
            if alias_candidate and alias_candidate.casefold() not in {alias.casefold() for alias in aliases}:
                aliases.append(alias_candidate)

        return LexiconEntry(
            cefr_level=entry.cefr_level,
            category=entry.category,
            lemma=lemma,
            term=f"{article} {lemma}",
            translation=entry.translation,
            article=article,
            aliases=tuple(aliases),
        )

    @staticmethod
    def _load_lexicon(data_path: Path) -> list[LexiconEntry]:
        with data_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [
                LexiconEntry(
                    cefr_level=row["cefr_level"],
                    category=row["category"],
                    lemma=row["lemma"],
                    term=row["term"],
                    translation=row["translation"],
                    article=row["article"] or None,
                    aliases=tuple(filter(None, row["aliases"].split("|"))),
                )
                for row in reader
            ]

    @staticmethod
    def _load_trusted_seed_categories(seed_path: Path) -> dict[str, set[str]]:
        if not seed_path.exists():
            return {}

        trusted_categories: dict[str, set[str]] = defaultdict(set)
        with seed_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                lemma = (row.get("lemma") or "").strip()
                category = (row.get("category") or "").strip()
                if lemma and category:
                    trusted_categories[lemma.casefold()].add(category)
        return trusted_categories

    @staticmethod
    def _load_translation_candidates(path: Path) -> dict[str, list[str]]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return {
            key: [value for value in values if value]
            for key, values in raw.items()
            if isinstance(values, list)
        }

    def _resolve_display_translation(self, entry: dict[str, Any]) -> str:
        current = (entry.get("translation") or "").strip()
        candidates = self._translation_candidates_for(entry["category"], entry["lemma"])
        if not candidates:
            return current

        deduped_candidates: list[str] = []
        seen = set()
        for candidate in candidates:
            normalized = candidate.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped_candidates.append(candidate)

        if not deduped_candidates:
            return current

        candidate_keys = {candidate.casefold() for candidate in deduped_candidates}
        if current and current.casefold() in candidate_keys:
            return current

        if len(deduped_candidates) == 1:
            return deduped_candidates[0]

        if self._should_surface_candidates(entry, current, deduped_candidates):
            return "; ".join(deduped_candidates[:4])

        if entry["category"] in {"nouns", "adjectives", "adverbs", "prepositions"} and current.casefold() not in candidate_keys:
            return deduped_candidates[0]

        return current or deduped_candidates[0]

    def _translation_candidates_for(self, category: str, lemma: str) -> list[str]:
        candidates: list[str] = []
        for variant in self._orthography_variants(lemma):
            key = f"{category}:{variant.casefold()}"
            candidates.extend(self.translation_candidates.get(key, []))
        return candidates

    def _should_surface_candidates(
        self,
        entry: dict[str, Any],
        current: str,
        candidates: list[str],
    ) -> bool:
        if len(candidates) <= 1:
            return False
        if not current:
            return entry["category"] == "verbs"
        if current.casefold() not in {candidate.casefold() for candidate in candidates}:
            return entry["category"] == "verbs"
        if entry["category"] == "verbs" and not current.casefold().startswith("to "):
            return True
        return False

    @staticmethod
    def _load_nlp():
        try:
            return spacy.load("de_core_news_sm", disable=["ner"])
        except OSError:
            try:
                return spacy.blank("de")
            except Exception:
                return None

    def _ensure_sentence_boundaries(self) -> None:
        if not self.nlp:
            return
        if "parser" not in self.nlp.pipe_names and "senter" not in self.nlp.pipe_names and "sentencizer" not in self.nlp.pipe_names:
            self.nlp.add_pipe("sentencizer")

    def _has_full_spacy_pipeline(self) -> bool:
        if not self.nlp:
            return False
        return "tagger" in self.nlp.pipe_names and "lemmatizer" in self.nlp.pipe_names
