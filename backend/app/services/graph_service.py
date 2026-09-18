from __future__ import annotations

import logging
from uuid import UUID

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import GraphSyncResult, PortfolioExposurePaths
from app.providers.base import EtfHoldingsProvider
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
    ) -> None:
        self.portfolio_repository = portfolio_repository
        self.graph_repository = graph_repository
        self.etf_holdings_provider = etf_holdings_provider

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

        self.graph_repository.sync_portfolio(portfolio, etf_holdings)

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
            ownership_edges_synced=len(synced_positions),
            holding_edges_synced=sum(len(items) for items in etf_holdings.values()),
            unexpanded_etfs=sorted(set(unexpanded_etfs)),
        )

    def get_paths(self, portfolio_id: UUID) -> PortfolioExposurePaths | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None
        return PortfolioExposurePaths(
            portfolio_id=portfolio_id,
            paths=self.graph_repository.get_exposure_paths(portfolio_id),
        )
