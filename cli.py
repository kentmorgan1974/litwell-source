#!/usr/bin/env python3
# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Command-line front end — used to verify search + Excel export before the GUI.

Examples
--------
    python cli.py --keyword "CRISPR gene editing" --start 2023 --end 2024
    python cli.py --source crossref --author "Yann LeCun" --keyword "deep learning"
    python cli.py --source pubmed,arxiv,openalex --keyword "CRISPR"   (several at once)
    python cli.py --source all --keyword "CRISPR"
    python cli.py --keyword "B2 protein" --match exact --must "protein,viral" --exclude "riboflavin,HER2"
    python cli.py --profile "Example: Ambiguous abbreviation" --source all
    python cli.py --set-excel ~/Desktop/literature_master.xlsx
"""

from __future__ import annotations

import argparse
import sys

from litsearch import profiles
from litsearch.config import CONFIG_PATH, load_config, save_config, selected_sources
from litsearch.models import SearchParams
from litsearch.search import SOURCES, run_multi_search


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Search scientific literature -> output file (.xlsx/.csv/.txt/.md/.ris/.bib).")
    p.add_argument("--keyword", default="")
    p.add_argument("--author", default="")
    p.add_argument("--title", default="")
    p.add_argument("--journal", default="")
    p.add_argument("--start", default="", help="Start date: YYYY, YYYY-MM, or YYYY-MM-DD")
    p.add_argument("--end", default="", help="End date: YYYY, YYYY-MM, or YYYY-MM-DD")
    p.add_argument(
        "--source",
        default=None,
        help="Source to search: pubmed, crossref, openalex, europepmc, arxiv, "
             "preprints, patents, epo. Several at once: comma-separated "
             "(--source pubmed,arxiv); every source: --source all; every paper "
             "source (no patents): --source papers",
    )
    p.add_argument("--max", type=int, default=None, help="Max results to fetch (per source)")
    p.add_argument("--match", choices=("exact", "all", "any"), default=None,
                   help="How the keyword is matched: exact phrase (default), all words, or any word")
    p.add_argument("--must", default=None, metavar="TERMS",
                   help="Must also contain: at least one of these comma-separated terms in the title or abstract")
    p.add_argument("--exclude", default=None, metavar="TERMS",
                   help="Exclude terms (comma-separated): in the title or journal removes the record")
    p.add_argument("--min-score", type=int, default=None, help="Drop records scoring below this (0 to 100)")
    p.add_argument("--profile", default=None, metavar="NAME", help="Use a saved profile's fields (see --list-profiles)")
    p.add_argument("--list-profiles", action="store_true", help="List saved profiles and exit")
    p.add_argument("--ai", action="store_true", help="Rate results with a local Ollama model (optional)")
    p.add_argument("--set-contact-email", metavar="EMAIL",
                   help="Save your contact email (Crossref / OpenAlex / NCBI polite pool) and exit")
    p.add_argument("--set-excel", metavar="PATH", help="Save the output file path to config and exit")
    p.add_argument("--show-config", action="store_true", help="Print current config and exit")
    p.add_argument("--check-dupes", action="store_true",
                   help="List duplicate rows in the .xlsx output file and exit")
    p.add_argument("--dedupe", action="store_true",
                   help="Remove duplicate rows from the .xlsx output file (backup first) and exit")
    p.add_argument("--set-patent-key", metavar="KEY",
                   help="Save your USPTO (data.uspto.gov) API key to config and exit")
    p.add_argument("--set-openalex-key", metavar="KEY",
                   help="Save your (free, optional) OpenAlex API key to config and exit")
    p.add_argument("--set-epo-key", nargs=2, metavar=("KEY", "SECRET"),
                   help="Save your EPO OPS consumer key + secret to config and exit")
    args = p.parse_args(argv)

    cfg = load_config()
    if profiles.seed_examples(cfg):
        save_config(cfg)

    if args.list_profiles:
        for name in profiles.names(cfg):
            print(name)
        return 0

    if args.set_contact_email is not None:
        cfg["contact_email"] = args.set_contact_email.strip()
        save_config(cfg)
        print("Saved contact email." if cfg["contact_email"] else "Cleared contact email.")
        return 0

    if args.set_patent_key:
        cfg["uspto_api_key"] = args.set_patent_key
        save_config(cfg)
        print("Saved USPTO API key.")
        return 0

    if args.set_openalex_key:
        cfg["openalex_api_key"] = args.set_openalex_key
        save_config(cfg)
        print("Saved OpenAlex API key.")
        return 0

    if args.set_epo_key:
        cfg["epo_ops_key"], cfg["epo_ops_secret"] = args.set_epo_key
        save_config(cfg)
        print("Saved EPO OPS key + secret.")
        return 0

    if args.show_config:
        print(f"Config file: {CONFIG_PATH}")
        for k, v in cfg.items():
            if v and any(w in k for w in ("key", "secret", "email")):
                v = "(set)"                 # never print keys or addresses
            print(f"  {k}: {v!r}")
        return 0

    if args.check_dupes or args.dedupe:
        from litsearch import excel_writer

        excel_path = (cfg.get("excel_path") or "").strip()
        if not excel_path:
            print("No output path set. Use --set-excel PATH first.", file=sys.stderr)
            return 1
        try:
            dupes = excel_writer.review_duplicates(excel_path)
        except (RuntimeError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        if not dupes:
            print("No duplicate rows found.")
            return 0
        print(f"{len(dupes)} duplicate row(s):")
        for title, row in dupes:
            print(f"  row {row}: {title[:90]}")
        if args.dedupe:
            result = excel_writer.remove_duplicates(excel_path)
            print(f"\nRemoved {result['removed']} row(s). Backup: {result['backup']}")
        else:
            print("\nRun again with --dedupe to remove them.")
        return 0

    if args.set_excel:
        cfg["excel_path"] = args.set_excel
        save_config(cfg)
        print(f"Saved output file: {args.set_excel}")
        return 0

    prof = {}
    if args.profile:
        prof = profiles.get(cfg, args.profile)
        if not prof:
            p.error(f"no profile called {args.profile!r} (see --list-profiles)")

    if args.source:
        spec = args.source.strip().lower()
        if spec == "all":
            sources = list(SOURCES)
        elif spec == "papers":
            sources = [k for k in SOURCES if k not in ("patents", "epo")]
        else:
            sources = [x.strip() for x in spec.split(",") if x.strip()]
    elif prof.get("sources"):
        sources = [k for k in prof["sources"] if k in SOURCES]
    else:
        sources = selected_sources(cfg, SOURCES)
    bad = [x for x in sources if x not in SOURCES]
    if bad:
        p.error(f"unknown source(s): {', '.join(bad)} (choose from: {', '.join(SOURCES)}, all, papers)")

    def pick(cli, key, default=""):
        return cli if cli is not None else (prof.get(key) if prof.get(key) not in (None, "") else default)

    params = SearchParams(
        keyword=args.keyword or prof.get("keyword", ""),
        author=args.author,
        title=args.title,
        journal=args.journal,
        date_start=args.start,
        date_end=args.end,
        source=sources[0],
        max_results=(args.max or int(cfg.get("max_results", 100))),
        match_mode=pick(args.match, "match_mode", "exact"),
        must_terms=pick(args.must, "must_terms"),
        exclude_terms=pick(args.exclude, "exclude_terms"),
        min_score=int(pick(args.min_score, "min_score", 0) or 0),
        profile_name=args.profile or "",
        profile_description=prof.get("description", ""),
        boost_terms=prof.get("boost_terms", ""),
    )
    if args.ai:
        cfg["ai_enabled"] = True       # for this run only (not saved)
    return _run_many(params, sources, cfg)


def _run_many(params, sources, cfg) -> int:
    multi = run_multi_search(params, sources, cfg, progress=lambda m: print(f"[..] {m}"))
    if multi.error:
        print(f"\nERROR: {multi.error}", file=sys.stderr)
        return 1
    print("\n--- per source (max results apply to each source) ---")
    for r in multi.results:
        o = r.outcome
        if o.ok:
            print(f"  {r.name:<26} matched {o.total_found}, fetched {o.fetched}, "
                  f"removed {o.removed}, new {o.added}")
        elif o.skipped:
            print(f"  {r.name:<26} SKIPPED: {o.error.splitlines()[0]}")
        else:
            print(f"  {r.name:<26} FAILED: {o.error.splitlines()[0]}")
    if multi.rules:
        print("\n--- filters ---")
        for rule, n in multi.rules:
            print(f"  {rule}: {n} removed")
    for note in multi.notes:
        print(f"\nNote: {note}")
    print(f"\nKept {multi.kept} record(s): {multi.new_rows} new, {multi.known_rows} already in the file "
          f"(a paper found by two sources is stored once). File now holds {multi.total_rows}.")
    print(f"Output file: {cfg['excel_path']}")
    return 0 if multi.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
