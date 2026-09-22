from __future__ import annotations

import hashlib
import re
import time
from html.parser import HTMLParser

import httpx

from app.domain.models import (
    FilingEvidence,
    FilingEvidenceBatch,
    FilingEvidenceTarget,
)
from app.providers.base import FilingEvidenceProvider


class _BlockTextParser(HTMLParser):
    BLOCK_TAGS = {
        "address",
        "article",
        "br",
        "dd",
        "div",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "td",
        "th",
        "tr",
    }
    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.segments: list[str] = []
        self._current: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized = tag.lower()
        if normalized in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth == 0 and normalized in self.BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth == 0 and normalized in self.BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._current.append(data)

    def finish(self) -> list[str]:
        self._flush()
        return self.segments

    def _flush(self) -> None:
        if not self._current:
            return
        text = " ".join(self._current)
        self._current = []
        if text.strip():
            self.segments.append(text)


class SecFilingEvidenceProvider(FilingEvidenceProvider):
    """Extract conservative dependency evidence candidates from SEC filing HTML."""

    EXTRACTION_METHOD = "sec_html_dependency_keywords_v3"
    EVIDENCE_TYPE = "dependency_candidate"
    MIN_SEGMENT_CHARS = 80
    MAX_EVIDENCE_CHARS = 8000
    STRONG_TERMS = (
        "supply chain",
        "single source",
        "sole source",
        "foundry",
        "foundries",
        "contract manufacturer",
        "contract manufacturers",
        "manufacturing partner",
        "manufacturing partners",
        "third-party manufacturer",
        "third-party manufacturers",
    )
    COUNTERPARTY_TERMS = (
        "supplier",
        "suppliers",
        "vendor",
        "vendors",
    )
    GENERIC_DEPENDENCY_TERMS = (
        "depend on",
        "depends on",
        "dependent on",
        "dependency",
        "rely on",
        "relies on",
        "reliance",
    )
    KEYWORDS = STRONG_TERMS + COUNTERPARTY_TERMS + GENERIC_DEPENDENCY_TERMS
    DEPENDENCY_CONTEXT_PATTERNS = (
        r"\bmanufactur(?:e|es|ed|ing)\b",
        r"\bsupply\b",
        r"\bprocure(?:s|d|ment)?\b",
        r"\bsourcing\b",
        r"\bsource(?:d|s)?\s+(?:components?|materials?|inventory)\b",
        r"\binventor(?:y|ies)\b",
        r"\bcomponents?\b",
        r"\bproduction\b",
        r"\bfabricat(?:e|es|ed|ion)\b",
        r"\bwafers?\b",
        r"\bassembl(?:y|ies|e|es|ed|ing)\b",
        r"\bpackag(?:e|es|ed|ing)\b",
        r"\bmaterials?\b",
        r"\bsemiconductors?\b",
        r"\bcapacity\b",
    )
    COUNTERPARTY_CONTEXT_PATTERNS = DEPENDENCY_CONTEXT_PATTERNS + (
        r"\bpurchas(?:e|es|ed|ing)\b",
        r"\borders?\b",
        r"\bdeliver(?:y|ies|ed|ing)?\b",
        r"\bshortages?\b",
        r"\blead\s+times?\b",
        r"\bavailability\b",
    )
    SENTENCE_BOUNDARY_PATTERN = re.compile(
        r"(?<=[.!?;])\s+(?=[A-Z0-9(])"
    )

    def __init__(
        self,
        user_agent: str | None,
        client: httpx.Client | None = None,
        min_request_interval_seconds: float = 0.11,
    ) -> None:
        self.user_agent = user_agent
        self.client = client or httpx.Client()
        self.min_request_interval_seconds = max(0.0, min_request_interval_seconds)
        self._cache: dict[str, FilingEvidenceBatch | None] = {}
        self._last_request_at: float | None = None
        self._patterns = [
            (
                term,
                re.compile(
                    r"(?<!\w)"
                    + re.escape(term).replace(r"\ ", r"\s+")
                    + r"(?!\w)",
                    re.IGNORECASE,
                ),
            )
            for term in self.KEYWORDS
        ]
        self._dependency_context_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.DEPENDENCY_CONTEXT_PATTERNS
        ]
        self._counterparty_context_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.COUNTERPARTY_CONTEXT_PATTERNS
        ]

    def extract_evidence(
        self,
        filing: FilingEvidenceTarget,
        limit: int,
    ) -> FilingEvidenceBatch | None:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        accession_number = filing.accession_number.strip()
        if accession_number not in self._cache:
            self._cache[accession_number] = self._load_evidence(filing)

        cached = self._cache[accession_number]
        if cached is None:
            return None
        return FilingEvidenceBatch(
            accession_number=cached.accession_number,
            source_url=cached.source_url,
            extraction_method=cached.extraction_method,
            evidence=cached.evidence[:limit],
        )

    def _load_evidence(
        self,
        filing: FilingEvidenceTarget,
    ) -> FilingEvidenceBatch | None:
        if not self.user_agent:
            raise RuntimeError(
                "SEC_USER_AGENT is required for SEC requests. "
                "Use a descriptive value such as 'Portfolio Exposure Graph your@email.com'."
            )

        self._respect_rate_limit()
        response = self.client.get(
            filing.source_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=15.0,
        )
        self._last_request_at = time.monotonic()

        if response.status_code == 404:
            return None
        response.raise_for_status()

        parser = _BlockTextParser()
        parser.feed(response.text)
        segments = parser.finish()

        evidence: list[FilingEvidence] = []
        seen: set[str] = set()
        for raw_segment in segments:
            normalized = re.sub(r"\s+", " ", raw_segment).strip()
            if len(normalized) < self.MIN_SEGMENT_CHARS:
                continue

            matches = [
                (term, match)
                for term, pattern in self._patterns
                for match in pattern.finditer(normalized)
            ]
            qualifying_matches = [
                (term, match)
                for term, match in matches
                if self._term_has_required_context(normalized, term, match)
            ]
            if not qualifying_matches:
                continue

            matched_terms = list(
                dict.fromkeys(term for term, _ in qualifying_matches)
            )
            first_match = min(match.start() for _, match in qualifying_matches)
            excerpt = self._make_excerpt(normalized, first_match)
            dedupe_key = excerpt.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            evidence_id = self._evidence_id(
                filing.accession_number,
                excerpt,
            )
            evidence.append(
                FilingEvidence(
                    evidence_id=evidence_id,
                    accession_number=filing.accession_number,
                    evidence_type=self.EVIDENCE_TYPE,
                    evidence_text=excerpt,
                    matched_terms=matched_terms,
                    source_url=filing.source_url,
                    source_date=filing.filing_date,
                    extraction_method=self.EXTRACTION_METHOD,
                )
            )

        return FilingEvidenceBatch(
            accession_number=filing.accession_number,
            source_url=filing.source_url,
            extraction_method=self.EXTRACTION_METHOD,
            evidence=evidence,
        )

    def _term_has_required_context(
        self,
        text: str,
        term: str,
        match: re.Match[str],
    ) -> bool:
        if term in self.STRONG_TERMS:
            return True

        sentence = self._sentence_for_match(
            text,
            match_start=match.start(),
            match_end=match.end(),
        )
        if term in self.COUNTERPARTY_TERMS:
            return any(
                pattern.search(sentence)
                for pattern in self._counterparty_context_patterns
            )

        if term in self.GENERIC_DEPENDENCY_TERMS:
            return any(
                pattern.search(sentence)
                for pattern in self._dependency_context_patterns
            )

        return False

    @classmethod
    def _sentence_for_match(
        cls,
        text: str,
        match_start: int,
        match_end: int,
    ) -> str:
        sentence_start = 0
        sentence_end = len(text)
        for boundary in cls.SENTENCE_BOUNDARY_PATTERN.finditer(text):
            if boundary.end() <= match_start:
                sentence_start = boundary.end()
                continue
            if boundary.start() >= match_end:
                sentence_end = boundary.start()
                break
        return text[sentence_start:sentence_end].strip()

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None or self.min_request_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait_for = self.min_request_interval_seconds - elapsed
        if wait_for > 0:
            time.sleep(wait_for)

    @classmethod
    def _make_excerpt(cls, text: str, match_start: int) -> str:
        if len(text) <= cls.MAX_EVIDENCE_CHARS:
            return text

        half_window = cls.MAX_EVIDENCE_CHARS // 2
        start = max(0, match_start - half_window)
        end = min(len(text), start + cls.MAX_EVIDENCE_CHARS)
        start = max(0, end - cls.MAX_EVIDENCE_CHARS)
        excerpt = text[start:end].strip()
        if start > 0:
            excerpt = "... " + excerpt
        if end < len(text):
            excerpt = excerpt + " ..."
        return excerpt

    @staticmethod
    def _evidence_id(accession_number: str, evidence_text: str) -> str:
        digest = hashlib.sha256(
            f"{accession_number}\n{evidence_text}".encode("utf-8")
        ).hexdigest()[:24]
        return f"{accession_number}:{digest}"
