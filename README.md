# DKG proof task

This repository contains a deliberately small Python enrichment pipeline for 12 records from `seed_organizations.csv`. It fetches each supplied first-party website with `requests`, cleans the HTML with BeautifulSoup, asks Gemini to extract founding year, HQ country, and a one-sentence description, then applies deterministic evidence checks before deciding whether to write each field. The output is field-level so every decision is independently traceable.

## Run

```powershell
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-key"
python enrich.py
```

The program refuses to replace `enriched_fields.csv`. An intentional rerun requires `python enrich.py --overwrite`.

## Selection and data observations

The selected IDs are `ORG-0001`, `0002`, `0004`, `0005`, `0006`, `0007`, `0011`, `0012`, `0016`, `0019`, `0024`, and `0032`. They all had first-party source URLs and distinct domains at selection time. The group mixes apparently consistent records with useful validation cases: recent-looking founding years and country/city combinations worth checking.

The seed also contains six duplicate-domain pairs and six records without source URLs. These may be deliberate test cases rather than defects. I did not resolve or merge entities because that would add a separate, ambiguous problem to a one-hour enrichment exercise.

## Provenance and write semantics

Each row in `enriched_fields.csv` records the seed value, extracted proposal, action, reason, final fetched URL after redirects, UTC retrieval timestamp, transform identifier, and a verbatim evidence quote. Evidence must occur in the cleaned source text. Years must be plausible and present in their quote; HQ evidence must explicitly mention headquarters and the country; descriptions must be concise, one sentence, and copied verbatim.

- **INSERTED:** the seed field is empty and the evidence passes validation.
- **UPDATED:** a non-empty seed value differs from a validated proposal.
- **LEFT_ALONE:** the values agree, the page has no explicit evidence, fetching/extraction fails, or validation rejects the proposal.

Worked example: the `ORG-0005 / founded_year` row changes `2025` to `1999`. It records `UPDATED`, the D-Wave first-party URL, `2026-09-04T15:49:20+00:00`, transform `llm_extract_v1:gemini-3.5-flash`, and evidence `Founded in 1999`. That single row is the six-month trace from value to source and decision.

## Deliberate limits

There is no crawler, database, async processing, entity resolution, confidence score, or heuristic fallback. Gemini is used only inside `extract_fields()` to propose structured values; deterministic Python decides whether to accept them. If `GEMINI_API_KEY` is absent, the program stops. `extract_fields()` is the small replacement point for a future OpenAI fallback. A coding assistant helped design and implement the repository; Gemini performed the webpage extraction.

At 20,000 records, sequential network and API latency would break first, followed by rate limits, website blocking, and the lack of durable checkpoints. The next step would be bounded concurrency, retries with backoff, cached raw responses, and resumable storage—not a larger framework until those needs are demonstrated.
