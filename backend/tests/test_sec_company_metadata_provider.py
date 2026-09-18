import httpx

from app.providers.sec_company_metadata_provider import SecCompanyMetadataProvider


NVDA_PAYLOAD = {
    "sic": "3674",
    "sicDescription": "Semiconductors & Related Devices",
    "addresses": {
        "business": {
            "stateOrCountry": "CA",
            "stateOrCountryDescription": "CALIFORNIA",
        }
    },
}

ASML_PAYLOAD = {
    "sic": "3559",
    "sicDescription": "Special Industry Machinery, NEC",
    "addresses": {
        "business": {
            "stateOrCountry": "P7",
            "stateOrCountryDescription": "NETHERLANDS",
        }
    },
}


def test_sec_company_metadata_provider_resolves_sic_country_and_caches():
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.headers["user-agent"] == "Portfolio Exposure Graph test@example.com"
        assert str(request.url).endswith("/CIK0001045810.json")
        return httpx.Response(200, json=NVDA_PAYLOAD)

    provider = SecCompanyMetadataProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_request_interval_seconds=0,
    )

    metadata = provider.get_metadata("1045810")
    cached = provider.get_metadata("0001045810")

    assert metadata is not None
    assert metadata.cik == "0001045810"
    assert metadata.industry_code == "3674"
    assert metadata.industry_name == "Semiconductors & Related Devices"
    assert metadata.country_code == "X1"
    assert metadata.country_name == "UNITED STATES"
    assert metadata.source_url.endswith("CIK0001045810.json")
    assert cached == metadata
    assert request_count == 1


def test_sec_company_metadata_provider_keeps_foreign_edgar_country_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ASML_PAYLOAD)

    provider = SecCompanyMetadataProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_request_interval_seconds=0,
    )

    metadata = provider.get_metadata("0000937966")

    assert metadata is not None
    assert metadata.country_code == "P7"
    assert metadata.country_name == "NETHERLANDS"
    assert metadata.industry_code == "3559"


def test_sec_company_metadata_provider_maps_canadian_province_to_country():
    payload = {
        "sic": "6500",
        "sicDescription": "Real Estate",
        "addresses": {
            "business": {
                "stateOrCountry": "A6",
                "stateOrCountryDescription": "ONTARIO, CANADA",
            }
        },
    }

    provider = SecCompanyMetadataProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            )
        ),
        min_request_interval_seconds=0,
    )

    metadata = provider.get_metadata("913353")

    assert metadata is not None
    assert metadata.country_code == "Z4"
    assert metadata.country_name == "CANADA"


def test_sec_company_metadata_provider_returns_none_for_missing_cik():
    provider = SecCompanyMetadataProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(404, json={"detail": "not found"})
            )
        ),
        min_request_interval_seconds=0,
    )

    assert provider.get_metadata("123") is None
