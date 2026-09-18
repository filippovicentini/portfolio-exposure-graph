from __future__ import annotations

import logging
from uuid import UUID

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import (
    CompanyMetadata,
    CompanyMetadataSyncResult,
    CompanyResolution,
    GraphSyncResult,
    PortfolioExposurePaths,
    PortfolioStructuralExposure,
)
from app.providers.base import (
    AssetDataProvider,
    CompanyMetadataProvider,
    EtfHoldingsProvider,
)
from app.repositories.graph_repository import GraphRepository
from app.repositories.portfolio_repository import PortfolioRepository

logger = logging.getLogger(__name__)


class GraphService:
    """Synchronize a portfolio into the graph and expose traversable paths."""

    def __init__(
        self,
        portfolio_repository: PortfolioRepository,
        graph_repository: GraphRepository,
        etf_holdings_provider: EtfHoldingsProvider,
        company_asset_provider: AssetDataProvider,
        company_metadata_provider: CompanyMetadataProvider,
    ) -> None:
        self.portfolio_repository = portfolio_repository
        self.graph_repository = graph_repository
        self.etf_holdings_provider = etf_holdings_provider
        self.company_asset_provider = company_asset_provider
        self.company_metadata_provider = company_metadata_provider

    def sync(self, portfolio_id: UUID) -> GraphSyncResult | None:
        portfolio = self.portfolio_repository.get(portfolio_id)
        if portfolio is None:
            return None

        etf_holdings = {}
        unexpanded_etfs: list[str] = []

        for position in portfolio.positions:
            if (
                position.asset.status != AssetStatus.READY
                or position.asset.asset_type != AssetType.ETF
            ):
                continue

            ticker = position.ticker.upper()
            try:
                holdings = self.etf_holdings_provider.get_holdings(ticker)
            except Exception:
                logger.exception("ETF holdings provider failed for graph sync: %s", ticker)
                unexpanded_etfs.append(ticker)
                continue

            positive_holdings = [holding for holding in holdings if holding.weight_pct > 0]
            if not positive_holdings:
                unexpanded_etfs.append(ticker)
                continue
            etf_holdings[ticker] = positive_holdings

        company_tickers = {
            position.ticker.upper()
            for position in portfolio.positions
            if position.asset.status == AssetStatus.READY
            and position.asset.asset_type == AssetType.EQUITY
        }
        for holdings in etf_holdings.values():
            company_tickers.update(holding.ticker.upper() for holding in holdings)

        company_resolutions, unresolved_company_assets = self._resolve_companies(
            company_tickers
        )

        self.graph_repository.sync_portfolio(
            portfolio,
            etf_holdings,
            company_resolutions,
        )

        synced_positions = [
            position
            for position in portfolio.positions
            if position.asset.status == AssetStatus.READY
            and position.asset.asset_type in {AssetType.EQUITY, AssetType.ETF}
        ]
        asset_tickers = {position.ticker for position in synced_positions}
        for holdings in etf_holdings.values():
            asset_tickers.update(holding.ticker for holding in holdings)

        return GraphSyncResult(
            portfolio_id=portfolio.portfolio_id,
            assets_synced=len(asset_tickers),
            companies_synced=len({item.cik for item in company_resolutions.values()}),
            ownership_edges_synced=len(synced_positions),
            holding_edges_synced=sum(len(items) for items in etf_holdings.values()),
            represents_edges_synced=len(company_resolutions),
            unexpanded_etfs=sorted(set(unexpanded_etfs)),
            unresolved_company_assets=unresolved_company_assets,
        )


    def sync_company_metadata(
        self,
        portfolio_id: UUID,
        limit: int = 25,
    ) -> CompanyMetadataSyncResult | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        targets = self.graph_repository.get_company_metadata_targets(
            portfolio_id,
            limit=limit,
        )
        metadata_by_cik: dict[str, CompanyMetadata] = {}
        unresolved: list[str] = []

        for target in targets:
            try:
                metadata = self.company_metadata_provider.get_metadata(target.cik)
            except Exception:
                logger.exception(
                    "Company metadata provider failed for CIK %s",
                    target.cik,
                )
                unresolved.append(target.cik)
                continue

            if metadata is None:
                unresolved.append(target.cik)
                continue
            metadata_by_cik[target.cik] = metadata

        self.graph_repository.sync_company_metadata(metadata_by_cik)

        return CompanyMetadataSyncResult(
            portfolio_id=portfolio_id,
            companies_requested=len(targets),
            companies_enriched=len(metadata_by_cik),
            industry_edges_synced=sum(
                1
                for item in metadata_by_cik.values()
                if item.industry_code and item.industry_name
            ),
            country_edges_synced=sum(
                1
                for item in metadata_by_cik.values()
                if item.country_code and item.country_name
            ),
            unresolved_company_ciks=sorted(set(unresolved)),
        )

    def get_paths(self, portfolio_id: UUID) -> PortfolioExposurePaths | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None
        return PortfolioExposurePaths(
            portfolio_id=portfolio_id,
            paths=self.graph_repository.get_exposure_paths(portfolio_id),
        )

    def get_structural_exposure(
        self,
        portfolio_id: UUID,
    ) -> PortfolioStructuralExposure | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        industries = self.graph_repository.get_industry_exposures(portfolio_id)
        countries = self.graph_repository.get_country_exposures(portfolio_id)
        return PortfolioStructuralExposure(
            portfolio_id=portfolio_id,
            industries=industries,
            countries=countries,
            industry_coverage_pct=round(
                sum(item.weight_pct for item in industries),
                6,
            ),
            country_coverage_pct=round(
                sum(item.weight_pct for item in countries),
                6,
            ),
        )

    def _resolve_companies(
        self,
        tickers: set[str],
    ) -> tuple[dict[str, CompanyResolution], list[str]]:
        resolutions: dict[str, CompanyResolution] = {}
        unresolved: list[str] = []
        ordered_tickers = sorted(tickers)

        for index, ticker in enumerate(ordered_tickers):
            try:
                asset = self.company_asset_provider.resolve(ticker)
            except Exception:
                logger.exception("Company asset provider failed during graph sync")
                unresolved.extend(ordered_tickers[index:])
                break

            if (
                asset is None
                or asset.status != AssetStatus.READY
                or asset.asset_type != AssetType.EQUITY
                or not asset.cik
                or not asset.company_name
            ):
                unresolved.append(ticker)
                continue

            resolutions[ticker] = CompanyResolution(
                ticker=ticker,
                cik=asset.cik,
                name=asset.company_name,
                exchange=asset.exchange,
            )

        return resolutions, sorted(set(unresolved))
