from app.core.config import settings
from app.providers.alpha_vantage_etf_provider import AlphaVantageEtfProvider
from app.providers.ollama_semantic_candidate_provider import (
    OllamaSemanticCandidateProvider,
)
from app.providers.sec_asset_provider import SecAssetProvider
from app.providers.sec_company_metadata_provider import SecCompanyMetadataProvider
from app.providers.sec_filing_evidence_provider import SecFilingEvidenceProvider
from app.providers.sec_filings_provider import SecFilingsProvider
from app.repositories.asset_registry import AssetRegistry, InMemoryAssetRegistry
from app.repositories.neo4j_graph_repository import Neo4jGraphRepository
from app.repositories.portfolio_repository import (
    InMemoryPortfolioRepository,
    PortfolioRepository,
)
from app.services.asset_resolver import AssetResolver
from app.services.enrichment_queue import EnrichmentQueue, InMemoryEnrichmentQueue
from app.services.enrichment_service import EnrichmentService
from app.services.graph_service import GraphService
from app.services.lookthrough_service import LookthroughService
from app.services.portfolio_service import PortfolioService



def _validated_store() -> str:
    store = settings.portfolio_store or "memory"
    if store not in ("memory", "postgres"):
        raise ValueError(
            f"Unsupported PORTFOLIO_STORE={settings.portfolio_store!r}; "
            "expected 'memory' or 'postgres'"
        )
    return store


def build_portfolio_repository() -> PortfolioRepository:
    if _validated_store() == "postgres":
        from app.repositories.postgres_portfolio_repository import (
            PostgresPortfolioRepository,
        )

        return PostgresPortfolioRepository(dsn=settings.database_url)
    return InMemoryPortfolioRepository()


def build_asset_registry() -> AssetRegistry:
    if _validated_store() == "postgres":
        from app.repositories.postgres_asset_registry import PostgresAssetRegistry

        return PostgresAssetRegistry(dsn=settings.database_url)
    return InMemoryAssetRegistry()


def build_enrichment_queue() -> EnrichmentQueue:
    if _validated_store() == "postgres":
        from app.repositories.postgres_enrichment_queue import (
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
)

enrichment_service = EnrichmentService(
    queue=enrichment_queue,
    asset_resolver=asset_resolver,
    portfolio_repository=portfolio_repository,
    max_attempts=settings.enrichment_max_attempts,
)
