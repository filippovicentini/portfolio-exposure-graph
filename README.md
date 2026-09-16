# Portfolio Exposure Graph

A small, explainable portfolio intelligence application that reveals direct and indirect economic exposures hidden behind a list of holdings.

The product question is intentionally narrow:

> **What am I actually exposed to, and through which paths?**

## Status

**Milestone 1: foundation / vertical slice**

Implemented:

- FastAPI backend
- portfolio input with strict weight validation
- ticker normalization
- asset registry abstraction
- non-blocking handling of unseen tickers
- enrichment job abstraction
- explicit domain model for equities vs ETFs
- graph schema v0.1
- PostgreSQL + Neo4j local infrastructure definition
- unit/API tests

Not implemented yet:

- external ticker provider
- SEC ingestion
- ETF holdings ingestion
- Neo4j persistence
- LLM relationship extraction
- frontend

## Key design decision: unseen tickers

The application is not based on a manually pre-mapped ticker universe.

When an asset is already known, it is returned immediately as `ready`. When a syntactically valid but unseen ticker is submitted, the portfolio is still created and the asset is marked `pending_enrichment`. An enrichment job is queued so a provider-backed pipeline can resolve the ticker and construct its graph data later.

This enables lazy indexing and a shared knowledge graph rather than rebuilding company data per user.

## Run the API

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open API docs at `http://127.0.0.1:8000/docs`.

## Example

```bash
curl -X POST http://127.0.0.1:8000/api/v1/portfolios \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Demo",
    "positions": [
      {"ticker": "NVDA", "weight_pct": 70},
      {"ticker": "ASML", "weight_pct": 30}
    ]
  }'
```

`NVDA` is part of the tiny development seed registry, while `ASML` demonstrates the desired cache-miss behavior and is queued for enrichment.

## Test

```bash
cd backend
pytest -q
```

## Local data services

The future persistence layer is already represented in `docker-compose.yml`:

```bash
docker compose up -d
```

- PostgreSQL: application state, documents, jobs, portfolios
- Neo4j: shared economic knowledge graph

See [`docs/graph-schema.md`](docs/graph-schema.md) and [`docs/mvp.md`](docs/mvp.md).
