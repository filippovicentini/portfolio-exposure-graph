from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from uuid import UUID

from app.domain.models import CompanyResolution, EtfHolding, ExposurePath, Portfolio


class GraphRepository(ABC):
    """Persistence boundary for portfolio exposure graph data."""

    @abstractmethod
    def sync_portfolio(
        self,
        portfolio: Portfolio,
        etf_holdings: Mapping[str, list[EtfHolding]],
        company_resolutions: Mapping[str, CompanyResolution],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_exposure_paths(self, portfolio_id: UUID) -> list[ExposurePath]:
        raise NotImplementedError

    def close(self) -> None:
        """Release repository resources when needed."""
