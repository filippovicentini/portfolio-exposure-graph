from app.repositories.asset_registry import InMemoryAssetRegistry
from app.repositories.portfolio_repository import InMemoryPortfolioRepository
from app.services.asset_resolver import AssetResolver
from app.services.enrichment_queue import InMemoryEnrichmentQueue
from app.services.portfolio_service import PortfolioService

asset_registry = InMemoryAssetRegistry()
portfolio_repository = InMemoryPortfolioRepository()
enrichment_queue = InMemoryEnrichmentQueue()
asset_resolver = AssetResolver(asset_registry)
portfolio_service = PortfolioService(
    repository=portfolio_repository,
    asset_resolver=asset_resolver,
    enrichment_queue=enrichment_queue,
)
