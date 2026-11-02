"""Package and verify a CI knowledge-base snapshot with SHA-256 checks.

No PIS or model requests. For public repositories, only pre-existing checked-in
fixtures are allowed to be exported through the offline workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

FILES = ("chunks.jsonl", "manifest.json", "kg.sqlite")
META = "bundle-metadata.json"


def digest(file: Path) -> str:
    hasher = hashlib.sha256()
    with file.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def check_payload(directory: Path, *, expected_kind: str) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    chunks = [json.loads(line) for line in
              (directory / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]

    if not manifest or not chunks:
        raise ValueError("The knowledge base must contain an act and article chunks")
    if expected_kind == "fixture":
        if len(manifest) != 1 or manifest[0]["slug"] != "zakon-o-radu":
            raise ValueError("Public fixture workflow must never export non-fixture corpus")
        if any(c.get("metadata", {}).get("law_slug") != "zakon-o-radu"
               for c in chunks):
            raise ValueError("Non-fixture chunks detected")

    with sqlite3.connect(f"file:{(directory / 'kg.sqlite').resolve()}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite knowledge graph is corrupted")
        acts = db.execute("SELECT COUNT(*) FROM akt").fetchone()[0]
        articles = db.execute("SELECT COUNT(*) FROM clan").fetchone()[0]
        bad_fk = db.execute("PRAGMA foreign_key_check").fetchone()
        if bad_fk:
            raise ValueError(f"SQLite graph has a foreign key violation: {bad_fk}")

    if acts != len(manifest) or articles != len(chunks):
        raise ValueError(
            f"Snapshot mismatch: {acts}/{len(manifest)} acts, "
            f"{articles}/{len(chunks)} article chunks"
        )
    return {"acts": acts, "article_chunks": len(chunks), "graph_articles": articles}


def export_bundle(corpus: Path, kg_path: Path, target: Path, *, kind: str) -> dict:
    if kind not in ("fixture", "authorized-live"):
        raise ValueError("Unsupported artifact kind")
    if target.exists() and list(target.iterdir()):
        raise ValueError("Destination bundle directory must be empty")
    target.mkdir(parents=True, exist_ok=True)

    paths = (corpus / FILES[0], corpus / FILES[1], kg_path)
    for name, source in zip(FILES, paths):
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing or unsafe snapshot component: {name}")
        shutil.copyfile(source, target / name)

    counts = check_payload(target, expected_kind=kind)
    metadata = {
        "schema": 1,
        "kind": kind,
        "files": {name: digest(target / name) for name in FILES},
        **counts,
    }
    (target / META).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def verify_bundle(directory: Path, *, kind: str) -> dict:
    expected = {*FILES, META}
    observed = {f.name for f in directory.iterdir()}
    if observed != expected:
        raise ValueError(f"Unexpected archive structure: {sorted(observed)}")
    if any((directory / f).is_symlink() for f in expected):
        raise ValueError("Symlink inside the snapshot is prohibited")
    metadata = json.loads((directory / META).read_text(encoding="utf-8"))
    if metadata.get("schema") != 1 or metadata.get("kind") != kind:
        raise ValueError("Unknown snapshot format or provenance kind")
    if set(metadata.get("files", {})) != set(FILES):
        raise ValueError("Missing SHA-256 entries")
    for name, expected_hash in metadata["files"].items():
        if digest(directory / name) != expected_hash:
            raise ValueError(f"SHA-256 mismatch: {name}")
    counts = check_payload(directory, expected_kind=kind)
    if any(metadata.get(key) != val for key, val in counts.items()):
        raise ValueError("Archive metadata counts do not match its contents")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["verify"])
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--kind", choices=["fixture", "authorized-live"], required=True)
    args = parser.parse_args()
    result = verify_bundle(args.bundle, kind=args.kind)
    print(f"[restore] PASS: {result['acts']} acts, "
          f"{result['article_chunks']} article chunks, "
          "SHA-256 + SQLite integrity verified")


if __name__ == "__main__":
    main()
