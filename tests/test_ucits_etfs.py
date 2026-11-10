import io
from uuid import uuid4

import httpx
import pytest
from openpyxl import Workbook

from portfolio_exposure_graph.domain.enums import AssetStatus, AssetType, PortfolioStatus
from portfolio_exposure_graph.domain.models import (
    AssetResolution,
    EtfHolding,
    Portfolio,
    PortfolioPosition,
)
from portfolio_exposure_graph.providers.base import EtfHoldingsProvider
from portfolio_exposure_graph.providers.ucits_etf_provider import (
    RoutingEtfHoldingsProvider,
    UcitsEtfProvider,
    UcitsFund,
    load_registry,
    parse_ishares_holdings,
    parse_xtrackers_holdings,
)
from portfolio_exposure_graph.repositories.portfolio_repository import (
    InMemoryPortfolioRepository,
)
from portfolio_exposure_graph.services.lookthrough_service import LookthroughService

# Shape of a real iShares latest-holdings.csv: preamble, blank line, table.
ISHARES_CSV = '''﻿Fund Holdings as of,"06/Nov/2026"

Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Shares,Price,Location,Exchange,Market Currency
"AAPL","APPLE","Information Technology","Equity","8,425,710,293.35","5.73","8,425,710,293.35","24,609,955.00","342.37","United States","NASDAQ","USD"
"BRK B","BERKSHIRE HATHAWAY INC CLASS B","Financials","Equity","1,349,104,412.40","0.92","1","1","1","United States","New York Stock Exchange Inc.","USD"
"SU","SCHNEIDER ELECTRIC","Industrials","Equity","1","0.50","1","1","1","France","Nyse Euronext - Euronext Paris","EUR"
"ESZ6","S&P500 EMINI DEC 26","Cash and/or Derivatives","Futures","0.00","0.00","464,475,500.00","1,255.00","7,402.00","-","Index And Options Market","USD"
"USD","USD CASH","Cash and/or Derivatives","Cash","1","0.30","1","1","1","United States","-","USD"
'''


def xtrackers_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None] * 11)
    sheet.append(["Although information in this document has been obtained from sources believed to be reliable..."])
    sheet.append([None] * 11)
    sheet.append([None, "Name", "ISIN", "Country", "Currency", "Exchange", "Type of Security", "Rating", "Primary Listing", "Industry Classification", "Weighting"])
    sheet.append([1, "TAIWAN SEMICONDUCTOR MANUFAC", "TW0002330008", "Taiwan", "TWD", "-", "Equities", "-", "-", "Information Technology", 0.1476850459])
    sheet.append([2, "SAMSUNG ELECTRONICS CO LTD", "KR7005930003", "Korea, Republic of", "KRW", "-", "Equities", "-", "-", "Information Technology", 0.0597256108])
    sheet.append([3, "TENCENT HOLDINGS LTD", "KYG875721634", "China", "HKD", "-", "Equities", "-", "Hang Seng Index", "Communication Services", 0.0301874521])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- parsers ---------------------------------------------------------------


def test_ishares_parser_reads_the_table_after_the_preamble():
    holdings = {h.ticker: h for h in parse_ishares_holdings(ISHARES_CSV)}

    apple = holdings["AAPL"]
    assert apple.weight_pct == 5.73
    assert apple.us_listed is True
    assert (apple.country, apple.sector, apple.asset_class) == (
        "United States",
        "Information Technology",
        "Equity",
    )


def test_ishares_share_classes_use_the_sec_ticker_format():
    holdings = {h.ticker: h for h in parse_ishares_holdings(ISHARES_CSV)}

    assert "BRK-B" in holdings  # iShares writes "BRK B"
    assert holdings["BRK-B"].us_listed is True


def test_non_us_tickers_are_listing_qualified_and_never_resolvable():
    holdings = {h.ticker: h for h in parse_ishares_holdings(ISHARES_CSV)}

    # "SU" alone would collide with Suncor on NYSE.
    assert "SU" not in holdings
    schneider = holdings["SU @ NYSE EURONEXT - EURONEXT PARIS"]
    assert schneider.us_listed is False
    assert schneider.country == "France"


def test_cash_and_futures_rows_are_kept_but_not_resolvable():
    holdings = {h.ticker: h for h in parse_ishares_holdings(ISHARES_CSV)}

    cash = next(h for key, h in holdings.items() if key.startswith("USD"))
    assert cash.asset_class == "Cash" and cash.us_listed is False
    assert any(h.asset_class == "Futures" and h.weight_pct == 0 for h in holdings.values())


def test_ishares_parser_rejects_an_unexpected_file():
    with pytest.raises(ValueError, match="Ticker"):
        parse_ishares_holdings("<!doctype html><html>product page</html>")


def test_xtrackers_parser_reads_isin_keyed_constituents():
    holdings = parse_xtrackers_holdings(xtrackers_xlsx())

    assert [h.ticker for h in holdings] == ["TW0002330008", "KR7005930003", "KYG875721634"]
    tsmc = holdings[0]
    assert tsmc.description == "TAIWAN SEMICONDUCTOR MANUFAC"
    assert tsmc.weight_pct == pytest.approx(14.76850459)
    assert tsmc.isin == "TW0002330008"
    assert tsmc.us_listed is False
    assert tsmc.country == "Taiwan"


# --- registry and provider ---------------------------------------------------


def test_registry_has_unique_isins_and_tickers():
    funds = load_registry()
    keys = [key for fund in funds for key in (fund.isin, *fund.tickers)]

    assert len(keys) == len(set(keys))
    assert {fund.issuer for fund in funds} <= {"ishares", "xtrackers", "vanguard"}
    assert all(fund.ishares_product_id for fund in funds if fund.issuer == "ishares")
    swda = next(fund for fund in funds if "SWDA" in fund.tickers)
    assert swda.isin == "IE00B4L5Y983"


def test_a_fund_resolves_by_any_ticker_or_by_isin():
    provider = UcitsEtfProvider()

    for key in ("SWDA", "iwda", "EUNL", "IE00B4L5Y983"):
        asset = provider.resolve(key)
        assert asset.asset_type == AssetType.ETF
        assert asset.status == AssetStatus.READY
        assert asset.isin == "IE00B4L5Y983"
    assert provider.resolve("NVDA") is None


def provider_with(handler):
    return UcitsEtfProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_holdings_are_fetched_from_the_issuer_and_cached_per_fund():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "ishares.com" in request.url.host:
            return httpx.Response(200, text=ISHARES_CSV)
        return httpx.Response(200, content=xtrackers_xlsx())

    provider = provider_with(handler)

    assert len(provider.get_holdings("SWDA")) == 5
    assert len(provider.get_holdings("IWDA")) == 5  # same fund: no new request
    assert len(provider.get_holdings("XMME")) == 3
    assert len(calls) == 2
    assert "/products/251882/" in calls[0] and calls[0].endswith("latest-holdings.csv")
    assert calls[1].endswith("/constituent/IE00BTJRMP35/")


def test_vanguard_is_recognised_but_reports_no_holdings():
    provider = provider_with(lambda request: pytest.fail("no request expected"))

    assert provider.resolve("VALL").company_name.startswith("Vanguard")
    assert provider.get_holdings("VALL") == []


def test_issuer_errors_propagate_so_callers_report_the_etf_unexpanded():
    provider = provider_with(lambda request: httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        provider.get_holdings("SWDA")


class RecordingFallback(EtfHoldingsProvider):
    def __init__(self):
        self.calls = []

    def get_holdings(self, ticker):
        self.calls.append(ticker)
        return [EtfHolding(ticker="NVDA", weight_pct=8.0)]


def test_routing_sends_ucits_etfs_to_issuers_and_others_to_the_fallback():
    fallback = RecordingFallback()
    router = RoutingEtfHoldingsProvider(
        ucits=provider_with(lambda request: httpx.Response(200, text=ISHARES_CSV)),
        fallback=fallback,
    )

    assert len(router.get_holdings("SWDA")) == 5
    assert router.get_holdings("QQQ")[0].ticker == "NVDA"
    assert fallback.calls == ["QQQ"]


# --- look-through classification ----------------------------------------------


class FixedHoldings(EtfHoldingsProvider):
    def __init__(self, holdings):
        self.holdings = holdings

    def get_holdings(self, ticker):
        return self.holdings.get(ticker, [])


def etf(ticker, weight):
    return PortfolioPosition(
        ticker=ticker,
        weight_pct=weight,
        asset=AssetResolution(ticker=ticker, asset_type=AssetType.ETF, status=AssetStatus.READY),
    )


def lookthrough(positions, holdings):
    repository = InMemoryPortfolioRepository()
    portfolio = Portfolio(
        portfolio_id=uuid4(), name="t", status=PortfolioStatus.READY, positions=positions
    )
    repository.save(portfolio)
    return LookthroughService(repository, FixedHoldings(holdings)).calculate(
        portfolio.portfolio_id
    )


def buckets(items):
    return {item.name: round(item.weight_pct, 6) for item in items}


def test_classification_uses_issuer_data_and_reports_the_unanalysed_rest():
    holdings = {
        "WORLD": parse_ishares_holdings(ISHARES_CSV),  # sums to 7.45%
        "EM": parse_xtrackers_holdings(xtrackers_xlsx()),
    }

    result = lookthrough([etf("WORLD", 80), etf("EM", 8), etf("VANG", 1)], holdings)

    assert result.analysed_weight_pct == 89.0
    assert result.not_analysed_weight_pct == 11.0
    assert result.unexpanded_etfs == ["VANG"]
    countries = buckets(result.countries)
    assert countries["United States"] == pytest.approx(80 * (5.73 + 0.92 + 0.30) / 100)
    # Korea is spelled "Korea, Republic of" by DWS; it is normalized.
    assert "South Korea" in countries
    assert countries["ETF holdings not available"] == 1.0
    # The fund's uncovered remainder is unclassified, not redistributed.
    assert countries["Unclassified"] == pytest.approx(80 * (100 - 7.45) / 100 + 8 * (100 - 23.75981088) / 100)
    for breakdown in (result.countries, result.sectors, result.asset_classes):
        assert sum(item.weight_pct for item in breakdown) == pytest.approx(89.0)


def test_rounded_weights_above_100_are_scaled_down():
    holdings = {
        "W": [
            EtfHolding(ticker="A", weight_pct=60.1, country="United States", sector="X", asset_class="Equity"),
            EtfHolding(ticker="B", weight_pct=40.1, country="Japan", sector="Y", asset_class="Equity"),
        ]
    }

    result = lookthrough([etf("W", 50)], holdings)

    countries = buckets(result.countries)
    assert "Unclassified" not in countries
    assert sum(countries.values()) == pytest.approx(50.0)
    assert countries["United States"] == pytest.approx(50 * 60.1 / 100.2)


def test_exposures_carry_name_and_classification():
    result = lookthrough([etf("EM", 10)], {"EM": parse_xtrackers_holdings(xtrackers_xlsx())})

    tsmc = next(item for item in result.exposures if item.ticker == "TW0002330008")
    assert tsmc.name == "TAIWAN SEMICONDUCTOR MANUFAC"
    assert tsmc.country == "Taiwan"
    assert tsmc.via_etfs == ["EM"]
    assert tsmc.total_weight_pct == pytest.approx(1.476850459)


# --- graph sync ---------------------------------------------------------------


def test_graph_sync_keeps_non_us_constituents_out_of_the_sec_graph():
    from tests.test_graph_service import (
        FakeCompanyAssetProvider,
        FakeCompanyFilingsProvider,
        FakeCompanyMetadataProvider,
        FakeFilingEvidenceProvider,
        FakeGraphRepository,
    )
    from portfolio_exposure_graph.services.graph_service import GraphService

    repository = InMemoryPortfolioRepository()
    portfolio = Portfolio(
        portfolio_id=uuid4(),
        name="UCITS",
        status=PortfolioStatus.READY,
        positions=[etf("WORLD", 80), etf("EM", 8)],
    )
    repository.save(portfolio)
    graph = FakeGraphRepository()
    service = GraphService(
        portfolio_repository=repository,
        graph_repository=graph,
        etf_holdings_provider=FixedHoldings(
            {
                "WORLD": parse_ishares_holdings(ISHARES_CSV),
                "EM": parse_xtrackers_holdings(xtrackers_xlsx()),
            }
        ),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    result = service.sync(portfolio.portfolio_id)

    # Only US equities (AAPL, BRK-B) reach the SEC graph; Schneider, cash and
    # the emerging-markets constituents do not.
    assert {h.ticker for h in graph.synced_holdings["WORLD"]} == {"AAPL", "BRK-B"}
    assert "EM" not in graph.synced_holdings
    # The EM fund was expanded; it just has no US constituents.
    assert result.unexpanded_etfs == []
    assert set(graph.synced_companies) == {"AAPL"}
    assert result.unresolved_company_assets == ["BRK-B"]
