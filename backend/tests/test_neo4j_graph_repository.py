from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.domain.enums import AssetStatus, AssetType, PortfolioStatus
from app.domain.models import (
    AssetResolution,
    CompanyFilings,
    CompanyMetadata,
    CompanyResolution,
    EtfHolding,
    Portfolio,
    PortfolioPosition,
    SecFiling,
)
from app.repositories.neo4j_graph_repository import Neo4jGraphRepository


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False
        self.path_records = []
        self.metadata_target_records = []
        self.filing_target_records = []
        self.industry_exposure_records = []
        self.country_exposure_records = []

    def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if "industry.sic AS code" in query:
            return self.industry_exposure_records, SimpleNamespace(), []
        if "country.sec_code AS code" in query:
            return self.country_exposure_records, SimpleNamespace(), []
        if "effective_weight_pct" in query:
            return self.path_records, SimpleNamespace(), []
        if "'sec_metadata_synced_at' IN keys(company)" in query:
            return self.metadata_target_records, SimpleNamespace(), []
        if "'sec_filings_synced_at' IN keys(company)" in query:
            return self.filing_target_records, SimpleNamespace(), []
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



def test_neo4j_repository_lists_and_writes_company_metadata():
    driver = FakeDriver()
    driver.metadata_target_records = [
        FakeRecord(cik="0001045810", name="NVIDIA CORP")
    ]
    repository = Neo4jGraphRepository(
        uri="bolt://unused",
        user="neo4j",
        password="test",
        driver=driver,
    )
    portfolio_id = uuid4()

    targets = repository.get_company_metadata_targets(portfolio_id, limit=25)
    repository.sync_company_metadata(
        {
            "0001045810": CompanyMetadata(
                cik="0001045810",
                industry_code="3674",
                industry_name="Semiconductors & Related Devices",
                country_code="X1",
                country_name="UNITED STATES",
                source_url="https://data.sec.gov/submissions/CIK0001045810.json",
            )
        }
    )

    assert len(targets) == 1
    assert targets[0].cik == "0001045810"
    assert targets[0].name == "NVIDIA CORP"

    target_query, target_call = driver.calls[0]
    assert "'sec_metadata_synced_at' IN keys(company)" in target_query
    assert target_call["portfolio_id"] == str(portfolio_id)
    assert target_call["limit"] == 25

    mark_query, mark_call = driver.calls[1]
    assert "sec_metadata_synced_at = datetime()" in mark_query
    assert mark_call["companies"][0]["cik"] == "0001045810"

    industry_query, industry_call = driver.calls[2]
    assert "MERGE (industry:Industry {sic: item.industry_code})" in industry_query
    assert industry_call["industries"][0]["industry_code"] == "3674"

    country_query, country_call = driver.calls[3]
    assert "MERGE (country:Country {sec_code: item.country_code})" in country_query
    assert country_call["countries"][0]["country_code"] == "X1"


def test_neo4j_repository_lists_and_writes_company_filings():
    driver = FakeDriver()
    driver.filing_target_records = [
        FakeRecord(cik="0001045810", name="NVIDIA CORP")
    ]
    repository = Neo4jGraphRepository(
        uri="bolt://unused",
        user="neo4j",
        password="test",
        driver=driver,
    )
    portfolio_id = uuid4()
    batch = CompanyFilings(
        cik="0001045810",
        source_url="https://data.sec.gov/submissions/CIK0001045810.json",
        filings=[
            SecFiling(
                cik="0001045810",
                accession_number="0001045810-26-000001",
                form="10-K",
                filing_date=date(2026, 2, 25),
                report_date=date(2026, 1, 25),
                primary_document="nvda-20260125.htm",
                source_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/nvda-20260125.htm",
                filing_index_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/0001045810-26-000001-index.html",
                submissions_url="https://data.sec.gov/submissions/CIK0001045810.json",
            )
        ],
    )

    targets = repository.get_company_filing_targets(portfolio_id, limit=5)
    repository.sync_company_filings({"0001045810": batch})

    assert targets[0].cik == "0001045810"
    target_query, target_call = driver.calls[0]
    assert "'sec_filings_synced_at' IN keys(company)" in target_query
    assert target_call["limit"] == 5

    mark_query, mark_call = driver.calls[1]
    assert "sec_filings_synced_at = datetime()" in mark_query
    assert mark_call["companies"][0]["cik"] == "0001045810"

    filing_query, filing_call = driver.calls[2]
    assert "MERGE (filing:Filing {accession_number: item.accession_number})" in filing_query
    assert "MERGE (company)-[r:FILED]->(filing)" in filing_query
    assert filing_call["filings"][0]["form"] == "10-K"
    assert filing_call["filings"][0]["filing_date"] == "2026-02-25"


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



def test_neo4j_repository_aggregates_structural_exposures():
    driver = FakeDriver()
    driver.industry_exposure_records = [
        FakeRecord(
            code="3674",
            name="Semiconductors & Related Devices",
            weight_pct=72.400000001,
        )
    ]
    driver.country_exposure_records = [
        FakeRecord(
            code="X1",
            name="UNITED STATES",
            weight_pct=74.500000001,
        )
    ]
    repository = Neo4jGraphRepository(
        uri="bolt://unused",
        user="neo4j",
        password="test",
        driver=driver,
    )
    portfolio_id = uuid4()

    industries = repository.get_industry_exposures(portfolio_id)
    countries = repository.get_country_exposures(portfolio_id)

    assert industries[0].code == "3674"
    assert industries[0].weight_pct == 72.4
    assert countries[0].code == "X1"
    assert countries[0].weight_pct == 74.5

    industry_query, industry_call = driver.calls[0]
    assert "owns.weight_pct * holds.weight_pct / 100.0" in industry_query
    assert "MATCH (company)-[:OPERATES_IN]->(industry:Industry)" in industry_query
    assert industry_call["portfolio_id"] == str(portfolio_id)

    country_query, country_call = driver.calls[1]
    assert "MATCH (company)-[:BASED_IN]->(country:Country)" in country_query
    assert country_call["portfolio_id"] == str(portfolio_id)

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
