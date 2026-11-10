import httpx

from portfolio_exposure_graph.domain.enums import AssetStatus, AssetType
from portfolio_exposure_graph.providers.sec_asset_provider import SecAssetProvider


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


def test_sec_provider_lists_one_directory_entry_per_cik():
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [1046179, "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "TSM", "NYSE"],
            [1046179, "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "TSMWF", "OTC"],
            [723125, "MICRON TECHNOLOGY INC", "MU", "Nasdaq"],
        ],
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    provider = SecAssetProvider(user_agent="Portfolio Exposure Graph test@example.com", client=client)

    companies = {company.cik: company for company in provider.list_companies()}

    assert set(companies) == {"0001046179", "0000723125"}
    assert companies["0001046179"].ticker == "TSM"  # first listed ticker wins
    assert companies["0000723125"].name == "MICRON TECHNOLOGY INC"
    assert provider.source_url == SecAssetProvider.DATA_URL
