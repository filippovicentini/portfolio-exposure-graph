"""UCITS ETFs: recognition and look-through from issuers' published files.

European UCITS ETFs are not in SEC or US listing data. This provider knows a
registry of funds (``data/ucits_etfs.json``) by ISIN and by their exchange
tickers, and reads each fund's holdings from the file its issuer publishes:

- iShares: ``latest-holdings.csv`` on the product page (ticker, sector,
  location, exchange, weight);
- Xtrackers (DWS): the constituent Excel export (name, ISIN, country,
  industry, weight; no tickers).

Only constituents located in the United States are marked ``us_listed`` and
keep their plain ticker, so they can be resolved to SEC companies. Every
other constituent gets a listing-qualified identifier (or its ISIN) and is
never resolved by ticker, because local tickers collide with unrelated US
ones. All constituents keep the issuer's country and sector, which feed the
look-through classification.

Issuers whose holdings have no stable public file (Vanguard, for now) are
recognised, so the position is valid, but report no holdings: the ETF shows
up as not expanded rather than being guessed.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass
from importlib import resources

import httpx

from portfolio_exposure_graph.domain.enums import AssetStatus, AssetType
from portfolio_exposure_graph.domain.models import AssetResolution, EtfHolding
from portfolio_exposure_graph.providers.base import AssetDataProvider, EtfHoldingsProvider

logger = logging.getLogger(__name__)

ISHARES_HOLDINGS_URL = (
    "https://www.ishares.com/uk/individual/en/products/{product_id}/fund/latest-holdings.csv"
)
XTRACKERS_HOLDINGS_URL = (
    "https://etf.dws.com/etfdata/export/GBR/ENG/excel/product/constituent/{isin}/"
)
SUPPORTED_ISSUERS = {"ishares", "xtrackers"}
_US = {"united states", "united states of america", "usa", "us"}


@dataclass(frozen=True)
class UcitsFund:
    isin: str
    name: str
    issuer: str
    tickers: tuple[str, ...]
    ishares_product_id: str | None = None

    @property
    def holdings_supported(self) -> bool:
        return self.issuer in SUPPORTED_ISSUERS


def load_registry() -> list[UcitsFund]:
    raw = json.loads(
        resources.files("portfolio_exposure_graph.data")
        .joinpath("ucits_etfs.json")
        .read_text(encoding="utf-8")
    )
    return [
        UcitsFund(
            isin=item["isin"].upper(),
            name=item["name"],
            issuer=item["issuer"],
            tickers=tuple(ticker.upper() for ticker in item.get("tickers", [])),
            ishares_product_id=item.get("ishares_product_id"),
        )
        for item in raw["funds"]
    ]


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in {"", "-"} else text


def parse_ishares_holdings(text: str) -> list[EtfHolding]:
    """Parse an iShares ``latest-holdings.csv`` (preamble lines, then a table)."""
    lines = text.lstrip("﻿").splitlines()
    header_index = next(
        (i for i, line in enumerate(lines) if line.startswith("Ticker,")), None
    )
    if header_index is None:
        raise ValueError("Unexpected iShares holdings file: no 'Ticker,' header row")

    holdings: list[EtfHolding] = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[header_index:]))):
        raw_ticker = _clean(row.get("Ticker"))
        weight = _number(row.get("Weight (%)"))
        if raw_ticker is None or weight is None or not 0 <= weight <= 100:
            continue
        country = _clean(row.get("Location"))
        exchange = _clean(row.get("Exchange"))
        asset_class = _clean(row.get("Asset Class"))
        is_equity = (asset_class or "").casefold() == "equity"
        us_listed = is_equity and (country or "").casefold() in _US
        if us_listed:
            # iShares writes share classes with a space ("BRK B"); SEC uses "BRK-B".
            identifier = raw_ticker.upper().replace(" ", "-")
        else:
            identifier = f"{raw_ticker.upper()} @ {exchange or country or 'unknown'}"[:64]
        holdings.append(
            EtfHolding(
                ticker=identifier,
                description=_clean(row.get("Name")),
                weight_pct=weight,
                country=country,
                sector=_clean(row.get("Sector")),
                asset_class=asset_class,
                exchange=exchange,
                us_listed=us_listed,
            )
        )
    return holdings


def parse_xtrackers_holdings(content: bytes) -> list[EtfHolding]:
    """Parse a DWS/Xtrackers constituent Excel export."""
    from openpyxl import load_workbook

    sheet = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
    rows = list(sheet.iter_rows(values_only=True))
    header_index = next(
        (
            i
            for i, row in enumerate(rows)
            if row and "Name" in row and "ISIN" in row and "Weighting" in row
        ),
        None,
    )
    if header_index is None:
        raise ValueError("Unexpected Xtrackers holdings file: no Name/ISIN/Weighting header")
    columns = {name: index for index, name in enumerate(rows[header_index]) if name}

    def cell(row: tuple, name: str) -> object:
        index = columns.get(name)
        return row[index] if index is not None and index < len(row) else None

    holdings: list[EtfHolding] = []
    for row in rows[header_index + 1 :]:
        name = _clean(cell(row, "Name"))
        isin = _clean(cell(row, "ISIN"))
        fraction = _number(cell(row, "Weighting"))
        if name is None or fraction is None or not 0 <= fraction <= 1:
            continue
        holdings.append(
            EtfHolding(
                # No tickers in this file: the ISIN identifies the constituent.
                ticker=(isin or name)[:64],
                description=name,
                weight_pct=fraction * 100.0,
                isin=isin,
                country=_clean(cell(row, "Country")),
                sector=_clean(cell(row, "Industry Classification")),
                asset_class=_clean(cell(row, "Type of Security")),
                exchange=_clean(cell(row, "Exchange")),
                # Without a ticker there is nothing safe to resolve by.
                us_listed=False,
            )
        )
    return holdings


class UcitsEtfProvider(AssetDataProvider, EtfHoldingsProvider):
    """Resolve registered UCITS ETFs by ticker or ISIN and expand their holdings."""

    def __init__(
        self,
        funds: list[UcitsFund] | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.funds = funds if funds is not None else load_registry()
        self.client = client or httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": "portfolio-exposure-graph (holdings look-through)"},
        )
        self.timeout_seconds = timeout_seconds
        self._by_key: dict[str, UcitsFund] = {}
        for fund in self.funds:
            for key in (fund.isin, *fund.tickers):
                self._by_key.setdefault(key, fund)
        self._holdings: dict[str, list[EtfHolding]] = {}

    def fund_for(self, ticker_or_isin: str) -> UcitsFund | None:
        return self._by_key.get(ticker_or_isin.strip().upper())

    def resolve(self, ticker: str) -> AssetResolution | None:
        fund = self.fund_for(ticker)
        if fund is None:
            return None
        return AssetResolution(
            ticker=ticker.strip().upper(),
            asset_type=AssetType.ETF,
            status=AssetStatus.READY,
            company_name=fund.name,
            isin=fund.isin,
        )

    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        fund = self.fund_for(ticker)
        if fund is None or not fund.holdings_supported:
            return []
        cached = self._holdings.get(fund.isin)
        if cached is not None:
            return cached

        if fund.issuer == "ishares":
            response = self.client.get(
                ISHARES_HOLDINGS_URL.format(product_id=fund.ishares_product_id),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            holdings = parse_ishares_holdings(response.text)
        else:
            response = self.client.get(
                XTRACKERS_HOLDINGS_URL.format(isin=fund.isin),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            holdings = parse_xtrackers_holdings(response.content)

        self._holdings[fund.isin] = holdings
        return holdings


class RoutingEtfHoldingsProvider(EtfHoldingsProvider):
    """Send UCITS ETFs to the UCITS provider and everything else to the fallback."""

    def __init__(self, ucits: UcitsEtfProvider, fallback: EtfHoldingsProvider) -> None:
        self.ucits = ucits
        self.fallback = fallback

    def get_holdings(self, ticker: str) -> list[EtfHolding]:
        if self.ucits.fund_for(ticker) is not None:
            return self.ucits.get_holdings(ticker)
        return self.fallback.get_holdings(ticker)
