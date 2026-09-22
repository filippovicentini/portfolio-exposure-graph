from datetime import date

import httpx
import pytest

from app.domain.models import FilingEvidenceTarget
from app.providers.sec_filing_evidence_provider import SecFilingEvidenceProvider


SOURCE_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/nvda-20260125.htm"


def make_target() -> FilingEvidenceTarget:
    return FilingEvidenceTarget(
        accession_number="0001045810-26-000001",
        cik="0001045810",
        form="10-K",
        filing_date=date(2026, 2, 25),
        source_url=SOURCE_URL,
    )


def test_sec_filing_evidence_provider_extracts_dependency_candidates_and_caches():
    html = """
    <html><body>
      <p>We depend on third-party foundries and suppliers for critical manufacturing capacity, and disruptions in this supply chain could affect our ability to deliver products.</p>
      <p>Our revenue and operating results may vary from quarter to quarter for many reasons unrelated to suppliers.</p>
      <p>We rely on contract manufacturers for certain components and manufacturing services that are important to our operations.</p>
    </body></html>
    """
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url) == SOURCE_URL
        assert request.headers["User-Agent"] == "Portfolio Exposure Graph test@example.com"
        return httpx.Response(200, text=html)

    provider = SecFilingEvidenceProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_request_interval_seconds=0,
    )

    one = provider.extract_evidence(make_target(), limit=1)
    many = provider.extract_evidence(make_target(), limit=5)

    assert one is not None
    assert many is not None
    assert len(requests) == 1
    assert len(one.evidence) == 1
    assert len(many.evidence) == 2
    assert many.evidence[0].evidence_type == "dependency_candidate"
    assert "depend on" in many.evidence[0].matched_terms
    assert "foundries" in many.evidence[0].matched_terms
    assert "suppliers" in many.evidence[0].matched_terms
    assert many.evidence[0].source_date == date(2026, 2, 25)
    assert many.evidence[0].extraction_method == "sec_html_dependency_keywords_v3"
    assert many.evidence[0].evidence_id.startswith("0001045810-26-000001:")
    assert many.evidence[0].evidence_id == one.evidence[0].evidence_id


def test_sec_filing_evidence_provider_returns_processed_batch_without_matches():
    html = "<html><body><p>This paragraph discusses ordinary business performance, revenue trends, and operating expenses for the period.</p></body></html>"
    provider = SecFilingEvidenceProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=html)
            )
        ),
        min_request_interval_seconds=0,
    )

    batch = provider.extract_evidence(make_target(), limit=5)

    assert batch is not None
    assert batch.evidence == []


def test_sec_filing_evidence_provider_returns_none_for_missing_document():
    provider = SecFilingEvidenceProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(404, text="not found")
            )
        ),
        min_request_interval_seconds=0,
    )

    assert provider.extract_evidence(make_target(), limit=5) is None


def test_sec_filing_evidence_provider_requires_user_agent():
    provider = SecFilingEvidenceProvider(
        user_agent=None,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text="<p>supplier dependency</p>")
            )
        ),
        min_request_interval_seconds=0,
    )

    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        provider.extract_evidence(make_target(), limit=5)

def test_sec_filing_evidence_provider_filters_generic_dependency_false_positives():
    html = """
    <html><body>
      <p>This Quarterly Report contains forward-looking statements and investors should not place undue reliance on them because actual results may differ materially.</p>
      <p>Expected lease start dates are subject to and dependent on timing of facility construction completion for our data centers.</p>
      <p>These strategic commitments may impact our financial results and are dependent on the performance of our customers and partners.</p>
      <p>Open-source AI is dependent on developer adoption and may affect demand for our products and services.</p>
      <p>We enter into agreements with our suppliers that allow them to procure inventory for manufacturing based upon our defined criteria.</p>
      <p>Manufacturing, supply, and capacity commitments include agreements with supply vendors for current and future product architectures.</p>
      <p>Other vendor commitments were $6 billion and are expected to be paid through the next fiscal year.</p>
      <p>Production complexity may create challenges in managing our supply chain and increase material costs.</p>
    </body></html>
    """
    provider = SecFilingEvidenceProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=html)
            )
        ),
        min_request_interval_seconds=0,
    )

    batch = provider.extract_evidence(make_target(), limit=20)

    assert batch is not None
    assert len(batch.evidence) == 3
    evidence_text = " ".join(item.evidence_text for item in batch.evidence).lower()
    assert "procure inventory" in evidence_text
    assert "supply vendors" in evidence_text
    assert "vendor commitments" not in evidence_text
    assert "supply chain" in evidence_text
    assert "undue reliance" not in evidence_text
    assert "construction completion" not in evidence_text
    assert "customers and partners" not in evidence_text
    assert "developer adoption" not in evidence_text
    assert all(
        item.extraction_method == "sec_html_dependency_keywords_v3"
        for item in batch.evidence
    )


def test_sec_filing_evidence_provider_requires_context_in_same_sentence():
    html = """
    <html><body>
      <p>Our partner network includes add-in board manufacturers, automotive manufacturers and tier-1 automotive suppliers, and other ecosystem participants.</p>
      <p>We rely primarily on patents and licensing arrangements to protect our IP. The laws of countries in which our products may be manufactured may provide different protections.</p>
      <p>Manufacturing capabilities are one competitive factor. Our ability to remain competitive will depend on how well we anticipate customer requirements.</p>
      <p>Our ability to increase manufacturing capabilities will depend on the domestic manufacturing ecosystem's capacity to ramp production supply to the required volume.</p>
      <p>We partner with key suppliers for the manufacturing process, including wafer fabrication, assembly, testing, and packaging.</p>
    </body></html>
    """
    provider = SecFilingEvidenceProvider(
        user_agent="Portfolio Exposure Graph test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=html)
            )
        ),
        min_request_interval_seconds=0,
    )

    batch = provider.extract_evidence(make_target(), limit=20)

    assert batch is not None
    assert len(batch.evidence) == 2
    evidence_text = " ".join(item.evidence_text for item in batch.evidence).lower()
    assert "ramp production supply" in evidence_text
    assert "key suppliers for the manufacturing process" in evidence_text
    assert "tier-1 automotive suppliers" not in evidence_text
    assert "protect our ip" not in evidence_text
    assert "anticipate customer requirements" not in evidence_text
    assert all(
        item.extraction_method == "sec_html_dependency_keywords_v3"
        for item in batch.evidence
    )
