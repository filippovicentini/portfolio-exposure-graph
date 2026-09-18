from __future__ import annotations

import csv
import io

import httpx

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution, EtfHolding
from app.providers.base import AssetDataProvider, EtfHoldingsProvider


class AlphaVantageEtfProvider(AssetDataProvider, EtfHoldingsProvider):
    """Resolve US-listed ETFs and fetch their constituents from Alpha Vantage."""

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str | None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client()
        self._etf_listings: dict[str, tuple[str | None, str | None]] | None = None
        self._holdings_by_ticker: dict[str, list[EtfHolding]] = {}

    def resolve(self, ticker: str) -> AssetResolution | None:
        """Resolve a ticker only when Alpha Vantage classifies it as an ETF."""
        normalized = ticker.strip().upper()

        # Asset resolution should degrade gracefully when Alpha Vantage is not
        # configured. The next provider (SEC) can still resolve equities.
        if not self.api_key:
            return None

        listing = self._load_etf_listings().get(normalized)
        if listing is None:
            return None

        name, exchange = listing
        return AssetResolution(
            ticker=normalized,
            exchange=exchange,
            asset_type=AssetType.ETF,
            status=AssetStatus.READY,
            company_name=name,
        )

    def _load_etf_listings(self) -> dict[str, tuple[str | None, str | None]]:
        if self._etf_listings is not None:
            return self._etf_listings

        if not self.api_key:
            return {}

        response = self.client.get(
            self.BASE_URL,
            params={
                "function": "LISTING_STATUS",
                "state": "active",
                "apikey": self.api_key,
            },
            timeout=10.0,
        )
        response.raise_for_status()

        reader = csv.DictReader(io.StringIO(response.text))
        required_fields = {"symbol", "name", "exchange", "assetType"}
        if reader.fieldnames is None or not required_fields.issubset(reader.fieldnames):
            raise RuntimeError("Unexpected Alpha Vantage listing status response")

        listings: dict[str, tuple[str | None, str | None]] = {}
        for row in reader:
            if (row.get("assetType") or "").strip().upper() != "ETF":
                continue

            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            name = (row.get("name") or "").strip() or None
            exchange = (row.get("exchange") or "").strip() or None
            listings[symbol] = (name, exchange)

        self._etf_listings = listings
        return listings

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
