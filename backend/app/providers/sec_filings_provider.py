from __future__ import annotations

import time
from datetime import date

import httpx

from app.domain.models import CompanyFilings, SecFiling
from app.providers.base import CompanyFilingsProvider


class SecFilingsProvider(CompanyFilingsProvider):
    """Read recent 10-K and 10-Q filing metadata from SEC submissions JSON."""

    DATA_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
    ARCHIVES_ROOT = "https://www.sec.gov/Archives/edgar/data"
    SUPPORTED_FORMS = {"10-K", "10-Q"}

    def __init__(
        self,
        user_agent: str | None,
        client: httpx.Client | None = None,
        min_request_interval_seconds: float = 0.11,
    ) -> None:
        self.user_agent = user_agent
        self.client = client or httpx.Client()
        self.min_request_interval_seconds = max(0.0, min_request_interval_seconds)
        self._cache: dict[str, CompanyFilings | None] = {}
        self._last_request_at: float | None = None

    def get_recent_filings(
        self,
        cik: str,
        limit: int,
    ) -> CompanyFilings | None:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        normalized_cik = self._normalize_cik(cik)
        if normalized_cik not in self._cache:
            self._cache[normalized_cik] = self._load_company_filings(normalized_cik)

        cached = self._cache[normalized_cik]
        if cached is None:
            return None
        return CompanyFilings(
            cik=cached.cik,
            source_url=cached.source_url,
            filings=cached.filings[:limit],
        )

    def _load_company_filings(self, normalized_cik: str) -> CompanyFilings | None:
        if not self.user_agent:
            raise RuntimeError(
                "SEC_USER_AGENT is required for SEC requests. "
                "Use a descriptive value such as 'Portfolio Exposure Graph your@email.com'."
            )

        self._respect_rate_limit()
        submissions_url = self.DATA_URL_TEMPLATE.format(cik=normalized_cik)
        response = self.client.get(
            submissions_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=10.0,
        )
        self._last_request_at = time.monotonic()

        if response.status_code == 404:
            return None

        response.raise_for_status()
        payload = response.json()
        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filings: list[SecFiling] = []

        for index, form in enumerate(forms):
            if form not in self.SUPPORTED_FORMS:
                continue

            accession_number = self._value_at(recent, "accessionNumber", index)
            filing_date_value = self._value_at(recent, "filingDate", index)
            if not accession_number or not filing_date_value:
                continue

            filing_date = self._parse_date(filing_date_value)
            if filing_date is None:
                continue

            report_date = self._parse_date(
                self._value_at(recent, "reportDate", index)
            )
            primary_document = self._value_at(recent, "primaryDocument", index)
            cik_path = str(int(normalized_cik))
            accession_path = accession_number.replace("-", "")
            filing_index_url = (
                f"{self.ARCHIVES_ROOT}/{cik_path}/{accession_path}/"
                f"{accession_number}-index.html"
            )
            primary_document_url = (
                f"{self.ARCHIVES_ROOT}/{cik_path}/{accession_path}/{primary_document}"
                if primary_document
                else filing_index_url
            )

            filings.append(
                SecFiling(
                    cik=normalized_cik,
                    accession_number=accession_number,
                    form=form,
                    filing_date=filing_date,
                    report_date=report_date,
                    primary_document=primary_document or None,
                    source_url=primary_document_url,
                    filing_index_url=filing_index_url,
                    submissions_url=submissions_url,
                )
            )

        filings.sort(
            key=lambda item: (item.filing_date, item.accession_number),
            reverse=True,
        )
        return CompanyFilings(
            cik=normalized_cik,
            source_url=submissions_url,
            filings=filings,
        )

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None or self.min_request_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait_for = self.min_request_interval_seconds - elapsed
        if wait_for > 0:
            time.sleep(wait_for)

    @staticmethod
    def _value_at(payload: dict, key: str, index: int) -> str | None:
        values = payload.get(key, [])
        if index >= len(values):
            return None
        value = values[index]
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _normalize_cik(cik: str) -> str:
        normalized = str(cik).strip()
        if not normalized.isdigit():
            raise ValueError("CIK must contain only digits")
        if len(normalized) > 10:
            raise ValueError("CIK must be at most 10 digits")
        return normalized.zfill(10)
