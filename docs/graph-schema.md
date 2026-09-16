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
| `HOLDS` | ETF -> Company | Yes when fund weight is sourced |
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
