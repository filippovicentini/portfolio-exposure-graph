from app.core.config import settings
from app.providers.alpha_vantage_etf_provider import AlphaVantageEtfProvider
from app.providers.sec_asset_provider import SecAssetProvider
from app.repositories.asset_registry import InMemoryAssetRegistry
from app.repositories.portfolio_repository import InMemoryPortfolioRepository
from app.services.asset_resolver import AssetResolver
from app.services.enrichment_queue import InMemoryEnrichmentQueue
from app.services.lookthrough_service import LookthroughService
from app.services.portfolio_service import PortfolioService

asset_registry = InMemoryAssetRegistry()
portfolio_repository = InMemoryPortfolioRepository()
enrichment_queue = InMemoryEnrichmentQueue()
sec_asset_provider = SecAssetProvider(user_agent=settings.sec_user_agent)
alpha_vantage_etf_provider = AlphaVantageEtfProvider(
    api_key=settings.alpha_vantage_api_key
)
asset_resolver = AssetResolver(asset_registry, providers=[sec_asset_provider])
portfolio_service = PortfolioService(
    repository=portfolio_repository,
    asset_resolver=asset_resolver,
    enrichment_queue=enrichment_queue,
)
lookthrough_service = LookthroughService(
    repository=portfolio_repository,
    etf_holdings_provider=alpha_vantage_etf_provider,
)
