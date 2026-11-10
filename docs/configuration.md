# Configuration

All settings are environment variables, read when the app starts.

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

Portfolios, the asset registry, and enrichment jobs are kept in memory by default and are lost when the server restarts. To persist them in the local PostgreSQL from `docker-compose.yml`:

```bash
export PORTFOLIO_STORE="postgres"
export DATABASE_URL="postgresql://peg:peg@localhost:5432/peg"
```

`DATABASE_URL` defaults to the compose credentials on `POSTGRES_PORT` (default `5432`). The `portfolios`, `assets`, and `enrichment_jobs` tables are created automatically on first use. The registry's development seeds (NVDA, MSFT) are inserted once and never overwrite a stored asset.

## Enrichment queue

| Variable | Default | Meaning |
|---|---|---|
| `ENRICHMENT_MAX_ATTEMPTS` | `3` | Attempts before a job fails |
| `ENRICHMENT_RETRY_BASE_SECONDS` | `60` | First retry delay; doubles per attempt |
| `ENRICHMENT_RETRY_MAX_SECONDS` | `3600` | Retry delay cap |
| `ENRICHMENT_WORKER_INTERVAL_SECONDS` | `0` | Background worker period; `0` disables it |
| `ENRICHMENT_WORKER_BATCH_SIZE` | `10` | Jobs per worker run |

See [`pipeline.md`](pipeline.md#unseen-tickers-the-enrichment-queue) for the queue's behaviour.

## Semantic extraction (optional)

| Variable | Default | Meaning |
|---|---|---|
| `SEMANTIC_PROVIDER` | unset | `ollama` enables the local LLM candidate step |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `qwen3:4b-instruct` | Model used for structured extraction |
