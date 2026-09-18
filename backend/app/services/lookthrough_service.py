from __future__ import annotations

import logging
from collections import defaultdict
from uuid import UUID

from app.domain.enums import AssetType
from app.domain.models import ExposureBreakdown, PortfolioLookthrough
from app.providers.base import EtfHoldingsProvider
from app.repositories.portfolio_repository import PortfolioRepository

logger = logging.getLogger(__name__)


class LookthroughService:
    """Expand ETF positions one level and aggregate known ticker exposure."""

    def __init__(
        self,
        repository: PortfolioRepository,
        etf_holdings_provider: EtfHoldingsProvider,
    ) -> None:
        self.repository = repository
        self.etf_holdings_provider = etf_holdings_provider

    def calculate(self, portfolio_id: UUID) -> PortfolioLookthrough | None:
        portfolio = self.repository.get(portfolio_id)
        if portfolio is None:
            return None

        direct: dict[str, float] = defaultdict(float)
        indirect: dict[str, float] = defaultdict(float)
        via_etfs: dict[str, set[str]] = defaultdict(set)
        unexpanded_etfs: list[str] = []

        for position in portfolio.positions:
            ticker = position.ticker.upper()

            if position.asset.asset_type == AssetType.EQUITY:
                direct[ticker] += position.weight_pct
                continue

            if position.asset.asset_type != AssetType.ETF:
                continue

            try:
                holdings = self.etf_holdings_provider.get_holdings(ticker)
            except Exception:
                logger.exception("ETF holdings provider failed for ticker %s", ticker)
                unexpanded_etfs.append(ticker)
                continue

            if not holdings:
                unexpanded_etfs.append(ticker)
                continue

            for holding in holdings:
                exposure = position.weight_pct * holding.weight_pct / 100.0
                indirect[holding.ticker] += exposure
                via_etfs[holding.ticker].add(ticker)

        exposure_tickers = set(direct) | set(indirect)
        exposures = []
        for ticker in exposure_tickers:
            direct_weight = direct[ticker]
            indirect_weight = indirect[ticker]
            total_weight = direct_weight + indirect_weight
            exposures.append(
                ExposureBreakdown(
                    ticker=ticker,
                    direct_weight_pct=round(direct_weight, 6),
                    indirect_weight_pct=round(indirect_weight, 6),
                    total_weight_pct=round(total_weight, 6),
                    via_etfs=sorted(via_etfs[ticker]),
                )
            )

        exposures.sort(key=lambda item: (-item.total_weight_pct, item.ticker))
        return PortfolioLookthrough(
            portfolio_id=portfolio.portfolio_id,
            exposures=exposures,
            unexpanded_etfs=sorted(set(unexpanded_etfs)),
        )
