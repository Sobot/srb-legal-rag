"""Offline integration smoke test: fixture HTML -> ingest -> article chunks -> KG.

Never contacts PIS, Gemini or other external APIs. Output contains only
counts and article-level citation metadata, never law text or downloaded HTML.
"""

from __future__ import annotations

import argparse
import json
import socket
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from lexsr import index, ingest, kg, pis

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "zakon_o_radu_consolidated.html"
ELI = "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/skupstina/zakon/2005/24/1/reg"
LAW_SLUG = "zakon-o-radu"


def deny_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("Network access is forbidden in offline ingest smoke test")


def run_offline(corpus_dir: Path, kg_path: Path) -> dict:
    html = FIXTURE.read_text(encoding="utf-8")
    version = pis.LawVersion(
        uuid="offline-fixture-version",
        regactid="offline-fixture-regactid",
        applies_from=date(2018, 12, 8),
    )
    view = pis.LawView(
        law_guid="offline-fixture-guid",
        title="Закон о раду (offline fixture)",
        current=version,
        previous=[],
    )

    # The real ingest, parser, chunk writer and graph builder run. Only PIS
    # boundary calls are mocked, with a socket-level guard as a second gate.
    with (
        patch.object(socket.socket, "connect", side_effect=deny_network),
        patch.object(socket.socket, "connect_ex", side_effect=deny_network),
        patch.object(ingest, "CORPUS_DIR", corpus_dir),
        patch.object(index, "CORPUS_DIR", corpus_dir),
        patch.object(kg, "CORPUS_DIR", corpus_dir),
        patch.object(kg, "KG_PATH", kg_path),
        patch.object(pis, "get_law_view", return_value=view),
        patch.object(pis, "get_eli_link", return_value=ELI),
        patch.object(pis, "fetch_consolidated_html", return_value=html),
        patch.object(pis, "get_references", side_effect=deny_network),
        patch.object(pis, "fetch_doc", side_effect=deny_network),
        patch.object(pis, "resolve_eli", side_effect=deny_network),
        patch.object(pis, "search_registry", side_effect=deny_network),
    ):
        summary = ingest.ingest(
            LAW_SLUG,
            fetch_references=False,
            incremental=False,
            use_cache=False,
        )
        if summary["failures"] or summary["laws"] != 1:
            raise AssertionError(f"Expected one successfully parsed law: {summary}")

        graph = kg.build_kg()

        manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
        chunks = [
            json.loads(line)
            for line in (corpus_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        refs = (corpus_dir / "references.jsonl").read_text(encoding="utf-8").strip()

        if len(manifest) != 1 or manifest[0]["slug"] != LAW_SLUG:
            raise AssertionError("Unexpected corpus manifest: only the fixture law is allowed")
        if not chunks or refs:
            raise AssertionError("Expected article chunks and zero reference expansion")
        if graph["akti"] != 1 or graph["clanovi"] != len(chunks):
            raise AssertionError("Graph does not match parsed article chunks")

        for chunk in chunks:
            provenance = chunk["provenance"]
            if (
                chunk["metadata"]["law_slug"] != LAW_SLUG
                or "/clan-" not in chunk["chunk_id"]
                or not provenance.get("fragment", "").startswith("član ")
                or provenance.get("url") != ELI
            ):
                raise AssertionError(f"Missing article provenance: {chunk['chunk_id']}")

        return {
            "mode": "offline-fixture",
            "source_fixture": str(FIXTURE.relative_to(ROOT)),
            "selector": LAW_SLUG,
            "pis_requests": 0,
            "reference_expansion": False,
            "embedding": False,
            "acts": len(manifest),
            "versions": len(manifest[0]["versions"]),
            "article_chunks": len(chunks),
            "graph_acts": graph["akti"],
            "graph_article_nodes": graph["clanovi"],
            "eli": ELI,
            "citations": [
                {
                    "chunk_id": c["chunk_id"],
                    "fragment": c["provenance"]["fragment"],
                    "source_url": c["provenance"]["url"],
                }
                for c in chunks[:3]
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lexsr-offline-smoke-") as tmp:
        root = Path(tmp)
        report = run_offline(root / "corpus", root / "kg.sqlite")

    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[smoke] PASS: {report['article_chunks']} article chunks; "
          f"{report['graph_article_nodes']} KG article nodes; zero external requests")


if __name__ == "__main__":
    main()
