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
- Neo4j graph repository for `Portfolio -> Asset` and `ETF -> Asset` paths
- mocked provider/repository tests that do not require external services

Next milestones:

- canonical `Company` nodes and `Asset -> Company` resolution
- SEC filing ingestion
- sourced supplier/dependency extraction
- provenance on document-derived graph edges
- small frontend

Out of scope for the MVP: price prediction, trading recommendations, portfolio optimization, broker integration, and real-time market data.

## Architecture today

```text
Portfolio
  |-- OWNS --> Equity
  `-- OWNS --> ETF
                 `-- HOLDS --> Asset
```

The graph layer intentionally stores ETF constituents as `Asset` nodes first. Canonical company resolution comes later, so the system does not claim a legal-entity mapping that has not yet been established.

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
GET  /api/v1/portfolios/{portfolio_id}/graph/paths
```

## Test

```bash
cd backend
python -m pytest
```

Provider tests use mocks. The normal test suite does not require SEC, Alpha Vantage, or a running Neo4j instance.

See [`docs/graph-schema.md`](docs/graph-schema.md) and [`docs/mvp.md`](docs/mvp.md).
