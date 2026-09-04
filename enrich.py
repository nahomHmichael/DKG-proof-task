"""Small, traceable enrichment pipeline for the DKG proof task."""

import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


SEED_PATH = Path("seed_organizations.csv")
OUTPUT_PATH = Path("enriched_fields.csv")
SELECTED_IDS = (
    "ORG-0001",
    "ORG-0002",
    "ORG-0004",
    "ORG-0005",
    "ORG-0006",
    "ORG-0007",
    "ORG-0011",
    "ORG-0012",
    "ORG-0016",
    "ORG-0019",
    "ORG-0024",
    "ORG-0032",
)
FIELD_NAMES = ("founded_year", "hq_country", "description")
OUTPUT_COLUMNS = (
    "record_id",
    "organization_name",
    "domain",
    "field_name",
    "old_value",
    "new_value",
    "write_action",
    "decision_reason",
    "source_url",
    "retrieved_at",
    "transform",
    "evidence",
)

PROMPT_VERSION = "v1"
GEMINI_MODEL = "gemini-3.5-flash"
TRANSFORM = f"llm_extract_{PROMPT_VERSION}:{GEMINI_MODEL}"
USER_AGENT = "DKG-proof-task/1.0 (field provenance exercise)"
REQUEST_TIMEOUT = (5, 20)
MAX_DESCRIPTION_WORDS = 35

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "founded_year": {"type": ["string", "null"]},
        "founded_year_evidence": {"type": ["string", "null"]},
        "hq_country": {"type": ["string", "null"]},
        "hq_country_evidence": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "description_evidence": {"type": ["string", "null"]},
    },
    "required": [
        "founded_year",
        "founded_year_evidence",
        "hq_country",
        "hq_country_evidence",
        "description",
        "description_evidence",
    ],
    "additionalProperties": False,
}

EXTRACTION_PROMPT = """Extract facts only from the supplied first-party webpage text.
Return null when the page does not explicitly support a field.
- founded_year: a four-digit year explicitly described as the organization's founding year.
- hq_country: a full country name explicitly connected to headquarters; an office alone is insufficient.
- description: one concise complete sentence copied verbatim from the source, not synthesized.
For every non-null value, return a short verbatim evidence quote containing the value.
Do not use outside knowledge and do not infer a country from a city or state abbreviation.
"""


def normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_seed(path=SEED_PATH):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    rows_by_id = {row["record_id"]: row for row in rows}
    missing = [record_id for record_id in SELECTED_IDS if record_id not in rows_by_id]
    if missing:
        raise ValueError(f"Selected record IDs missing from seed: {', '.join(missing)}")

    selected = [rows_by_id[record_id] for record_id in SELECTED_IDS]
    without_urls = [row["record_id"] for row in selected if not row["source_url"].strip()]
    if without_urls:
        raise ValueError(f"Selected records lack source URLs: {', '.join(without_urls)}")
    return selected


def fetch_page(url):
    retrieved_at = utc_now()
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
        return {
            "html": response.text,
            "source_url": response.url,
            "retrieved_at": retrieved_at,
            "error": "",
        }
    except requests.RequestException as exc:
        return {
            "html": "",
            "source_url": url,
            "retrieved_at": retrieved_at,
            "error": f"fetch failed: {exc}",
        }


def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "svg", "nav", "footer", "form"]):
        element.decompose()
    return normalize_whitespace(soup.get_text(" "))


def gemini_config():
    from google.genai import types

    return types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_json_schema=EXTRACTION_SCHEMA,
    )


def extract_fields(source_text):
    """Use Gemini only for structured extraction; all acceptance is deterministic."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set; no heuristic fallback is available")

    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{EXTRACTION_PROMPT}\n\nSOURCE TEXT:\n{source_text}",
        config=gemini_config(),
    )
    result = json.loads(response.text)
    return {key: normalize_whitespace(result.get(key)) for key in EXTRACTION_SCHEMA["properties"]}


def validate_evidence(field_name, value, evidence, source_text):
    value = normalize_whitespace(value)
    evidence = normalize_whitespace(evidence)
    source_text = normalize_whitespace(source_text)

    if not value:
        return False, "no value was extracted"
    if not evidence:
        return False, "no supporting evidence quote was extracted"
    if evidence.casefold() not in source_text.casefold():
        return False, "evidence quote was not found in the fetched source text"

    if field_name == "founded_year":
        if not re.fullmatch(r"\d{4}", value):
            return False, "founding year is not a four-digit integer"
        year = int(value)
        if year < 1800 or year > datetime.now(timezone.utc).year:
            return False, "founding year is outside the plausible range 1800-current year"
        if value not in evidence:
            return False, "founding year does not appear in its evidence quote"

    elif field_name == "hq_country":
        if value.casefold() not in evidence.casefold():
            return False, "HQ country does not appear in its evidence quote"
        if "headquarter" not in evidence.casefold():
            return False, "evidence does not explicitly identify a headquarters"

    elif field_name == "description":
        if len(value.split()) > MAX_DESCRIPTION_WORDS:
            return False, f"description exceeds {MAX_DESCRIPTION_WORDS} words"
        if value[-1] not in ".!?":
            return False, "description is not a complete sentence"
        sentence_ends = re.findall(r"[.!?](?=\s+[A-Z]|$)", value)
        if len(sentence_ends) != 1:
            return False, "description is not exactly one sentence"
        if value.casefold() not in source_text.casefold():
            return False, "description was not copied verbatim from the source"
        if value.casefold() not in evidence.casefold():
            return False, "description does not appear in its evidence quote"

    return True, "accepted: deterministic validation passed"


def comparable_value(value):
    normalized = normalize_whitespace(value).casefold().rstrip(".")
    aliases = {
        "u.s.": "united states",
        "u.s.a.": "united states",
        "usa": "united states",
        "united states of america": "united states",
        "uk": "united kingdom",
        "u.k.": "united kingdom",
    }
    return aliases.get(normalized, normalized)


def decide_write(old_value, new_value, is_valid, validation_reason):
    old_value = normalize_whitespace(old_value)
    new_value = normalize_whitespace(new_value)

    if not is_valid:
        return "LEFT_ALONE", validation_reason
    if not old_value:
        return "INSERTED", "accepted first-party evidence for an empty seed field"
    if comparable_value(old_value) == comparable_value(new_value):
        return "LEFT_ALONE", "validated first-party evidence agrees with the seed value"
    return "UPDATED", "validated first-party evidence supports a different value"


def decision_rows(seed_row, extraction, source_text, source_url, retrieved_at, extraction_error=""):
    rows = []
    for field_name in FIELD_NAMES:
        old_value = "" if field_name == "description" else seed_row[field_name]
        new_value = normalize_whitespace(extraction.get(field_name))
        evidence = normalize_whitespace(extraction.get(f"{field_name}_evidence"))

        if extraction_error:
            is_valid = False
            validation_reason = extraction_error
        else:
            is_valid, validation_reason = validate_evidence(
                field_name, new_value, evidence, source_text
            )

        action, reason = decide_write(old_value, new_value, is_valid, validation_reason)
        rows.append(
            {
                "record_id": seed_row["record_id"],
                "organization_name": seed_row["organization_name"],
                "domain": seed_row["domain"],
                "field_name": field_name,
                "old_value": old_value,
                "new_value": new_value,
                "write_action": action,
                "decision_reason": reason,
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "transform": TRANSFORM if not extraction_error.startswith("fetch failed") else "http_fetch_v1:no_extraction",
                "evidence": evidence,
            }
        )
    return rows


def write_output(rows, path=OUTPUT_PATH, overwrite=False):
    check_output_path(path, overwrite)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def check_output_path(path=OUTPUT_PATH, overwrite=False):
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; pass --overwrite to replace it")


def main():
    parser = argparse.ArgumentParser(description="Enrich 12 seed organizations with field-level provenance")
    parser.add_argument("--overwrite", action="store_true", help="replace enriched_fields.csv if it exists")
    args = parser.parse_args()

    try:
        check_output_path(overwrite=args.overwrite)
    except FileExistsError as exc:
        raise SystemExit(str(exc)) from exc

    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is required; no heuristic fallback is used")

    output_rows = []
    for seed_row in load_seed():
        fetched = fetch_page(seed_row["source_url"])
        if fetched["error"]:
            extraction = {}
            source_text = ""
            extraction_error = fetched["error"]
        else:
            source_text = clean_html(fetched["html"])
            try:
                extraction = extract_fields(source_text)
                extraction_error = ""
            except Exception as exc:
                extraction = {}
                extraction_error = f"extraction failed: {exc}"

        output_rows.extend(
            decision_rows(
                seed_row,
                extraction,
                source_text,
                fetched["source_url"],
                fetched["retrieved_at"],
                extraction_error,
            )
        )

    write_output(output_rows, overwrite=args.overwrite)
    print(f"Wrote {len(output_rows)} field decisions to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
