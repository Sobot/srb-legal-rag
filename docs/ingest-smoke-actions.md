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
5. Only the already-public fixture is exported to a temporary build artifact;
   HTML fetch caches are not included. Two jobs test snapshot upload and restore.
6. On restore, SHA-256 digests, SQLite integrity, foreign keys and counts are
   verified against the generated manifest.

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

The workflow creates **offline-fixture-kb** (three-day retention), containing:
`chunks.jsonl`, `manifest.json`, `kg.sqlite`, `bundle-metadata.json` (SHA-256).
Another GitHub Actions job downloads it and verifies integrity. To check locally:

```bash
python scripts/ci_artifact.py verify --bundle /path/to/downloaded/files --kind fixture
```

**This fixture artifact is NOT private.** This fork is public, so users with
repository read access can download its Actions artifacts. The fixture HTML
already exists in the public repository; do not use this workflow for PIS text
that was not previously published.

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

After the initial run, live ingestion was changed to manual-only, with two
attestations: `confirm_live=true` and `confirm_written_consent=true`.
The operator's [PIS Terms of Service](https://fp.pravno-informacioni-sistem.rs/api/prins/GetStaticPageByCode/TermsOfService)
require prior express **written** approval for automated extraction/indexing/storage;
selecting a checkbox is not a substitute for that approval.

The optional `archive_private_snapshot` flag is **off by default** and the job
aborts **before contacting PIS** if archiving is requested on a public repository.
The live Python runner independently checks `GITHUB_REPOSITORY_VISIBILITY=private`
and the written-consent attestation before allowing any text archive export.
In an authorized private repository only, the saved archive uses the same
four-file format and three-day retention. No external API key is required for
parsing or the SQLite graph. No schedule or full-corpus option exists.

**There is no recoverable text snapshot from the first Ustav live run.** Its
working directory was intentionally temporary and only the metadata report
was uploaded. Therefore enabling the archive workflow later cannot recover
those 206 texts; a future ingest would need separate authorization.

## Production recommendation

Do not use Actions artifacts as the primary production database: they expire
and are immutable per upload. Store approved snapshot versions in a PRIVATE
versioned S3 bucket with SSE-KMS, IAM access control and lifecycle rules.
Keep `chunks.jsonl`, `manifest.json`, `kg.sqlite` and hash metadata together;
for serving, materialize a read-only SQLite KG and LanceDB/other index on
persistent compute. Workflow artifacts are appropriate only for CI transfer
and short-lived diagnostics. No S3 integration is configured yet.

**Important:** this technical success is not permission from JP Službeni
glasnik. Their published terms restrict automated access and storage.
Seek written authorization before continuing to larger-scale ingestion
or redistribution.
