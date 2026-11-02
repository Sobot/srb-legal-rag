"""Offline search contracts: no PIS, LLM, embeddings or AWS credentials."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lexsr import api
from lexsr.offline_search import CorpusUnavailable, OfflineSearchIndex
from lexsr.parser import parse_consolidated_html, to_chunks


def chunk(number: str, body: str, *, law: str = "zakon-o-radu",
          start: str = "2005-03-23", end: str | None = None,
          slice_: bool = False) -> dict:
    return {
        "chunk_id": f"sgrs/zakon/2005/24/1/clan-{number}" + ("@old" if slice_ else ""),
        "text": body,
        "provenance": {
            "source_id": "sgrs/zakon/2005/24/1",
            "source_title": "Закон о раду",
            "fragment": f"član {number}",
            "version": "75/2014" if slice_ else None,
            "valid_from": start,
            "valid_to": end,
            "url": "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/skupstina/zakon/2005/24/1/reg",
        },
        "metadata": {"law_slug": law, "is_version_slice": slice_, "repealed": bool(end)},
    }


def search_index(tmp_path: Path, rows: list[dict]) -> OfflineSearchIndex:
    corpus = tmp_path / "corpus"
    corpus.mkdir(exist_ok=True)
    path = corpus / "chunks.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return OfflineSearchIndex(path, tmp_path / "search.sqlite")


def test_no_corpus_gives_helpful_error(tmp_path):
    index = OfflineSearchIndex(tmp_path / "missing.jsonl", tmp_path / "index.sqlite")
    assert index.status()["corpus_available"] is False
    with pytest.raises(CorpusUnavailable, match="chunks.jsonl"):
        index.search("ugovor o radu")


def test_serbian_latin_to_cyrillic_and_article_provenance(tmp_path):
    index = search_index(tmp_path, [
        chunk("179", "Послодавац може да уручи отказ уговора о раду."),
        chunk("42", "Запослени има право на плаћено одсуство."),
    ])
    result = index.search("otkaz ugovora", limit=5)
    assert result["method"] == "bm25"
    assert result["total_indexed_articles"] == 2
    assert result["results"][0]["fragment"] == "član 179"
    assert result["results"][0]["source_url"].startswith("https://")
    assert "отказ" in result["normalized_query"]
    assert result["results"][0]["rank"] == 1
    assert index.status()["index_exists"] is True


def test_filters_date_and_version_slices(tmp_path):
    index = search_index(tmp_path, [
        chunk("10", "Уговор може да се откаже.", start="2024-01-01"),
        chunk("11", "Послодавац може да откаже уговор.", start="2010-01-01",
              end="2020-01-01"),
        chunk("12", "Уговор може да се откаже.", slice_=True),
    ])
    result = index.search("ugovor otkaže", as_of=date(2018, 1, 1))
    assert [r["fragment"] for r in result["results"]] == ["član 11"]
    current = index.search("ugovor", as_of=date(2024, 1, 1))
    assert [r["fragment"] for r in current["results"]] == ["član 10"]
    assert index.search("ugovor", law_slug="nepostojeci")["results"] == []


def test_index_rebuilds_when_source_changes(tmp_path):
    idx = search_index(tmp_path, [chunk("1", "Право на рад.")])
    assert idx.search("право")["total_indexed_articles"] == 1
    with idx.corpus_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(chunk("2", "Право на одмор."), ensure_ascii=False) + "\n")
    assert idx.search("одмор")["total_indexed_articles"] == 2
    assert idx.search("одмор")["results"][0]["fragment"] == "član 2"


@pytest.mark.parametrize("unsafe_query", ['otkaz\" OR *', "()", "  "])
def test_user_input_never_executes_raw_fts_syntax(tmp_path, unsafe_query):
    idx = search_index(tmp_path, [chunk("179", "Послодавац може да уручи отказ уговора.")])
    if unsafe_query.strip() == "()":
        with pytest.raises(ValueError):
            idx.search(unsafe_query)
    elif not unsafe_query.strip():
        with pytest.raises(ValueError):
            idx.search(unsafe_query)
    else:
        assert isinstance(idx.search(unsafe_query)["results"], list)


def test_fastapi_routes_do_not_require_gemini(monkeypatch, tmp_path):
    idx = search_index(tmp_path, [chunk("179", "Послодавац може да уручи отказ уговора.")])
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(api, "_offline_index", lambda: idx)
    client = TestClient(api.app)
    status = client.get("/api/search/status")
    assert status.status_code == 200
    assert status.json()["requires_api_key"] is False
    result = client.post("/api/search", json={"query": "otkaz"})
    assert result.status_code == 200
    assert result.json()["results"][0]["fragment"] == "član 179"
    assert client.post("/api/search", json={"query": " ", "limit": 10}).status_code == 422
    assert client.post("/api/search", json={"query": "otkaz", "limit": 51}).status_code == 422
    assert client.post("/api/search", json={"query": "otkaz", "as_of": "not-a-date"}).status_code == 422


def test_actual_checked_in_fixture_parses_and_is_searchable(tmp_path):
    fixture = Path(__file__).parent / "fixtures/zakon_o_radu_consolidated.html"
    url = "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/skupstina/zakon/2005/24/1/reg"
    law = parse_consolidated_html(fixture.read_text(encoding="utf-8"), eli=url)
    chunks = to_chunks(law, source_id="sgrs/skupstina/zakon/2005/24/1")
    rows = []
    for item in chunks:
        row = item.model_dump(mode="json")
        row["metadata"]["law_slug"] = "zakon-o-radu"
        rows.append(row)
    assert len(rows) == 298
    idx = search_index(tmp_path, rows)
    result = idx.search("prava obaveze odgovornosti", limit=50)
    assert result["total_indexed_articles"] == 298
    assert result["results"]
    assert all(r["source_url"] == url for r in result["results"])
