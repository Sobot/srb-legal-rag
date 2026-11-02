import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type OfflineSearchRequest, type OfflineSearchResult } from "../api";

const initial = {
  query: "",
  law_slug: "",
  as_of: "",
  limit: 10,
};

export default function Search() {
  const [form, setForm] = useState(initial);
  const { data: status } = useQuery({
    queryKey: ["offlineSearchStatus"],
    queryFn: api.offlineSearchStatus,
    retry: false,
  });
  const search = useMutation({
    mutationFn: (request: OfflineSearchRequest) => api.offlineSearch(request),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = form.query.trim();
    if (!query) return;
    search.mutate({
      query,
      law_slug: form.law_slug.trim() || null,
      as_of: form.as_of || null,
      limit: form.limit,
    });
  }

  return (
    <div className="h-full space-y-4 overflow-y-auto pb-8">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Knowledge Base Explorer</h2>
            <p className="text-sm text-slate-500">
              Offline pretraga članova · SQLite FTS5 / BM25 · bez LLM odgovora
            </p>
          </div>
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${
            status?.corpus_available
              ? "bg-emerald-50 text-emerald-800"
              : "bg-amber-50 text-amber-800"
          }`}>
            {status?.corpus_available ? "Local corpus ready" : "No local corpus"}
          </span>
        </div>

        {!status?.corpus_available && (
          <p className="mb-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
            Nema lokalnog <code>data/corpus/chunks.jsonl</code> fajla.
            Napravi offline fixture korpus prema dokumentaciji
            <code> docs/offline-kb-explorer.md</code>.
          </p>
        )}

        <form onSubmit={onSubmit} className="space-y-3">
          <div>
            <label htmlFor="kb-query" className="mb-1 block text-sm font-medium">
              Pitanje ili ključne reči
            </label>
            <input
              id="kb-query"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              placeholder="npr. uslovi za otkaz ugovora o radu"
              value={form.query}
              maxLength={500}
              onChange={(e) => setForm((f) => ({ ...f, query: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Law slug (opciono)</span>
              <input
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                placeholder="zakon-o-radu"
                value={form.law_slug}
                maxLength={120}
                onChange={(e) => setForm((f) => ({ ...f, law_slug: e.target.value }))}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Važi na dan (opciono)</span>
              <input
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                type="date"
                value={form.as_of}
                onChange={(e) => setForm((f) => ({ ...f, as_of: e.target.value }))}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Broj rezultata</span>
              <select
                className="w-full rounded-md border border-slate-300 px-3 py-2"
                value={form.limit}
                onChange={(e) => setForm((f) => ({ ...f, limit: Number(e.target.value) }))}
              >
                {[5, 10, 20, 50].map((n) => <option value={n} key={n}>{n}</option>)}
              </select>
            </label>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-slate-500">
              Srpska latinica se automatski transliteriše u ćirilicu.
              BM25 skor je relativna mera, ne procenat tačnosti.
            </p>
            <button
              type="submit"
              disabled={search.isPending || !form.query.trim() || !status?.corpus_available}
              className="rounded-md bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {search.isPending ? "Pretražujem…" : "Pretraži"}
            </button>
          </div>
        </form>
      </div>

      {search.isError && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          Pretraga nije uspela: {String(search.error)}
        </div>
      )}

      {search.data && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <p className="font-medium">
              {search.data.results.length} rezultata · {search.data.total_indexed_articles} indeksiranih članova
            </p>
            <span className="text-slate-500">
              {search.data.elapsed_ms} ms · BM25 (offline)
            </span>
          </div>
          {search.data.results.length === 0 && (
            <p className="rounded-lg border border-slate-200 p-4 text-sm text-slate-600">
              Nema pogodaka. Probaj kraći upit ili ukloni filter zakona/datuma.
              Pretraga još nema semantičko prepoznavanje sinonima.
            </p>
          )}
          {search.data.results.map((item) => (
            <ResultCard key={item.chunk_id} item={item} />
          ))}
          {form.as_of && (
            <p className="text-xs text-amber-800">
              Istorijska pokrivenost zavisi od verzija koje postoje u učitanom korpusu.
              Filter datuma ne garantuje rekonstrukciju svih ranijih formulacija članova.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ResultCard({ item }: { item: OfflineSearchResult }) {
  const [expanded, setExpanded] = useState(false);
  const text = expanded ? item.text : item.text.slice(0, 420);
  const truncated = !expanded && item.text.length > 420;

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-xs text-slate-500">#{item.rank} · {item.law_slug}</div>
          <h3 className="text-sm font-semibold text-slate-900">
            {item.source_title} — {item.fragment}
          </h3>
        </div>
        <span className="rounded-md bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700">
          BM25 {item.score.toFixed(4)}
        </span>
      </div>

      <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
        {text}{truncated ? "…" : ""}
      </p>

      {item.text.length > 420 && (
        <button
          type="button"
          className="mt-2 text-xs font-medium text-blue-700 hover:underline"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Prikaži manje" : "Pročitaj ceo član"}
        </button>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-100 pt-3 text-xs text-slate-500">
        <span>Verzija: {item.version || "nije navedena"}</span>
        <span>Važi od: {item.valid_from || "nepoznato"}</span>
        <span>Važi do: {item.valid_to || "nije navedeno"}</span>
        {item.repealed && <span className="font-medium text-amber-700">Brisan/ukinut član</span>}
        {item.source_url ? (
          <a href={item.source_url} target="_blank" rel="noopener noreferrer"
            className="font-medium text-blue-700 hover:underline">
            Zvanični ELI izvor ↗
          </a>
        ) : <span>Bez ELI linka</span>}
      </div>
      <p className="mt-1 break-all font-mono text-[10px] text-slate-400">
        {item.chunk_id}
      </p>
    </article>
  );
}
