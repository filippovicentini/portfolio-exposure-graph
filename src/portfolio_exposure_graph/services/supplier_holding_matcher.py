"""Match Suppliers to non-US ETF constituents by name.

A Supplier such as "Samsung Electronics Co., Ltd." has no SEC identity, but a
UCITS ETF may hold it ("SAMSUNG ELECTRONICS CO LTD" in an Xtrackers file).
Matching them shows how much of a supplier the portfolio already holds.

Two methods, both deterministic:

- ``normalized_name_exact``: the constituent name equals a Supplier name or
  alias after the same normalization as Supplier-to-SEC-company linking
  (case, punctuation, trailing legal forms).
- ``truncated_name_prefix``: issuers cut long names mid-word
  ("TAIWAN SEMICONDUCTOR MANUFAC"). Accepted only when the constituent name
  is long (>= 24 characters, where truncation happens), has at least three
  words, every word but the last equals the Supplier's, and the last word is
  a prefix (>= 4 characters) of the Supplier's word at that position. A
  different company that merely shares a prefix, such as
  "SAMSUNG ELECTRO MECHANICS" against "Samsung Electronics", fails these
  rules.

Short all-caps acronyms are never used as Supplier names here either.
"""

from __future__ import annotations

from portfolio_exposure_graph.services.supplier_company_linker import (
    is_linkable_alias,
    normalize_entity_name,
)

EXACT = "normalized_name_exact"
TRUNCATED_PREFIX = "truncated_name_prefix"

_MIN_TRUNCATED_LENGTH = 24
_MIN_WORDS = 3
_MIN_CUT_WORD = 4


def supplier_name_keys(names: list[str]) -> set[str]:
    return {
        normalize_entity_name(name)
        for name in names
        if is_linkable_alias(name) and normalize_entity_name(name)
    }


def match_constituent(constituent_name: str, supplier_keys: set[str]) -> str | None:
    """Return the match method, or None when the names do not match."""
    if not constituent_name or not supplier_keys:
        return None
    key = normalize_entity_name(constituent_name)
    if not key:
        return None
    if key in supplier_keys:
        return EXACT

    if len(constituent_name.strip()) < _MIN_TRUNCATED_LENGTH:
        return None
    words = key.split()
    if len(words) < _MIN_WORDS or len(words[-1]) < _MIN_CUT_WORD:
        return None
    candidates = 0
    for supplier_key in supplier_keys:
        supplier_words = supplier_key.split()
        if len(supplier_words) < len(words):
            continue
        if supplier_words[: len(words) - 1] != words[:-1]:
            continue
        cut = supplier_words[len(words) - 1]
        if cut != words[-1] and cut.startswith(words[-1]):
            candidates += 1
    return TRUNCATED_PREFIX if candidates == 1 else None
