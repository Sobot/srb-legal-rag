# Offline GitHub Actions ingest smoke test

Workflow: [Ingest smoke test](../.github/workflows/ingest-smoke.yml).

**Scope:** One checked-in Zakon o radu HTML fixture, no live PIS access,
no reference traversal, no Gemini API, no embeddings and no full-registry ingest.

## What it validates

1. Existing parser/ingestion/KG contract tests pass.
2. The real ingest pipeline parses fixture HTML to article-level chunks.
3. Every chunk has a source ELI URL and a specific article citation.
4. The SQLite temporal knowledge graph has one act and the same number of
   articles as the chunk output.
5. Test data remains in temporary runner storage; only counts and citation
   identifiers are uploaded as a three-day GitHub Actions artifact.

## Run

Open the **Actions** tab and choose **Offline ingest and parsing smoke test**.
Use **Run workflow** on branch `feature/ingest-smoke-actions`, if available.
A push to that same branch also triggers the workflow. Forks may require
enabling Actions in their repository settings first.

To run locally after installing `uv`:

```bash
uv python install 3.12
uv sync --locked --python 3.12 --extra dev
uv run --no-sync python -m pytest -q tests/test_parser.py tests/test_ingest.py tests/test_kg.py
uv run --no-sync python scripts/ci_ingest_smoke.py --report /tmp/ingest-report.json
```

Expected: `acts=1`, `article_chunks>0`, `graph_article_nodes=article_chunks`,
`pis_requests=0`, `reference_expansion=false`, `embedding=false`.

## Live one-act test (completed)

A separate one-time [live workflow](../.github/workflows/live-one-act-smoke.yml)
uses [the bounded runner](../scripts/ci_live_one_act_smoke.py). It fetches
**only the current Constitution of Serbia** (`ustav-rs`, CURRENT_ONLY)
through at most four allowlisted PIS GET endpoints. The 3-second client
throttle stays enabled. No references, previous versions, embeddings or
entire registry are fetched. The HTML/chunks/SQLite KG stay in temporary
runner storage and are removed; only metadata and citation identifiers
appear in the report.

**Observed first run:** [GitHub Actions #41446116665](https://github.com/Sobot/srb-legal-rag/actions/runs/41446116665)
completed successfully: 1 act, 1 version, 206 article chunks,
206 KG article nodes, 4 PIS GET requests, 0 reference edges,
0 embedding requests, 0 failures. The report contains the source ELI URL.

Manual future runs require `confirm_live=true`. No schedule or broad
ingestion option exists in this workflow.

**Important:** this technical success is not permission from JP Službeni
glasnik. Their published terms restrict automated access and storage.
Seek written authorization before continuing to larger-scale ingestion
or redistribution.
