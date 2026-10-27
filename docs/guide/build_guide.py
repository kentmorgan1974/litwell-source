# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Builds the Litwell How-to Guide: docs/guide/Litwell_How_To_Guide.html and, with a
Chromium-based browser installed (Edge, Chrome or Brave), docs/Litwell_How_To_Guide.pdf.

    python docs/guide/build_guide.py

The look follows the Snapback guide (numbered sections, one entry per control with
"Valid values / Default / Use it when / Skip it when / Related"). The worked example
numbers come from docs/guide/b2_example.json, written by the final test run.
"""

from __future__ import annotations

import base64
import datetime as _dt
import html
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from litsearch import CREDIT, LICENSE_LINE, __version__  # noqa: E402
from litsearch.excel_writer import GLOSSARY  # noqa: E402

NAVY = "#001F5B"
BROWSERS = [
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def esc(t: str) -> str:
    return html.escape(t, quote=False)


def inline(t: str) -> str:
    """**bold** and `code` inside a sentence; everything else is escaped."""
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)", t):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(f"<strong>{esc(part[2:-2])}</strong>")
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append(f"<em>{esc(part[1:-1])}</em>")
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append(f"<code>{esc(part[1:-1])}</code>")
        else:
            out.append(esc(part))
    return "".join(out)


def p(t: str) -> str:
    return f"<p>{inline(t)}</p>"


def steps(items) -> str:
    return "".join(f'<p class="step"><strong>{i}.</strong> {inline(t)}</p>' for i, t in enumerate(items, 1))


def bullets(items) -> str:
    return "<ul>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ul>"


def table(head, rows, widths=None) -> str:
    th = "".join(f"<th>{inline(h)}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{inline(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'


def field(name, what, valid, default, use, skip, related="") -> str:
    out = [f"<h4>{esc(name)}</h4>", p(what), "<ul>",
           f"<li><strong>Valid values:</strong> {inline(valid)}</li>",
           f"<li><strong>Default:</strong> {inline(default)}</li>"]
    out.append("<li><strong>Use it when:</strong></li><ul>" + "".join(f"<li>{inline(u)}</li>" for u in use) + "</ul>")
    if skip:
        out.append("<li><strong>Skip it when:</strong></li><ul>" + "".join(f"<li>{inline(u)}</li>" for u in skip) + "</ul>")
    if related:
        out.append(f"<li><strong>Related:</strong> {inline(related)}</li>")
    out.append("</ul>")
    return "".join(out)


def callout(t: str) -> str:
    return f'<div class="note">{inline(t)}</div>'


def sections(ex: dict):
    """(title, html) for each numbered section."""
    S = []

    S.append(("What Litwell does", "".join([
        p("Litwell searches the scientific literature, preprints and patents for you, all at once, and saves what it finds to one tidy Excel workbook. You type a topic, tick the places to look, and click Search. Litwell asks every source, removes duplicates, filters out the obvious misses, scores what is left from 0 to 100, and sorts the best matches to the top."),
        p("It was built for the common problem of a search that returns far too much: an abbreviation that means several things (B2 can be a viral protein, vitamin B2, or a breast-cancer receptor), a phrase that is split across unrelated words, or a topic spread over papers, preprints and patents. Litwell searches phrases as phrases, lets you say what must and must not appear, and shows you exactly what every source and every filter did."),
        p("Litwell is free and open source, runs on your own computer, needs no account, and sends your searches only to the public sources you tick. It is a search tool, not a judge of quality: a high score means a record matches your words well, not that the science is sound."),
    ])))

    S.append(("Quick start: your first search in 5 steps", "".join([
        steps([
            "Open Litwell. Choose **File, Set Output File** and pick where your workbook should be saved (for example `My Search.xlsx`).",
            "Type a **Topic / keyword**, for example `double-stranded RNA`. Leave the match mode on **Exact phrase**.",
            "Tick the sources you want. **Papers only** is a good start: it skips the two patent sources, which need free keys (see section 5).",
            "Click **Search**. The Status box shows each source as it answers, then a summary: what each source returned, what your filters removed, and the best matches.",
            "Click **Open File**. The Results sheet is sorted with the best matches first; read the Summary and Search Log sheets to see what happened.",
        ]),
        p("Search again with a different topic into the same file and Litwell merges the new records in, marks which rows are new, and never duplicates a paper."),
        callout("Everything in Litwell is free. The only keys it ever asks for are free ones (USPTO and EPO for patents; NCBI and OpenAlex are optional), and none is needed to search papers and preprints."),
    ])))

    fields = [
        field("Topic / keyword", "The words you are looking for. With the default match mode this is searched as one exact phrase in titles and abstracts.",
              "Any text. Do not add quotes or AND/OR yourself; use the match mode instead.", "Empty",
              ["You know the subject: a protein, a technique, a disease, a technology."],
              ["You only want a particular author or journal; leave it empty and use those boxes."], "Match topic as, Must also contain, Exclude terms"),
        field("Author", "Restricts the search to papers by a person (or, for patents, an inventor).",
              "A name such as `Smith J` or `Marie Curie`.", "Empty",
              ["You want everything by one researcher, or a topic by one group."],
              ["Searching the preprint source on its own: one of its backends (OSF) has no author search and is skipped."], "Journal"),
        field("Title contains", "Words that must be in the title, searched as a phrase.",
              "Any text.", "Empty",
              ["The topic is common and you want only papers that are really about it, which shows in the title."],
              ["You are happy for the words to appear only in the abstract."], "Topic / keyword"),
        field("Journal", "Restricts papers to one journal. For patents this is the applicant (the company or institution). In the preprint source it names the server, for example `bioRxiv`.",
              "A journal, server or applicant name.", "Empty",
              ["You follow one journal, or want a particular company's patents."], [], "Author"),
        field("Date range", "Limits results to a publication period. Both ends are optional.",
              "`YYYY`, `YYYY-MM` or `YYYY-MM-DD`.", "Empty (all dates)",
              ["You want recent work, or a fixed window for a review."],
              ["You are not sure when the work appeared; leave it open and sort by date in Excel."]),
        field("Match topic as", "How the topic words must appear. See section 4 for a worked example.",
              "**Exact phrase**, **All words** or **Any word**.", "Exact phrase",
              ["Exact phrase: the words belong together, such as `B2 protein` or `dot blot`.",
               "All words: you want every word but in any order or position.",
               "Any word: you are brainstorming and will filter afterwards."], [], "Must also contain, Exclude terms"),
        field("Must also contain (any of)", "A comma-separated list. The title or abstract must contain at least one of the terms, or the record is removed. Use it to demand context.",
              "Terms separated by commas, for example `protein, viral, RNAi, assay`.", "Empty (no requirement)",
              ["The topic is ambiguous and you know words that real hits will also contain."],
              ["Many records have no abstract (some Crossref and all USPTO records); a strict list removes those unless the title has a term."], "Exclude terms, Profile"),
        field("Exclude terms", "A comma-separated list of things you do not want. A term in the title or journal name removes the record. A term found only in the abstract keeps the record but lowers its score by 20 points per term, up to 40.",
              "Terms separated by commas, for example `riboflavin, vitamin, HER2`.", "Empty",
              ["A second meaning of your topic keeps flooding the results."],
              ["The term could also appear in genuinely relevant records; prefer Must also contain, or accept the score penalty."], "Must also contain, Relevance Score"),
        field("What counts as relevant (for AI)", "A plain-language description of what you are after. It is used only by the optional AI triage, which judges each record against it, and it is saved with a profile.",
              "One or two sentences.", "Empty (the AI then uses your search terms)",
              ["You switched on AI triage."], ["You are not using AI triage."], "AI triage"),
        field("Profile", "A saved set of the fields above plus the ticked sources. Pick one to fill the form, type a new name and click Save to store the current form, or Delete to remove one.",
              "A name. Two examples ship with Litwell, both marked `Example:`; delete them if you do not want them.", "None",
              ["You repeat the same kind of search."], [], "Search profiles (section 7)"),
        field("Max results (per source)", "The most records Litwell asks each source for. Filters are applied to what was fetched.",
              "1 to 500 (PubMed 500, most others 200, patents 100).", "100",
              ["Raise it for a broad search, lower it for a quick look."],
              ["With a very loose search a small cap can leave few records after filtering; tighten the search instead."]),
        field("Hide scores below", "Removes records whose Relevance Score is lower than this number. The removal is counted in the Search Log.",
              "0 to 100.", "0 (keep everything, sorted)",
              ["You want a short list and trust the score."], ["You are still learning what a good score looks like for your topic."], "Relevance Score"),
        field("AI triage (local Ollama, optional)", "Asks a model running on your own computer to rate each record Relevant, Maybe or Not relevant, with a one-line reason. Off by default. See section 11.",
              "On or off.", "Off",
              ["You have Ollama installed and want a second opinion on a long list."],
              ["You do not have Ollama, or want the fastest possible search."], "What counts as relevant"),
        field("Search in (sources)", "The databases to search. Tick any number; they are asked at the same time. **All**, **Papers only** and **None** are shortcuts.",
              "PubMed, Crossref, OpenAlex, Europe PMC, arXiv, Preprint servers, USPTO, EPO.", "Whatever you ticked last time",
              ["See section 5 for how to choose."], [], "Free keys"),
    ]
    S.append(("Every field explained", p("This section describes every box on the main window, in the order it appears. Each entry has the same layout: what it does, the values it accepts, its default, and when to use or skip it.") + "".join(fields)))

    ex_rows = ex["rows"]
    S.append(("Match modes, with a worked example", "".join([
        p("The match mode decides how the words of your topic must appear. Each source is sent the query in its own native syntax (for example PubMed's `[Title/Abstract]`, OpenAlex's `title_and_abstract.search`, EPO's CQL). Crossref and EPO cannot match a phrase themselves, so Litwell checks their results against your phrase afterwards."),
        table(["Mode", "Means", "Example: topic `B2 Protein`"],
              [["Exact phrase", "The words together, in order", "finds \"the B2 protein of nodaviruses\", not \"vitamin B2 and a protein\""],
               ["All words", "Every word, anywhere, any order", "finds both of the above"],
               ["Any word", "At least one word", "finds anything with B2, or with protein"]]),
        "<h3>Worked example: B2 Protein</h3>",
        p(f"B2 is an ambiguous abbreviation. A search for `B2 Protein` without quotes (how earlier versions searched) returned **{ex['old_rows']:,} rows** in the test file. Only about 16% of those had B2, beta-2, FHV or dsRNA in the title; the rest were vitamin B2, HER2, heart failure and food science. Only **{ex['old_phrase_in_title']}** had the phrase B2 Protein in the title."),
        p("The same search as an exact phrase, then with the *Example: Ambiguous abbreviation* profile (must contain `protein, viral, virus, RNAi, assay`; exclude `riboflavin, vitamin, HER2`):"),
        table(["Source", "Matches before (plain words)", "Matches now (exact phrase)"], ex_rows),
        table(["Run", "Rows in the workbook", "Rows scoring 50 or more"],
              [["Earlier version, plain words, all sources", f"{ex['old_rows']:,}", "not scored"],
               ["Exact phrase, all sources", str(ex["exact_rows"]), str(ex["exact_ge50"])],
               ["Exact phrase with the example profile", str(ex["profile_rows"]), str(ex["profile_ge50"])]]),
        p(ex["note"]),
        callout("Search counts change from day to day, and the numbers above come from one test run. Treat them as an illustration of the size of the effect, not as fixed figures."),
    ])))

    S.append(("Choosing sources, and getting the free keys", "".join([
        table(["Source", "Best for", "Needs"], [
            ["PubMed", "Biomedical and life-science papers, with good abstracts", "nothing"],
            ["Crossref", "Papers in every field; the broadest record of who published what", "nothing"],
            ["OpenAlex", "All disciplines; abstracts, citation counts and open-access links", "nothing"],
            ["Europe PMC", "Biomedical papers plus preprints; free full-text links", "nothing"],
            ["arXiv", "Physics, maths, computer science, quantitative biology", "nothing"],
            ["Preprint servers", "bioRxiv, medRxiv, SSRN, ChemRxiv, OSF servers and many more, found through three aggregators", "nothing"],
            ["USPTO", "US patents and published applications", "free key"],
            ["EPO", "Patents from about 100 offices", "free key and secret"]]),
        "<h3>Papers, preprints and patents</h3>",
        bullets(["**Papers** have been peer reviewed. PubMed, Crossref, OpenAlex and Europe PMC overlap heavily; Litwell merges the overlap into one row and fills in what one copy lacks.",
                 "**Preprints** are shared before peer review. They are the newest work and also the least checked. The Type column says Preprint so you can filter them in or out.",
                 "**Patents** describe inventions rather than findings. In the workbook the inventors are in Authors, the applicant is in Journal, and the patent number is in DOI. An application that is not yet granted is marked `(application)` after its date."]),
        "<h3>Getting the free keys</h3>",
        p("Paste keys under **File, API Keys & Contact**. They are saved only on your computer."),
        bullets(["**USPTO:** sign in or create a free account at data.uspto.gov, generate or copy your API key, and paste it into *USPTO API key*.",
                 "**EPO:** register free at developers.epo.org, create an app to get a *Consumer Key* and a *Consumer Secret*, and paste them into *EPO OPS key* and *EPO OPS secret*. The free tier allows about 4 GB a week.",
                 "**NCBI (optional):** a free key from your NCBI account (Settings, API Key Management) raises PubMed's limit from 3 to 10 requests a second. Most people do not need it.",
                 "**OpenAlex (optional):** a free key gives you your own daily allowance if you ever see \"rate limit reached\"."]),
        p("If USPTO or EPO is ticked but its key is missing, Litwell does not fail the whole search. It warns you in the Status box, skips that source, runs the others, and records *Skipped: no key* in the Search Log."),
    ])))

    S.append(("The contact email setting", "".join([
        p("Crossref, OpenAlex and NCBI run a faster, friendlier lane for programs that identify a contact. If you type an email under **File, API Keys & Contact, Contact email**, Litwell includes it in requests to those three services so they can reach you if something misbehaves."),
        bullets(["It is **optional** and **blank by default**. Litwell works without it.",
                 "It is stored **only** in your own settings file (`.litsearch_config.json` in your home folder) and is never sent anywhere except to those three services.",
                 "It is never built into the app. Each person who uses Litwell adds their own, if they want one."]),
    ])))

    S.append(("Search profiles and exclusion terms", "".join([
        p("A **profile** remembers a precise search so you can repeat it: the topic, match mode, must-contain and exclude lists, the plain-language description for AI triage, the minimum score and the ticked sources. Pick a profile from the Profile box to fill the form; type a name and click **Save** to store the current form; **Delete** removes one."),
        p("Two examples are included, clearly labelled and safe to delete. They are only illustrations of the kind of thing a profile holds."),
        table(["Example profile", "Topic and rules"], [
            ["Example: Ambiguous abbreviation", "Topic `B2 Protein`, exact phrase. Must contain `protein, viral, virus, RNAi, assay`. Exclude `riboflavin, vitamin, HER2`."],
            ["Example: Patent landscape", "Topic `double-stranded RNA detection`, all words. Must contain `antibody, assay, kit, immunoassay, sensor`. Sources USPTO, EPO and OpenAlex."]]),
        "<h3>Tips for exclusion terms</h3>",
        bullets(["Terms match **whole words**, ignoring capitals; `HER2` does not match `HER23`. A space and a hyphen are interchangeable, so `B2 protein` also finds `B2-protein`.",
                 "Start with two or three terms for the second meaning you keep seeing, then look at the Search Log to see how many rows each one removed.",
                 "If a term removes good records too, move it out of *Exclude* and rely on the score: a term found only in the abstract already costs 20 points."]),
    ])))

    S.append(("How the Relevance Score is calculated", "".join([
        p("Every record gets a number from 0 to 100 using fixed rules. No AI is involved and no key is needed. The score is a guide to how well the record matches your words; it is not a judgement of quality."),
        table(["What Litwell looks for", "Points"], [
            ["Your topic as a phrase in the **title**", "50"],
            ["If not as a phrase: the share of your topic's words in the title", "up to 30"],
            ["Your topic as a phrase in the **abstract**", "25"],
            ["If not as a phrase: the share of your topic's words in the abstract", "up to 15"],
            ["Each *Must also contain* term found in the title or abstract", "10 each, up to 20"],
            ["The journal matches the Journal box, or a field in the profile", "5"],
            ["Each *Exclude* term found only in the abstract (a title or journal hit removes the record)", "minus 20 each, up to 40"]]),
        p("The total is kept between 0 and 100. If you did not type a topic or a title (for example an author-only search), there is no text to judge and every record scores 50. The Title box counts as the topic when the Topic box is empty."),
        "<h3>An example</h3>",
        p("Topic `B2 protein`, must contain `viral`, exclude `vitamin`. A paper titled \"The B2 protein of a virus\" whose abstract mentions a viral B2 protein scores 50 + 25 + 10 = 85. A paper called \"Cheese ripening\" whose abstract mentions vitamin B2 proteins scores a few points: no title match, a partial abstract match, minus 20 for the excluded word."),
        p("**Hide scores below** removes records under a number you choose. Sorting best first is usually enough; use it for a short list once you know what a good score looks like for your topic."),
    ])))

    S.append(("Reading the workbook", "".join([
        "<h3>Results</h3>",
        p("One row per paper, best first. Header frozen, filters on every column, abstracts wrapped (click a cell to read the whole abstract)."),
        table(["Column", "What it tells you"], [
            ["Relevance Score", "0 to 100, coloured from red to green"],
            ["AI Rating, AI Reason", "From the optional local AI triage; blank when it was off"],
            ["New Since Last Run", "Yes if the record was not in the file before the latest run (section 10)"],
            ["Title, Authors, Journal, Date", "As published. For patents: inventors, applicant, publication date"],
            ["Abstract", "When any source supplied one"],
            ["DOI, Link, Open-access link", "Identifier, a page for the record, and a free full-text link when one is known"],
            ["Citation count", "How many works cite it (the highest figure any source reported)"],
            ["Type", "Paper, Preprint or Patent"],
            ["PubMed ... EPO", "Yes or No: which sources returned it. Filter a column to Yes to see one source's records"],
            ["Search Date, Search Terms", "When it was first found and with which fields"]]),
        "<h3>Summary</h3>",
        p("Counts by source, type, year, AI rating and score band, plus how many rows the latest run added and removed. It is rebuilt every run."),
        "<h3>Search Log</h3>",
        p("One row per source per run, including sources that failed or were skipped (with the reason), and one row per filter rule with the number of rows it removed. It answers \"why is this missing?\" and \"why only this many?\"."),
        "<h3>Glossary</h3>",
        p("Every column and scoring term explained, inside the workbook, with the credit and license at the foot."),
        p("You can also save to `.csv`, `.txt`, `.md`, `.ris` or `.bib`. Those files receive the same filtered, scored records but not the extra sheets."),
    ])))

    S.append(("New Since Last Run", "".join([
        p("When the output file already exists, each run marks which rows are new. Search the same topic every month into the same file, and filter *New Since Last Run* to **Yes** to see only what appeared since last time."),
        bullets(["**Yes:** the record was not in the file before this run.",
                 "**No:** it was already there (even if this run found it again). Records found again also gain any extra source flags and missing details.",
                 "**Blank:** the first run into a brand-new file, when there is no earlier run to compare with."]),
        p("Files made by older versions are upgraded the first time they are searched into: nothing is lost, old rows are marked No, and the extra columns start empty for them."),
        callout("Close the workbook in Excel before searching into it. If it is open, Litwell cannot update it; it saves the results to a recovery CSV next to it so nothing is lost."),
    ])))

    S.append(("Optional local AI triage (Ollama, free)", "".join([
        p("AI triage is a second opinion for long lists. It is **off by default**, runs **only on your own computer**, and costs nothing. Litwell never sends records to a cloud AI service, and refuses any Ollama address that is not your own computer."),
        "<h3>Setting it up once</h3>",
        steps(["Install Ollama from ollama.com (free, Windows and Mac).",
               "Open a terminal and pull a model, for example: `ollama pull llama3.1`. Any chat model will work, and Ollama may already have one.",
               "Nothing to set in Litwell: with the **Ollama model** box (File, API Keys & Contact) left blank, Litwell detects an installed model automatically and tells you which one it used, in the Status box and in the Search Log. To pick a model yourself, or to switch to a newer one later, type its name there; no update of Litwell is needed.",
               "Describe what you want in **What counts as relevant**, tick **AI triage**, and search."]),
        p("For each record Litwell shows the model the title, journal and abstract plus your description, and asks for a rating (**Relevant**, **Maybe**, **Not relevant**) and a one-line reason. These fill the *AI Rating* and *AI Reason* columns. Records are rated best-score first, up to 200 per run (setting `ai_max_records`), and progress shows in the Status box. Expect roughly a second or a few seconds per record on a typical laptop."),
        bullets(["If Ollama is not installed or not running, the Status box shows one line (for example *AI triage skipped: Ollama is not running on this computer*) and the search carries on without it.",
                 "A model can be wrong. Treat the rating as a prompt to look, not a decision, and read the reason.",
                 "Records with no abstract are rated from the title alone and usually come back *Maybe*."]),
    ])))

    S.append(("Troubleshooting", "".join([
        table(["What you see", "What it means and what to do"], [
            ["No results", "The exact phrase may be too narrow. Try **All words**, check the spelling, widen the date range, or remove Must also contain. The Search Log shows how many each source matched and how many your rules removed."],
            ["A source says **skipped** or **NOT searched**", "The reason is shown. *No USPTO key* or *no EPO key*: add the free key (section 5). *Could not reach ... HTTP 503*: that service is down; try again later. The other sources still ran."],
            ["**Rate limit reached**", "A service asked you to slow down. Wait and search again. For OpenAlex a free key or a contact email helps (sections 5 and 6)."],
            ["**Missing key** warning", "USPTO or EPO is ticked without a key. Add it under File, API Keys & Contact, or untick the source."],
            ["**Could not update ... it is open in Excel**", "Close the workbook and search again. The results were saved to a recovery CSV next to the file."],
            ["Far more rows than expected", "Use the exact phrase mode, add Must also contain or Exclude terms, or set Hide scores below."],
            ["Far fewer rows than expected", "Lower the strictness: All words, fewer must-contain terms, a larger Max results. Crossref and USPTO records often have no abstract, so a must-contain rule can remove them."],
            ["The score seems wrong", "Read section 8. The score reflects your words, not quality. A paper with the phrase only in the abstract scores lower than one with it in the title."],
            ["macOS says the app cannot be opened", "The app is not code-signed. Open System Settings, Privacy & Security, and choose Open Anyway."],
            ["Windows says Windows protected your PC", "Click More info, then Run anyway."],
            ["AI triage does nothing", "Check that Ollama is running and has a chat model (`ollama list`). If you typed a model name and it is not installed, Litwell uses an installed model instead and says so; the Status box gives any other reason."]]),
    ])))

    S.append(("Credits and license", "".join([
        p(esc(CREDIT)),
        p("Litwell is open source under the **Apache License, Version 2.0**. You may use, copy, modify and share it under that license; see the LICENSE and NOTICE files that come with the app. Bundled third-party software and its licenses are listed in THIRD_PARTY_NOTICES."),
        p("The Litwell name and icon are not licensed for use as the name of derivative products. If you fork Litwell, please give your version its own name and icon."),
        p("Litwell does not collect anything. Your searches go only to the public sources you tick. Each database and patent office has its own terms of use, which you are responsible for following."),
    ])))

    gl = [(t, m) for t, m in GLOSSARY]
    extra = [
        ("DOI", "Digital Object Identifier: a permanent code for a paper, such as 10.1038/s41586-020-2649-2. Litwell uses it to recognise the same paper in different sources."),
        ("Crossref", "A non-profit registry of journal articles and their DOIs. It covers every field but often lacks abstracts."),
        ("OpenAlex", "A free, open index of papers, authors and institutions across all fields, with abstracts, citation counts and open-access links."),
        ("Europe PMC", "A free biomedical literature database run by the European Bioinformatics Institute, covering PubMed content, preprints, patents and free full text."),
        ("PubMed", "The US National Library of Medicine's index of biomedical literature."),
        ("EPO", "The European Patent Office. Its Open Patent Services give access to Espacenet, covering about 100 patent offices."),
        ("USPTO", "The United States Patent and Trademark Office. Its Open Data Portal lists granted US patents and published applications."),
        ("Boolean search", "Combining words with AND, OR and NOT. Litwell's match modes build the right Boolean query for each source: All words is AND, Any word is OR, and Exclude terms act like NOT."),
        ("Open access", "Free to read online without a subscription. The Open-access link column points to a free copy when one is known."),
        ("Citation count", "The number of other works that cite a paper. A rough signal of influence; it differs between databases and favours older papers."),
        ("Application (patent)", "A published patent application that has not (yet) been granted. Marked `(application)` after the date."),
        ("Abstract", "The short summary at the start of a paper or patent."),
        ("Ollama", "Free software that runs AI language models on your own computer."),
        ("Profile", "A named, saved set of search fields in Litwell."),
    ]
    seen = {t for t, _ in extra}
    merged = sorted(extra + [(t, m) for t, m in gl if t not in seen and not t.startswith(("Title /", "PubMed ..."))], key=lambda x: x[0].lower())
    S.append(("Glossary", "<dl>" + "".join(f"<dt>{esc(t)}</dt><dd>{inline(m)}</dd>" for t, m in merged) + "</dl>"))
    return S


CSS = f"""
@page {{ size: Letter; margin: 0.9in 0.85in 0.9in 0.85in; @bottom-center {{ content: "Litwell How-to Guide  |  page " counter(page); font: 9pt -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; color: #666; }} }}
@page :first {{ margin: 0; @bottom-center {{ content: none; }} }}
html, body {{ margin: 0; }}
body {{ font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; line-height: 1.5; color: #1d1d1f; font-size: 10.5pt; }}
.cover {{ width: 8.5in; height: 10.95in; margin: 0; background: {NAVY}; color: #fff; padding: 2.2in 1in 0 1in; box-sizing: border-box; page-break-after: always; position: relative; }}
.cover img {{ width: 1.6in; height: 1.6in; border-radius: 0.3in; }}
.cover h1 {{ font-size: 40pt; margin: 0.45in 0 0.05in 0; letter-spacing: 0.5px; border: 0; color: #fff; }}
.cover .sub {{ font-size: 17pt; color: #c9d6f2; margin: 0 0 0.6in 0; }}
.cover .meta {{ font-size: 12pt; color: #c9d6f2; }}
.cover .credit {{ position: absolute; left: 1in; right: 1in; bottom: 0.7in; font-size: 9pt; color: #9fb2de; line-height: 1.4; }}
h1 {{ font-size: 22pt; color: {NAVY}; }}
h2 {{ font-size: 16pt; color: {NAVY}; margin-top: 1.6em; padding-bottom: .2em; border-bottom: 2px solid {NAVY}; page-break-after: avoid; }}
h3 {{ font-size: 12.5pt; color: {NAVY}; margin-top: 1.3em; page-break-after: avoid; }}
h4 {{ font-size: 11pt; margin: 1.2em 0 .2em 0; color: #111; page-break-after: avoid; }}
p {{ margin: .45em 0; }}
code {{ background: #eef1f8; padding: 0 .25em; border-radius: 3px; font-size: 9.5pt; }}
ul {{ margin: .25em 0 .5em 0; padding-left: 1.3em; }} li {{ margin: .15em 0; }}
.step {{ margin: .3em 0 .3em 1.4em; text-indent: -1.4em; }}
.toc p {{ margin: .15em 0 .15em 1em; }}
table {{ border-collapse: collapse; width: 100%; margin: .7em 0; font-size: 9.5pt; page-break-inside: auto; }}
th {{ background: {NAVY}; color: #fff; text-align: left; padding: 5px 7px; }}
th code {{ background: transparent; color: #fff; padding: 0; }}
td {{ border-bottom: 1px solid #d9deea; padding: 5px 7px; vertical-align: top; }}
tr {{ page-break-inside: avoid; }}
.note {{ border-left: 4px solid {NAVY}; background: #eef1f8; padding: .5em .8em; margin: .8em 0; }}
dt {{ font-weight: 700; margin-top: .7em; color: {NAVY}; }} dd {{ margin: .1em 0 0 1.2em; }}
.contents {{ padding-top: 0; }} .contents h2 {{ border: 0; margin-top: 0; }}
.body {{ }}
h2.start {{ page-break-before: always; }}
"""


def main() -> int:
    ex = json.loads((HERE / "b2_example.json").read_text(encoding="utf-8"))
    icon = base64.b64encode((ROOT / "litwell_icons" / "litwell_256.png").read_bytes()).decode()
    date = _dt.date.today().strftime("%d %B %Y").lstrip("0")
    secs = sections(ex)

    toc = "".join(f'<p><strong>{i}.</strong> {esc(t)}</p>' for i, (t, _b) in enumerate(secs, 1))
    body = []
    for i, (title, content) in enumerate(secs, 1):
        body.append(f'<h2 id="s{i}">{i}. {esc(title)}</h2>{content}')

    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Litwell How-to Guide</title><style>{CSS}</style></head><body>
<div class="cover"><img src="data:image/png;base64,{icon}" alt="Litwell">
<h1>Litwell</h1><div class="sub">How-to Guide</div>
<div class="meta">Version {esc(__version__)}<br>{esc(date)}</div>
<div class="sub" style="font-size:12pt;margin-top:.4in">Search papers, preprints and patents in one go,<br>and get one tidy, ranked Excel file.</div>
<div class="credit">{esc(CREDIT)}<br>{esc(LICENSE_LINE)}</div></div>
<div class="contents"><h2>Contents</h2><div class="toc">{toc}</div>
<p style="margin-top:1.2em">Litwell is free and open source. This guide is written for any researcher; no programming is needed.</p></div>
{''.join(body)}
</body></html>"""
    out_html = HERE / "Litwell_How_To_Guide.html"
    out_html.write_text(doc, encoding="utf-8")
    print("wrote", out_html.relative_to(ROOT))

    browser = next((b for b in BROWSERS if Path(b).exists()), None)
    if not browser:
        print("No Edge, Chrome or Brave found: open the HTML in a browser and print to PDF.")
        return 1
    pdf = ROOT / "docs" / "Litwell_How_To_Guide.pdf"
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", out_html.as_uri()]
    subprocess.run(cmd, check=False, capture_output=True, timeout=180)
    print("wrote", pdf.relative_to(ROOT), pdf.stat().st_size if pdf.exists() else "FAILED")
    return 0 if pdf.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
