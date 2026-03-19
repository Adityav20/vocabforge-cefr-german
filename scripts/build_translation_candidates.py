from __future__ import annotations

import argparse
import csv
import gzip
import html
import json
import re
import struct
import tarfile
from pathlib import Path

from wordfreq import zipf_frequency


CATEGORY_TAGS = {
    "verbs": ("verb",),
    "nouns": ("noun",),
    "adjectives": ("adjective",),
    "adverbs": ("adverb",),
}
BLOCKED_INITIAL_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "it",
    "make",
    "of",
    "on",
    "or",
    "take",
    "that",
    "the",
    "their",
    "this",
    "those",
    "to",
    "under",
    "with",
    "you",
    "your",
}
BLOCKED_WORDS = {
    "he",
    "her",
    "his",
    "i",
    "it",
    "she",
    "someone",
    "something",
    "sth",
    "that",
    "their",
    "them",
    "they",
    "this",
    "those",
    "we",
    "you",
    "your",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a generic multi-sense translation map.")
    parser.add_argument(
        "--archive",
        type=Path,
        required=True,
        help="Path to the FreeDict German-English stardict archive.",
    )
    parser.add_argument(
        "--vocabulary",
        type=Path,
        default=Path("data/cefr_vocabulary.csv"),
        help="Path to the main vocabulary CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/translation_candidates.json"),
        help="Destination JSON path.",
    )
    return parser.parse_args()


def normalize_lookup(text: str) -> str:
    cleaned = html.unescape(text).strip()
    cleaned = cleaned.strip("\"' ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.casefold()


def strip_article(term: str) -> str:
    lowered = term.casefold()
    for article in ("der ", "die ", "das "):
        if lowered.startswith(article):
            return term[len(article) :]
    return term


def infer_category(meta: str) -> str | None:
    lowered = meta.casefold()
    for category, markers in CATEGORY_TAGS.items():
        if any(marker in lowered for marker in markers):
            return category
    return None


def clean_translation(text: str, category: str) -> str | None:
    cleaned = html.unescape(text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip("\"' ")
    if not cleaned:
        return None
    if len(cleaned) > 60:
        return None
    if any(symbol in cleaned for symbol in ".!?…,:()[]"):
        return None
    if cleaned.count("/") >= 2:
        return None
    if len(cleaned.split()) > 5:
        return None
    if "…" in cleaned or "..." in cleaned:
        return None

    words = cleaned.lower().replace("/", " ").split()
    if not words:
        return None
    if words[0] in BLOCKED_INITIAL_WORDS and category != "verbs":
        return None
    if any(word in BLOCKED_WORDS for word in words):
        return None
    if category == "nouns" and len(words) > 2:
        return None
    if category == "verbs" and len(words) > 3:
        return None
    if category in {"adjectives", "adverbs"} and len(words) > 3:
        return None

    if category == "verbs":
        cleaned = cleaned.replace(" / ", "/")
        if not cleaned.startswith("to ") and re.fullmatch(r"[A-Za-z][A-Za-z' -]*", cleaned):
            cleaned = f"to {cleaned}"
        probe = cleaned[3:] if cleaned.startswith("to ") else cleaned
        if re.fullmatch(r"[A-Za-z-]+", probe) and probe.lower().endswith(
            ("tion", "sion", "ment", "ness", "ity", "ance", "ence", "ship", "ure")
        ):
            return None
    return cleaned


def extract_dictionary_entries(archive_path: Path) -> dict[str, list[tuple[str, list[str]]]]:
    entry_map: dict[str, list[tuple[str, list[str]]]] = {}

    with tarfile.open(archive_path, "r:xz") as archive:
        idx_member = archive.getmember("deu-eng/deu-eng.idx.gz")
        dict_member = archive.getmember("deu-eng/deu-eng.dict.dz")
        idx_data = gzip.decompress(archive.extractfile(idx_member).read())
        dict_data = gzip.decompress(archive.extractfile(dict_member).read())

    position = 0
    while position < len(idx_data):
        end = idx_data.index(b"\x00", position)
        headword = idx_data[position:end].decode("utf-8", errors="ignore")
        offset, size = struct.unpack(">II", idx_data[end + 1 : end + 9])
        article = dict_data[offset : offset + size].decode("utf-8", errors="ignore")
        position = end + 9

        key = normalize_lookup(headword)
        if not key:
            continue

        meta_match = re.search(r'<font color="green">([^<]+)</font>', article)
        category = infer_category(meta_match.group(1) if meta_match else "")
        if not category:
            continue

        raw_candidates = re.findall(r'lang="en">([^<]+)', article)
        candidates: list[str] = []
        for candidate in raw_candidates:
            cleaned = clean_translation(candidate, category)
            if cleaned and cleaned.casefold() not in {value.casefold() for value in candidates}:
                candidates.append(cleaned)
        if not candidates:
            continue

        entry_map.setdefault(key, []).append((category, candidates))

    return entry_map


def build_candidates(vocabulary_path: Path, dictionary_entries: dict[str, list[tuple[str, list[str]]]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    seen_result_keys: set[str] = set()

    with vocabulary_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            category = row["category"]
            lemma = row["lemma"]
            result_key = f"{category}:{lemma.casefold()}"
            if result_key in seen_result_keys:
                continue
            seen_result_keys.add(result_key)

            lookup_keys = [
                normalize_lookup(lemma),
                normalize_lookup(strip_article(row["term"])),
                normalize_lookup(row["term"]),
            ]
            candidates: list[str] = []
            for lookup_key in lookup_keys:
                for entry_category, entry_candidates in dictionary_entries.get(lookup_key, []):
                    if entry_category != category:
                        continue
                    for candidate in entry_candidates:
                        if candidate.casefold() not in {value.casefold() for value in candidates}:
                            candidates.append(candidate)
            if candidates:
                candidates.sort(key=_candidate_rank)
                result[result_key] = candidates[:6]

    return result


def _candidate_rank(candidate: str) -> tuple[float, int, str]:
    probe = candidate[3:] if candidate.startswith("to ") else candidate
    probe = probe.split("/")[0].split()[0].lower()
    return (-zipf_frequency(probe, "en"), len(candidate), candidate)


def main() -> None:
    args = parse_args()
    dictionary_entries = extract_dictionary_entries(args.archive)
    candidates = build_candidates(args.vocabulary, dictionary_entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(candidates, handle, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Wrote {len(candidates)} candidate sets to {args.output}")


if __name__ == "__main__":
    main()
