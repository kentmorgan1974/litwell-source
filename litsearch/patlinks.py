# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Pick the best clickable link for a patent or published application.

The hard case is *recent* documents: Google Patents builds its per-patent
pages days-to-weeks after a document publishes, so a direct Google link 404s
until then. So:

  * US documents  -> the official USPTO PDF, which is live the day of
                     publication (and always, for pre-grant publications,
                     which Google indexes especially slowly).
  * non-US recent -> Espacenet (the canonical worldwide source).
  * anything older -> the Google Patents page (nicer: claims, family, citations).
"""

from __future__ import annotations

import datetime as _dt
import re

_USPTO_PDF = "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/{}"
_GOOGLE = "https://patents.google.com/patent/{}"
_ESPACENET = "https://worldwide.espacenet.com/patent/search?q=pn%3D{}"
_PATENTSCOPE = "https://patentscope.wipo.int/search/en/detail.jsf?docId={}"

_US_FRESH_DAYS = 30
_WORLD_FRESH_DAYS = 75


def _days_old(date_iso: str):
    try:
        return (_dt.date.today() - _dt.date.fromisoformat(date_iso[:10])).days
    except (ValueError, TypeError):
        return None


def patent_url(
    number: str,
    *,
    date_iso: str = "",
    is_application: bool = False,
) -> str:
    """``number`` e.g. 'US11848417', 'USD1143981', 'US20260258400A1',
    'EP1234567B1', 'WO2026183119A1'."""
    n = re.sub(r"[\s\-]", "", (number or "").upper())
    if not n:
        return ""
    age = _days_old(date_iso)

    if n[:2] == "US":
        core = re.sub(r"[A-Z]\d?$", "", n[2:])  # drop 'US' and trailing kind code
        # core is now e.g. '12719081', 'D1143981', 'RE49825', '20260258400'
        if re.fullmatch(r"[A-Z]{0,2}\d+", core):
            if is_application or age is None or age < _US_FRESH_DAYS:
                return _USPTO_PDF.format(core)  # official, live on publication day
            if core[:1] == "D" and not re.search(r"S\d*$", n):
                return _GOOGLE.format(f"USD{core[1:]}S1")  # design needs S1
            return _GOOGLE.format(n)
        return _GOOGLE.format(n)

    # WO (PCT) applications: WIPO's Patentscope is the authoritative source.
    if n[:2] == "WO":
        return _PATENTSCOPE.format(re.sub(r"[A-Z]\d?$", "", n))

    # Other non-US: Google eventually indexes everything; until then, Espacenet.
    if age is None or age < _WORLD_FRESH_DAYS:
        return _ESPACENET.format(n)
    return _GOOGLE.format(n)
