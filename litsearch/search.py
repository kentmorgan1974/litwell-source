# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""High-level search orchestration used by both the CLI and the GUI."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import inspect
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Sequence

from . import arxiv, crossref, epo, europepmc, openalex, patents, preprints, pubmed
from .http_client import NetworkError
from . import ai, excel_writer, output, records
from .models import Article, MultiOutcome, SearchOutcome, SearchParams, SourceResult

ProgressFn = Callable[[str], None]

# key -> (display name, module). The GUI dropdown and CLI --source use the keys.
SOURCES = {
    "pubmed": ("PubMed", pubmed),
    "crossref": ("Crossref", crossref),
    "openalex": ("OpenAlex", openalex),
    "europepmc": ("Europe PMC", europepmc),
    "arxiv": ("arXiv", arxiv),
    "preprints": ("Preprint servers", preprints),
    "patents": ("USPTO Patents", patents),
    "epo": ("EPO / Worldwide Patents", epo),
}


def key_problem(source: str, cfg: Dict[str, str]) -> str:
    """A one-line reason a source cannot be searched (missing free key), or ''."""
    if source == "patents":
        if not (cfg.get("uspto_api_key") or cfg.get("patentsview_api_key") or "").strip():
            return ("no USPTO API key. It is free: sign in at data.uspto.gov, copy your key, "
                    "and paste it under File > API Keys & Contact.")
    if source == "epo":
        if not ((cfg.get("epo_ops_key") or "").strip() and (cfg.get("epo_ops_secret") or "").strip()):
            return ("no EPO key. It is free: register at developers.epo.org, create an app, "
                    "and paste the Consumer Key and Secret under File > API Keys & Contact.")
    return ""


def _fetch(source: str, params: SearchParams, cfg: Dict[str, str], say: ProgressFn):
    """Ask one source for results. Returns (articles, total); raises on failure."""
    display_name, module = SOURCES[source]
    say(f"Searching {display_name}…")
    if "say" in inspect.signature(module.search).parameters:
        return module.search(params, cfg, say=say)
    return module.search(params, cfg)


def _fetch_safely(source: str, params: SearchParams, cfg: Dict[str, str], say: ProgressFn):
    """_fetch with every failure turned into a message. Returns (articles, total, error)."""
    try:
        articles, total = _fetch(source, params, cfg, say)
        return articles, total, ""
    except (NetworkError, ValueError) as exc:
        return [], 0, str(exc)
    except Exception as exc:  # pragma: no cover - last-resort safety net
        return [], 0, f"Unexpected error during search: {exc}"


def run_search(
    params: SearchParams,
    cfg: Dict[str, str],
    progress: Optional[ProgressFn] = None,
) -> SearchOutcome:
    """Search the one source named in ``params.source`` (the older single-source API)."""
    multi = run_multi_search(params, [params.source], cfg, progress)
    if multi.results:
        return multi.results[0].outcome
    return SearchOutcome(params=params, error=multi.error or "Nothing was searched.")


# Several sources are asked at once, but never more than this many at a time.
MAX_PARALLEL_SOURCES = 4


def run_multi_search(
    params: SearchParams,
    sources: Sequence[str],
    cfg: Dict[str, str],
    progress: Optional[ProgressFn] = None,
) -> MultiOutcome:
    """Search several sources with the same fields and save the result.

    1. The sources are queried in parallel (different servers). A source that
       fails or has no key does not stop the others.
    2. Copies of the same paper (same DOI, else same title) are merged into one
       record and gaps are filled from the other copies.
    3. Crossref results are checked against the keyword (it cannot do phrases).
    4. "Must also contain" and "Exclude terms" are applied; each rule's count is
       kept for the Search Log.
    5. Every record gets a Relevance Score; optional local AI triage rates them.
    6. The output file is rewritten: Results (best first), Summary, Search Log,
       Glossary. Other formats (csv, txt, md, ris, bib) get the same records.

    Never raises.
    """
    say = progress or (lambda _msg: None)
    multi = MultiOutcome(params=params)

    keys: List[str] = []
    for k in sources:
        k = k.lower().strip()
        if k and k not in keys:
            keys.append(k)
    unknown = [k for k in keys if k not in SOURCES]
    if unknown:
        multi.error = f"Unknown source(s): {', '.join(unknown)}."
        return multi
    if not keys:
        multi.error = "Tick at least one source to search."
        return multi
    if params.is_empty():
        multi.error = "Enter at least one search field before searching."
        return multi
    excel_path = (cfg.get("excel_path") or "").strip()
    if not excel_path:
        multi.error = "Set an output file first (File → Set Output File)."
        return multi

    run_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 1. fetch ------------------------------------------------------
    def job(key: str):
        name = SOURCES[key][0]
        p = dataclasses.replace(params, source=key)
        problem = key_problem(key, cfg)
        if problem:
            say(f"WARNING: {name} is ticked but has {problem}")
            return key, p, ([], 0, "Skipped: " + problem, True)
        arts, total, err = _fetch_safely(
            key, p, cfg, lambda m, _n=name: say(m if m.startswith(_n) else f"{_n}: {m}")
        )
        return key, p, (arts, total, err, False)

    if len(keys) == 1:
        fetched = [job(keys[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_SOURCES, len(keys))) as pool:
            fetched = list(pool.map(job, keys))      # keeps the order of ``keys``

    per_source: List[tuple] = []                     # (key, kept records)
    for key, p, (arts, total, err, skipped) in fetched:
        name = SOURCES[key][0]
        outcome = SearchOutcome(params=p, total_found=total, fetched=len(arts),
                                error=err, skipped=skipped)
        multi.results.append(SourceResult(key, name, outcome))
        if err:
            if not skipped:
                say(f"{name}: skipped — {err.splitlines()[0]}")
            continue
        arts, dropped = records.enforce(arts, params, key)
        outcome.removed += dropped
        if dropped:
            say(f"{name}: {dropped} record(s) did not contain the phrase and were removed.")
        for a in arts:
            if not a.source:
                a.source = name
            a.search_date, a.search_terms = run_at, params.summary()
        outcome.articles = arts
        say(f"{name}: retrieved {outcome.fetched} record(s) (of {total} matched).")
        per_source.append((key, arts))

    if not per_source:
        # Nothing to write, but the failures still belong in the log of an existing file.
        _write_log_only(multi, excel_path, run_at, say)
        return multi

    # ---- 2. merge copies of the same paper -----------------------------
    merged = records.merge(per_source)
    multi.merged_copies = sum(len(a) for _k, a in per_source) - len(merged)
    if multi.merged_copies:
        say(f"Merged {multi.merged_copies} copy(ies) of papers found by more than one source.")

    # ---- 3. filters -----------------------------------------------------
    before = {id(a): a for a in merged}
    kept, rules = records.filter_records(merged, params)
    records.score_all(kept, params)
    if params.min_score > 0:
        low = [a for a in kept if (a.score or 0) < params.min_score]
        rules.append((f"Minimum score: below {params.min_score}", len(low)))
        kept = [a for a in kept if (a.score or 0) >= params.min_score]
    multi.rules = rules
    kept_ids = {id(a) for a in kept}
    for key, _arts in per_source:
        out = next(r.outcome for r in multi.results if r.key == key)
        out.removed += sum(1 for a in before.values()
                           if key in a.sources and id(a) not in kept_ids)
    multi.kept = len(kept)
    for rule, n in rules:
        if n:
            say(f"Filter — {rule}: {n} record(s) removed.")
    records.sort_best_first(kept)

    # ---- 4. optional AI triage ------------------------------------------
    if cfg.get("ai_enabled") and kept:
        wanted = params.profile_description.strip() or params.summary()
        tri = ai.triage(kept, wanted, cfg, say)
        if tri.note:
            multi.notes.append(tri.note)
            say(tri.note)
        if tri.model:
            multi.ai_model = f"{tri.model} ({tri.how}); rated {tri.rated} record(s)"

    # ---- 5. write --------------------------------------------------------
    ext = Path(excel_path).expanduser().suffix.lower()
    fresh_keys = None
    try:
        if ext == ".xlsx" or ext not in output.FORMATS:
            try:
                existing, old_log, _had = excel_writer.load_existing(excel_path)
            except excel_writer.DamagedWorkbook as exc:
                say(str(exc))
                existing, old_log = [], []
            known_before = records.Merger()
            for a in existing:
                known_before.add(a)
            added, known = excel_writer.save_run(
                excel_path, existing, old_log, kept,
                lambda: _log_rows(multi, kept, run_at),
                {"run_at": run_at, "removed": multi.removed},
            )
            multi.new_rows, multi.known_rows = added, known
            multi.total_rows = len(known_before.items) + added
        else:
            added, known, fresh_keys = _write_text(excel_path, kept, params)
            multi.new_rows, multi.known_rows = added, known
            multi.total_rows = output.count_entries(excel_path)
    except (RuntimeError, OSError) as exc:
        msg = _with_recovery(str(exc), excel_path, kept, say)
        for r in multi.results:
            if r.outcome.ok:
                r.outcome.error = msg
        return multi

    # ---- per-source numbers ---------------------------------------------
    for key, _arts in per_source:
        out = next(r.outcome for r in multi.results if r.key == key)
        mine = [a for a in kept if key in a.sources]
        if fresh_keys is not None:
            new_n = sum(1 for a in mine if (a.dedupe_key() or f"row::{id(a)}") in fresh_keys)
        else:
            new_n = sum(1 for a in mine if a.is_new is not False)
        out.added = new_n
        out.skipped_duplicates = len(mine) - new_n
    return multi


def _log_rows(multi: MultiOutcome, kept: List[Article], run_at: str) -> List[list]:
    p = multi.params
    base = [p.keyword, p.mode_label() if p.keyword.strip() else "", p.must_terms, p.exclude_terms,
            p.author, p.title, p.journal, p.date_start, p.date_end]
    rows = []
    for r in multi.results:
        o = r.outcome
        mine = [a for a in kept if r.key in a.sources]
        new_n = sum(1 for a in mine if a.is_new is not False)
        rows.append([run_at, r.name, o.status] + base +
                    [o.total_found, o.fetched, o.removed,
                     new_n if o.ok else None, (len(mine) - new_n) if o.ok else None,
                     (o.error if not o.ok else "")[:500]])
    for rule, n in multi.rules:
        rows.append([run_at, "(all sources)", rule] + base + [None, None, n, None, None,
                     "Rows removed by this rule."])
    if multi.ai_model:
        rows.append([run_at, "(all sources)", "AI triage"] + base + [None, None, None, None, None,
                     "Local model: " + multi.ai_model])
    if multi.merged_copies:
        rows.append([run_at, "(all sources)", "Merged copies of the same paper"] + base +
                    [None, None, None, None, None, f"{multi.merged_copies} copies folded into one row each."])
    return rows


def _write_log_only(multi: MultiOutcome, excel_path: str, run_at: str, say) -> None:
    """Every source failed: still record the attempt in an existing workbook's log."""
    if Path(excel_path).expanduser().suffix.lower() not in (".xlsx", ""):
        return
    try:
        existing, old_log, had = excel_writer.load_existing(excel_path)
        if not had:
            return
        excel_writer.save_run(excel_path, existing, old_log, [], _log_rows(multi, [], run_at),
                              {"run_at": run_at, "removed": 0})
    except (RuntimeError, OSError):
        pass


def _write_text(path: str, kept: List[Article], params: SearchParams):
    """csv / txt / md / ris / bib: append the records not already in the file."""
    p = Path(path).expanduser()
    ext = p.suffix.lower()
    existing = output._read_keys(p, ext)
    for a in kept:
        a.source = "; ".join(SOURCES[k][0] for k in a.sources if k in SOURCES) or a.source
    fresh = {(a.dedupe_key() or f"row::{id(a)}") for a in kept} - existing
    added, skipped = output.append_results(path, kept, params, total_found=len(kept), fetched=len(kept))
    return added, skipped, fresh


def _with_recovery(message: str, target: str, articles, say) -> str:
    """On a write failure, dump the fetched records to a sibling CSV so the
    search is never lost, and fold that into the error message."""
    import csv

    try:
        t = Path(target).expanduser()
        stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        rec = t.with_name(f"{t.stem} (recovered {stamp}).csv")
        n = 1
        while rec.exists():      # never overwrite an earlier recovery file
            n += 1
            rec = t.with_name(f"{t.stem} (recovered {stamp} {n}).csv")
        with open(rec, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Relevance Score", "Title", "Authors", "Journal", "Date", "Link",
                        "DOI", "Source", "Abstract"])
            for a in articles:
                w.writerow([a.score, a.title, a.authors_str, a.journal, a.date, a.link,
                            a.doi, a.source or "; ".join(a.sources), a.abstract])
        say(f"Results saved to '{rec.name}' so nothing is lost.")
        return f"{message}\n\nThe {len(articles)} results were saved to '{rec.name}' instead."
    except OSError:
        return message
