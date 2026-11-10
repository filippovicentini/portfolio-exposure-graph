from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from portfolio_exposure_graph.domain.enums import AssetStatus
from portfolio_exposure_graph.domain.models import Portfolio

# Positions an enrichment job may still resolve.
UNRESOLVED_ASSET_STATUSES = (AssetStatus.PENDING_ENRICHMENT, AssetStatus.UNSUPPORTED)


class PortfolioRepository(ABC):
    @abstractmethod
    def save(self, portfolio: Portfolio) -> Portfolio:
        raise NotImplementedError

    @abstractmethod
    def get(self, portfolio_id: UUID) -> Portfolio | None:
        raise NotImplementedError

    @abstractmethod
    def list(self, limit: int = 50) -> list[Portfolio]:
        """Return the most recently created portfolios first."""
        raise NotImplementedError

    @abstractmethod
    def find_with_unresolved_ticker(self, ticker: str) -> list[Portfolio]:
        """Return portfolios holding ``ticker`` as PENDING_ENRICHMENT or UNSUPPORTED."""
        raise NotImplementedError


class InMemoryPortfolioRepository(PortfolioRepository):
    def __init__(self) -> None:
        self._portfolios: dict[UUID, Portfolio] = {}

    def save(self, portfolio: Portfolio) -> Portfolio:
        self._portfolios[portfolio.portfolio_id] = portfolio
        return portfolio

    def get(self, portfolio_id: UUID) -> Portfolio | None:
        return self._portfolios.get(portfolio_id)

    def list(self, limit: int = 50) -> list[Portfolio]:
        ordered = sorted(
            self._portfolios.values(),
            key=lambda portfolio: portfolio.created_at,
            reverse=True,
        )
        return ordered[:limit]

    def find_with_unresolved_ticker(self, ticker: str) -> list[Portfolio]:
        return [
            portfolio
            for portfolio in self._portfolios.values()
            if any(
                position.ticker == ticker
                and position.asset.status in UNRESOLVED_ASSET_STATUSES
                for position in portfolio.positions
            )
        ]
