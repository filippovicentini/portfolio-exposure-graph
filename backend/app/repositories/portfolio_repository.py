from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.models import Portfolio


class PortfolioRepository(ABC):
    @abstractmethod
    def save(self, portfolio: Portfolio) -> Portfolio:
        raise NotImplementedError

    @abstractmethod
    def get(self, portfolio_id: UUID) -> Portfolio | None:
        raise NotImplementedError


class InMemoryPortfolioRepository(PortfolioRepository):
    def __init__(self) -> None:
        self._portfolios: dict[UUID, Portfolio] = {}

    def save(self, portfolio: Portfolio) -> Portfolio:
        self._portfolios[portfolio.portfolio_id] = portfolio
        return portfolio

    def get(self, portfolio_id: UUID) -> Portfolio | None:
        return self._portfolios.get(portfolio_id)
