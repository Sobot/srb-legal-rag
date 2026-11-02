"""One-act live PIS smoke test: current Constitution -> parser -> temporary KG.

Intentionally hardcoded to a single current act (ustav-rs). No references,
historical versions, embeddings or full ingest. Snapshot export is explicitly
blocked unless running in a private GitHub repository with written consent.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from lexsr import index, ingest, kg, pis
from ci_artifact import export_bundle

LAW_SLUG = "ustav-rs"
LAW_GUID = "f0d72ce3-dad2-4395-a2c1-c3d3226f22c2"
ALLOWED_URLS = frozenset({
    pis.REG_API + "GetLawActViewByGuid",
    pis.REG_API + "GetLawActTimeline",
    pis.REG_API + "GetEliInfoByGuid",
    pis.VIEWDOC_URL,
})
EXPECTED_REQUESTS = 4
MAX_RESPONSE_BYTES = 3_000_000


def run_once(bundle_dir: Path | None = None) -> dict:
    if bundle_dir is not None:
        if (os.environ.get("GITHUB_REPOSITORY_VISIBILITY") != "private" or
                os.environ.get("PIS_WRITTEN_CONSENT") != "true"):
            raise RuntimeError("Archiving live PIS text requires a private repository and written consent")
    original_request = pis._request
    calls: list[str] = []

    def guarded_request(method: str, url: str, **kwargs):
        if method != "GET" or url not in ALLOWED_URLS:
            raise RuntimeError("Unexpected request: this test permits only four PIS GET endpoints")
        if len(calls) >= EXPECTED_REQUESTS or url in calls:
            raise RuntimeError("PIS request limit exceeded or endpoint repeated")
        params = kwargs.get("params") or {}
        if url == pis.VIEWDOC_URL:
            if params.get("doctype") != "reg" or not params.get("regactid"):
                raise RuntimeError("Invalid consolidated-text request")
        elif params.get("guid") != LAW_GUID:
            raise RuntimeError("Unexpected law requested")
        calls.append(url)
        response = original_request(method, url, **kwargs)
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise RuntimeError("PIS response is larger than the per-request safety limit")
        return response

    with tempfile.TemporaryDirectory(prefix="lexsr-one-act-") as temporary:
        root = Path(temporary)
        corpus = root / "corpus"
        graph_path = root / "kg.sqlite"

        with (
            patch.object(ingest, "CORPUS_DIR", corpus),
            patch.object(index, "CORPUS_DIR", corpus),
            patch.object(kg, "CORPUS_DIR", corpus),
            patch.object(kg, "KG_PATH", graph_path),
            patch.object(pis, "USER_AGENT",
                         "srb-legal-rag-single-act-smoke/0.1 (https://github.com/Sobot/srb-legal-rag)"),
            patch.object(pis, "_request", side_effect=guarded_request),
        ):
            summary = ingest.ingest(
                LAW_SLUG, fetch_references=False, incremental=False, use_cache=False,
            )
            if summary["failures"] != 0 or summary["laws"] != 1:
                raise RuntimeError(f"Single-act ingestion failed: {summary}")
            if len(calls) != EXPECTED_REQUESTS or set(calls) != ALLOWED_URLS:
                raise RuntimeError(f"Unexpected number of PIS GET requests: {len(calls)}")

            graph = kg.build_kg()
            manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
            chunks = [
                json.loads(line)
                for line in (corpus / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            references = (corpus / "references.jsonl").read_text(encoding="utf-8").strip()
            if len(manifest) != 1 or manifest[0]["slug"] != LAW_SLUG:
                raise RuntimeError("Corpus selection was not exactly the intended act")
            if manifest[0].get("law_guid") != LAW_GUID:
                raise RuntimeError("PIS returned an unexpected act")
            if len(manifest[0]["versions"]) != 1:
                raise RuntimeError("Historical versions were unexpectedly fetched")
            if references or not chunks:
                raise RuntimeError("Expected parsed articles without reference expansion")
            if graph["akti"] != 1 or graph["clanovi"] != len(chunks):
                raise RuntimeError("KG node counts do not match parsed article chunks")

            eli = manifest[0].get("eli")
            for chunk in chunks:
                if (chunk["metadata"].get("law_slug") != LAW_SLUG
                    or "/clan-" not in chunk["chunk_id"]
                    or not chunk["provenance"].get("fragment")
                    or chunk["provenance"].get("url") != eli):
                    raise RuntimeError("Missing article-level provenance")

            # Only public identifiers and counts leave the runner.
            report = {
                "mode": "live-single-act",
                "law_slug": LAW_SLUG,
                "title": manifest[0]["title"],
                "version_regactid": manifest[0]["regactid"],
                "versions_fetched": 1,
                "pis_requests": len(calls),
                "references_fetched": False,
                "embeddings_created": False,
                "acts": 1,
                "article_chunks": len(chunks),
                "graph_acts": graph["akti"],
                "graph_articles": graph["clanovi"],
                "eli": eli,
                "sample_citations": [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "article": chunk["provenance"]["fragment"],
                        "url": chunk["provenance"]["url"],
                    }
                    for chunk in chunks[:3]
                ],
            }
            if bundle_dir is not None:
                export_bundle(corpus, graph_path, bundle_dir, kind="authorized-live")

    # The temporary HTML, chunks and graph are deleted before returning.
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--bundle-dir", type=Path, default=None)
    args = parser.parse_args()
    report = run_once(args.bundle_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[live smoke] PASS: {report['article_chunks']} article chunks, "
          f"{report['graph_articles']} KG nodes, {report['pis_requests']} PIS GET requests")


if __name__ == "__main__":
    main()
