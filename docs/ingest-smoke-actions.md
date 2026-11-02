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

## Next step (not yet implemented)

After checking these results, a separate, explicitly approved workflow could
fetch a single live act. PIS terms restrict automated extraction/storage, so
review access permissions first. Do not add a full ingest or automated schedule
until that question is resolved.
