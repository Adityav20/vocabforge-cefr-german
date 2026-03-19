from __future__ import annotations

import re
from dataclasses import dataclass

from langdetect import DetectorFactory, LangDetectException, detect_langs


DetectorFactory.seed = 0


GERMAN_MARKERS = {
    "der",
    "die",
    "das",
    "und",
    "ist",
    "nicht",
    "mit",
    "auf",
    "für",
    "ich",
    "du",
    "wir",
    "sie",
    "ein",
    "eine",
    "den",
    "dem",
    "des",
    "zu",
    "im",
    "am",
}


@dataclass
class LanguageAssessment:
    primary_language: str
    confidence: float
    is_german: bool
    warning: str | None = None


@dataclass
class ChunkAssessment:
    primary_language: str
    confidence: float
    marker_ratio: float
    marker_hits: int
    umlaut_hits: int
    is_german: bool


class LanguageService:
    def assess(self, text: str) -> LanguageAssessment:
        normalized_text = text.strip()
        if not normalized_text:
            return LanguageAssessment(
                primary_language="unknown",
                confidence=0.0,
                is_german=False,
                warning="The document did not contain enough readable text to assess its language.",
            )

        chunks = self._build_chunks(normalized_text)
        assessments = [self._assess_chunk(chunk) for chunk in chunks]
        german_chunks = [assessment for assessment in assessments if assessment.is_german]

        if german_chunks:
            strongest_german = max(german_chunks, key=lambda assessment: assessment.confidence)
            mixed_language = len(german_chunks) != len(assessments) or any(
                assessment.primary_language != "de" for assessment in assessments
            )
            return LanguageAssessment(
                primary_language="de",
                confidence=strongest_german.confidence,
                is_german=True,
                warning=(
                    "The document mixes German with other content. We will continue and prioritize German-looking vocabulary."
                    if mixed_language
                    else None
                ),
            )

        fallback = assessments[0]
        return LanguageAssessment(
            primary_language=fallback.primary_language,
            confidence=fallback.confidence,
            is_german=False,
            warning="This file does not look like a German-language document. Try a file with more German text.",
        )

    def _assess_chunk(self, sample: str) -> ChunkAssessment:
        try:
            candidates = detect_langs(sample)
        except LangDetectException:
            candidates = []

        primary_language = "unknown"
        confidence = 0.0
        if candidates:
            primary_language = candidates[0].lang
            confidence = float(candidates[0].prob)

        tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+", sample.lower())
        marker_hits = sum(1 for token in tokens if token in GERMAN_MARKERS)
        marker_ratio = marker_hits / max(len(tokens), 1)
        umlaut_hits = len(re.findall(r"[äöüß]", sample.lower()))

        is_german = (
            (primary_language == "de" and confidence >= 0.45)
            or marker_ratio >= 0.07
            or (marker_hits >= 6 and marker_ratio >= 0.04)
            or (umlaut_hits >= 2 and marker_ratio >= 0.03)
        )
        return ChunkAssessment(
            primary_language=primary_language,
            confidence=confidence,
            marker_ratio=marker_ratio,
            marker_hits=marker_hits,
            umlaut_hits=umlaut_hits,
            is_german=is_german,
        )

    @staticmethod
    def _build_chunks(text: str, chunk_size: int = 2400) -> list[str]:
        if len(text) <= chunk_size:
            return [text]

        positions = {
            0,
            max(0, len(text) // 4 - chunk_size // 2),
            max(0, len(text) // 2 - chunk_size // 2),
            max(0, (len(text) * 3) // 4 - chunk_size // 2),
            max(0, len(text) - chunk_size),
        }
        chunks = []
        for start in sorted(positions):
            chunk = text[start : start + chunk_size].strip()
            if chunk:
                chunks.append(chunk)
        return chunks
