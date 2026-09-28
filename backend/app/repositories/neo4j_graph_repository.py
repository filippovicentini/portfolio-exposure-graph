from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from neo4j import GraphDatabase

from app.domain.enums import AssetStatus, AssetType
from app.domain.models import (
    CandidateEntityResolution,
    CandidateEntityResolutionTarget,
    CompanyFilingTarget,
    CompanyFilings,
    CompanyMetadata,
    CompanyMetadataTarget,
    CompanyResolution,
    EvidenceSemanticCandidateBatch,
    EvidenceSemanticTarget,
    EtfHolding,
    ExposurePath,
    FilingEvidenceBatch,
    FilingEvidenceTarget,
    Portfolio,
    StructuralExposureItem,
    SupplierIdentity,
)
from app.repositories.graph_repository import GraphRepository


class Neo4jGraphRepository(GraphRepository):
    """Store portfolio, asset, ETF holding, and canonical company graph data."""

    UPSERT_PORTFOLIO_QUERY = """
    MERGE (p:Portfolio {portfolio_id: $portfolio_id})
    SET p.name = $name,
        p.status = $status,
        p.updated_at = datetime()
    WITH p
    OPTIONAL MATCH (p)-[r:OWNS]->()
    DELETE r
    """

    UPSERT_POSITIONS_QUERY = """
    MATCH (p:Portfolio {portfolio_id: $portfolio_id})
    UNWIND $positions AS position
    MERGE (a:Asset {ticker: position.ticker})
    SET a.asset_type = position.asset_type,
        a.name = position.name,
        a.exchange = position.exchange,
        a.cik = position.cik,
        a.updated_at = datetime()
    FOREACH (_ IN CASE WHEN position.asset_type = 'etf' THEN [1] ELSE [] END |
        SET a:ETF
    )
    FOREACH (_ IN CASE WHEN position.asset_type = 'equity' THEN [1] ELSE [] END |
        SET a:Equity
    )
    MERGE (p)-[r:OWNS]->(a)
    SET r.weight_pct = position.weight_pct,
        r.updated_at = datetime()
    """

    DELETE_ETF_HOLDINGS_QUERY = """
    UNWIND $etf_tickers AS etf_ticker
    MATCH (etf:Asset {ticker: etf_ticker})-[r:HOLDS]->()
    DELETE r
    """

    UPSERT_ETF_HOLDINGS_QUERY = """
    UNWIND $holdings AS holding
    MERGE (etf:Asset {ticker: holding.etf_ticker})
    SET etf:ETF,
        etf.asset_type = 'etf',
        etf.updated_at = datetime()
    MERGE (asset:Asset {ticker: holding.ticker})
    ON CREATE SET asset.asset_type = 'unknown'
    SET asset.name = coalesce(asset.name, holding.description),
        asset.updated_at = datetime()
    MERGE (etf)-[r:HOLDS]->(asset)
    SET r.weight_pct = holding.weight_pct,
        r.updated_at = datetime()
    """

    UPSERT_COMPANIES_QUERY = """
    UNWIND $companies AS company
    MATCH (asset:Asset {ticker: company.ticker})
    SET asset:Equity,
        asset.asset_type = 'equity',
        asset.name = company.name,
        asset.exchange = company.exchange,
        asset.cik = company.cik,
        asset.updated_at = datetime()
    WITH asset, company
    OPTIONAL MATCH (asset)-[old:REPRESENTS]->(:Company)
    DELETE old
    WITH asset, company
    MERGE (canonical:Company {cik: company.cik})
    SET canonical.name = company.name,
        canonical.updated_at = datetime()
    MERGE (asset)-[r:REPRESENTS]->(canonical)
    SET r.updated_at = datetime()
    """


    COMPANY_METADATA_TARGETS_QUERY = """
    MATCH path =
      (p:Portfolio {portfolio_id: $portfolio_id})
      -[:OWNS|HOLDS*1..2]->(asset:Asset)
      -[:REPRESENTS]->(company:Company)
    WHERE NOT ('sec_metadata_synced_at' IN keys(company))
    WITH company, min(length(path)) AS path_length
    RETURN company.cik AS cik, company.name AS name
    ORDER BY path_length ASC, company.name ASC
    LIMIT $limit
    """

    MARK_COMPANY_METADATA_SYNCED_QUERY = """
    UNWIND $companies AS item
    MATCH (company:Company {cik: item.cik})
    SET company.sec_metadata_synced_at = datetime(),
        company.sec_metadata_source_url = item.source_url,
        company.updated_at = datetime()
    """

    UPSERT_INDUSTRIES_QUERY = """
    UNWIND $industries AS item
    MATCH (company:Company {cik: item.cik})
    OPTIONAL MATCH (company)-[old:OPERATES_IN]->(:Industry)
    DELETE old
    WITH company, item
    MERGE (industry:Industry {sic: item.industry_code})
    SET industry.name = item.industry_name,
        industry.source = 'SEC SIC',
        industry.updated_at = datetime()
    WITH company, industry, item
    MERGE (company)-[r:OPERATES_IN]->(industry)
    SET r.source = 'SEC submissions API',
        r.source_url = item.source_url,
        r.updated_at = datetime()
    """

    UPSERT_COUNTRIES_QUERY = """
    UNWIND $countries AS item
    MATCH (company:Company {cik: item.cik})
    OPTIONAL MATCH (company)-[old:BASED_IN]->(:Country)
    DELETE old
    WITH company, item
    MERGE (country:Country {sec_code: item.country_code})
    SET country.name = item.country_name,
        country.source = 'SEC business address',
        country.updated_at = datetime()
    WITH company, country, item
    MERGE (company)-[r:BASED_IN]->(country)
    SET r.source = 'SEC submissions API',
        r.source_url = item.source_url,
        r.updated_at = datetime()
    """

    EXPOSURE_PATHS_QUERY = """
    MATCH (p:Portfolio {portfolio_id: $portfolio_id})-[owns:OWNS]->(asset:Asset:Equity)
    RETURN [asset.ticker] AS asset_path,
           ['OWNS'] AS relations,
           owns.weight_pct AS effective_weight_pct
    UNION ALL
    MATCH (p:Portfolio {portfolio_id: $portfolio_id})-[owns:OWNS]->(etf:Asset:ETF)-[holds:HOLDS]->(asset:Asset)
    RETURN [etf.ticker, asset.ticker] AS asset_path,
           ['OWNS', 'HOLDS'] AS relations,
           owns.weight_pct * holds.weight_pct / 100.0 AS effective_weight_pct
    """

    COMPANY_FILING_TARGETS_QUERY = """
    MATCH path =
      (p:Portfolio {portfolio_id: $portfolio_id})
      -[:OWNS|HOLDS*1..2]->(asset:Asset)
      -[:REPRESENTS]->(company:Company)
    WHERE NOT ('sec_filings_synced_at' IN keys(company))
    WITH company, min(length(path)) AS path_length
    RETURN company.cik AS cik, company.name AS name
    ORDER BY path_length ASC, company.name ASC
    LIMIT $limit
    """

    MARK_COMPANY_FILINGS_SYNCED_QUERY = """
    UNWIND $companies AS item
    MATCH (company:Company {cik: item.cik})
    SET company.sec_filings_synced_at = datetime(),
        company.sec_filings_source_url = item.source_url,
        company.updated_at = datetime()
    """

    UPSERT_FILINGS_QUERY = """
    UNWIND $filings AS item
    MATCH (company:Company {cik: item.cik})
    MERGE (filing:Filing {accession_number: item.accession_number})
    SET filing.cik = item.cik,
        filing.form = item.form,
        filing.filing_date = item.filing_date,
        filing.report_date = item.report_date,
        filing.primary_document = item.primary_document,
        filing.source_url = item.source_url,
        filing.filing_index_url = item.filing_index_url,
        filing.submissions_url = item.submissions_url,
        filing.updated_at = datetime()
    MERGE (company)-[r:FILED]->(filing)
    SET r.source_url = item.submissions_url,
        r.updated_at = datetime()
    """

    FILING_EVIDENCE_TARGETS_QUERY = """
    MATCH path =
      (p:Portfolio {portfolio_id: $portfolio_id})
      -[:OWNS|HOLDS*1..2]->(asset:Asset)
      -[:REPRESENTS]->(company:Company)
      -[:FILED]->(filing:Filing)
    WHERE NOT ('evidence_extracted_at' IN keys(filing))
    WITH filing, min(length(path)) AS path_length
    RETURN filing.accession_number AS accession_number,
           filing.cik AS cik,
           filing.form AS form,
           filing.filing_date AS filing_date,
           filing.source_url AS source_url
    ORDER BY path_length ASC, filing.filing_date DESC, filing.accession_number ASC
    LIMIT $limit
    """

    MARK_FILINGS_EVIDENCE_EXTRACTED_QUERY = """
    UNWIND $filings AS item
    MATCH (filing:Filing {accession_number: item.accession_number})
    SET filing.evidence_extracted_at = datetime(),
        filing.evidence_extraction_method = item.extraction_method,
        filing.evidence_count = item.evidence_count,
        filing.updated_at = datetime()
    """

    UPSERT_EVIDENCE_QUERY = """
    UNWIND $evidence AS item
    MATCH (filing:Filing {accession_number: item.accession_number})
    MERGE (evidence:Evidence {evidence_id: item.evidence_id})
    SET evidence.evidence_type = item.evidence_type,
        evidence.evidence_text = item.evidence_text,
        evidence.matched_terms = item.matched_terms,
        evidence.source_document_id = item.accession_number,
        evidence.source_url = item.source_url,
        evidence.source_date = item.source_date,
        evidence.extraction_method = item.extraction_method,
        evidence.updated_at = datetime()
    MERGE (filing)-[r:CONTAINS_EVIDENCE]->(evidence)
    SET r.source_document_id = item.accession_number,
        r.source_url = item.source_url,
        r.extraction_method = item.extraction_method,
        r.updated_at = datetime()
    """

    EVIDENCE_SEMANTIC_TARGETS_QUERY = """
    MATCH path =
      (p:Portfolio {portfolio_id: $portfolio_id})
      -[:OWNS|HOLDS*1..2]->(asset:Asset)
      -[:REPRESENTS]->(company:Company)
      -[:FILED]->(filing:Filing)
      -[:CONTAINS_EVIDENCE]->(evidence:Evidence)
    WHERE evidence.evidence_type = 'dependency_candidate'
      AND NOT ('semantic_candidates_extracted_at' IN keys(evidence))
    WITH company, filing, evidence, min(length(path)) AS path_length
    RETURN evidence.evidence_id AS evidence_id,
           company.cik AS subject_cik,
           company.name AS subject_name,
           filing.accession_number AS accession_number,
           evidence.evidence_text AS evidence_text,
           evidence.source_url AS source_url,
           evidence.source_date AS source_date
    ORDER BY path_length ASC, evidence.source_date DESC, evidence.evidence_id ASC
    LIMIT $limit
    """

    MARK_EVIDENCE_SEMANTIC_EXTRACTED_QUERY = """
    UNWIND $evidence AS item
    MATCH (evidence:Evidence {evidence_id: item.evidence_id})
    SET evidence.semantic_candidates_extracted_at = datetime(),
        evidence.semantic_candidate_extraction_method = item.extraction_method,
        evidence.semantic_candidate_model = item.model_name,
        evidence.semantic_candidate_count = item.candidate_count,
        evidence.updated_at = datetime()
    """

    UPSERT_RELATIONSHIP_CANDIDATES_QUERY = """
    UNWIND $candidates AS item
    MATCH (evidence:Evidence {evidence_id: item.evidence_id})
    MERGE (candidate:RelationshipCandidate {candidate_id: item.candidate_id})
    SET candidate.subject_cik = item.subject_cik,
        candidate.subject_name = item.subject_name,
        candidate.object_mention = item.object_mention,
        candidate.proposed_relation = item.proposed_relation,
        candidate.role = item.role,
        candidate.supporting_text = item.supporting_text,
        candidate.extraction_method = item.extraction_method,
        candidate.model_name = item.model_name,
        candidate.updated_at = datetime()
    MERGE (evidence)-[r:SUPPORTS_CANDIDATE]->(candidate)
    SET r.extraction_method = item.extraction_method,
        r.model_name = item.model_name,
        r.updated_at = datetime()
    """

    CANDIDATE_ENTITY_RESOLUTION_TARGETS_QUERY = """
    MATCH path =
      (p:Portfolio {portfolio_id: $portfolio_id})
      -[:OWNS|HOLDS*1..2]->(asset:Asset)
      -[:REPRESENTS]->(company:Company)
      -[:FILED]->(filing:Filing)
      -[:CONTAINS_EVIDENCE]->(evidence:Evidence)
      -[:SUPPORTS_CANDIDATE]->(candidate:RelationshipCandidate)
    WHERE NOT ('entity_resolved_at' IN keys(candidate))
    WITH company, evidence, candidate, min(length(path)) AS path_length
    RETURN candidate.candidate_id AS candidate_id,
           evidence.evidence_id AS evidence_id,
           company.cik AS subject_cik,
           company.name AS subject_name,
           candidate.object_mention AS object_mention,
           candidate.role AS role,
           candidate.supporting_text AS supporting_text,
           evidence.evidence_text AS evidence_text
    ORDER BY path_length ASC, evidence.source_date DESC, candidate.candidate_id ASC
    LIMIT $limit
    """

    SUPPLIER_BY_ALIAS_QUERY = """
    MATCH (supplier:Supplier)
    WHERE any(alias IN coalesce(supplier.aliases, [])
              WHERE toLower(trim(alias)) = toLower(trim($alias)))
    RETURN supplier.supplier_id AS supplier_id,
           supplier.canonical_name AS canonical_name,
           supplier.aliases AS aliases
    ORDER BY supplier.supplier_id ASC
    LIMIT 1
    """

    UPSERT_CANDIDATE_ENTITY_RESOLUTIONS_QUERY = """
    UNWIND $resolutions AS item
    MATCH (candidate:RelationshipCandidate {candidate_id: item.candidate_id})
    MERGE (supplier:Supplier {supplier_id: item.supplier_id})
    ON CREATE SET supplier.canonical_name = item.canonical_name,
                  supplier.aliases = []
    SET supplier.canonical_name = coalesce(supplier.canonical_name, item.canonical_name),
        supplier.aliases = reduce(
            acc = coalesce(supplier.aliases, []),
            alias IN item.aliases |
            CASE
                WHEN any(existing IN acc WHERE toLower(existing) = toLower(alias)) THEN acc
                ELSE acc + alias
            END
        ),
        supplier.updated_at = datetime(),
        candidate.entity_resolved_at = datetime(),
        candidate.entity_resolution_method = item.resolution_method,
        candidate.resolved_supplier_id = item.supplier_id,
        candidate.updated_at = datetime()
    MERGE (candidate)-[r:RESOLVES_TO]->(supplier)
    SET r.resolution_method = item.resolution_method,
        r.updated_at = datetime()
    """

    INDUSTRY_EXPOSURES_QUERY = """
    CALL () {
        MATCH (p:Portfolio {portfolio_id: $portfolio_id})-[owns:OWNS]->(asset:Asset)-[:REPRESENTS]->(company:Company)
        RETURN company, owns.weight_pct AS effective_weight_pct
        UNION ALL
        MATCH (p:Portfolio {portfolio_id: $portfolio_id})-[owns:OWNS]->(etf:Asset:ETF)-[holds:HOLDS]->(asset:Asset)-[:REPRESENTS]->(company:Company)
        RETURN company, owns.weight_pct * holds.weight_pct / 100.0 AS effective_weight_pct
    }
    MATCH (company)-[:OPERATES_IN]->(industry:Industry)
    RETURN industry.sic AS code,
           industry.name AS name,
           sum(effective_weight_pct) AS weight_pct
    ORDER BY weight_pct DESC, name ASC
    """

    COUNTRY_EXPOSURES_QUERY = """
    CALL () {
        MATCH (p:Portfolio {portfolio_id: $portfolio_id})-[owns:OWNS]->(asset:Asset)-[:REPRESENTS]->(company:Company)
        RETURN company, owns.weight_pct AS effective_weight_pct
        UNION ALL
        MATCH (p:Portfolio {portfolio_id: $portfolio_id})-[owns:OWNS]->(etf:Asset:ETF)-[holds:HOLDS]->(asset:Asset)-[:REPRESENTS]->(company:Company)
        RETURN company, owns.weight_pct * holds.weight_pct / 100.0 AS effective_weight_pct
    }
    MATCH (company)-[:BASED_IN]->(country:Country)
    RETURN country.sec_code AS code,
           country.name AS name,
           sum(effective_weight_pct) AS weight_pct
    ORDER BY weight_pct DESC, name ASC
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver=None,
    ) -> None:
        self.database = database
        self.driver = driver or GraphDatabase.driver(uri, auth=(user, password))

    def sync_portfolio(
        self,
        portfolio: Portfolio,
        etf_holdings: Mapping[str, list[EtfHolding]],
        company_resolutions: Mapping[str, CompanyResolution],
    ) -> None:
        portfolio_id = str(portfolio.portfolio_id)
        positions = [
            {
                "ticker": position.ticker,
                "weight_pct": position.weight_pct,
                "asset_type": position.asset.asset_type.value,
                "name": position.asset.company_name,
                "exchange": position.asset.exchange,
                "cik": position.asset.cik,
            }
            for position in portfolio.positions
            if position.asset.status == AssetStatus.READY
            and position.asset.asset_type in {AssetType.EQUITY, AssetType.ETF}
        ]

        self.driver.execute_query(
            self.UPSERT_PORTFOLIO_QUERY,
            portfolio_id=portfolio_id,
            name=portfolio.name,
            status=portfolio.status.value,
            database_=self.database,
        )

        if positions:
            self.driver.execute_query(
                self.UPSERT_POSITIONS_QUERY,
                portfolio_id=portfolio_id,
                positions=positions,
                database_=self.database,
            )

        etf_tickers = sorted(etf_holdings)
        if etf_tickers:
            self.driver.execute_query(
                self.DELETE_ETF_HOLDINGS_QUERY,
                etf_tickers=etf_tickers,
                database_=self.database,
            )

            holdings = [
                {
                    "etf_ticker": etf_ticker,
                    "ticker": holding.ticker,
                    "description": holding.description,
                    "weight_pct": holding.weight_pct,
                }
                for etf_ticker, items in etf_holdings.items()
                for holding in items
                if holding.weight_pct > 0
            ]
            if holdings:
                self.driver.execute_query(
                    self.UPSERT_ETF_HOLDINGS_QUERY,
                    holdings=holdings,
                    database_=self.database,
                )

        if company_resolutions:
            companies = [
                {
                    "ticker": resolution.ticker,
                    "cik": resolution.cik,
                    "name": resolution.name,
                    "exchange": resolution.exchange,
                }
                for _, resolution in sorted(company_resolutions.items())
            ]
            self.driver.execute_query(
                self.UPSERT_COMPANIES_QUERY,
                companies=companies,
                database_=self.database,
            )


    def get_company_metadata_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[CompanyMetadataTarget]:
        records, _, _ = self.driver.execute_query(
            self.COMPANY_METADATA_TARGETS_QUERY,
            portfolio_id=str(portfolio_id),
            limit=limit,
            database_=self.database,
        )
        return [
            CompanyMetadataTarget(
                cik=str(record["cik"]),
                name=str(record["name"]),
            )
            for record in records
        ]

    def sync_company_metadata(
        self,
        company_metadata: Mapping[str, CompanyMetadata],
    ) -> None:
        if not company_metadata:
            return

        companies = [
            {
                "cik": metadata.cik,
                "source_url": metadata.source_url,
            }
            for _, metadata in sorted(company_metadata.items())
        ]
        self.driver.execute_query(
            self.MARK_COMPANY_METADATA_SYNCED_QUERY,
            companies=companies,
            database_=self.database,
        )

        industries = [
            {
                "cik": metadata.cik,
                "industry_code": metadata.industry_code,
                "industry_name": metadata.industry_name,
                "source_url": metadata.source_url,
            }
            for _, metadata in sorted(company_metadata.items())
            if metadata.industry_code and metadata.industry_name
        ]
        if industries:
            self.driver.execute_query(
                self.UPSERT_INDUSTRIES_QUERY,
                industries=industries,
                database_=self.database,
            )

        countries = [
            {
                "cik": metadata.cik,
                "country_code": metadata.country_code,
                "country_name": metadata.country_name,
                "source_url": metadata.source_url,
            }
            for _, metadata in sorted(company_metadata.items())
            if metadata.country_code and metadata.country_name
        ]
        if countries:
            self.driver.execute_query(
                self.UPSERT_COUNTRIES_QUERY,
                countries=countries,
                database_=self.database,
            )

    def get_company_filing_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[CompanyFilingTarget]:
        records, _, _ = self.driver.execute_query(
            self.COMPANY_FILING_TARGETS_QUERY,
            portfolio_id=str(portfolio_id),
            limit=limit,
            database_=self.database,
        )
        return [
            CompanyFilingTarget(
                cik=str(record["cik"]),
                name=str(record["name"]),
            )
            for record in records
        ]

    def sync_company_filings(
        self,
        company_filings: Mapping[str, CompanyFilings],
    ) -> None:
        if not company_filings:
            return

        companies = [
            {
                "cik": batch.cik,
                "source_url": batch.source_url,
            }
            for _, batch in sorted(company_filings.items())
        ]
        self.driver.execute_query(
            self.MARK_COMPANY_FILINGS_SYNCED_QUERY,
            companies=companies,
            database_=self.database,
        )

        filings = [
            {
                "cik": filing.cik,
                "accession_number": filing.accession_number,
                "form": filing.form,
                "filing_date": filing.filing_date.isoformat(),
                "report_date": (
                    filing.report_date.isoformat() if filing.report_date else None
                ),
                "primary_document": filing.primary_document,
                "source_url": filing.source_url,
                "filing_index_url": filing.filing_index_url,
                "submissions_url": filing.submissions_url,
            }
            for _, batch in sorted(company_filings.items())
            for filing in batch.filings
        ]
        if filings:
            self.driver.execute_query(
                self.UPSERT_FILINGS_QUERY,
                filings=filings,
                database_=self.database,
            )

    def get_exposure_paths(self, portfolio_id: UUID) -> list[ExposurePath]:
        records, _, _ = self.driver.execute_query(
            self.EXPOSURE_PATHS_QUERY,
            portfolio_id=str(portfolio_id),
            database_=self.database,
        )
        paths = [
            ExposurePath(
                asset_path=list(record["asset_path"]),
                relations=list(record["relations"]),
                effective_weight_pct=round(float(record["effective_weight_pct"]), 6),
            )
            for record in records
        ]
        paths.sort(key=lambda item: (-item.effective_weight_pct, item.asset_path))
        return paths

    def get_filing_evidence_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[FilingEvidenceTarget]:
        records, _, _ = self.driver.execute_query(
            self.FILING_EVIDENCE_TARGETS_QUERY,
            portfolio_id=str(portfolio_id),
            limit=limit,
            database_=self.database,
        )
        return [
            FilingEvidenceTarget(
                accession_number=str(record["accession_number"]),
                cik=str(record["cik"]),
                form=str(record["form"]),
                filing_date=record["filing_date"],
                source_url=str(record["source_url"]),
            )
            for record in records
        ]

    def sync_filing_evidence(
        self,
        evidence_batches: Mapping[str, FilingEvidenceBatch],
    ) -> None:
        if not evidence_batches:
            return

        filings = [
            {
                "accession_number": batch.accession_number,
                "extraction_method": batch.extraction_method,
                "evidence_count": len(batch.evidence),
            }
            for _, batch in sorted(evidence_batches.items())
        ]
        self.driver.execute_query(
            self.MARK_FILINGS_EVIDENCE_EXTRACTED_QUERY,
            filings=filings,
            database_=self.database,
        )

        evidence = [
            {
                "evidence_id": item.evidence_id,
                "accession_number": item.accession_number,
                "evidence_type": item.evidence_type,
                "evidence_text": item.evidence_text,
                "matched_terms": item.matched_terms,
                "source_url": item.source_url,
                "source_date": item.source_date.isoformat(),
                "extraction_method": item.extraction_method,
            }
            for _, batch in sorted(evidence_batches.items())
            for item in batch.evidence
        ]
        if evidence:
            self.driver.execute_query(
                self.UPSERT_EVIDENCE_QUERY,
                evidence=evidence,
                database_=self.database,
            )

    def get_evidence_semantic_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[EvidenceSemanticTarget]:
        records, _, _ = self.driver.execute_query(
            self.EVIDENCE_SEMANTIC_TARGETS_QUERY,
            portfolio_id=str(portfolio_id),
            limit=limit,
            database_=self.database,
        )
        return [
            EvidenceSemanticTarget(
                evidence_id=str(record["evidence_id"]),
                subject_cik=str(record["subject_cik"]),
                subject_name=str(record["subject_name"]),
                accession_number=str(record["accession_number"]),
                evidence_text=str(record["evidence_text"]),
                source_url=str(record["source_url"]),
                source_date=record["source_date"],
            )
            for record in records
        ]

    def sync_evidence_semantic_candidates(
        self,
        candidate_batches: Mapping[str, EvidenceSemanticCandidateBatch],
    ) -> None:
        if not candidate_batches:
            return

        evidence = [
            {
                "evidence_id": batch.evidence_id,
                "extraction_method": batch.extraction_method,
                "model_name": batch.model_name,
                "candidate_count": len(batch.candidates),
            }
            for _, batch in sorted(candidate_batches.items())
        ]
        self.driver.execute_query(
            self.MARK_EVIDENCE_SEMANTIC_EXTRACTED_QUERY,
            evidence=evidence,
            database_=self.database,
        )

        candidates = [
            {
                "candidate_id": item.candidate_id,
                "evidence_id": item.evidence_id,
                "subject_cik": item.subject_cik,
                "subject_name": item.subject_name,
                "object_mention": item.object_mention,
                "proposed_relation": item.proposed_relation.value,
                "role": item.role.value,
                "supporting_text": item.supporting_text,
                "extraction_method": item.extraction_method,
                "model_name": item.model_name,
            }
            for _, batch in sorted(candidate_batches.items())
            for item in batch.candidates
        ]
        if candidates:
            self.driver.execute_query(
                self.UPSERT_RELATIONSHIP_CANDIDATES_QUERY,
                candidates=candidates,
                database_=self.database,
            )

    def get_candidate_entity_resolution_targets(
        self,
        portfolio_id: UUID,
        limit: int,
    ) -> list[CandidateEntityResolutionTarget]:
        records, _, _ = self.driver.execute_query(
            self.CANDIDATE_ENTITY_RESOLUTION_TARGETS_QUERY,
            portfolio_id=str(portfolio_id),
            limit=limit,
            database_=self.database,
        )
        return [
            CandidateEntityResolutionTarget(
                candidate_id=str(record["candidate_id"]),
                evidence_id=str(record["evidence_id"]),
                subject_cik=str(record["subject_cik"]),
                subject_name=str(record["subject_name"]),
                object_mention=str(record["object_mention"]),
                role=str(record["role"]),
                supporting_text=str(record["supporting_text"]),
                evidence_text=str(record["evidence_text"]),
            )
            for record in records
        ]

    def get_supplier_by_alias(self, alias: str) -> SupplierIdentity | None:
        records, _, _ = self.driver.execute_query(
            self.SUPPLIER_BY_ALIAS_QUERY,
            alias=alias,
            database_=self.database,
        )
        if not records:
            return None
        record = records[0]
        return SupplierIdentity(
            supplier_id=str(record["supplier_id"]),
            canonical_name=str(record["canonical_name"]),
            aliases=[str(alias) for alias in record["aliases"]],
        )

    def sync_candidate_entity_resolutions(
        self,
        resolutions: list[CandidateEntityResolution],
    ) -> None:
        if not resolutions:
            return

        payload = [
            {
                "candidate_id": resolution.candidate_id,
                "supplier_id": resolution.supplier.supplier_id,
                "canonical_name": resolution.supplier.canonical_name,
                "aliases": resolution.supplier.aliases,
                "resolution_method": resolution.resolution_method,
            }
            for resolution in resolutions
        ]
        self.driver.execute_query(
            self.UPSERT_CANDIDATE_ENTITY_RESOLUTIONS_QUERY,
            resolutions=payload,
            database_=self.database,
        )

    def get_industry_exposures(
        self,
        portfolio_id: UUID,
    ) -> list[StructuralExposureItem]:
        return self._get_structural_exposures(
            self.INDUSTRY_EXPOSURES_QUERY,
            portfolio_id,
        )

    def get_country_exposures(
        self,
        portfolio_id: UUID,
    ) -> list[StructuralExposureItem]:
        return self._get_structural_exposures(
            self.COUNTRY_EXPOSURES_QUERY,
            portfolio_id,
        )

    def _get_structural_exposures(
        self,
        query: str,
        portfolio_id: UUID,
    ) -> list[StructuralExposureItem]:
        records, _, _ = self.driver.execute_query(
            query,
            portfolio_id=str(portfolio_id),
            database_=self.database,
        )
        return [
            StructuralExposureItem(
                code=str(record["code"]),
                name=str(record["name"]),
                weight_pct=round(float(record["weight_pct"]), 6),
            )
            for record in records
        ]

    def close(self) -> None:
        self.driver.close()
