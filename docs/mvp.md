# MVP v0.1

## In scope

1. Create a portfolio from US-listed ticker symbols and weights.
2. Resolve known assets immediately.
3. Accept unseen syntactically valid tickers and queue them for enrichment.
4. Distinguish equities from ETFs once resolved.
5. Expand ETF holdings from sourced data.
6. Build a shared company knowledge graph with SEC-backed company identity, primary industry, and business-address country metadata.
7. Ingest recent SEC 10-K/10-Q filing metadata as canonical source-document nodes.
8. Extract traceable dependency-candidate evidence from SEC filing text without promoting it to graph facts.
9. Represent structured relationship candidates separately from trusted graph relationships, preserving their source Evidence, with optional local Ollama extraction.
10. Resolve exact candidate mentions into reusable internal Supplier identities while preserving evidence-derived aliases and keeping relationship roles on the candidate.
11. Promote only resolved, source-verifiable dependency candidates into qualitative `DEPENDS_ON` edges while preserving graph-linked provenance.
12. Store evidence/provenance for document-derived edges.
13. Return bounded exposure and supplier-dependency paths explaining why a portfolio is connected to an entity, including source provenance for promoted dependencies.
14. Aggregate sourced portfolio/look-through weights by primary SEC industry and business-address country.
15. Provide a small interactive web UI.

## Explicitly out of scope

- Price prediction
- Buy/sell recommendations
- Portfolio optimization
- Automated trading
- Options/crypto
- Broker integrations
- Realtime market data
- Generic finance chatbot
- Precise numeric risk impact for structural relationships

## Unknown ticker behavior

An unseen ticker does not block portfolio creation.

`known -> READY`

`unseen but syntactically valid -> PENDING_ENRICHMENT -> queued job`

`invalid -> INVALID`

Provider-backed equity and ETF resolution are implemented. Remaining unresolved assets stay non-blocking and can be enriched later.
