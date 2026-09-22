from enum import Enum


class AssetType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    UNKNOWN = "unknown"


class AssetStatus(str, Enum):
    READY = "ready"
    PENDING_ENRICHMENT = "pending_enrichment"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class PortfolioStatus(str, Enum):
    READY = "ready"
    PARTIALLY_READY = "partially_ready"


class NodeType(str, Enum):
    PORTFOLIO = "portfolio"
    ASSET = "asset"
    COMPANY = "company"
    ETF = "etf"
    INDUSTRY = "industry"
    COUNTRY = "country"
    SUPPLIER = "supplier"
    FILING = "filing"
    EVIDENCE = "evidence"
    THEME = "theme"


class RelationType(str, Enum):
    OWNS = "OWNS"
    REPRESENTS = "REPRESENTS"
    HOLDS = "HOLDS"
    OPERATES_IN = "OPERATES_IN"
    BASED_IN = "BASED_IN"
    DEPENDS_ON = "DEPENDS_ON"
    FILED = "FILED"
    CONTAINS_EVIDENCE = "CONTAINS_EVIDENCE"
    EXPOSED_TO = "EXPOSED_TO"
