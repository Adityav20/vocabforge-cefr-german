from __future__ import annotations

import argparse
import csv
import gzip
import html
import re
import struct
import tarfile
from dataclasses import dataclass
from pathlib import Path

import spacy
from wordfreq import top_n_list, zipf_frequency


HEADERS = ["cefr_level", "category", "lemma", "term", "translation", "article", "aliases"]
POS_CATEGORY_MAP = {
    "VERB": "verbs",
    "AUX": "verbs",
    "ADJ": "adjectives",
    "ADV": "adverbs",
    "ADP": "prepositions",
    "NOUN": "nouns",
}
COMMON_PREPOSITIONS = {
    "ab",
    "an",
    "auf",
    "aus",
    "außer",
    "bei",
    "bis",
    "dank",
    "durch",
    "entlang",
    "für",
    "gegen",
    "gegenüber",
    "gemäß",
    "hinsichtlich",
    "hinter",
    "in",
    "innerhalb",
    "mit",
    "nach",
    "neben",
    "ohne",
    "seit",
    "trotz",
    "über",
    "um",
    "unter",
    "von",
    "vor",
    "während",
    "wegen",
    "zu",
    "zwischen",
}
EXCLUDED_TERMS = {
    "aber",
    "als",
    "am",
    "an",
    "auch",
    "das",
    "dass",
    "dein",
    "dem",
    "den",
    "der",
    "des",
    "dessen",
    "deren",
    "dies",
    "diese",
    "dieser",
    "dieses",
    "du",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "er",
    "es",
    "euer",
    "fürs",
    "ihr",
    "ihm",
    "ihn",
    "ich",
    "im",
    "ins",
    "ja",
    "jener",
    "jene",
    "jenes",
    "kein",
    "keine",
    "man",
    "mein",
    "mich",
    "mir",
    "nicht",
    "oder",
    "sein",
    "seine",
    "seiner",
    "sie",
    "so",
    "und",
    "unser",
    "vom",
    "wir",
}
MANUAL_TRANSLATIONS = {
    "ab": "from",
    "an": "at",
    "auf": "on",
    "aus": "out of",
    "bei": "at",
    "bis": "until",
    "durch": "through",
    "für": "for",
    "gegen": "against",
    "hinter": "behind",
    "in": "in",
    "innerhalb": "within",
    "mit": "with",
    "nach": "after",
    "neben": "next to",
    "ohne": "without",
    "seit": "since",
    "über": "over",
    "um": "around",
    "unter": "under",
    "von": "from",
    "vor": "before",
    "während": "during",
    "wegen": "because of",
    "zu": "to",
    "zwischen": "between",
}


@dataclass(frozen=True)
class DictionaryEntry:
    headword: str
    translation: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a large CEFR-style German vocabulary CSV.")
    parser.add_argument(
        "--archive",
        type=Path,
        required=True,
        help="Path to the FreeDict German-English stardict archive.",
    )
    parser.add_argument(
        "--seed",
        type=Path,
        default=Path("data/cefr_vocabulary_seed.csv"),
        help="Path to the curated starter CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/cefr_vocabulary.csv"),
        help="Destination CSV file.",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=32000,
        help="Minimum number of rows to produce.",
    )
    parser.add_argument(
        "--topn",
        type=int,
        default=250000,
        help="Number of high-frequency German candidates to inspect.",
    )
    return parser.parse_args()


def normalize_key(text: str) -> str:
    cleaned = html.unescape(text).strip()
    cleaned = cleaned.strip("\"' ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.casefold()


def clean_headword(text: str) -> str:
    cleaned = html.unescape(text).strip()
    cleaned = cleaned.strip("\"' ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def clean_translation(text: str) -> str:
    cleaned = html.unescape(text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip("\"' ")


def extract_freedict_entries(archive_path: Path) -> dict[str, DictionaryEntry]:
    translation_pattern = re.compile(r'lang="en">([^<]+)')
    entries: dict[str, DictionaryEntry] = {}

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

        matches = translation_pattern.findall(article)
        if not matches:
            continue

        cleaned_headword = clean_headword(headword)
        key = normalize_key(cleaned_headword)
        if not key or key in entries:
            continue

        translation = clean_translation(matches[0])
        if not translation:
            continue

        entries[key] = DictionaryEntry(headword=cleaned_headword, translation=translation)

    return entries


def load_seed_rows(seed_path: Path) -> list[dict[str, str]]:
    with seed_path.open("r", encoding="utf-8", newline="") as handle:
        rows: list[dict[str, str]] = []
        for row in csv.DictReader(handle):
            cleaned = {header: row.get(header, "") for header in HEADERS}
            rows.append(cleaned)
        return rows


def seed_lookup(rows: list[dict[str, str]]) -> tuple[set[tuple[str, str]], dict[str, dict[str, str]]]:
    seen = set()
    overrides: dict[str, dict[str, str]] = {}
    for row in rows:
        seen.add((row["category"], row["lemma"].casefold()))
        overrides[row["lemma"].casefold()] = row
        overrides[row["term"].casefold()] = row
    return seen, overrides


def valid_candidate(text: str) -> bool:
    if not text or len(text) < 2 or len(text) > 60:
        return False
    if text.count(" ") > 4:
        return False
    if any(char.isdigit() for char in text):
        return False
    if not re.fullmatch(r"[A-Za-zÄÖÜäöüßẞàáâéèêëíìîóòôúùûçñ' -]+", text):
        return False
    lower = text.casefold()
    if lower in EXCLUDED_TERMS:
        return False
    return True


def guess_article(noun: str) -> str:
    lower = noun.casefold()
    if lower.endswith(("ung", "heit", "keit", "schaft", "tion", "ik", "ie", "ur", "tät")):
        return "die"
    if lower.endswith(("chen", "lein", "ment", "um", "ma")):
        return "das"
    if lower.endswith(("ismus", "ling", "ich", "ig", "er")):
        return "der"
    return "die" if lower.endswith("e") else "der"


def zipf_to_cefr(term: str) -> str:
    score = zipf_frequency(term, "de")
    if score >= 6.2:
        return "A1"
    if score >= 5.7:
        return "A2"
    if score >= 5.1:
        return "B1"
    if score >= 4.5:
        return "B2"
    if score >= 3.8:
        return "C1"
    return "C2"


def detect_category(term: str, entry: DictionaryEntry, doc) -> tuple[str, str, str | None] | None:
    override_noun = bool(entry.headword and entry.headword[:1].isupper() and " " not in entry.headword)

    if " " in term:
        return "phrases", term.casefold(), None

    lower = term.casefold()
    if lower in COMMON_PREPOSITIONS:
        return "prepositions", lower, None

    token = next((token for token in doc if not token.is_space), None)
    if token is None:
        return None

    if override_noun:
        lemma = re.sub(r"[^A-Za-zÄÖÜäöüß-]", "", token.lemma_ or entry.headword or term).capitalize()
        if not lemma:
            lemma = clean_headword(entry.headword).capitalize()
        return "nouns", lemma, guess_article(lemma)

    if token.pos_ in POS_CATEGORY_MAP:
        category = POS_CATEGORY_MAP[token.pos_]
        lemma = re.sub(r"[^A-Za-zÄÖÜäöüß-]", "", token.lemma_ or term)
        if not lemma:
            lemma = term
        lemma = lemma.capitalize() if category == "nouns" else lemma.casefold()
        article = guess_article(lemma) if category == "nouns" else None
        return category, lemma, article

    if lower.endswith(("ieren", "eln", "ern", "en")):
        return "verbs", lower, None
    if lower.endswith(("weise", "wärts")):
        return "adverbs", lower, None
    if lower.endswith(("lich", "ig", "isch", "los", "sam", "bar")):
        return "adjectives", lower, None

    return None


def build_row(
    *,
    term: str,
    entry: DictionaryEntry,
    doc,
    overrides: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    override = overrides.get(term.casefold()) or overrides.get(entry.headword.casefold())
    if override:
        return {
            "cefr_level": override["cefr_level"],
            "category": override["category"],
            "lemma": override["lemma"],
            "term": override["term"],
            "translation": override["translation"],
            "article": override["article"],
            "aliases": override["aliases"],
        }

    detected = detect_category(term, entry, doc)
    if not detected:
        return None

    category, lemma, article = detected
    if not lemma or len(lemma) < 2:
        return None

    display_term = term if category == "phrases" else lemma
    if category == "nouns":
        display_term = f"{article} {lemma}"

    translation = MANUAL_TRANSLATIONS.get(term.casefold(), entry.translation)

    if category != "phrases" and lemma.casefold() in EXCLUDED_TERMS:
        return None

    return {
        "cefr_level": zipf_to_cefr(lemma if category != "phrases" else term),
        "category": category,
        "lemma": lemma,
        "term": display_term,
        "translation": translation,
        "article": article or "",
        "aliases": "",
    }


def write_rows(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    seed_rows = load_seed_rows(args.seed)
    seen, overrides = seed_lookup(seed_rows)
    rows = list(seed_rows)

    dictionary_entries = extract_freedict_entries(args.archive)
    nlp = spacy.load("de_core_news_sm", disable=["ner"])

    candidates: list[str] = []
    seen_candidate_keys: set[str] = set()
    for term in top_n_list("de", args.topn):
        normalized_term = term.casefold()
        if normalized_term in seen_candidate_keys:
            continue
        seen_candidate_keys.add(normalized_term)
        if valid_candidate(term):
            candidates.append(term)
    docs = nlp.pipe(candidates, batch_size=512)

    for term, doc in zip(candidates, docs, strict=False):
        if len(rows) >= args.target:
            break

        entry = dictionary_entries.get(term.casefold())
        if not entry:
            continue

        row = build_row(term=term, entry=entry, doc=doc, overrides=overrides)
        if not row:
            continue

        dedupe_key = (row["category"], row["lemma"].casefold())
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        rows.append(row)

    if len(rows) < args.target:
        remaining_terms = [
            key
            for key, entry in dictionary_entries.items()
            if valid_candidate(entry.headword)
        ]
        remaining_terms.sort(key=lambda item: zipf_frequency(item, "de"), reverse=True)

        fallback_docs = nlp.pipe((dictionary_entries[key].headword for key in remaining_terms), batch_size=512)
        for key, doc in zip(remaining_terms, fallback_docs, strict=False):
            if len(rows) >= args.target:
                break

            entry = dictionary_entries[key]
            row = build_row(term=entry.headword, entry=entry, doc=doc, overrides=overrides)
            if not row:
                continue

            dedupe_key = (row["category"], row["lemma"].casefold())
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            rows.append(row)

    write_rows(rows, args.output)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
