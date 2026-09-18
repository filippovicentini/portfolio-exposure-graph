from __future__ import annotations

import time

import httpx

from app.domain.models import CompanyMetadata
from app.providers.base import CompanyMetadataProvider


class SecCompanyMetadataProvider(CompanyMetadataProvider):
    """Resolve primary SIC industry and business-address country from SEC submissions."""

    DATA_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"

    US_STATE_CODES = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
        "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
        "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
        "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
        "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
        "WY", "X1",
    }
    CANADIAN_PROVINCE_CODES = {
        "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
        "B0", "Z4",
        "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE",
        "QC", "SK", "YT",
    }

    def __init__(
        self,
        user_agent: str | None,
        client: httpx.Client | None = None,
        min_request_interval_seconds: float = 0.12,
    ) -> None:
        self.user_agent = user_agent
        self.client = client or httpx.Client()
        self.min_request_interval_seconds = max(0.0, min_request_interval_seconds)
        self._cache: dict[str, CompanyMetadata | None] = {}
        self._last_request_at: float | None = None

    def get_metadata(self, cik: str) -> CompanyMetadata | None:
        normalized_cik = self._normalize_cik(cik)
        if normalized_cik in self._cache:
            return self._cache[normalized_cik]

        if not self.user_agent:
            raise RuntimeError(
                "SEC_USER_AGENT is required for SEC requests. "
                "Use a descriptive value such as 'Portfolio Exposure Graph your@email.com'."
            )

        self._respect_rate_limit()
        source_url = self.DATA_URL_TEMPLATE.format(cik=normalized_cik)
        response = self.client.get(
            source_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=10.0,
        )
        self._last_request_at = time.monotonic()

        if response.status_code == 404:
            self._cache[normalized_cik] = None
            return None

        response.raise_for_status()
        payload = response.json()

        raw_sic = payload.get("sic")
        raw_sic_description = payload.get("sicDescription")
        industry_code = str(raw_sic).strip() if raw_sic not in (None, "") else None
        industry_name = (
            str(raw_sic_description).strip()
            if raw_sic_description not in (None, "")
            else None
        )

        business_address = (payload.get("addresses") or {}).get("business") or {}
        country_code, country_name = self._normalize_business_country(
            business_address.get("stateOrCountry"),
            business_address.get("stateOrCountryDescription"),
        )

        metadata = CompanyMetadata(
            cik=normalized_cik,
            industry_code=industry_code,
            industry_name=industry_name,
            country_code=country_code,
            country_name=country_name,
            source_url=source_url,
        )
        self._cache[normalized_cik] = metadata
        return metadata

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None or self.min_request_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait_for = self.min_request_interval_seconds - elapsed
        if wait_for > 0:
            time.sleep(wait_for)

    @classmethod
    def _normalize_cik(cls, cik: str) -> str:
        normalized = str(cik).strip()
        if not normalized.isdigit():
            raise ValueError("CIK must contain only digits")
        if len(normalized) > 10:
            raise ValueError("CIK must be at most 10 digits")
        return normalized.zfill(10)

    @classmethod
    def _normalize_business_country(
        cls,
        state_or_country: str | None,
        description: str | None,
    ) -> tuple[str | None, str | None]:
        code = str(state_or_country).strip().upper() if state_or_country else None
        name = str(description).strip().upper() if description else None

        if code in cls.US_STATE_CODES:
            return "X1", "UNITED STATES"
        if code in cls.CANADIAN_PROVINCE_CODES:
            return "Z4", "CANADA"
        if code == "XX" or name in {"UNKNOWN", "#N/A"}:
            return None, None
        if code and name:
            return code, name
        return None, None
