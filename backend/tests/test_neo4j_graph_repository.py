from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.domain.enums import AssetStatus, AssetType, PortfolioStatus
from app.domain.models import (
    AssetResolution,
    CompanyResolution,
    EtfHolding,
    Portfolio,
    PortfolioPosition,
)
from app.repositories.neo4j_graph_repository import Neo4jGraphRepository


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False
        self.path_records = []

    def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if "effective_weight_pct" in query:
            return self.path_records, SimpleNamespace(), []
        return [], SimpleNamespace(), []

    def close(self):
        self.closed = True


def make_portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        name="Graph repo",
        status=PortfolioStatus.READY,
        positions=[
            PortfolioPosition(
                ticker="NVDA",
                weight_pct=70,
                asset=AssetResolution(
                    ticker="NVDA",
                    exchange="Nasdaq",
                    asset_type=AssetType.EQUITY,
                    status=AssetStatus.READY,
                    company_name="NVIDIA CORP",
                    cik="0001045810",
                ),
            ),
            PortfolioPosition(
                ticker="QQQ",
                weight_pct=30,
                asset=AssetResolution(
                    ticker="QQQ",
                    exchange="NASDAQ",
                    asset_type=AssetType.ETF,
                    status=AssetStatus.READY,
                    company_name="Invesco QQQ Trust",
                ),
            ),
        ],
    )


def test_neo4j_repository_writes_portfolio_holdings_and_companies():
    driver = FakeDriver()
    repository = Neo4jGraphRepository(
        uri="bolt://unused",
        user="neo4j",
        password="test",
        driver=driver,
    )
    portfolio = make_portfolio()

    repository.sync_portfolio(
        portfolio,
        {
            "QQQ": [
                EtfHolding(ticker="NVDA", description="NVIDIA", weight_pct=8.0),
                EtfHolding(ticker="AAPL", description="Apple", weight_pct=7.0),
                EtfHolding(ticker="ZERO", description="Zero", weight_pct=0.0),
            ]
        },
        {
            "NVDA": CompanyResolution(
                ticker="NVDA",
                cik="0001045810",
                name="NVIDIA CORP",
                exchange="Nasdaq",
            ),
            "AAPL": CompanyResolution(
                ticker="AAPL",
                cik="0000320193",
                name="Apple Inc.",
                exchange="Nasdaq",
            ),
        },
    )

    assert len(driver.calls) == 5
    _, positions_call = driver.calls[1]
    assert positions_call["portfolio_id"] == str(portfolio.portfolio_id)
    assert {item["ticker"] for item in positions_call["positions"]} == {"NVDA", "QQQ"}

    _, holdings_call = driver.calls[3]
    assert [item["ticker"] for item in holdings_call["holdings"]] == ["NVDA", "AAPL"]
    assert holdings_call["database_"] == "neo4j"

    company_query, companies_call = driver.calls[4]
    assert "WITH asset, company\n    OPTIONAL MATCH" in company_query
    assert "MERGE (canonical:Company {cik: company.cik})" in company_query
    assert [item["ticker"] for item in companies_call["companies"]] == ["AAPL", "NVDA"]
    assert companies_call["companies"][1]["cik"] == "0001045810"


def test_neo4j_repository_parses_exposure_paths():
    driver = FakeDriver()
    driver.path_records = [
        FakeRecord(
            asset_path=["QQQ", "NVDA"],
            relations=["OWNS", "HOLDS"],
            effective_weight_pct=2.400000001,
        )
    ]
    repository = Neo4jGraphRepository(
        uri="bolt://unused",
        user="neo4j",
        password="test",
        driver=driver,
    )
    portfolio_id = uuid4()

    paths = repository.get_exposure_paths(portfolio_id)

    assert len(paths) == 1
    assert paths[0].asset_path == ["QQQ", "NVDA"]
    assert paths[0].relations == ["OWNS", "HOLDS"]
    assert paths[0].effective_weight_pct == 2.4


def test_neo4j_repository_closes_driver():
    driver = FakeDriver()
    repository = Neo4jGraphRepository(
        uri="bolt://unused",
        user="neo4j",
        password="test",
        driver=driver,
    )

    repository.close()

    assert driver.closed is True
