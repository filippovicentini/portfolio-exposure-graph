from enum import StrEnum


class AssetType(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    UNKNOWN = "unknown"


class AssetStatus(StrEnum):
    READY = "ready"
    PENDING_ENRICHMENT = "pending_enrichment"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class PortfolioStatus(StrEnum):
    READY = "ready"
    PARTIALLY_READY = "partially_ready"


class NodeType(StrEnum):
    PORTFOLIO = "portfolio"
    ASSET = "asset"
    COMPANY = "company"
    ETF = "etf"
    INDUSTRY = "industry"
    COUNTRY = "country"
    SUPPLIER = "supplier"
    THEME = "theme"


class RelationType(StrEnum):
    OWNS = "OWNS"
    REPRESENTS = "REPRESENTS"
    HOLDS = "HOLDS"
    OPERATES_IN = "OPERATES_IN"
    BASED_IN = "BASED_IN"
    DEPENDS_ON = "DEPENDS_ON"
    EXPOSED_TO = "EXPOSED_TO"
