# DKG proof task

This repository contains a deliberately small Python enrichment pipeline for 12 records from `seed_organizations.csv`. It fetches each supplied first-party website with `requests`, cleans the HTML with BeautifulSoup, asks Gemini to extract founding year, HQ country, and a one-sentence description, then applies deterministic evidence checks before deciding whether to write each field.

## Run

```powershell
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-key"
python enrich.py
```

The program refuses to replace `enriched_fields.csv`. An intentional rerun requires `python enrich.py --overwrite`.

## Selection and data observations

The selected IDs are `ORG-0001`, `ORG-0002`, `ORG-0004`, `ORG-0005`, `ORG-0006`, `ORG-0007`, `ORG-0011`, `ORG-0012`, `ORG-0016`, `ORG-0019`, `ORG-0024`, and `ORG-0032`. They all had first-party source URLs and distinct domains at selection time. The group mixes apparently consistent records with useful validation cases: recent-looking founding years and country/city combinations worth checking.

The seed also contains six duplicate-domain pairs and six records without source URLs. These may be deliberate test cases rather than defects. I did not resolve or merge entities because that would add a separate, ambiguous problem to a one-hour enrichment exercise.

## Provenance and write semantics

Each row in `enriched_fields.csv` is the authoritative field-level provenance record. It contains the organization and field, seed value, extracted proposal, action, reason, final fetched URL after redirects, UTC retrieval timestamp, evidence quote, and every transformation stage. A shared `run_id` groups all 36 decisions produced by one execution.

A successful field follows `HTTP fetch -> HTML cleaning -> LLM extraction -> deterministic validation -> write decision`. The CSV exposes the first four stages in `fetch_transform`, `extraction_transform`, `validation_transform`, and `transform_chain`; the final decision is kept separately in `write_action` and `decision_reason`.

Evidence must occur in the cleaned source text. Years must be plausible, appear in their quote, and have a founding term; HQ evidence must mention headquarters and the proposed country; descriptions must be concise, end with sentence punctuation, and occur verbatim in the source.

- **INSERTED:** the seed field is empty and the evidence passes validation.
- **UPDATED:** a non-empty seed value differs from a validated proposal.
- **LEFT_ALONE:** the values agree, the page has no explicit evidence, fetching/extraction fails, or validation rejects the proposal.

Worked example: `ORG-0005 / founded_year` changes `2025` to `1999`. Its row records `UPDATED`, source `https://www.dwavequantum.com/company/about-d-wave/`, retrieval time `2026-09-04T15:49:20+00:00`, run `5d984b53-4bf8-4a0e-83a9-fcc09408e3fb`, the full successful transform chain, and evidence `Founded in 1999`. This is a complete single-row audit trace suitable for checking again six months later.

## Run-level lineage and deliberate limits

OpenLineage was deliberately not added as a dependency or service. If this job later emitted OpenLineage events, the logical job would be `organization_enrichment`, `run_id` would identify the run, `seed_organizations.csv` would be the input dataset, and `enriched_fields.csv` would be the output dataset. OpenLineage would describe run-level START/COMPLETE/FAIL relationships; the CSV would remain responsible for evidence and write decisions at field level. They solve different lineage questions, and full infrastructure is not justified for a one-hour, 12-record proof task.

There is no crawler, database, async processing, entity resolution, confidence score, or heuristic fallback. Gemini is used only inside `extract_fields()` to propose structured values; deterministic Python decides whether to accept them. If `GEMINI_API_KEY` is absent, the program stops. `extract_fields()` is the small replacement point for a future OpenAI fallback. A coding assistant helped design and implement the repository; Gemini performed the webpage extraction.

At 20,000 records, sequential network and API latency would break first, followed by rate limits, website blocking, and the lack of durable checkpoints. The next step would be bounded concurrency, retries with backoff, cached raw responses, and resumable storage - not a larger framework until those needs are demonstrated.
