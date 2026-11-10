# Portfolio Exposure Graph

[![CI](https://github.com/filippovicentini/portfolio-exposure-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/filippovicentini/portfolio-exposure-graph/actions/workflows/ci.yml)
![Python 3.11–3.13](https://img.shields.io/badge/python-3.11%E2%80%933.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**What am I actually exposed to, and through which paths?**

A list of holdings hides most of a portfolio's real exposure: ETF look-through, the industries and countries behind each company, and the suppliers those companies depend on. Portfolio Exposure Graph builds that picture as a knowledge graph from primary sources, mainly SEC EDGAR filings. Every edge it shows can be traced back to the document it came from.

> **Not investment advice.** This project is a research and engineering showcase. Its output describes sourced structural exposures; it is not financial, investment, legal or tax advice, and it must not be relied on to make investment decisions. Data comes from third-party sources (SEC EDGAR, Alpha Vantage) and may be incomplete, delayed or wrong.

## What it shows

Take a portfolio of **80% NVIDIA (NVDA) and 20% TSMC (TSM)**.

NVIDIA's FY2026 10-K names its key suppliers in one paragraph:

> We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited, or TSMC, and Samsung Electronics Co., Ltd., or Samsung, to produce our semiconductor wafers. We purchase memory from SK Hynix Inc., Micron Technology, Inc., and Samsung. […] We engage with independent subcontractors and contract manufacturers such as Hon Hai Precision Industry Co., Ltd., Wistron Corporation, and Fabrinet to perform assembly, testing and packaging of our final products.
>
> — NVIDIA Corp., Form 10-K filed 2026-02-25 (accession 0001045810-26-000021)

From that, the graph answers questions a holdings list cannot:

- **80% of the portfolio reaches companies that depend on TSMC**, as a foundry, through NVIDIA.
- **TSMC is also held directly at 20%.** The portfolio is concentrated on TSMC from two directions, and a plain holdings list shows only one of them.
- **Which suppliers are SEC registrants:** TSMC, SK hynix, Micron and Fabrinet are linked to their SEC CIKs. Samsung, Hon Hai and Wistron are not SEC registrants and stay unlinked rather than being matched by guesswork.

![Supplier exposure for 80% NVDA + 20% TSM](docs/images/supplier-exposure.png)

*Supplier exposure in the web UI. Portfolio resolution, SEC company data and supplier-to-SEC-company linking come from a live run against SEC EDGAR. For this screenshot the seven `DEPENDS_ON` edges were entered from the verbatim 10-K paragraph above, because the LLM extraction step that normally proposes them was not run.*

## How it works

```mermaid
flowchart LR
    P[Portfolio<br/>tickers + weights] --> R[Resolve<br/>SEC tickers · ETFs]
    R --> G[Graph<br/>Asset → Company by CIK<br/>ETF look-through]
    G --> M[SEC metadata<br/>industry · country]
    G --> F[SEC 10-K / 10-Q]
    F --> E[Evidence<br/>source excerpts]
    E --> C[Candidates<br/>local LLM + validation]
    C --> D[DEPENDS_ON<br/>promoted, with provenance]
    D --> L[Supplier ↔ SEC company]
    M --> X[(Industry / country exposure)]
    D --> Y[(Dependency paths<br/>Supplier exposure)]
    L --> Y
```

The graph lives in Neo4j:

```text
Portfolio -OWNS-> Asset -REPRESENTS-> Company -DEPENDS_ON-> Supplier -IDENTIFIED_AS-> Company
          -OWNS-> ETF -HOLDS-> Asset              -OPERATES_IN-> Industry
                                                  -BASED_IN-> Country
Company -FILED-> Filing -CONTAINS_EVIDENCE-> Evidence -SUPPORTS_CANDIDATE-> RelationshipCandidate -RESOLVES_TO-> Supplier
```

Each step is a separate, bounded, re-runnable API call; the web UI can run them in order. Details: [`docs/pipeline.md`](docs/pipeline.md) and [`docs/graph-schema.md`](docs/graph-schema.md).

## Design decisions

**Provenance is mandatory.** A `DEPENDS_ON` edge exists only if its graph path leads back to a specific filing, excerpt and candidate. The dependency-path API returns that provenance with every path, and the UI links to the SEC source.

**The LLM proposes, deterministic code decides.** A local model (Ollama, constrained JSON output) only proposes relationship candidates. Before anything becomes a graph fact:
- the mentioned supplier must appear verbatim in the supporting text;
- the supporting text must appear verbatim in the source excerpt;
- the excerpt must belong to the same company's filing.

A hallucinated supplier or quote is rejected rather than stored. How well this works is measured, not assumed: `peg eval` scores the model on 66 hand-labeled real filing excerpts, before and after validation. See [`evals/`](evals/README.md).

**No invented numbers.** The only numeric weights are sourced ones: portfolio weights, and ETF holding weights for look-through. A supplier's weight means "portfolio weight reaching companies that depend on it". It is not an estimate of revenue share or impact, and the exposure responses state their basis explicitly. Supplier weights overlap and can sum to more than 100%; a separate coverage figure counts each holding route once.

**Conservative entity resolution.** Suppliers are linked to SEC companies only by exact match after normalizing case, punctuation and legal forms ("Company Limited" equals "CO LTD"). Short acronyms such as "TSMC" are never used for linking, and names that point at more than one company are reported as ambiguous. An unlinked supplier is a correct answer, not a failure.

**Failure-tolerant ingestion.** Unknown tickers do not block portfolio creation; they go to an enrichment queue with:
- retries and exponential backoff;
- leases, so a crashed worker's job is picked up again;
- `FOR UPDATE SKIP LOCKED` on PostgreSQL, so several workers never take the same job.

A provider outage is never recorded as "this ticker does not exist".

## Quickstart

Requires Python 3.11+ and Docker (for Neo4j). From a clone, `docker compose up -d neo4j` starts the same Neo4j (and `postgres` if needed).

```bash
pip install "portfolio-exposure-graph @ git+https://github.com/filippovicentini/portfolio-exposure-graph"
```

```bash
docker run -d --name peg-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/portfolioexposure neo4j:5.26-community
```

```bash
export SEC_USER_AGENT="Portfolio Exposure Graph your-email@example.com"
```

```bash
peg serve
```

Open `http://127.0.0.1:8000/` for the web UI and `http://127.0.0.1:8000/docs` for the API.

- `SEC_USER_AGENT` is required by SEC EDGAR's fair-access policy: a contact address for your requests.
- ETF recognition needs `ALPHA_VANTAGE_API_KEY`.
- LLM extraction needs a local Ollama (`SEMANTIC_PROVIDER=ollama`).
- Install the `postgres` extra and set `PORTFOLIO_STORE=postgres` to keep portfolios across restarts.

All settings: [`docs/configuration.md`](docs/configuration.md).

## API

| Area | Endpoints |
|---|---|
| Portfolios | `POST /api/v1/portfolios`, `GET /api/v1/portfolios`, `GET /api/v1/portfolios/{id}`, `GET …/{id}/lookthrough` |
| Graph build | `POST …/{id}/graph/sync`, `…/graph/company-metadata/sync`, `…/graph/sec-filings/sync`, `…/graph/filing-evidence/sync` |
| Dependencies | `POST …/{id}/graph/evidence-semantic-candidates/sync`, `…/graph/candidate-entities/sync`, `…/graph/evidence-backed-dependencies/sync`, `…/graph/supplier-companies/sync` |
| Exposure | `GET …/{id}/graph/paths`, `…/graph/dependency-paths`, `…/graph/structural-exposure`, `…/graph/supplier-exposure` |
| Enrichment queue | `GET /api/v1/enrichment-jobs`, `GET /api/v1/enrichment-jobs/{job_id}`, `POST /api/v1/enrichment-jobs/process` |

`…/{id}` stands for `/api/v1/portfolios/{id}`. Sync endpoints take `limit`-style parameters that bound the work done per call; the interactive docs at `/docs` list them all.

## Development

```bash
git clone https://github.com/filippovicentini/portfolio-exposure-graph
```

```bash
cd portfolio-exposure-graph && python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -e ".[postgres,dev]"
```

```bash
python -m pytest
```

The test suite needs no network, SEC, Alpha Vantage, Ollama or Neo4j: providers are mocked and the Neo4j repository is tested against a fake driver. PostgreSQL store tests run when `TEST_DATABASE_URL` is set, each in a temporary schema:

```bash
TEST_DATABASE_URL="postgresql://peg:peg@localhost:5432/peg" python -m pytest
```

CI runs on every pull request and push to `main`:

- the full suite on Python 3.11, 3.12 and 3.13, against PostgreSQL 16;
- a packaging job that builds the wheel, installs it in a clean virtualenv and serves the app from it.

To evaluate LLM extraction against the labeled dataset (needs Ollama):

```bash
peg eval --out evals/report.json
```

Layout: `src/portfolio_exposure_graph/` (`providers/` for external data sources, `repositories/` for Neo4j and PostgreSQL storage, `services/` for pipeline logic, `api/` for FastAPI routes, `web/` for the UI), `tests/`, `docs/`, `evals/` (labeled dataset and evaluation notes).

## Limitations

- Look-through is one ETF level deep; ETF holdings come from Alpha Vantage.
- Only US-listed instruments, via SEC ticker data.
- Dependency evidence comes from recent 10-K and 10-Q filings and keyword-selected excerpts, so suppliers a filing never names are invisible.
- Suppliers that are not SEC registrants (e.g. Samsung, Hon Hai) are not linked to a company. Another identifier source, such as LEI, would be needed.
- Weights are structural, not economic: no revenue share, impact or risk numbers are inferred.

Out of scope by design: price prediction, trading recommendations, portfolio optimization, broker integration and real-time market data. See [`docs/mvp.md`](docs/mvp.md).

## License

[MIT](LICENSE). The software is provided "as is", without warranty of any kind; see the license for the full terms. Third-party data retrieved at runtime (SEC EDGAR, Alpha Vantage) is subject to its providers' own terms.
