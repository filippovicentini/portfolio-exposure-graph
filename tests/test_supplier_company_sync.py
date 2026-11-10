from uuid import uuid4

import pytest

from portfolio_exposure_graph.domain.enums import CandidateRole, SupplierCompanyLinkStatus
from portfolio_exposure_graph.domain.models import (
    CompanyResolution,
    DependencyExposureRow,
    SupplierIdentity,
)
from portfolio_exposure_graph.providers.base import CompanyDirectoryProvider
from portfolio_exposure_graph.services.graph_service import GraphService, aggregate_supplier_exposure
from tests.test_graph_service import (
    FakeCompanyAssetProvider,
    FakeCompanyFilingsProvider,
    FakeCompanyMetadataProvider,
    FakeEtfHoldingsProvider,
    FakeFilingEvidenceProvider,
    FakeGraphRepository,
)

TSMC_CIK = "0001046179"


class FakeDirectory(CompanyDirectoryProvider):
    source_url = "https://www.sec.gov/files/company_tickers_exchange.json"

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def list_companies(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("SEC unreachable")
        return [
            CompanyResolution(
                ticker="TSM", cik=TSMC_CIK, name="TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"
            )
        ]


def make_service(portfolio_repository, directory):
    graph = FakeGraphRepository()
    service = GraphService(
        portfolio_repository=portfolio_repository,
        graph_repository=graph,
        etf_holdings_provider=FakeEtfHoldingsProvider(),
        company_asset_provider=FakeCompanyAssetProvider(),
        company_metadata_provider=FakeCompanyMetadataProvider(),
        company_filings_provider=FakeCompanyFilingsProvider(),
        filing_evidence_provider=FakeFilingEvidenceProvider(),
        company_directory_provider=directory,
    )
    return service, graph


@pytest.fixture
def portfolio_id(client):
    created = client.post(
        "/api/v1/portfolios",
        json={"name": "Links", "positions": [{"ticker": "NVDA", "weight_pct": 100}]},
    ).json()
    from uuid import UUID

    return UUID(created["portfolio_id"])


TARGETS = [
    SupplierIdentity(
        supplier_id="s:tsmc",
        canonical_name="Taiwan Semiconductor Manufacturing Company Limited",
        aliases=["Taiwan Semiconductor Manufacturing Company Limited", "TSMC"],
    ),
    SupplierIdentity(
        supplier_id="s:samsung",
        canonical_name="Samsung Electronics Co., Ltd.",
        aliases=["Samsung Electronics Co., Ltd.", "Samsung"],
    ),
]


def test_sync_links_registered_suppliers_and_records_the_rest(
    portfolio_repository, portfolio_id
):
    directory = FakeDirectory()
    service, graph = make_service(portfolio_repository, directory)
    graph.supplier_link_targets = TARGETS

    result = service.sync_supplier_companies(portfolio_id)

    assert result.suppliers_requested == 2
    assert result.suppliers_linked == 1
    assert result.linked_supplier_ids == ["s:tsmc"]
    assert result.unmatched_supplier_ids == ["s:samsung"]
    assert result.directory_unavailable is False
    statuses = {link.supplier_id: link.status for link in graph.synced_supplier_links}
    assert statuses == {
        "s:tsmc": SupplierCompanyLinkStatus.LINKED,
        "s:samsung": SupplierCompanyLinkStatus.UNMATCHED,
    }


def test_directory_failure_leaves_suppliers_for_a_later_run(
    portfolio_repository, portfolio_id
):
    service, graph = make_service(portfolio_repository, FakeDirectory(fail=True))
    graph.supplier_link_targets = TARGETS

    result = service.sync_supplier_companies(portfolio_id)

    assert result.directory_unavailable is True
    assert result.suppliers_linked == 0
    assert not hasattr(graph, "synced_supplier_links")  # nothing marked as checked


def test_no_targets_does_not_load_the_directory(portfolio_repository, portfolio_id):
    directory = FakeDirectory()
    service, _graph = make_service(portfolio_repository, directory)

    result = service.sync_supplier_companies(portfolio_id)

    assert result.suppliers_requested == 0
    assert directory.calls == 0


def test_sync_requires_a_live_portfolio(portfolio_repository):
    service, _graph = make_service(portfolio_repository, FakeDirectory())

    assert service.sync_supplier_companies(uuid4()) is None


def row(asset_path, supplier_id, name, weight, supplier_cik=None):
    return DependencyExposureRow(
        asset_path=asset_path,
        company_cik="0001045810",
        company_name="NVIDIA CORP",
        supplier_id=supplier_id,
        supplier_name=name,
        roles=[CandidateRole.FOUNDRY],
        company_path_weight_pct=weight,
        supplier_company_cik=supplier_cik,
        supplier_company_name="TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD" if supplier_cik else None,
    )


def test_exposure_reports_weight_already_held_in_a_linked_supplier():
    rows = [
        row(["NVDA"], "s:tsmc", "TSMC", 60.0, TSMC_CIK),
        row(["NVDA"], "s:samsung", "Samsung", 60.0),
    ]
    # e.g. 15% TSM held directly + 1.2% TSMC inside an ETF
    holdings = {TSMC_CIK: 16.2, "0001045810": 60.0}

    result = aggregate_supplier_exposure(uuid4(), rows, holdings)

    items = {item.supplier_id: item for item in result.suppliers}
    assert items["s:tsmc"].supplier_company_cik == TSMC_CIK
    assert items["s:tsmc"].held_weight_pct == 16.2
    assert items["s:samsung"].supplier_company_cik is None
    assert items["s:samsung"].held_weight_pct is None
    assert "only reported for suppliers linked to an SEC registrant" in result.held_basis


def test_linked_supplier_not_held_reports_zero():
    result = aggregate_supplier_exposure(
        uuid4(), [row(["NVDA"], "s:tsmc", "TSMC", 60.0, TSMC_CIK)], {}
    )

    assert result.suppliers[0].held_weight_pct == 0.0


def test_service_only_loads_holdings_when_a_supplier_is_linked(
    portfolio_repository, portfolio_id
):
    service, graph = make_service(portfolio_repository, FakeDirectory())
    graph.dependency_exposure_rows = [row(["NVDA"], "s:samsung", "Samsung", 100.0)]
    graph.company_holding_weights = {"x": 1.0}

    unlinked = service.get_supplier_exposure(portfolio_id)
    assert unlinked.suppliers[0].held_weight_pct is None

    graph.dependency_exposure_rows = [row(["NVDA"], "s:tsmc", "TSMC", 100.0, TSMC_CIK)]
    graph.company_holding_weights = {TSMC_CIK: 7.5}
    linked = service.get_supplier_exposure(portfolio_id)
    assert linked.suppliers[0].held_weight_pct == 7.5


def test_ties_put_suppliers_the_portfolio_also_holds_first():
    rows = [
        row(["NVDA"], "s:fabrinet", "Fabrinet", 80.0),
        row(["NVDA"], "s:tsmc", "TSMC", 80.0, TSMC_CIK),
    ]

    result = aggregate_supplier_exposure(uuid4(), rows, {TSMC_CIK: 20.0})

    assert [item.supplier_id for item in result.suppliers] == ["s:tsmc", "s:fabrinet"]
