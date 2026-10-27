# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Output dispatch: choose the writer by the output file's extension.

    .xlsx  Excel workbook (Results + Search Log sheets, clickable links)
    .csv   comma-separated values, one row per record
    .txt   plain readable list
    .md    Markdown table
    .ris   RIS — imports into EndNote / Zotero / Mendeley
    .bib   BibTeX — for LaTeX / reference managers

Every format skips duplicates on write (by DOI, else normalized title), the
same rule the Excel writer uses.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Set, Tuple

from . import excel_writer
from .models import Article, SearchParams, make_dedupe_key

# extension -> human label (drives the Save dialog and validation)
FORMATS: Dict[str, str] = {
    ".xlsx": "Excel workbook",
    ".csv": "CSV (spreadsheet)",
    ".txt": "Plain text",
    ".md": "Markdown",
    ".ris": "RIS (EndNote / Zotero / Mendeley)",
    ".bib": "BibTeX",
}

_CSV_HEADER = [
    "Title", "Authors", "Journal", "Date", "Link", "DOI",
    "Source", "Search Date", "Search Terms",
]
_TXT_SEP = "-" * 70


def append_results(
    path_str: str,
    articles: Iterable[Article],
    params: SearchParams,
    *,
    total_found: int,
    fetched: int,
) -> Tuple[int, int]:
    """Append new records to the output file. Returns (added, skipped)."""
    path = Path(path_str).expanduser()
    ext = path.suffix.lower()
    if ext == ".xlsx" or ext not in FORMATS:
        return excel_writer.append_results(
            str(path), articles, params, total_found=total_found, fetched=fetched
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = _TEXT_WRITERS[ext]
    existing = _read_keys(path, ext)
    run_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    terms = params.summary()

    fresh: List[Article] = []
    skipped = 0
    for art in articles:
        key = art.dedupe_key() or f"row::{id(art)}"
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        fresh.append(art)

    if fresh:
        chunk = writer(fresh, run_at, terms, new_file=not path.exists())
        _append_text(path, chunk)
    return len(fresh), skipped


def count_entries(path_str: str) -> int:
    """Roughly how many records the output file already holds (0 if new)."""
    path = Path(path_str).expanduser()
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return excel_writer.count_entries(str(path))
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    if ext == ".ris":
        return len(re.findall(r"(?m)^TY  - ", text))
    if ext == ".bib":
        return len(re.findall(r"(?m)^@\w+\s*\{", text))
    if ext == ".md":
        return max(0, sum(1 for l in text.splitlines() if l.startswith("| ")) - 1)
    if ext == ".csv":
        try:
            return max(0, sum(1 for _ in csv.reader(io.StringIO(text))) - 1)
        except csv.Error:
            return max(0, len(text.splitlines()) - 1)
    # .txt: one separator per record, plus one under the file header
    seps = sum(1 for l in text.splitlines() if l == _TXT_SEP)
    # (older files carry the app's previous name in the header)
    has_header = text.startswith(("Litwell results", "Literature Search results"))
    return max(0, seps - (1 if has_header else 0))


# --------------------------------------------------------------------------
# reading existing dedupe keys
# --------------------------------------------------------------------------
def _read_keys(path: Path, ext: str) -> Set[str]:
    keys: Set[str] = set()
    if not path.exists():
        return keys
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return keys

    if ext == ".csv":
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                k = make_dedupe_key(
                    (row.get("Title") or ""), (row.get("DOI") or "")
                )
                if k:
                    keys.add(k)
            return keys
        except csv.Error:
            pass

    # generic: pull DOIs and titles out of the raw text
    for m in re.finditer(r"10\.\d{4,9}/[^\s\"'<>|)}\]]+", text):
        keys.add(m.group(0).strip().lower().rstrip(".,;"))
    title_pat = {
        ".txt": r"(?m)^\S.*$",              # first line of each block-ish
        ".md": r"(?m)^\|\s*(.+?)\s*\|",
        ".ris": r"(?m)^TI  - (.+)$",
        ".bib": r"(?m)title\s*=\s*[{\"](.+?)[}\"]",
    }.get(ext)
    if title_pat:
        for m in re.finditer(title_pat, text):
            raw = m.group(1) if m.groups() else m.group(0)
            k = make_dedupe_key(raw, "")
            if k:
                keys.add(k)
    return keys


def _append_text(path: Path, chunk: str) -> None:
    try:
        with open(path, "a", encoding="utf-8", newline="") as fh:
            fh.write(chunk)
    except PermissionError as exc:
        raise RuntimeError(
            f"Could not write to '{path.name}' — it may be open in another "
            f"program. Close it and search again."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Could not write to '{path.name}': {exc}") from exc


# --------------------------------------------------------------------------
# per-format record writers  (return the text to append)
# --------------------------------------------------------------------------
def _w_csv(arts: List[Article], run_at: str, terms: str, *, new_file: bool) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    if new_file:
        w.writerow(_CSV_HEADER)
    for a in arts:
        w.writerow([
            a.title, a.authors_str, a.journal, a.date, a.link, a.doi,
            a.source, run_at, terms,
        ])
    return buf.getvalue()


def _w_txt(arts: List[Article], run_at: str, terms: str, *, new_file: bool) -> str:
    out: List[str] = []
    if new_file:
        out.append(f"Litwell results\n{_TXT_SEP}\n")
    for a in arts:
        out.append(a.title or "(untitled)")
        if a.authors_str:
            out.append(f"    Authors: {a.authors_str}")
        loc = ", ".join(x for x in (a.journal, a.date) if x)
        if loc:
            out.append(f"    {loc}")
        if a.doi:
            out.append(f"    DOI: {a.doi}")
        if a.link:
            out.append(f"    Link: {a.link}")
        out.append(f"    Source: {a.source or '?'} | Retrieved: {run_at}"
                   + (f" | Search: {terms}" if terms else ""))
        out.append(_TXT_SEP)
    return "\n".join(out) + "\n"


def _md_cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def _w_md(arts: List[Article], run_at: str, terms: str, *, new_file: bool) -> str:
    out: List[str] = []
    if new_file:
        out.append("# Litwell results\n")
        out.append("| Title | Authors | Journal | Date | DOI | Link | Source | Retrieved | Search |")
        out.append("|---|---|---|---|---|---|---|---|---|")
    for a in arts:
        link = f"[link]({a.link})" if a.link else ""
        out.append(
            "| " + " | ".join(_md_cell(x) for x in (
                a.title, a.authors_str, a.journal, a.date, a.doi, link,
                a.source, run_at, terms,
            )) + " |"
        )
    return "\n".join(out) + "\n"


def _w_ris(arts: List[Article], run_at: str, terms: str, *, new_file: bool) -> str:
    out: List[str] = []
    for a in arts:
        ty = "PAT" if "patent" in (a.source or "").lower() else "JOUR"
        out.append(f"TY  - {ty}")
        if a.title:
            out.append(f"TI  - {a.title}")
        for name in a.authors:
            out.append(f"AU  - {name}")
        if a.journal:
            out.append(f"JO  - {a.journal}")
        year = a.date[:4]
        if year.isdigit():
            out.append(f"PY  - {year}")
        if a.date:
            out.append(f"DA  - {a.date.replace('-', '/')}")
        if a.doi:
            out.append(f"DO  - {a.doi}")
        if a.link:
            out.append(f"UR  - {a.link}")
        out.append(f"DP  - {a.source}")
        if terms:
            out.append(f"N1  - Retrieved {run_at}; search: {terms}")
        out.append("ER  - ")
        out.append("")
    return "\n".join(out) + "\n"


def _bib_key(a: Article, used: Set[str]) -> str:
    first = a.authors[0].split(",")[0] if a.authors else (a.source or "ref")
    first = re.sub(r"[^A-Za-z]", "", first).lower() or "ref"
    year = a.date[:4] if a.date[:4].isdigit() else "nd"
    word = ""
    for tok in re.findall(r"[A-Za-z]+", a.title or ""):
        if tok.lower() not in {"the", "a", "an", "of", "and", "for", "on", "in"}:
            word = tok.lower()
            break
    base = f"{first}{year}{word}"
    key, i = base, 1
    while key in used:
        i += 1
        key = f"{base}{i}"
    used.add(key)
    return key


def _bib_field(name: str, value: str) -> str:
    value = value.replace("{", "(").replace("}", ")")
    return f"  {name} = {{{value}}},\n"


def _w_bibtex(arts: List[Article], run_at: str, terms: str, *, new_file: bool) -> str:
    out: List[str] = []
    used: Set[str] = set()
    for a in arts:
        etype = "patent" if "patent" in (a.source or "").lower() else "article"
        key = _bib_key(a, used)
        out.append(f"@{etype}{{{key},")
        if a.title:
            out.append(_bib_field("title", a.title))
        if a.authors:
            out.append(_bib_field("author", " and ".join(a.authors)))
        if a.journal:
            out.append(_bib_field("journal", a.journal))
        if a.date[:4].isdigit():
            out.append(_bib_field("year", a.date[:4]))
        if a.doi:
            out.append(_bib_field("doi", a.doi))
        if a.link:
            out.append(_bib_field("url", a.link))
        note = f"Source: {a.source}; retrieved {run_at}"
        if terms:
            note += f"; search: {terms}"
        out.append(_bib_field("note", note))
        out.append("}\n")
    return "".join(
        p if p.endswith("\n") else p + "\n" for p in out
    ) + "\n"


_TEXT_WRITERS: Dict[str, Callable[..., str]] = {
    ".csv": _w_csv,
    ".txt": _w_txt,
    ".md": _w_md,
    ".ris": _w_ris,
    ".bib": _w_bibtex,
}
