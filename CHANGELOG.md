# Changelog

The version number lives in `litsearch/__init__.py` and is shown in the window title
and the About box. It is bumped with every change.

## 1.4.3 — 2026-10-27
- The credit line now reads "Created by J. Kent Morgan, Ph.D." (About box, workbook Glossary, guide, license notice, source headers). The company name, J. Kent Morgan Consulting, LLC, is unchanged. Text only; no change to how Litwell searches or runs.

## 1.4.2 — 2026-10-27
- The credit line now reads "Created by J. Kent Morgan." (About box, workbook Glossary, guide, license notice, source headers). Text only; no change to how Litwell searches or runs.

## 1.4.1 — 2026-10-27
- **AI triage finds your Ollama model by itself.** The *Ollama model* setting is now blank by default and Litwell uses an installed chat model (skipping embedding-only ones), saying which one it used in the Status box and the Search Log. A model you name is still used when it is installed; if it is not, an installed model is used instead and the Status box says so.
- The copyright holder is now J. Kent Morgan Consulting, LLC (About box, workbook Glossary, guide, license notice).

## 1.4.0 — 2026-10-27
- **Exact searches.** New *Match topic as* option: **Exact phrase** (the new default), **All words** or **Any word**. Each source gets the query in its own native syntax; Crossref and EPO, which cannot match a phrase, are checked afterwards. A search for `B2 Protein` no longer returns every paper that has "B2" somewhere and "protein" somewhere else.
- **Precision tools.** *Must also contain* and *Exclude terms* fields, a *Hide scores below* setting, and named **profiles** you can save, load and delete (two deletable examples are included, labelled "Example:").
- **Abstracts** (PubMed, Europe PMC, OpenAlex, Crossref when present, arXiv, preprint servers, EPO), **citation counts** and **open-access links**.
- **Relevance Score (0 to 100)** for every record, best first, from a published rule set; no AI and no key needed.
- **Optional AI triage** with a local Ollama model (off by default; the model name is a setting). A missing Ollama gives a one-line note and the search carries on. Nothing is sent to a cloud service.
- **One row per paper across sources:** copies found by several sources are merged and missing authors, dates, DOIs and abstracts are filled from the other copy.
- **New workbook:** Results (Relevance Score, AI Rating, AI Reason, New Since Last Run, Abstract, Open-access link, Citation count, Type, one Yes/No column per source), **Summary**, **Search Log** (every source including errors and "Skipped: no key", plus the rows each filter rule removed) and **Glossary**. Older files are upgraded automatically.
- **New Since Last Run** flag when the output file already exists.
- Fixed: USPTO searches that matched nothing in one half of the query (granted patents or pending applications) failed the whole source with "HTTP 404"; an empty result is now an empty result. A ticked USPTO or EPO source with no key is now skipped with a clear warning instead of an error.
- **Contact email** setting (blank by default, stored only in your own settings file) for the Crossref, OpenAlex and NCBI polite pool; it replaces the old use of the "ncbi_email" setting, which is carried over once.
- **Help / How-to Guide** button opens a PDF guide shipped with the app. The About box shows the credit and license.
- **Open source:** Apache License 2.0 (LICENSE, NOTICE, THIRD_PARTY_NOTICES.md), CONTRIBUTING.md, a privacy note, and a rewritten README. The macOS bundle identifier no longer names a company.

## 1.3.0 — 2026-10-26
- **Source column in Excel.** The Results sheet has a new last column, *Source*, naming the database that returned each record (for preprints, the server too, e.g. "Preprint — bioRxiv"). When a later search finds a paper that is already in the file, the extra source is added to its row (e.g. "PubMed; Crossref") instead of being lost. It is the last column so existing columns don't move; an older workbook gets the new header on its next search, and its existing rows stay blank until a search finds them again. CSV, text, Markdown, RIS and BibTeX files already recorded the source.

## 1.2.0 — 2026-10-26
- **Search several sources at once.** The Source drop-down is now a set of checkboxes: tick any number of the eight sources (or use **All / Papers only / None**) and one click of Search asks all of them at the same time. Everything goes into the one output file, a paper found by two sources is stored once, and each source gets its own row in the Search Log. If one source can't be searched (no API key, server down, rate limit), the rest still run and you are told which one failed and why. Your ticked sources are remembered.
- Command line: `--source pubmed,arxiv` (comma-separated), `--source all`, `--source papers`.
- *Max results* now applies to each source.
- Fixed: a Crossref record with no date made the whole Crossref search fail.
- Fixed: if the output file can't be written during a multi-source search, every unsaved record is kept in a single recovery file (two recovery files written in the same second could overwrite each other).

## 1.1.1 — 2026-10-06
- Automatic build pipeline: one GitHub workflow builds the Windows `.exe` and the macOS `.app` (Intel + Apple silicon) and can publish both as a GitHub Release.

## 1.1.0 — 2026-10-06
- Renamed the app from "Literature Search" to **Litwell**, with a new app icon.
- Output defaults renamed: `Litwell Results.xlsx`, "Litwell results" header in text/Markdown files.
- Fixed an intermittent macOS crash at launch ("Litwell quit unexpectedly").
- Added a GitHub Actions workflow that builds the Windows `Litwell.exe`.
- Since 1.0.0: OpenAlex, Europe PMC, arXiv, USPTO and EPO patent search, preprint servers,
  more output formats (txt, csv, md, ris, bib), continue-or-new-file choice, crash-safe saving.

## 1.0.0 — 2026-08-27
- First release: PubMed and Crossref search to a master Excel workbook.
