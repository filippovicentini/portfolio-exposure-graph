import httpx
import pytest

from app.providers.alpha_vantage_etf_provider import AlphaVantageEtfProvider


def test_provider_parses_holdings_and_caches_response():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["function"] == "ETF_PROFILE"
        assert request.url.params["symbol"] == "QQQ"
        assert request.url.params["apikey"] == "test-key"
        return httpx.Response(
            200,
            json={
                "holdings": [
                    {
                        "symbol": "NVDA",
                        "description": "NVIDIA Corporation",
                        "weight": "0.08",
                    },
                    {
                        "symbol": "AAPL",
                        "description": "Apple Inc",
                        "weight": "0.075",
                    },
                    {
                        "symbol": "N/A",
                        "description": "Cash or non-security allocation",
                        "weight": "0.01",
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AlphaVantageEtfProvider(api_key="test-key", client=client)

    first = provider.get_holdings("qqq")
    second = provider.get_holdings("QQQ")

    assert calls == 1
    assert first == second
    assert first[0].ticker == "NVDA"
    assert first[0].weight_pct == 8.0
    assert first[1].description == "Apple Inc"
    assert len(first) == 2


def test_provider_requires_api_key():
    provider = AlphaVantageEtfProvider(api_key=None)

    with pytest.raises(RuntimeError, match="ALPHA_VANTAGE_API_KEY"):
        provider.get_holdings("QQQ")
