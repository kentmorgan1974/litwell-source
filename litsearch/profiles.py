# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Named search profiles, kept in the user's config file.

A profile remembers the fields that make a search precise: topic, match mode,
"must also contain", "exclude", a plain-language description (used by the
optional AI triage) and the ticked sources. Two clearly labelled examples are
added to a new config once; they can be deleted and stay deleted.
"""

from __future__ import annotations

from typing import Any, Dict, List

PROFILE_FIELDS = (
    "keyword", "match_mode", "must_terms", "exclude_terms", "boost_terms",
    "description", "sources", "min_score",
)

EXAMPLES: Dict[str, Dict[str, Any]] = {
    "Example: Ambiguous abbreviation": {
        "keyword": "B2 Protein",
        "match_mode": "exact",
        "must_terms": "protein, viral, virus, RNAi, assay",
        "exclude_terms": "riboflavin, vitamin, HER2",
        "boost_terms": "virology, RNA, nucleic acids, biochemistry",
        "description": (
            "Papers about the B2 protein of nodaviruses (a double-stranded RNA "
            "binding protein that suppresses RNA interference). Not relevant: "
            "vitamin B2 (riboflavin), HER2, or food science."
        ),
        "sources": ["pubmed", "europepmc", "openalex", "preprints"],
        "min_score": 0,
    },
    "Example: Patent landscape": {
        "keyword": "double-stranded RNA detection",
        "match_mode": "all",
        "must_terms": "antibody, assay, kit, immunoassay, sensor",
        "exclude_terms": "",
        "boost_terms": "",
        "description": (
            "Patents and published applications describing methods, antibodies "
            "or kits for detecting double-stranded RNA."
        ),
        "sources": ["patents", "epo", "openalex"],
        "min_score": 0,
    },
}


def seed_examples(cfg: Dict[str, Any]) -> bool:
    """Add the two example profiles to ``cfg`` once. True if ``cfg`` changed."""
    if cfg.get("profiles_seeded"):
        return False
    profiles = cfg.setdefault("profiles", {})
    for name, data in EXAMPLES.items():
        profiles.setdefault(name, dict(data))
    cfg["profiles_seeded"] = True
    return True


def names(cfg: Dict[str, Any]) -> List[str]:
    p = cfg.get("profiles")
    return sorted(p) if isinstance(p, dict) else []


def get(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    p = cfg.get("profiles")
    return dict(p[name]) if isinstance(p, dict) and name in p else {}


def save(cfg: Dict[str, Any], name: str, data: Dict[str, Any]) -> None:
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("Give the profile a name.")
    cfg.setdefault("profiles", {})[name] = {k: data.get(k, "") for k in PROFILE_FIELDS}


def delete(cfg: Dict[str, Any], name: str) -> bool:
    p = cfg.get("profiles")
    if isinstance(p, dict) and name in p:
        del p[name]
        return True
    return False
