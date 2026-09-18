# Graph schema v0.1

The graph answers one product question:

> Given a portfolio of securities, which direct and indirect economic exposures are connected to it, and why?

## Node types

| Node | Purpose |
|---|---|
| `Portfolio` | User-specific portfolio root |
| `Asset` | Exchange-listed instrument / ticker |
| `Company` | Canonical legal/economic company entity |
| `ETF` | Fund entity used for look-through |
| `Industry` | Industry classification |
| `Country` | Geographic exposure/entity |
| `Supplier` | Company acting as an upstream dependency |
| `Theme` | Economic/technology theme |

## Relationship types

| Relationship | Example | Quantitative? |
|---|---|---|
| `OWNS` | Portfolio -> Asset | Yes: portfolio weight |
| `REPRESENTS` | Asset -> Company | No |
| `HOLDS` | ETF -> Asset | Yes when fund weight is sourced |
| `OPERATES_IN` | Company -> Industry | Structural |
| `BASED_IN` | Company -> Country | Structural |
| `DEPENDS_ON` | Company -> Supplier | Structural |
| `EXPOSED_TO` | Company -> Theme | Structural |

## Provenance rule

Every AI- or document-derived structural edge must carry provenance before it can be marked trusted:

- `source_document_id`
- `source_url`
- `source_date`
- `evidence_text`
- `confidence`
- `extraction_method`

No numeric impact is inferred from a structural edge. Quantitative weights are used only when a sourced numeric relationship exists (portfolio weights, ETF holdings, etc.).

## Current Neo4j MVP representation

The graph separates listed instruments from canonical companies:

- `(:Portfolio)` is the user-specific root.
- Listed instruments are stored as `(:Asset)` nodes.
- Resolved assets also receive `:Equity` or `:ETF` labels.
- `(:Portfolio)-[:OWNS {weight_pct}]->(:Asset)` stores direct portfolio weights.
- `(:ETF)-[:HOLDS {weight_pct}]->(:Asset)` stores one-level sourced ETF holdings.
- SEC-resolved equity assets link to `(:Company {cik})` through `[:REPRESENTS]`.
- `Company.cik` is the canonical identity key; ticker symbols remain properties of `Asset`.

Company resolution is deliberately best-effort. A provider failure or an unresolved ETF constituent does not block portfolio graph sync; the asset remains in the graph and the sync response reports its ticker in `unresolved_company_assets`.
