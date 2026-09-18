from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from neo4j import GraphDatabase

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import (
    CompanyResolution,
    EtfHolding,
    ExposurePath,
    Portfolio,
)
from app.repositories.graph_repository import GraphRepository


class Neo4jGraphRepository(GraphRepository):
    """Store portfolio, asset, ETF holding, and canonical company graph data."""

    UPSERT_PORTFOLIO_QUERY = """
    MERGE (p:Portfolio {portfolio_id: $portfolio_id})
    SET p.name = $name,
        p.status = $status,
        p.updated_at = datetime()
    WITH p
    OPTIONAL MATCH (p)-[r:OWNS]->()
    DELETE r
    """

    UPSERT_POSITIONS_QUERY = """
    MATCH (p:Portfolio {portfolio_id: $portfolio_id})
    UNWIND $positions AS position
    MERGE (a:Asset {ticker: position.ticker})
    SET a.asset_type = position.asset_type,
        a.name = position.name,
        a.exchange = position.exchange,
        a.cik = position.cik,
        a.updated_at = datetime()
    FOREACH (_ IN CASE WHEN position.asset_type = 'etf' THEN [1] ELSE [] END |
        SET a:ETF
    )
    FOREACH (_ IN CASE WHEN position.asset_type = 'equity' THEN [1] ELSE [] END |
        SET a:Equity
    )
    MERGE (p)-[r:OWNS]->(a)
    SET r.weight_pct = position.weight_pct,
        r.updated_at = datetime()
    """

    DELETE_ETF_HOLDINGS_QUERY = """
    UNWIND $etf_tickers AS etf_ticker
    MATCH (etf:Asset {ticker: etf_ticker})-[r:HOLDS]->()
    DELETE r
    """

    UPSERT_ETF_HOLDINGS_QUERY = """
    UNWIND $holdings AS holding
    MERGE (etf:Asset {ticker: holding.etf_ticker})
    SET etf:ETF,
        etf.asset_type = 'etf',
        etf.updated_at = datetime()
    MERGE (asset:Asset {ticker: holding.ticker})
    ON CREATE SET asset.asset_type = 'unknown'
    SET asset.name = coalesce(asset.name, holding.description),
        asset.updated_at = datetime()
    MERGE (etf)-[r:HOLDS]->(asset)
    SET r.weight_pct = holding.weight_pct,
        r.updated_at = datetime()
    """

    UPSERT_COMPANIES_QUERY = """
    UNWIND $companies AS company
    MATCH (asset:Asset {ticker: company.ticker})
    SET asset:Equity,
        asset.asset_type = 'equity',
        asset.name = company.name,
        asset.exchange = company.exchange,
        asset.cik = company.cik,
        asset.updated_at = datetime()
    WITH asset, company
    OPTIONAL MATCH (asset)-[old:REPRESENTS]->(:Company)
    DELETE old
    WITH asset, company
    MERGE (canonical:Company {cik: company.cik})
    SET canonical.name = company.name,
        canonical.updated_at = datetime()
    MERGE (asset)-[r:REPRESENTS]->(canonical)
    SET r.updated_at = datetime()
    """

    EXPOSURE_PATHS_QUERY = """
    MATCH (p:Portfolio {portfolio_id: $portfolio_id})-[owns:OWNS]->(asset:Asset:Equity)
    RETURN [asset.ticker] AS asset_path,
           ['OWNS'] AS relations,
           owns.weight_pct AS effective_weight_pct
    UNION ALL
    MATCH (p:Portfolio {portfolio_id: $portfolio_id})-[owns:OWNS]->(etf:Asset:ETF)-[holds:HOLDS]->(asset:Asset)
    RETURN [etf.ticker, asset.ticker] AS asset_path,
           ['OWNS', 'HOLDS'] AS relations,
           owns.weight_pct * holds.weight_pct / 100.0 AS effective_weight_pct
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver=None,
    ) -> None:
        self.database = database
        self.driver = driver or GraphDatabase.driver(uri, auth=(user, password))

    def sync_portfolio(
        self,
        portfolio: Portfolio,
        etf_holdings: Mapping[str, list[EtfHolding]],
        company_resolutions: Mapping[str, CompanyResolution],
    ) -> None:
        portfolio_id = str(portfolio.portfolio_id)
        positions = [
            {
                "ticker": position.ticker,
                "weight_pct": position.weight_pct,
                "asset_type": position.asset.asset_type.value,
                "name": position.asset.company_name,
                "exchange": position.asset.exchange,
                "cik": position.asset.cik,
            }
            for position in portfolio.positions
            if position.asset.status == AssetStatus.READY
            and position.asset.asset_type in {AssetType.EQUITY, AssetType.ETF}
        ]

        self.driver.execute_query(
            self.UPSERT_PORTFOLIO_QUERY,
            portfolio_id=portfolio_id,
            name=portfolio.name,
            status=portfolio.status.value,
            database_=self.database,
        )

        if positions:
            self.driver.execute_query(
                self.UPSERT_POSITIONS_QUERY,
                portfolio_id=portfolio_id,
                positions=positions,
                database_=self.database,
            )

        etf_tickers = sorted(etf_holdings)
        if etf_tickers:
            self.driver.execute_query(
                self.DELETE_ETF_HOLDINGS_QUERY,
                etf_tickers=etf_tickers,
                database_=self.database,
            )

            holdings = [
                {
                    "etf_ticker": etf_ticker,
                    "ticker": holding.ticker,
                    "description": holding.description,
                    "weight_pct": holding.weight_pct,
                }
                for etf_ticker, items in etf_holdings.items()
                for holding in items
                if holding.weight_pct > 0
            ]
            if holdings:
                self.driver.execute_query(
                    self.UPSERT_ETF_HOLDINGS_QUERY,
                    holdings=holdings,
                    database_=self.database,
                )

        if company_resolutions:
            companies = [
                {
                    "ticker": resolution.ticker,
                    "cik": resolution.cik,
                    "name": resolution.name,
                    "exchange": resolution.exchange,
                }
                for _, resolution in sorted(company_resolutions.items())
            ]
            self.driver.execute_query(
                self.UPSERT_COMPANIES_QUERY,
                companies=companies,
                database_=self.database,
            )

    def get_exposure_paths(self, portfolio_id: UUID) -> list[ExposurePath]:
        records, _, _ = self.driver.execute_query(
            self.EXPOSURE_PATHS_QUERY,
            portfolio_id=str(portfolio_id),
            database_=self.database,
        )
        paths = [
            ExposurePath(
                asset_path=list(record["asset_path"]),
                relations=list(record["relations"]),
                effective_weight_pct=round(float(record["effective_weight_pct"]), 6),
            )
            for record in records
        ]
        paths.sort(key=lambda item: (-item.effective_weight_pct, item.asset_path))
        return paths

    def close(self) -> None:
        self.driver.close()
