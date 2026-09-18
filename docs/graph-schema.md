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
- SEC submissions metadata can link `Company` to `Industry` through `[:OPERATES_IN]`; the industry key is the SEC SIC code.
- SEC business-address metadata can link `Company` to `Country` through `[:BASED_IN]`; the country key is the normalized SEC/EDGAR country code.

`OPERATES_IN` currently means the company's primary SEC SIC classification, not an inferred list of every industry in which it participates. `BASED_IN` currently means the country derived from the SEC business address, not geographic revenue exposure. U.S. state codes are normalized to EDGAR code `X1` (United States), and Canadian province codes to `Z4` (Canada).

Portfolio structural breakdowns aggregate sourced `OWNS` weights and one-level `OWNS * HOLDS` look-through weights by these structural classifications. The classification edges themselves do not add a numeric multiplier. `industry_coverage_pct` and `country_coverage_pct` are therefore the summed portfolio/look-through weights for assets whose canonical companies currently have the corresponding metadata.

Company resolution is deliberately best-effort. A provider failure or an unresolved ETF constituent does not block portfolio graph sync; the asset remains in the graph and the sync response reports its ticker in `unresolved_company_assets`. Company metadata enrichment is also best-effort and runs in bounded batches so a large ETF does not cause hundreds of SEC requests in a single synchronous operation. Successfully enriched companies are marked with `sec_metadata_synced_at` and the SEC source URL so the shared graph can reuse the metadata across portfolios.
