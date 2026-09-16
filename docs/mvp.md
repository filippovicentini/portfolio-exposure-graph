# MVP v0.1

## In scope

1. Create a portfolio from US-listed ticker symbols and weights.
2. Resolve known assets immediately.
3. Accept unseen syntactically valid tickers and queue them for enrichment.
4. Distinguish equities from ETFs once resolved.
5. Expand ETF holdings from sourced data.
6. Build a shared company knowledge graph.
7. Store evidence/provenance for document-derived edges.
8. Return exposure paths explaining why a portfolio is connected to an entity.
9. Provide a small interactive web UI.

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

Provider-backed validation and enrichment are implemented in the next milestone.
