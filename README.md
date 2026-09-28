# Portfolio Exposure Graph

A small, explainable portfolio intelligence application that reveals direct and indirect economic exposures hidden behind a list of holdings.

The product question is intentionally narrow:

> **What am I actually exposed to, and through which paths?**

## Status

Implemented:

- FastAPI backend and portfolio weight validation
- dynamic equity resolution through SEC ticker data
- dynamic US ETF recognition through Alpha Vantage listing data
- ETF holdings ingestion and one-level look-through
- direct + indirect exposure aggregation
- Neo4j local infrastructure
- Neo4j graph repository for portfolio, ETF, asset, and canonical company paths
- SEC-backed `Asset -> Company` canonicalization keyed by CIK
- SEC submissions metadata for primary SIC industry and business-address country
- `Company -> Industry` and `Company -> Country` structural graph edges
- portfolio-weight aggregation by SEC primary industry and business-address country
- bounded SEC 10-K/10-Q filing metadata ingestion into canonical Filing nodes
- deterministic filing evidence extraction into provenance-preserving Evidence nodes
- semantic relationship-candidate graph plumbing from Evidence, with provider abstraction and no automatic dependency promotion
- optional local Ollama semantic extraction with structured JSON output and deterministic post-validation
- deterministic candidate-entity resolution into internal canonical `Supplier` identities with evidence-derived aliases
- deterministic promotion of fully resolved, source-verifiable candidates into qualitative `Company -> DEPENDS_ON -> Supplier` edges with graph-linked provenance
- bounded portfolio dependency-path API with direct/ETF routes and source-level provenance
- mocked provider/repository tests that do not require external services

Next milestones:

- enrich internal Supplier identities with external identifiers where defensible
- small frontend consuming dependency paths and provenance

Out of scope for the MVP: price prediction, trading recommendations, portfolio optimization, broker integration, and real-time market data.

## Architecture today

```text
Portfolio
  |-- OWNS --> Equity Asset -- REPRESENTS --> Company
  |                                      |-- OPERATES_IN --> Industry
  |                                      |-- BASED_IN ----> Country
  |                                      `-- DEPENDS_ON --> Supplier
  `-- OWNS --> ETF
                 `-- HOLDS --> Equity Asset -- REPRESENTS --> Company
                                                     |-- OPERATES_IN --> Industry
                                                     |-- BASED_IN ----> Country
                                                     `-- DEPENDS_ON --> Supplier
```

Listed instruments remain `Asset` nodes because the same economic company can be represented by more than one security. When SEC ticker data provides a CIK, the graph creates one canonical `Company` node keyed by that CIK and links the asset with `REPRESENTS`. ETF constituents that cannot be resolved to a canonical company remain valid `Asset` nodes and are reported by graph sync.

Company metadata enrichment is a separate bounded step. It reads the SEC submissions JSON for canonical companies and stores the SEC primary SIC classification as `OPERATES_IN` plus the SEC business-address country as `BASED_IN`. These are structural facts, not numeric exposure weights. The endpoint defaults to 25 companies per call so large ETFs do not trigger hundreds of SEC requests in one synchronous request.

SEC filing ingestion is also bounded and currently stores only recent `10-K` and `10-Q` metadata. Each filing is a canonical `Filing` node keyed by SEC accession number and linked from its canonical company with `FILED`. The node keeps the filing date, report date, form, primary-document URL, filing-index URL, and submissions source URL.

Filing evidence extraction is a separate bounded step. It downloads stored SEC primary-document URLs and records conservative dependency-related excerpts as `Evidence` nodes linked with `CONTAINS_EVIDENCE`. Extraction is deterministic keyword matching (`sec_html_dependency_keywords_v3`), not an AI judgment. An evidence node is only a source excerpt/candidate and does not create or imply a `DEPENDS_ON` relationship.

The next graph layer stores structured `RelationshipCandidate` nodes linked from source evidence with `SUPPORTS_CANDIDATE`. An optional local Ollama provider can populate these candidates from Evidence using constrained JSON output plus deterministic validation of verbatim mentions and supporting text. If no semantic provider is configured, targets remain unresolved and are not marked as processed. Candidate mentions can then be resolved deterministically into internal canonical `Supplier` identities through `RESOLVES_TO`. Explicit filing aliases such as `Samsung Electronics Co., Ltd., or Samsung` are preserved and reused; exact aliases already known in the graph are reused conservatively. A resolved candidate still is not trusted by itself; a separate bounded promotion step re-validates source spans and Supplier aliases before creating a qualitative, provenance-linked `DEPENDS_ON` edge.

The dependency-path API traverses portfolio holdings through canonical companies to promoted Suppliers and returns the source provenance required to explain each dependency. `company_path_weight_pct` is only the sourced direct or one-level ETF look-through weight reaching the dependent Company. It is not a supplier-dependency percentage, and `DEPENDS_ON` adds no numeric multiplier.

Structural exposure aggregation reuses only sourced numeric weights already present on `OWNS` and `HOLDS`. An industry bucket therefore means "portfolio/look-through weight whose canonical company has this SEC primary SIC". A country bucket means "portfolio/look-through weight whose canonical company has this SEC business-address country". It is not a revenue-by-country estimate, and no numeric weight is inferred from `OPERATES_IN` or `BASED_IN` themselves. Coverage fields report how much portfolio/look-through weight currently has metadata for each dimension.

## Environment

External provider credentials are read from environment variables:

```bash
export SEC_USER_AGENT="Portfolio Exposure Graph your-email@example.com"
export ALPHA_VANTAGE_API_KEY="..."
```

Neo4j defaults match the local `docker-compose.yml`, and can be overridden:

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="portfolioexposure"
export NEO4J_DATABASE="neo4j"
```

Semantic extraction is optional. To use a local Ollama model:

```bash
export SEMANTIC_PROVIDER="ollama"
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="qwen3:4b-instruct"
```

With `SEMANTIC_PROVIDER` unset, the rest of the application still works and semantic-candidate Evidence remains available for later processing. Ollama is contacted only when the semantic-candidate sync endpoint is called.

## Run locally

From the repository root:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
docker compose up -d neo4j
cd backend
uvicorn app.main:app --reload
```

Open API docs at `http://127.0.0.1:8000/docs`.

Useful endpoints include:

```text
POST /api/v1/portfolios
GET  /api/v1/portfolios/{portfolio_id}/lookthrough
POST /api/v1/portfolios/{portfolio_id}/graph/sync
POST /api/v1/portfolios/{portfolio_id}/graph/company-metadata/sync?limit=25
POST /api/v1/portfolios/{portfolio_id}/graph/sec-filings/sync?company_limit=5&filings_per_company=4
POST /api/v1/portfolios/{portfolio_id}/graph/filing-evidence/sync?filing_limit=4&evidence_per_filing=5
POST /api/v1/portfolios/{portfolio_id}/graph/evidence-semantic-candidates/sync?evidence_limit=10&candidates_per_evidence=5
POST /api/v1/portfolios/{portfolio_id}/graph/candidate-entities/sync?candidate_limit=25
POST /api/v1/portfolios/{portfolio_id}/graph/evidence-backed-dependencies/sync?candidate_limit=25
GET  /api/v1/portfolios/{portfolio_id}/graph/paths
GET  /api/v1/portfolios/{portfolio_id}/graph/dependency-paths?limit=100
GET  /api/v1/portfolios/{portfolio_id}/graph/structural-exposure
```

## Test

```bash
cd backend
python -m pytest
```

Provider tests use mocks. The normal test suite does not require SEC, Alpha Vantage, Ollama, or a running Neo4j instance.

See [`docs/graph-schema.md`](docs/graph-schema.md) and [`docs/mvp.md`](docs/mvp.md).
