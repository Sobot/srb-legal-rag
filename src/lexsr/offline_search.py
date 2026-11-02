"""Standalone, fully offline Serbian-law lexical search (SQLite FTS5/BM25).

Consumes an existing chunks.jsonl snapshot. This module never imports Gemini,
calls PIS, or uses a network service. The FTS index is a regenerable local
cache and is rebuilt when the snapshot content hash changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import date
from pathlib import Path

from lexsr.translit import to_cyrillic

SCHEMA_VERSION = "1"
_MAX_QUERY_TERMS = 16
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)


class CorpusUnavailable(FileNotFoundError):
    """The KB snapshot has not been installed locally."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _match_expression(query: str) -> str:
    """Only pass quoted Unicode word tokens to FTS MATCH; never raw user syntax.

    OR is deliberate: natural-language questions contain extra words, and
    Serbian FTS5 unicode61 has no Serbian stemming.
    """
    terms = _WORDS.findall(to_cyrillic(query).lower())
    terms = list(dict.fromkeys(t for t in terms if len(t) >= 2))
    if not terms:
        raise ValueError("Enter at least one searchable word (2+ characters)")
    return " OR ".join(f'"{term}"' for term in terms[:_MAX_QUERY_TERMS])


class OfflineSearchIndex:
    def __init__(self, corpus_path: Path, index_path: Path):
        self.corpus_path = Path(corpus_path)
        self.index_path = Path(index_path)
        self._lock = threading.Lock()
        self._checked_stat: tuple[int, int] | None = None

    def _source_stat(self) -> tuple[int, int]:
        try:
            stat = self.corpus_path.stat()
        except FileNotFoundError as exc:
            raise CorpusUnavailable(
                "No local chunks.jsonl found. Generate the offline fixture KB first "
                "or restore an authorized snapshot."
            ) from exc
        return (stat.st_size, stat.st_mtime_ns)

    def _stored_hash(self) -> str | None:
        if not self.index_path.is_file():
            return None
        try:
            with closing(sqlite3.connect(
                f"file:{self.index_path.resolve()}?mode=ro", uri=True
            )) as db:
                rows = dict(db.execute("SELECT key, value FROM search_meta"))
                if rows.get("schema") == SCHEMA_VERSION:
                    return rows.get("corpus_sha256")
        except (sqlite3.Error, OSError):
            pass
        return None

    def ensure_ready(self) -> None:
        with self._lock:
            stat = self._source_stat()
            if self._checked_stat == stat and self.index_path.is_file():
                return
            digest = _sha256(self.corpus_path)
            if self._stored_hash() != digest:
                self._rebuild(digest)
            self._checked_stat = stat

    def _rebuild(self, digest: str) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.index_path.with_name(
            f".{self.index_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with closing(sqlite3.connect(temp)) as db:
                db.executescript("""
                    CREATE TABLE articles (
                        id INTEGER PRIMARY KEY,
                        chunk_id TEXT NOT NULL UNIQUE,
                        law_slug TEXT NOT NULL,
                        title TEXT NOT NULL,
                        fragment TEXT NOT NULL,
                        body TEXT NOT NULL,
                        url TEXT,
                        version TEXT,
                        valid_from TEXT,
                        valid_to TEXT,
                        applies_from TEXT,
                        published TEXT,
                        repealed INTEGER NOT NULL,
                        is_version_slice INTEGER NOT NULL
                    );
                    CREATE INDEX articles_law ON articles(law_slug);
                    CREATE VIRTUAL TABLE articles_fts USING fts5(
                        title, fragment, body,
                        content='articles', content_rowid='id',
                        tokenize='unicode61 remove_diacritics 2'
                    );
                    CREATE TABLE search_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """)
                with self.corpus_path.open(encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        source = chunk["provenance"]
                        md = chunk.get("metadata") or {}
                        db.execute(
                            """INSERT INTO articles (
                                 chunk_id, law_slug, title, fragment, body, url,
                                 version, valid_from, valid_to, applies_from,
                                 published, repealed, is_version_slice
                               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                chunk["chunk_id"], md.get("law_slug", ""),
                                source.get("source_title") or "",
                                source.get("fragment") or "",
                                chunk.get("text") or "",
                                source.get("url") or "",
                                source.get("version") or "",
                                source.get("valid_from") or "",
                                source.get("valid_to") or "",
                                md.get("applies_from") or "",
                                md.get("published") or "",
                                int(bool(md.get("repealed", False))),
                                int(bool(md.get("is_version_slice", False))),
                            ),
                        )
                db.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
                db.executemany("INSERT INTO search_meta VALUES (?,?)", [
                    ("schema", SCHEMA_VERSION),
                    ("corpus_sha256", digest),
                ])
                db.commit()
            os.replace(temp, self.index_path)
        finally:
            temp.unlink(missing_ok=True)

    def status(self) -> dict:
        available = self.corpus_path.is_file()
        return {
            "corpus_available": available,
            "index_exists": self.index_path.is_file(),
            "method": "sqlite-fts5-bm25",
            "requires_api_key": False,
        }

    def search(
        self, query: str, *, law_slug: str | None = None,
        as_of: date | None = None, limit: int = 10,
    ) -> dict:
        started = time.perf_counter()
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        match = _match_expression(query)
        self.ensure_ready()

        filters = ["articles_fts MATCH ?", "a.is_version_slice = 0"]
        params: list[object] = [match]
        if law_slug:
            filters.append("a.law_slug = ?")
            params.append(law_slug)
        if as_of:
            # End dates are exclusive; historical accuracy is limited by the
            # source snapshot's version coverage.
            filters.extend([
                "(a.valid_from = '' OR a.valid_from <= ?)",
                "(a.valid_to = '' OR a.valid_to > ?)",
            ])
            params.extend([as_of.isoformat(), as_of.isoformat()])

        sql = """
            SELECT a.chunk_id, a.law_slug, a.title, a.fragment, a.body,
                   a.url, a.version, a.valid_from, a.valid_to,
                   a.applies_from, a.published, a.repealed,
                   -bm25(articles_fts, 8.0, 5.0, 1.0) AS score
            FROM articles_fts
            JOIN articles a ON a.id = articles_fts.rowid
            WHERE """ + " AND ".join(filters) + """
            ORDER BY bm25(articles_fts, 8.0, 5.0, 1.0)
            LIMIT ?
        """
        params.append(limit)

        with closing(sqlite3.connect(
            f"file:{self.index_path.resolve()}?mode=ro", uri=True
        )) as db:
            db.row_factory = sqlite3.Row
            results = [dict(row) for row in db.execute(sql, params)]
            total = db.execute(
                "SELECT COUNT(*) FROM articles WHERE is_version_slice=0"
            ).fetchone()[0]

        for rank, result in enumerate(results, 1):
            result["rank"] = rank
            result["score"] = round(result["score"], 5)
            result["repealed"] = bool(result["repealed"])
            result["text"] = result.pop("body")
            result["source_url"] = result.pop("url")
            result["source_title"] = result.pop("title")

        return {
            "method": "bm25",
            "query": query,
            "normalized_query": to_cyrillic(query),
            "total_indexed_articles": total,
            "results": results,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "note": "Lexical search only; no stemming, embeddings or legal interpretation.",
        }
