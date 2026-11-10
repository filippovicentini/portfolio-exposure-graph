"""Deterministic matching of internal Supplier identities to SEC companies.

A Supplier comes from filing text ("Taiwan Semiconductor Manufacturing
Company Limited, or TSMC"). The SEC company directory spells registrants
differently ("TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"). Both sides are
normalized the same way and compared for exact equality; nothing is fuzzy.

The matcher is deliberately conservative:

- only the canonical name and aliases are used, never the filing context;
- short all-caps acronyms (e.g. "TSMC", "AMD") are skipped as aliases,
  because an acronym equal to some registrant's full name is too weak a
  signal;
- when the names point at more than one CIK, nothing is linked and the
  Supplier is reported as ambiguous.

Suppliers that are not SEC registrants (e.g. Samsung Electronics, Hon Hai)
stay unmatched, which is the correct outcome, not a failure.
"""

from __future__ import annotations

import re

from app.domain.enums import SupplierCompanyLinkStatus
from app.domain.models import CompanyResolution, SupplierCompanyLink, SupplierIdentity

METHOD = "sec_directory_normalized_exact_v1"

# Legal-form words removed from the END of a name, repeatedly
# ("Company Limited", "Co., Ltd.", "Inc."). Words elsewhere are kept.
_LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "plc",
    "llc",
    "lp",
    "nv",
    "sa",
    "ag",
    "se",
    "spa",
    "bv",
}
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_ACRONYM = re.compile(r"^[A-Z0-9&.\-]{2,5}$")


def normalize_entity_name(name: str) -> str:
    """Lowercase, drop punctuation and trailing legal-form words."""
    text = name.casefold().replace("&", " and ")
    # "N.V." / "S.A." become "nv" / "sa" before punctuation is dropped.
    text = re.sub(r"\b([a-z])\.(?=[a-z]\.)", r"\1", text)
    text = re.sub(r"\b([a-z])\.\b", r"\1", text)
    tokens = [token for token in _NON_ALNUM.split(text) if token]
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    if tokens and tokens[0] == "the" and len(tokens) > 1:
        tokens = tokens[1:]
    return " ".join(tokens)


def is_linkable_alias(name: str) -> bool:
    """False for short acronyms such as "TSMC", which are too ambiguous."""
    stripped = name.strip()
    return bool(stripped) and not _ACRONYM.fullmatch(stripped)


class SupplierCompanyLinker:
    def __init__(
        self,
        directory: list[CompanyResolution],
        source_url: str | None = None,
    ) -> None:
        self.source_url = source_url
        self._index: dict[str, dict[str, str]] = {}
        for company in directory:
            key = normalize_entity_name(company.name)
            if key:
                self._index.setdefault(key, {}).setdefault(company.cik, company.name)

    def link(self, supplier: SupplierIdentity) -> SupplierCompanyLink:
        names = [supplier.canonical_name] + [
            alias for alias in supplier.aliases if is_linkable_alias(alias)
        ]
        matches: dict[str, tuple[str, str]] = {}  # cik -> (sec name, matched name)
        for name in names:
            for cik, sec_name in self._index.get(normalize_entity_name(name), {}).items():
                matches.setdefault(cik, (sec_name, name))

        if len(matches) == 1:
            [(cik, (sec_name, matched_name))] = matches.items()
            return SupplierCompanyLink(
                supplier_id=supplier.supplier_id,
                status=SupplierCompanyLinkStatus.LINKED,
                method=METHOD,
                company_cik=cik,
                company_name=sec_name,
                matched_name=matched_name,
                candidate_ciks=[cik],
                source_url=self.source_url,
            )
        return SupplierCompanyLink(
            supplier_id=supplier.supplier_id,
            status=(
                SupplierCompanyLinkStatus.AMBIGUOUS
                if matches
                else SupplierCompanyLinkStatus.UNMATCHED
            ),
            method=METHOD,
            candidate_ciks=sorted(matches),
            source_url=self.source_url,
        )
