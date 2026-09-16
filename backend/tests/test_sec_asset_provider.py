import httpx

from app.domain.enums import AssetStatus, AssetType
from app.providers.sec_asset_provider import SecAssetProvider


SEC_PAYLOAD = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [937966, "ASML HOLDING NV", "ASML", "Nasdaq"],
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
    ],
}


def test_sec_provider_resolves_equity_and_caches_dataset():
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.headers["user-agent"] == "Portfolio Exposure Graph test@example.com"
        return httpx.Response(200, json=SEC_PAYLOAD)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = SecAssetProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=client,
    )

    asset = provider.resolve("asml")
    second_asset = provider.resolve("AAPL")

    assert asset is not None
    assert asset.ticker == "ASML"
    assert asset.company_name == "ASML HOLDING NV"
    assert asset.exchange == "Nasdaq"
    assert asset.cik == "0000937966"
    assert asset.asset_type == AssetType.EQUITY
    assert asset.status == AssetStatus.READY
    assert second_asset is not None
    assert request_count == 1


def test_sec_provider_returns_none_for_unknown_ticker():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SEC_PAYLOAD)

    provider = SecAssetProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.resolve("NOTREAL") is None
