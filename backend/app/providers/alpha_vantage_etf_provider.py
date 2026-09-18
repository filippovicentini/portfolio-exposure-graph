from __future__ import annotations

import httpx

from app.domain.models import EtfHolding
from app.providers.base import EtfHoldingsProvider


class AlphaVantageEtfProvider(EtfHoldingsProvider):
    """Fetch ETF constituents from Alpha Vantage ETF_PROFILE."""

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str | None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client()
        self._holdings_by_ticker: dict[str, list[EtfHolding]] = {}

    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        normalized = ticker.strip().upper()
        cached = self._holdings_by_ticker.get(normalized)
        if cached is not None:
            return cached

        if not self.api_key:
            raise RuntimeError("ALPHA_VANTAGE_API_KEY is required for ETF look-through")

        response = self.client.get(
            self.BASE_URL,
            params={
                "function": "ETF_PROFILE",
                "symbol": normalized,
                "apikey": self.api_key,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()

        if "Error Message" in payload:
            raise ValueError(f"Alpha Vantage could not resolve ETF {normalized}")
        if "Note" in payload or "Information" in payload:
            raise RuntimeError("Alpha Vantage request was not completed")

        raw_holdings = payload.get("holdings")
        if raw_holdings is None:
            return []
        if not isinstance(raw_holdings, list):
            raise ValueError("Unexpected Alpha Vantage ETF holdings schema")

        holdings: list[EtfHolding] = []
        for raw in raw_holdings:
            if not isinstance(raw, dict):
                continue

            symbol = raw.get("symbol")
            weight = raw.get("weight")
            if not symbol or weight is None:
                continue

            normalized_symbol = str(symbol).strip().upper()
            if normalized_symbol in {"N/A", "NA", "NONE", "-"}:
                continue

            try:
                weight_fraction = float(weight)
            except (TypeError, ValueError):
                continue

            # Alpha Vantage ETF_PROFILE returns holding weights as 0..1 fractions.
            if not 0 <= weight_fraction <= 1:
                continue
            weight_pct = weight_fraction * 100.0

            holdings.append(
                EtfHolding(
                    ticker=normalized_symbol,
                    description=raw.get("description"),
                    weight_pct=weight_pct,
                )
            )

        self._holdings_by_ticker[normalized] = holdings
        return holdings
