# Offline Knowledge Base Explorer

**Goal:** test retrieval over an existing local legal KB snapshot, with no
PIS requests, Gemini/LLM invocation, embeddings, AWS infrastructure or MCP.

This extends the existing FastAPI + React/Vite application with a **Search**
tab. The search API uses the built-in SQLite FTS5 BM25 engine, with Serbian
Latin-to-Cyrillic query transliteration. Results contain the original text,
article identifiers, validity metadata, BM25 rank and the official act-level
ELI URL. An ELI URL may lead to the **act**, not directly to the article.

## 1. Create the offline fixture locally (no network calls to PIS)

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22+
and npm. Clone the fork and checkout `feature/offline-kb-explorer`.

```bash
uv python install 3.12
uv sync --locked --python 3.12 --extra dev
mkdir -p .local-kb/corpus
uv run --no-sync python scripts/ci_ingest_smoke.py \
  --report .local-kb/fixture-report.json \
  --bundle-dir .local-kb/fixture-snapshot
python scripts/ci_artifact.py verify \
  --bundle .local-kb/fixture-snapshot --kind fixture
cp .local-kb/fixture-snapshot/chunks.jsonl .local-kb/corpus/
cp .local-kb/fixture-snapshot/manifest.json .local-kb/corpus/
cp .local-kb/fixture-snapshot/kg.sqlite .local-kb/kg.sqlite
```

This uses the **already checked-in** `tests/fixtures/zakon_o_radu_consolidated.html`.
It generates approximately 298 article chunks and a local SQLite knowledge
graph. The `.local-kb/` folder is ignored by Git and prevents accidental
modification of the project's tracked corpus metadata.

Do not run `lexsr.ingest all`. The live PIS source has separate access
restrictions and is not needed for this Explorer.

## 2. Run the Explorer locally

In terminal 1:

```bash
LEXSR_DATA_DIR="$PWD/.local-kb" uv run --no-sync uvicorn lexsr.api:app \
  --host 127.0.0.1 --port 8000
```

In terminal 2:

```bash
cd web
npm ci
npm run dev -- --host 127.0.0.1
```

Open http://127.0.0.1:5173 and choose **Search**. Both services listen
on localhost only. No API key or AWS account is required.

Example: `prava obaveze odgovornosti`, optionally filter to
`zakon-o-radu`. The first search automatically creates the local SQLite
FTS5 index in `.local-kb/search.sqlite`. Subsequent queries reuse it;
a changed `chunks.jsonl` causes a rebuild.

## API

- `GET /api/search/status`: reports whether the local corpus is present.
- `POST /api/search`: body example:

```json
{
  "query": "prava i obaveze zaposlenih",
  "law_slug": "zakon-o-radu",
  "as_of": null,
  "limit": 10
}
```

Response includes `results` with `chunk_id`, `source_title`, `fragment`,
`text`, `source_url`, `version`, `valid_from`, `valid_to`, `rank` and
`score`. Higher score means stronger **relative** BM25 relevance within
the current corpus, not a confidence percentage.

**Limitations:** this is lexical matching only. It does not stem Serbian
words, understand synonyms, or reconstruct missing historical versions.
`as_of` filters the validity metadata of stored **current** article chunks;
dated version slices are excluded, so it is not a comprehensive historical
law search. The result order does not establish legal correctness.

## Tests

```bash
uv run --no-sync python -m pytest -q \
  tests/test_offline_search.py tests/test_api.py tests/test_parser.py
cd web && npm run build
```

Tests include a real checked-in HTML fixture, Latin/Cyrillic handling,
filters, cache invalidation, safe FTS query construction and search API
without a Gemini key. GitHub Actions runs these on the feature branch.

## Later phases (not implemented)

After validating lexical results, add a labeled set of questions with
expected article citations and measure Recall@5 / Recall@10. Then evaluate
optional LanceDB embeddings and hybrid retrieval on **the same frozen KB
snapshot**. Continue to keep MCP/API hosting and AWS separate decisions.
