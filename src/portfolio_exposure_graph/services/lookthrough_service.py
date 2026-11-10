from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from portfolio_exposure_graph.domain.enums import AssetType
from portfolio_exposure_graph.domain.models import (
    ClassificationBucket,
    EtfHolding,
    ExposureBreakdown,
    Portfolio,
    PortfolioLookthrough,
)
from portfolio_exposure_graph.providers.base import EtfHoldingsProvider
from portfolio_exposure_graph.repositories.portfolio_repository import PortfolioRepository

logger = logging.getLogger(__name__)

UNCLASSIFIED = "Unclassified"
NOT_EXPANDED = "ETF holdings not available"

# Issuers spell the same classification differently; sums must not split.
_COUNTRY_ALIASES = {
    "korea (south)": "South Korea",
    "korea, republic of": "South Korea",
    "republic of korea": "South Korea",
    "korea": "South Korea",
    "russian federation": "Russia",
    "united states of america": "United States",
    "usa": "United States",
    "uk": "United Kingdom",
    "taiwan, province of china": "Taiwan",
    "czechia": "Czech Republic",
}
_SECTOR_ALIASES = {
    "communication": "Communication Services",
    "telecommunication services": "Communication Services",
    "information tech": "Information Technology",
    "it": "Information Technology",
}
_EQUITY_CLASSES = {
    "equity",
    "equities",
    "depository receipts",
    "preferred stock",
    "real estate investment trust",
    "share class",
    "right",
    "rights",
    "common stock",
}
_CASH_CLASSES = {
    "cash",
    "fx",
    "futures",
    "money market",
    "cash collateral and margins",
    "cash and/or derivatives",
}


def _blank(value: str | None) -> bool:
    return value is None or value.strip().casefold() in {"", "-", "none", "unknown", "n/a"}


def normalize_country(value: str | None) -> str:
    if _blank(value):
        return UNCLASSIFIED
    return _COUNTRY_ALIASES.get(value.strip().casefold(), value.strip())


def normalize_sector(value: str | None) -> str:
    if _blank(value):
        return UNCLASSIFIED
    return _SECTOR_ALIASES.get(value.strip().casefold(), value.strip())


def normalize_asset_class(value: str | None) -> str:
    if _blank(value):
        return UNCLASSIFIED
    key = value.strip().casefold()
    if key in _EQUITY_CLASSES:
        return "Equity"
    if key in _CASH_CLASSES:
        return "Cash and derivatives"
    return value.strip()


def _known(normalize, value: str | None) -> str | None:
    """Per-holding field: None when the issuer gave nothing (not a bucket name)."""
    return None if _blank(value) else normalize(value)


def _buckets(weights: dict[str, float]) -> list[ClassificationBucket]:
    buckets = [
        ClassificationBucket(name=name, weight_pct=round(weight, 6))
        for name, weight in weights.items()
        if round(weight, 6) != 0
    ]
    # Largest first; the catch-all buckets go last.
    catch_all = {UNCLASSIFIED, NOT_EXPANDED}
    buckets.sort(key=lambda item: (item.name in catch_all, -item.weight_pct, item.name))
    return buckets


@dataclass(frozen=True)
class ConstituentExposure:
    """One ETF constituent's share of the portfolio (position x holding weight)."""

    etf_ticker: str
    holding: EtfHolding
    weight_pct: float


@dataclass(frozen=True)
class EtfExpansion:
    etf_ticker: str
    position_weight_pct: float
    constituents: list[ConstituentExposure]
    # Part of the position the published holdings do not cover (cash, gaps).
    uncovered_weight_pct: float
    expanded: bool


def expand_etf_positions(
    portfolio: Portfolio, provider: EtfHoldingsProvider
) -> list[EtfExpansion]:
    """Expand every ETF position one level.

    Issuers round each weight (iShares to 2 decimals), so over a thousand
    holdings the published weights can add up to slightly more than 100%;
    they are then scaled down proportionally. A shortfall below 100% is
    never redistributed: it is returned as uncovered weight.
    """
    expansions: list[EtfExpansion] = []
    for position in portfolio.positions:
        if position.asset.asset_type != AssetType.ETF:
            continue
        ticker = position.ticker.upper()
        weight = position.weight_pct
        try:
            holdings = provider.get_holdings(ticker)
        except Exception:
            logger.exception("ETF holdings provider failed for ticker %s", ticker)
            holdings = []
        if not holdings:
            expansions.append(EtfExpansion(ticker, weight, [], weight, expanded=False))
            continue
        published = sum(holding.weight_pct for holding in holdings)
        scale = 100.0 / published if published > 100.0 else 1.0
        constituents = [
            ConstituentExposure(ticker, holding, weight * holding.weight_pct * scale / 100.0)
            for holding in holdings
        ]
        covered = sum(item.weight_pct for item in constituents)
        expansions.append(
            EtfExpansion(ticker, weight, constituents, weight - covered, expanded=True)
        )
    return expansions


class LookthroughService:
    """Expand ETF positions one level and aggregate exposure and classification."""

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
        details: dict[str, EtfHolding] = {}
        unexpanded_etfs: list[str] = []
        countries: dict[str, float] = defaultdict(float)
        sectors: dict[str, float] = defaultdict(float)
        asset_classes: dict[str, float] = defaultdict(float)

        for position in portfolio.positions:
            ticker = position.ticker.upper()
            weight = position.weight_pct

            if position.asset.asset_type == AssetType.EQUITY:
                direct[ticker] += weight
                countries[UNCLASSIFIED] += weight
                sectors[UNCLASSIFIED] += weight
                asset_classes["Equity"] += weight
                continue

            if position.asset.asset_type != AssetType.ETF:
                # Pending or unsupported: counted, but nothing is known about it.
                for breakdown in (countries, sectors, asset_classes):
                    breakdown[UNCLASSIFIED] += weight

        for expansion in expand_etf_positions(portfolio, self.etf_holdings_provider):
            if not expansion.expanded:
                unexpanded_etfs.append(expansion.etf_ticker)
                for breakdown in (countries, sectors, asset_classes):
                    breakdown[NOT_EXPANDED] += expansion.position_weight_pct
                continue
            for item in expansion.constituents:
                holding = item.holding
                indirect[holding.ticker] += item.weight_pct
                via_etfs[holding.ticker].add(expansion.etf_ticker)
                details.setdefault(holding.ticker, holding)
                countries[normalize_country(holding.country)] += item.weight_pct
                sectors[normalize_sector(holding.sector)] += item.weight_pct
                asset_classes[normalize_asset_class(holding.asset_class)] += item.weight_pct
            if abs(expansion.uncovered_weight_pct) > 1e-9:
                for breakdown in (countries, sectors, asset_classes):
                    breakdown[UNCLASSIFIED] += expansion.uncovered_weight_pct

        exposures = []
        for key in set(direct) | set(indirect):
            holding = details.get(key)
            exposures.append(
                ExposureBreakdown(
                    ticker=key,
                    direct_weight_pct=round(direct[key], 6),
                    indirect_weight_pct=round(indirect[key], 6),
                    total_weight_pct=round(direct[key] + indirect[key], 6),
                    via_etfs=sorted(via_etfs[key]),
                    name=holding.description if holding else None,
                    country=_known(normalize_country, holding.country) if holding else None,
                    sector=_known(normalize_sector, holding.sector) if holding else None,
                    asset_class=(
                        _known(normalize_asset_class, holding.asset_class) if holding else None
                    ),
                )
            )
        exposures.sort(key=lambda item: (-item.total_weight_pct, item.ticker))

        analysed = sum(position.weight_pct for position in portfolio.positions)
        return PortfolioLookthrough(
            portfolio_id=portfolio.portfolio_id,
            exposures=exposures,
            unexpanded_etfs=sorted(set(unexpanded_etfs)),
            analysed_weight_pct=round(analysed, 6),
            not_analysed_weight_pct=round(max(0.0, 100.0 - analysed), 6),
            countries=_buckets(countries),
            sectors=_buckets(sectors),
            asset_classes=_buckets(asset_classes),
        )
