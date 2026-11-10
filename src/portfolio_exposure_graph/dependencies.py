from portfolio_exposure_graph.core.config import settings
from portfolio_exposure_graph.providers.alpha_vantage_etf_provider import AlphaVantageEtfProvider
from portfolio_exposure_graph.providers.ollama_semantic_candidate_provider import (
    OllamaSemanticCandidateProvider,
)
from portfolio_exposure_graph.providers.sec_asset_provider import SecAssetProvider
from portfolio_exposure_graph.providers.sec_company_metadata_provider import SecCompanyMetadataProvider
from portfolio_exposure_graph.providers.sec_filing_evidence_provider import SecFilingEvidenceProvider
from portfolio_exposure_graph.providers.sec_filings_provider import SecFilingsProvider
from portfolio_exposure_graph.repositories.asset_registry import AssetRegistry, InMemoryAssetRegistry
from portfolio_exposure_graph.repositories.neo4j_graph_repository import Neo4jGraphRepository
from portfolio_exposure_graph.repositories.portfolio_repository import (
    InMemoryPortfolioRepository,
    PortfolioRepository,
)
from portfolio_exposure_graph.services.asset_resolver import AssetResolver
from portfolio_exposure_graph.services.enrichment_queue import EnrichmentQueue, InMemoryEnrichmentQueue
from portfolio_exposure_graph.services.enrichment_service import EnrichmentService
from portfolio_exposure_graph.services.graph_service import GraphService
from portfolio_exposure_graph.services.lookthrough_service import LookthroughService
from portfolio_exposure_graph.services.portfolio_service import PortfolioService



def _validated_store() -> str:
    store = settings.portfolio_store or "memory"
    if store not in ("memory", "postgres"):
        raise ValueError(
            f"Unsupported PORTFOLIO_STORE={settings.portfolio_store!r}; "
            "expected 'memory' or 'postgres'"
        )
    return store


def _require_postgres_driver() -> None:
    try:
        import psycopg  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "PORTFOLIO_STORE=postgres needs the PostgreSQL driver: "
            "pip install 'portfolio-exposure-graph[postgres]'"
        ) from exc


def build_portfolio_repository() -> PortfolioRepository:
    if _validated_store() == "postgres":
        _require_postgres_driver()
        from portfolio_exposure_graph.repositories.postgres_portfolio_repository import (
            PostgresPortfolioRepository,
        )

        return PostgresPortfolioRepository(dsn=settings.database_url)
    return InMemoryPortfolioRepository()


def build_asset_registry() -> AssetRegistry:
    if _validated_store() == "postgres":
        _require_postgres_driver()
        from portfolio_exposure_graph.repositories.postgres_asset_registry import PostgresAssetRegistry

        return PostgresAssetRegistry(dsn=settings.database_url)
    return InMemoryAssetRegistry()


def build_enrichment_queue() -> EnrichmentQueue:
    if _validated_store() == "postgres":
        _require_postgres_driver()
        from portfolio_exposure_graph.repositories.postgres_enrichment_queue import (
            PostgresEnrichmentQueue,
        )

        return PostgresEnrichmentQueue(dsn=settings.database_url)
    return InMemoryEnrichmentQueue()


asset_registry = build_asset_registry()
portfolio_repository = build_portfolio_repository()
enrichment_queue = build_enrichment_queue()
sec_asset_provider = SecAssetProvider(user_agent=settings.sec_user_agent)
sec_company_metadata_provider = SecCompanyMetadataProvider(
    user_agent=settings.sec_user_agent
)
sec_filings_provider = SecFilingsProvider(user_agent=settings.sec_user_agent)
sec_filing_evidence_provider = SecFilingEvidenceProvider(user_agent=settings.sec_user_agent)
alpha_vantage_etf_provider = AlphaVantageEtfProvider(
    api_key=settings.alpha_vantage_api_key
)
semantic_candidate_provider = (
    OllamaSemanticCandidateProvider(
        base_url=settings.ollama_base_url,
        model_name=settings.ollama_model,
    )
    if settings.semantic_provider == "ollama"
    else None
)
graph_repository = Neo4jGraphRepository(
    uri=settings.neo4j_uri,
    user=settings.neo4j_user,
    password=settings.neo4j_password,
    database=settings.neo4j_database,
)
asset_resolver = AssetResolver(
    asset_registry,
    providers=[alpha_vantage_etf_provider, sec_asset_provider],
)
portfolio_service = PortfolioService(
    repository=portfolio_repository,
    asset_resolver=asset_resolver,
    enrichment_queue=enrichment_queue,
)
lookthrough_service = LookthroughService(
    repository=portfolio_repository,
    etf_holdings_provider=alpha_vantage_etf_provider,
)

graph_service = GraphService(
    portfolio_repository=portfolio_repository,
    graph_repository=graph_repository,
    etf_holdings_provider=alpha_vantage_etf_provider,
    company_asset_provider=sec_asset_provider,
    company_metadata_provider=sec_company_metadata_provider,
    company_filings_provider=sec_filings_provider,
    filing_evidence_provider=sec_filing_evidence_provider,
    semantic_candidate_provider=semantic_candidate_provider,
    company_directory_provider=sec_asset_provider,
)

enrichment_service = EnrichmentService(
    queue=enrichment_queue,
    asset_resolver=asset_resolver,
    portfolio_repository=portfolio_repository,
    max_attempts=settings.enrichment_max_attempts,
    retry_base_seconds=settings.enrichment_retry_base_seconds,
    retry_max_seconds=settings.enrichment_retry_max_seconds,
)
