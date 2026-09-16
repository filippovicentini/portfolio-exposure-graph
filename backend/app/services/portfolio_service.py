from __future__ import annotations

from uuid import UUID

from app.domain.enums import AssetStatus, PortfolioStatus
from app.domain.models import Portfolio, PortfolioCreate, PortfolioPosition
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.asset_resolver import AssetResolver
from app.services.enrichment_queue import EnrichmentQueue


class PortfolioService:
    def __init__(
        self,
        repository: PortfolioRepository,
        asset_resolver: AssetResolver,
        enrichment_queue: EnrichmentQueue,
    ) -> None:
        self.repository = repository
        self.asset_resolver = asset_resolver
        self.enrichment_queue = enrichment_queue

    def create(self, payload: PortfolioCreate) -> Portfolio:
        positions: list[PortfolioPosition] = []
        jobs = []

        for position in payload.positions:
            asset = self.asset_resolver.resolve(position.ticker)
            positions.append(
                PortfolioPosition(
                    ticker=position.ticker,
                    weight_pct=position.weight_pct,
                    asset=asset,
                )
            )

            if asset.status == AssetStatus.PENDING_ENRICHMENT:
                jobs.append(self.enrichment_queue.enqueue(asset.ticker))

        status = PortfolioStatus.PARTIALLY_READY if jobs else PortfolioStatus.READY
        portfolio = Portfolio(
            name=payload.name,
            status=status,
            positions=positions,
            enrichment_jobs=jobs,
        )
        return self.repository.save(portfolio)

    def get(self, portfolio_id: UUID) -> Portfolio | None:
        return self.repository.get(portfolio_id)
