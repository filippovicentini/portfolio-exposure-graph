from uuid import uuid4

import pytest

from portfolio_exposure_graph.domain.enums import CandidateRole
from portfolio_exposure_graph.domain.models import DependencyExposureRow, EtfHolding
from portfolio_exposure_graph.services.graph_service import aggregate_supplier_exposure
from portfolio_exposure_graph.services.lookthrough_service import ConstituentExposure
from portfolio_exposure_graph.services.supplier_holding_matcher import (
    EXACT,
    TRUNCATED_PREFIX,
    match_constituent,
    supplier_name_keys,
)

TSMC = ["Taiwan Semiconductor Manufacturing Company Limited", "TSMC"]
SAMSUNG = ["Samsung Electronics Co., Ltd.", "Samsung"]


# Constituent names exactly as the Xtrackers (XMME) and iShares (EIMI) files spell them.
@pytest.mark.parametrize(
    ("constituent", "supplier", "expected"),
    [
        ("TAIWAN SEMICONDUCTOR MANUFACTURING", TSMC, EXACT),
        ("TAIWAN SEMICONDUCTOR MANUFAC", TSMC, TRUNCATED_PREFIX),
        ("SAMSUNG ELECTRONICS CO LTD", SAMSUNG, EXACT),
        ("SAMSUNG ELECTRONICS LTD", SAMSUNG, EXACT),
        ("SK HYNIX INC", ["SK Hynix Inc."], EXACT),
        ("HON HAI PRECISION INDUSTRY", ["Hon Hai Precision Industry Co., Ltd."], EXACT),
        ("WISTRON CORP", ["Wistron Corporation"], EXACT),
        # Different companies sharing a prefix must not match.
        ("SAMSUNG ELECTRO MECHANICS CO", SAMSUNG, None),
        ("WISTRON NEWEB", ["Wistron Corporation"], None),
        ("UNIMICRON TECHNOLOGY CORP", ["Micron Technology, Inc."], None),
        ("HANA MICRON INC", ["Micron Technology, Inc."], None),
        # Another share class of the same issuer is not matched (conservative).
        ("SAMSUNG ELECTRONICS PREF", SAMSUNG, None),
    ],
)
def test_constituent_names_from_real_issuer_files(constituent, supplier, expected):
    assert match_constituent(constituent, supplier_name_keys(supplier)) == expected


def test_truncation_rule_needs_a_long_name_and_a_real_cut():
    keys = supplier_name_keys(TSMC)

    assert match_constituent("TAIWAN SEMI", keys) is None  # short: not a truncation
    # Whole-word prefix is not a mid-word cut.
    assert match_constituent("TAIWAN SEMICONDUCTOR", keys) is None


def test_acronym_aliases_are_never_matched():
    assert match_constituent("TSMC", supplier_name_keys(TSMC)) is None


def row(supplier_id, name, aliases, weight=60.0, cik=None):
    return DependencyExposureRow(
        asset_path=["SWDA", "NVDA"],
        company_cik="0001045810",
        company_name="NVIDIA CORP",
        supplier_id=supplier_id,
        supplier_name=name,
        roles=[CandidateRole.FOUNDRY],
        company_path_weight_pct=weight,
        supplier_company_cik=cik,
        supplier_company_name="TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD" if cik else None,
        supplier_aliases=aliases,
    )


def constituent(etf, name, weight, us_listed=False, key=None):
    return ConstituentExposure(
        etf_ticker=etf,
        holding=EtfHolding(ticker=key or name[:20], description=name, weight_pct=1.0, us_listed=us_listed),
        weight_pct=weight,
    )


def test_held_weight_adds_sec_company_and_etf_constituents():
    rows = [row("s:tsmc", TSMC[0], TSMC, cik="0001046179")]
    constituents = [
        constituent("XMME", "TAIWAN SEMICONDUCTOR MANUFAC", 1.034),
        constituent("EIMI", "TAIWAN SEMICONDUCTOR MANUFACTURING", 0.5),
        constituent("XMME", "SAMSUNG ELECTRO MECHANICS CO", 0.02),
    ]

    result = aggregate_supplier_exposure(
        uuid4(), rows, holding_weights={"0001046179": 2.0}, constituents=constituents
    )

    [tsmc] = result.suppliers
    # 2.0 through TSM (SEC company) + 1.034 + 0.5 through the two EM ETFs.
    assert tsmc.held_weight_pct == pytest.approx(3.534)
    assert [(r.etf, r.method) for r in tsmc.held_via] == [
        ("XMME", TRUNCATED_PREFIX),
        ("EIMI", EXACT),
    ]


def test_a_supplier_without_sec_identity_is_held_through_etfs():
    rows = [row("s:samsung", SAMSUNG[0], SAMSUNG)]
    constituents = [
        constituent("XMME", "SAMSUNG ELECTRONICS CO LTD", 0.418),
        constituent("XMME", "SAMSUNG ELECTRONICS PREF", 0.057),
    ]

    [samsung] = aggregate_supplier_exposure(uuid4(), rows, constituents=constituents).suppliers

    assert samsung.supplier_company_cik is None
    assert samsung.held_weight_pct == pytest.approx(0.418)
    assert [route.constituent_name for route in samsung.held_via] == ["SAMSUNG ELECTRONICS CO LTD"]


def test_no_link_and_no_matching_constituent_stays_unknown():
    rows = [row("s:wistron", "Wistron Corporation", ["Wistron Corporation"])]

    [wistron] = aggregate_supplier_exposure(
        uuid4(), rows, constituents=[constituent("XMME", "WISTRON NEWEB", 0.1)]
    ).suppliers

    assert wistron.held_weight_pct is None
    assert wistron.held_via == []


def test_service_matches_only_non_us_constituents(portfolio_repository, client):
    """US-listed constituents are counted through the SEC company, never twice."""
    from tests.test_graph_service import (
        FakeCompanyAssetProvider,
        FakeCompanyFilingsProvider,
        FakeCompanyMetadataProvider,
        FakeFilingEvidenceProvider,
        FakeGraphRepository,
    )
    from portfolio_exposure_graph.domain.enums import AssetStatus, AssetType
    from portfolio_exposure_graph.domain.models import AssetResolution, Portfolio, PortfolioPosition
    from portfolio_exposure_graph.domain.enums import PortfolioStatus
    from portfolio_exposure_graph.providers.base import EtfHoldingsProvider
    from portfolio_exposure_graph.services.graph_service import GraphService

    class Holdings(EtfHoldingsProvider):
        def get_holdings(self, ticker):
            return [
                EtfHolding(ticker="TSM", description="TAIWAN SEMICONDUCTOR MANUFACTURING", weight_pct=5, us_listed=True),
                EtfHolding(ticker="TW0002330008", description="TAIWAN SEMICONDUCTOR MANUFAC", weight_pct=10, us_listed=False),
            ]

    portfolio = Portfolio(
        portfolio_id=uuid4(),
        name="EM",
        status=PortfolioStatus.READY,
        positions=[
            PortfolioPosition(
                ticker="XMME",
                weight_pct=50,
                asset=AssetResolution(ticker="XMME", asset_type=AssetType.ETF, status=AssetStatus.READY),
            )
        ],
    )
    portfolio_repository.save(portfolio)
    graph = FakeGraphRepository()
    graph.dependency_exposure_rows = [row("s:tsmc", TSMC[0], TSMC, cik="0001046179")]
    graph.company_holding_weights = {"0001046179": 2.5}  # 50% x 5% via the US listing
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph,
        etf_holdings_provider=Holdings(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
    )

    [tsmc] = service.get_supplier_exposure(portfolio.portfolio_id).suppliers

    # 2.5 (US listing, from the graph) + 5.0 (50% x 10% local share), not 2.5 twice.
    assert tsmc.held_weight_pct == pytest.approx(7.5)
    assert [route.constituent for route in tsmc.held_via] == ["TW0002330008"]
