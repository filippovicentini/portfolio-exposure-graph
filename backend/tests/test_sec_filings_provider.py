import httpx
import pytest

from app.providers.sec_filings_provider import SecFilingsProvider


SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "accessionNumber": [
                "0001045810-26-000001",
                "0001045810-25-000200",
                "0001045810-25-000150",
                "0001045810-25-000100",
            ],
            "filingDate": [
                "2026-02-25",
                "2025-11-19",
                "2025-08-27",
                "2025-05-28",
            ],
            "reportDate": [
                "2026-01-25",
                "2025-10-26",
                "2025-07-27",
                "2025-04-27",
            ],
            "form": ["10-K", "10-Q", "8-K", "10-Q/A"],
            "primaryDocument": [
                "nvda-20260125.htm",
                "nvda-20251026.htm",
                "nvda-8k.htm",
                "nvda-10qa.htm",
            ],
        }
    }
}


def test_sec_filings_provider_filters_forms_builds_urls_and_caches():
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.headers["user-agent"] == "Portfolio Exposure Graph test@example.com"
        assert str(request.url).endswith("/CIK0001045810.json")
        return httpx.Response(200, json=SUBMISSIONS_PAYLOAD)

    provider = SecFilingsProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_request_interval_seconds=0,
    )

    one = provider.get_recent_filings("1045810", limit=1)
    two = provider.get_recent_filings("0001045810", limit=2)

    assert one is not None
    assert two is not None
    assert len(one.filings) == 1
    assert len(two.filings) == 2
    assert [filing.form for filing in two.filings] == ["10-K", "10-Q"]
    assert two.filings[0].accession_number == "0001045810-26-000001"
    assert two.filings[0].source_url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000104581026000001/nvda-20260125.htm"
    )
    assert two.filings[0].filing_index_url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000104581026000001/0001045810-26-000001-index.html"
    )
    assert request_count == 1


def test_sec_filings_provider_falls_back_to_index_url_without_primary_document():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000001"],
                "filingDate": ["2026-08-01"],
                "reportDate": ["2026-06-27"],
                "form": ["10-Q"],
                "primaryDocument": [""],
            }
        }
    }
    provider = SecFilingsProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            )
        ),
        min_request_interval_seconds=0,
    )

    batch = provider.get_recent_filings("320193", limit=4)

    assert batch is not None
    assert batch.filings[0].primary_document is None
    assert batch.filings[0].source_url == batch.filings[0].filing_index_url


def test_sec_filings_provider_returns_none_for_missing_cik():
    provider = SecFilingsProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(404, json={"detail": "not found"})
            )
        ),
        min_request_interval_seconds=0,
    )

    assert provider.get_recent_filings("123", limit=4) is None


def test_sec_filings_provider_requires_user_agent():
    provider = SecFilingsProvider(
        user_agent=None,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=SUBMISSIONS_PAYLOAD)
            )
        ),
        min_request_interval_seconds=0,
    )

    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        provider.get_recent_filings("1045810", limit=4)
