from __future__ import annotations

import logging
from uuid import UUID

from portfolio_exposure_graph.domain.enums import (
    AssetStatus,
    AssetType,
    CandidateRole,
    SupplierCompanyLinkStatus,
)
from portfolio_exposure_graph.domain.models import (
    CandidateEntityResolution,
    CandidateEntityResolutionSyncResult,
    DependencyPromotionRejection,
    EvidenceBackedDependenciesSyncResult,
    EvidenceBackedDependency,
    CompanyFilings,
    CompanyFilingsSyncResult,
    CompanyMetadata,
    CompanyMetadataSyncResult,
    CompanyResolution,
    DependencyExposureRow,
    DependentCompanyExposure,
    EvidenceSemanticCandidateBatch,
    EvidenceSemanticCandidatesSyncResult,
    FilingEvidenceBatch,
    FilingEvidenceSyncResult,
    GraphSyncResult,
    PortfolioDependencyPaths,
    PortfolioExposurePaths,
    PortfolioStructuralExposure,
    PortfolioSupplierExposure,
    RoleExposureItem,
    SupplierCompanyLink,
    SupplierCompanyLinkSyncResult,
    SupplierExposureItem,
    SupplierIdentity,
)
from portfolio_exposure_graph.providers.base import (
    AssetDataProvider,
    CompanyDirectoryProvider,
    CompanyFilingsProvider,
    CompanyMetadataProvider,
    EvidenceSemanticCandidateProvider,
    EtfHoldingsProvider,
    FilingEvidenceProvider,
)
from portfolio_exposure_graph.repositories.graph_repository import GraphRepository
from portfolio_exposure_graph.repositories.portfolio_repository import PortfolioRepository
from portfolio_exposure_graph.services.candidate_entity_resolver import DeterministicCandidateEntityResolver
from portfolio_exposure_graph.services.dependency_promoter import (
    DependencyPromotionRejected,
    DeterministicDependencyPromoter,
)
from portfolio_exposure_graph.services.supplier_company_linker import SupplierCompanyLinker

logger = logging.getLogger(__name__)


class GraphService:
    """Synchronize a portfolio into the graph and expose traversable paths."""

    def __init__(
        self,
        portfolio_repository: PortfolioRepository,
        graph_repository: GraphRepository,
        etf_holdings_provider: EtfHoldingsProvider,
        company_asset_provider: AssetDataProvider,
        company_metadata_provider: CompanyMetadataProvider,
        company_filings_provider: CompanyFilingsProvider,
        filing_evidence_provider: FilingEvidenceProvider,
        semantic_candidate_provider: EvidenceSemanticCandidateProvider | None = None,
        candidate_entity_resolver: DeterministicCandidateEntityResolver | None = None,
        dependency_promoter: DeterministicDependencyPromoter | None = None,
        company_directory_provider: CompanyDirectoryProvider | None = None,
    ) -> None:
        self.company_directory_provider = company_directory_provider
        self.portfolio_repository = portfolio_repository
        self.graph_repository = graph_repository
        self.etf_holdings_provider = etf_holdings_provider
        self.company_asset_provider = company_asset_provider
        self.company_metadata_provider = company_metadata_provider
        self.company_filings_provider = company_filings_provider
        self.filing_evidence_provider = filing_evidence_provider
        self.semantic_candidate_provider = semantic_candidate_provider
        self.candidate_entity_resolver = (
            candidate_entity_resolver or DeterministicCandidateEntityResolver()
        )
        self.dependency_promoter = dependency_promoter or DeterministicDependencyPromoter()

    def sync(self, portfolio_id: UUID) -> GraphSyncResult | None:
        portfolio = self.portfolio_repository.get(portfolio_id)
        if portfolio is None:
            return None

        etf_holdings = {}
        unexpanded_etfs: list[str] = []

        for position in portfolio.positions:
            if (
                position.asset.status != AssetStatus.READY
                or position.asset.asset_type != AssetType.ETF
            ):
                continue

            ticker = position.ticker.upper()
            try:
                holdings = self.etf_holdings_provider.get_holdings(ticker)
            except Exception:
                logger.exception("ETF holdings provider failed for graph sync: %s", ticker)
                unexpanded_etfs.append(ticker)
                continue

            positive_holdings = [holding for holding in holdings if holding.weight_pct > 0]
            if not positive_holdings:
                unexpanded_etfs.append(ticker)
                continue
            etf_holdings[ticker] = positive_holdings

        company_tickers = {
            position.ticker.upper()
            for position in portfolio.positions
            if position.asset.status == AssetStatus.READY
            and position.asset.asset_type == AssetType.EQUITY
        }
        for holdings in etf_holdings.values():
            company_tickers.update(holding.ticker.upper() for holding in holdings)

        company_resolutions, unresolved_company_assets = self._resolve_companies(
            company_tickers
        )

        self.graph_repository.sync_portfolio(
            portfolio,
            etf_holdings,
            company_resolutions,
        )

        synced_positions = [
            position
            for position in portfolio.positions
            if position.asset.status == AssetStatus.READY
            and position.asset.asset_type in {AssetType.EQUITY, AssetType.ETF}
        ]
        asset_tickers = {position.ticker for position in synced_positions}
        for holdings in etf_holdings.values():
            asset_tickers.update(holding.ticker for holding in holdings)

        return GraphSyncResult(
            portfolio_id=portfolio.portfolio_id,
            assets_synced=len(asset_tickers),
            companies_synced=len({item.cik for item in company_resolutions.values()}),
            ownership_edges_synced=len(synced_positions),
            holding_edges_synced=sum(len(items) for items in etf_holdings.values()),
            represents_edges_synced=len(company_resolutions),
            unexpanded_etfs=sorted(set(unexpanded_etfs)),
            unresolved_company_assets=unresolved_company_assets,
        )


    def sync_company_metadata(
        self,
        portfolio_id: UUID,
        limit: int = 25,
    ) -> CompanyMetadataSyncResult | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        targets = self.graph_repository.get_company_metadata_targets(
            portfolio_id,
            limit=limit,
        )
        metadata_by_cik: dict[str, CompanyMetadata] = {}
        unresolved: list[str] = []

        for target in targets:
            try:
                metadata = self.company_metadata_provider.get_metadata(target.cik)
            except Exception:
                logger.exception(
                    "Company metadata provider failed for CIK %s",
                    target.cik,
                )
                unresolved.append(target.cik)
                continue

            if metadata is None:
                unresolved.append(target.cik)
                continue
            metadata_by_cik[target.cik] = metadata

        self.graph_repository.sync_company_metadata(metadata_by_cik)

        return CompanyMetadataSyncResult(
            portfolio_id=portfolio_id,
            companies_requested=len(targets),
            companies_enriched=len(metadata_by_cik),
            industry_edges_synced=sum(
                1
                for item in metadata_by_cik.values()
                if item.industry_code and item.industry_name
            ),
            country_edges_synced=sum(
                1
                for item in metadata_by_cik.values()
                if item.country_code and item.country_name
            ),
            unresolved_company_ciks=sorted(set(unresolved)),
        )

    def sync_company_filings(
        self,
        portfolio_id: UUID,
        company_limit: int = 5,
        filings_per_company: int = 4,
    ) -> CompanyFilingsSyncResult | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        targets = self.graph_repository.get_company_filing_targets(
            portfolio_id,
            limit=company_limit,
        )
        filings_by_cik: dict[str, CompanyFilings] = {}
        unresolved: list[str] = []

        for target in targets:
            try:
                company_filings = self.company_filings_provider.get_recent_filings(
                    target.cik,
                    limit=filings_per_company,
                )
            except Exception:
                logger.exception(
                    "Company filings provider failed for CIK %s",
                    target.cik,
                )
                unresolved.append(target.cik)
                continue

            if company_filings is None:
                unresolved.append(target.cik)
                continue
            filings_by_cik[target.cik] = company_filings

        self.graph_repository.sync_company_filings(filings_by_cik)

        return CompanyFilingsSyncResult(
            portfolio_id=portfolio_id,
            companies_requested=len(targets),
            companies_synced=len(filings_by_cik),
            filings_synced=sum(
                len(batch.filings) for batch in filings_by_cik.values()
            ),
            unresolved_company_ciks=sorted(set(unresolved)),
        )

    def sync_filing_evidence(
        self,
        portfolio_id: UUID,
        filing_limit: int = 4,
        evidence_per_filing: int = 5,
    ) -> FilingEvidenceSyncResult | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        targets = self.graph_repository.get_filing_evidence_targets(
            portfolio_id,
            limit=filing_limit,
        )
        evidence_by_accession: dict[str, FilingEvidenceBatch] = {}
        unresolved: list[str] = []

        for target in targets:
            try:
                batch = self.filing_evidence_provider.extract_evidence(
                    target,
                    limit=evidence_per_filing,
                )
            except Exception:
                logger.exception(
                    "Filing evidence provider failed for accession %s",
                    target.accession_number,
                )
                unresolved.append(target.accession_number)
                continue

            if batch is None:
                unresolved.append(target.accession_number)
                continue
            evidence_by_accession[target.accession_number] = batch

        self.graph_repository.sync_filing_evidence(evidence_by_accession)

        return FilingEvidenceSyncResult(
            portfolio_id=portfolio_id,
            filings_requested=len(targets),
            filings_processed=len(evidence_by_accession),
            filings_with_evidence=sum(
                1 for batch in evidence_by_accession.values() if batch.evidence
            ),
            evidence_synced=sum(
                len(batch.evidence) for batch in evidence_by_accession.values()
            ),
            filings_without_evidence=sorted(
                accession
                for accession, batch in evidence_by_accession.items()
                if not batch.evidence
            ),
            unresolved_filing_accessions=sorted(set(unresolved)),
        )

    def sync_evidence_semantic_candidates(
        self,
        portfolio_id: UUID,
        evidence_limit: int = 10,
        candidates_per_evidence: int = 5,
    ) -> EvidenceSemanticCandidatesSyncResult | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        targets = self.graph_repository.get_evidence_semantic_targets(
            portfolio_id,
            limit=evidence_limit,
        )
        candidate_batches: dict[str, EvidenceSemanticCandidateBatch] = {}
        unresolved: list[str] = []

        if self.semantic_candidate_provider is None:
            unresolved.extend(target.evidence_id for target in targets)
        else:
            for target in targets:
                try:
                    batch = self.semantic_candidate_provider.extract_candidates(
                        target,
                        limit=candidates_per_evidence,
                    )
                except Exception:
                    logger.exception(
                        "Semantic candidate provider failed for evidence %s",
                        target.evidence_id,
                    )
                    unresolved.append(target.evidence_id)
                    continue

                if batch is None:
                    unresolved.append(target.evidence_id)
                    continue
                candidate_batches[target.evidence_id] = batch

        self.graph_repository.sync_evidence_semantic_candidates(candidate_batches)

        return EvidenceSemanticCandidatesSyncResult(
            portfolio_id=portfolio_id,
            evidence_requested=len(targets),
            evidence_processed=len(candidate_batches),
            evidence_with_candidates=sum(
                1 for batch in candidate_batches.values() if batch.candidates
            ),
            candidates_synced=sum(
                len(batch.candidates) for batch in candidate_batches.values()
            ),
            evidence_without_candidates=sorted(
                evidence_id
                for evidence_id, batch in candidate_batches.items()
                if not batch.candidates
            ),
            unresolved_evidence_ids=sorted(set(unresolved)),
        )

    def sync_candidate_entity_resolutions(
        self,
        portfolio_id: UUID,
        candidate_limit: int = 25,
    ) -> CandidateEntityResolutionSyncResult | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        targets = self.graph_repository.get_candidate_entity_resolution_targets(
            portfolio_id,
            limit=candidate_limit,
        )
        resolutions: list[CandidateEntityResolution] = []
        unresolved: list[str] = []
        suppliers_by_alias: dict[str, SupplierIdentity] = {}

        for target in targets:
            try:
                proposed = self.candidate_entity_resolver.resolve(target)
                supplier = self._reuse_supplier_identity(
                    proposed,
                    suppliers_by_alias,
                )
            except Exception:
                logger.exception(
                    "Candidate entity resolution failed for candidate %s",
                    target.candidate_id,
                )
                unresolved.append(target.candidate_id)
                continue

            resolutions.append(
                CandidateEntityResolution(
                    candidate_id=target.candidate_id,
                    supplier=supplier,
                    resolution_method=self.candidate_entity_resolver.RESOLUTION_METHOD,
                )
            )
            for alias in supplier.aliases:
                suppliers_by_alias[
                    self.candidate_entity_resolver.normalize_alias(alias)
                ] = supplier

        self.graph_repository.sync_candidate_entity_resolutions(resolutions)

        return CandidateEntityResolutionSyncResult(
            portfolio_id=portfolio_id,
            candidates_requested=len(targets),
            candidates_resolved=len(resolutions),
            suppliers_synced=len(
                {resolution.supplier.supplier_id for resolution in resolutions}
            ),
            unresolved_candidate_ids=sorted(set(unresolved)),
        )

    def sync_evidence_backed_dependencies(
        self,
        portfolio_id: UUID,
        candidate_limit: int = 25,
    ) -> EvidenceBackedDependenciesSyncResult | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        targets = self.graph_repository.get_dependency_promotion_targets(
            portfolio_id,
            limit=candidate_limit,
        )
        promotions: list[EvidenceBackedDependency] = []
        rejections: list[DependencyPromotionRejection] = []
        unresolved: list[str] = []

        for target in targets:
            try:
                promotions.append(self.dependency_promoter.promote(target))
            except DependencyPromotionRejected as exc:
                rejections.append(
                    DependencyPromotionRejection(
                        candidate_id=target.candidate_id,
                        reason=exc.reason,
                        promotion_method=self.dependency_promoter.PROMOTION_METHOD,
                    )
                )
            except Exception:
                logger.exception(
                    "Dependency promotion failed for candidate %s",
                    target.candidate_id,
                )
                unresolved.append(target.candidate_id)

        self.graph_repository.sync_evidence_backed_dependencies(
            promotions,
            rejections,
        )

        return EvidenceBackedDependenciesSyncResult(
            portfolio_id=portfolio_id,
            candidates_requested=len(targets),
            candidates_promoted=len(promotions),
            dependency_edges_synced=len(
                {(item.subject_cik, item.supplier_id) for item in promotions}
            ),
            candidates_rejected=len(rejections),
            rejected_candidate_ids=sorted(
                item.candidate_id for item in rejections
            ),
            unresolved_candidate_ids=sorted(set(unresolved)),
        )

    def _reuse_supplier_identity(
        self,
        proposed: SupplierIdentity,
        suppliers_by_alias: dict[str, SupplierIdentity],
    ) -> SupplierIdentity:
        matched: SupplierIdentity | None = None

        for alias in proposed.aliases:
            normalized = self.candidate_entity_resolver.normalize_alias(alias)
            batch_match = suppliers_by_alias.get(normalized)
            repository_match = self.graph_repository.get_supplier_by_alias(alias)

            for candidate in (batch_match, repository_match):
                if candidate is None:
                    continue
                if matched is not None and candidate.supplier_id != matched.supplier_id:
                    raise ValueError(
                        f"Conflicting supplier identities for alias {alias!r}"
                    )
                matched = candidate

        if matched is None:
            return proposed

        aliases = list(matched.aliases)
        seen = {
            self.candidate_entity_resolver.normalize_alias(alias)
            for alias in aliases
        }
        for alias in proposed.aliases:
            normalized = self.candidate_entity_resolver.normalize_alias(alias)
            if normalized in seen:
                continue
            seen.add(normalized)
            aliases.append(alias)

        return SupplierIdentity(
            supplier_id=matched.supplier_id,
            canonical_name=matched.canonical_name,
            aliases=aliases,
        )

    def get_paths(self, portfolio_id: UUID) -> PortfolioExposurePaths | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None
        return PortfolioExposurePaths(
            portfolio_id=portfolio_id,
            paths=self.graph_repository.get_exposure_paths(portfolio_id),
        )

    def get_dependency_paths(
        self,
        portfolio_id: UUID,
        limit: int = 100,
    ) -> PortfolioDependencyPaths | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None
        return PortfolioDependencyPaths(
            portfolio_id=portfolio_id,
            paths=self.graph_repository.get_dependency_paths(
                portfolio_id,
                limit=limit,
            ),
        )

    def get_structural_exposure(
        self,
        portfolio_id: UUID,
    ) -> PortfolioStructuralExposure | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        industries = self.graph_repository.get_industry_exposures(portfolio_id)
        countries = self.graph_repository.get_country_exposures(portfolio_id)
        return PortfolioStructuralExposure(
            portfolio_id=portfolio_id,
            industries=industries,
            countries=countries,
            industry_coverage_pct=round(
                sum(item.weight_pct for item in industries),
                6,
            ),
            country_coverage_pct=round(
                sum(item.weight_pct for item in countries),
                6,
            ),
        )

    def get_supplier_exposure(
        self,
        portfolio_id: UUID,
    ) -> PortfolioSupplierExposure | None:
        if self.portfolio_repository.get(portfolio_id) is None:
            return None
        rows = self.graph_repository.get_dependency_exposure_rows(portfolio_id)
        holding_weights = (
            self.graph_repository.get_company_holding_weights(portfolio_id)
            if any(row.supplier_company_cik for row in rows)
            else {}
        )
        return aggregate_supplier_exposure(portfolio_id, rows, holding_weights)

    def sync_supplier_companies(
        self,
        portfolio_id: UUID,
        limit: int = 50,
    ) -> SupplierCompanyLinkSyncResult | None:
        """Link the portfolio's dependency Suppliers to SEC-registered companies.

        Suppliers are only marked as checked once the directory loaded, so a
        directory outage leaves them for a later run.
        """
        if self.portfolio_repository.get(portfolio_id) is None:
            return None

        targets = self.graph_repository.get_supplier_company_link_targets(
            portfolio_id, limit=limit
        )
        result = SupplierCompanyLinkSyncResult(
            portfolio_id=portfolio_id,
            suppliers_requested=len(targets),
            suppliers_linked=0,
        )
        if not targets:
            return result

        directory = None
        if self.company_directory_provider is not None:
            try:
                directory = self.company_directory_provider.list_companies()
            except Exception:
                logger.exception("Company directory provider failed")
        if not directory:
            return result.model_copy(update={"directory_unavailable": True})

        linker = SupplierCompanyLinker(
            directory, source_url=self.company_directory_provider.source_url
        )
        links: list[SupplierCompanyLink] = [linker.link(target) for target in targets]
        self.graph_repository.sync_supplier_company_links(links)

        by_status: dict[SupplierCompanyLinkStatus, list[str]] = {
            status: [] for status in SupplierCompanyLinkStatus
        }
        for link in links:
            by_status[link.status].append(link.supplier_id)
        return result.model_copy(
            update={
                "suppliers_linked": len(by_status[SupplierCompanyLinkStatus.LINKED]),
                "linked_supplier_ids": by_status[SupplierCompanyLinkStatus.LINKED],
                "ambiguous_supplier_ids": by_status[SupplierCompanyLinkStatus.AMBIGUOUS],
                "unmatched_supplier_ids": by_status[SupplierCompanyLinkStatus.UNMATCHED],
            }
        )

    def _resolve_companies(
        self,
        tickers: set[str],
    ) -> tuple[dict[str, CompanyResolution], list[str]]:
        resolutions: dict[str, CompanyResolution] = {}
        unresolved: list[str] = []
        ordered_tickers = sorted(tickers)

        for index, ticker in enumerate(ordered_tickers):
            try:
                asset = self.company_asset_provider.resolve(ticker)
            except Exception:
                logger.exception("Company asset provider failed during graph sync")
                unresolved.extend(ordered_tickers[index:])
                break

            if (
                asset is None
                or asset.status != AssetStatus.READY
                or asset.asset_type != AssetType.EQUITY
                or not asset.cik
                or not asset.company_name
            ):
                unresolved.append(ticker)
                continue

            resolutions[ticker] = CompanyResolution(
                ticker=ticker,
                cik=asset.cik,
                name=asset.company_name,
                exchange=asset.exchange,
            )

        return resolutions, sorted(set(unresolved))


def aggregate_supplier_exposure(
    portfolio_id: UUID,
    rows: list[DependencyExposureRow],
    holding_weights: dict[str, float] | None = None,
) -> PortfolioSupplierExposure:
    """Aggregate dependency rows by supplier and by role.

    The unit of weight is a holding route to a company (e.g. NVDA held
    directly, or NVDA inside QQQ): its sourced weight is added once to every
    supplier, and once to every role, the company depends on. Routes are
    disjoint slices of the portfolio, so summing them never double counts
    within one supplier or role. Different suppliers and roles overlap.

    ``holding_weights`` (CIK -> direct + look-through weight) adds, for
    suppliers linked to an SEC company, how much of that supplier the
    portfolio already holds.
    """
    holding_weights = holding_weights or {}

    def route_key(row: DependencyExposureRow) -> tuple[tuple[str, ...], str]:
        return tuple(row.asset_path), row.company_cik

    route_weights: dict[tuple[tuple[str, ...], str], float] = {}
    suppliers: dict[str, dict] = {}
    roles: dict[CandidateRole, dict] = {}

    for row in rows:
        key = route_key(row)
        route_weights[key] = row.company_path_weight_pct

        supplier = suppliers.setdefault(
            row.supplier_id,
            {
                "name": row.supplier_name,
                "routes": {},
                "roles": set(),
                "companies": {},
                "company_cik": None,
                "company_name": None,
            },
        )
        if row.supplier_company_cik:
            supplier["company_cik"] = row.supplier_company_cik
            supplier["company_name"] = row.supplier_company_name
        supplier["routes"][key] = row.company_path_weight_pct
        supplier["roles"].update(row.roles)
        company = supplier["companies"].setdefault(
            row.company_cik, {"name": row.company_name, "routes": {}}
        )
        company["routes"][key] = row.company_path_weight_pct

        for role in row.roles:
            entry = roles.setdefault(role, {"routes": {}, "suppliers": set()})
            entry["routes"][key] = row.company_path_weight_pct
            entry["suppliers"].add(row.supplier_id)

    def total(weights: dict) -> float:
        return round(sum(weights.values()), 6)

    supplier_items = [
        SupplierExposureItem(
            supplier_id=supplier_id,
            supplier_name=data["name"],
            weight_pct=total(data["routes"]),
            roles=sorted(data["roles"], key=lambda role: role.value),
            companies=sorted(
                (
                    DependentCompanyExposure(
                        company_cik=cik,
                        company_name=company["name"],
                        weight_pct=total(company["routes"]),
                    )
                    for cik, company in data["companies"].items()
                ),
                key=lambda item: (-item.weight_pct, item.company_name),
            ),
            supplier_company_cik=data["company_cik"],
            supplier_company_name=data["company_name"],
            held_weight_pct=(
                round(holding_weights.get(data["company_cik"], 0.0), 6)
                if data["company_cik"]
                else None
            ),
        )
        for supplier_id, data in suppliers.items()
    ]
    # Ties: suppliers the portfolio also holds come first (hidden concentration).
    supplier_items.sort(
        key=lambda item: (-item.weight_pct, -(item.held_weight_pct or 0.0), item.supplier_name)
    )

    role_items = [
        RoleExposureItem(
            role=role,
            weight_pct=total(data["routes"]),
            supplier_count=len(data["suppliers"]),
        )
        for role, data in roles.items()
    ]
    role_items.sort(key=lambda item: (-item.weight_pct, item.role.value))

    return PortfolioSupplierExposure(
        portfolio_id=portfolio_id,
        suppliers=supplier_items,
        roles=role_items,
        dependency_coverage_pct=total(route_weights),
    )
