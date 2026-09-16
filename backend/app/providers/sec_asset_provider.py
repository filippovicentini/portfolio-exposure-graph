from __future__ import annotations

import httpx

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import AssetResolution
from app.providers.base import AssetDataProvider


class SecAssetProvider(AssetDataProvider):
    """Resolve US-listed equities from the SEC ticker/CIK mapping."""

    DATA_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

    def __init__(
        self,
        user_agent: str | None,
        client: httpx.Client | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.client = client or httpx.Client()
        self._assets_by_ticker: dict[str, AssetResolution] | None = None

    def resolve(self, ticker: str) -> AssetResolution | None:
        normalized = ticker.strip().upper()
        assets = self._load_assets()
        return assets.get(normalized)

    def _load_assets(self) -> dict[str, AssetResolution]:
        if self._assets_by_ticker is not None:
            return self._assets_by_ticker

        if not self.user_agent:
            raise RuntimeError(
                "SEC_USER_AGENT is required for SEC requests. "
                "Use a descriptive value such as 'Portfolio Exposure Graph your@email.com'."
            )

        response = self.client.get(
            self.DATA_URL,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()

        fields = payload.get("fields", [])
        rows = payload.get("data", [])
        required_fields = {"cik", "name", "ticker", "exchange"}
        if not required_fields.issubset(fields):
            raise ValueError("Unexpected SEC ticker mapping schema")

        indexes = {field: fields.index(field) for field in required_fields}
        assets: dict[str, AssetResolution] = {}

        for row in rows:
            raw_ticker = row[indexes["ticker"]]
            if not raw_ticker:
                continue

            normalized_ticker = str(raw_ticker).strip().upper()
            cik = str(row[indexes["cik"]]).zfill(10)
            exchange = row[indexes["exchange"]]
            company_name = row[indexes["name"]]

            assets.setdefault(
                normalized_ticker,
                AssetResolution(
                    ticker=normalized_ticker,
                    exchange=exchange,
                    asset_type=AssetType.EQUITY,
                    status=AssetStatus.READY,
                    company_name=company_name,
                    cik=cik,
                ),
            )

        self._assets_by_ticker = assets
        return assets
