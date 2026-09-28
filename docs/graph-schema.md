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
| `Supplier` | Internal canonical identity for a named upstream supplier candidate |
| `Filing` | Canonical SEC filing / source document keyed by accession number |
| `Evidence` | Traceable excerpt extracted from a source document; not a graph fact by itself |
| `RelationshipCandidate` | Structured relationship proposal extracted from Evidence; not a trusted graph fact |
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
| `FILED` | Company -> Filing | Provenance / source document |
| `CONTAINS_EVIDENCE` | Filing -> Evidence | Provenance / extracted source excerpt |
| `SUPPORTS_CANDIDATE` | Evidence -> RelationshipCandidate | Provenance / semantic extraction proposal |
| `RESOLVES_TO` | RelationshipCandidate -> Supplier | Internal entity identity resolution; not dependency validation |
| `EXPOSED_TO` | Company -> Theme | Structural |

## Provenance rule

Every AI- or document-derived structural edge must remain traceably linked to provenance before it can be marked trusted. Full source metadata lives on `Filing`, `Evidence`, and `RelationshipCandidate`; promoted edges keep the candidate/evidence/accession identifiers needed to traverse back to that source material. Provenance includes:

- `source_document_id` / filing accession number
- `source_url`
- `source_date`
- `evidence_text`
- `extraction_method`

Confidence is not currently assigned. A future confidence field must have an explicit calibration/meaning before it is used.

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
- Recent SEC `10-K` and `10-Q` submissions are stored as `(:Filing {accession_number})` nodes and linked with `(:Company)-[:FILED]->(:Filing)`. The filing node stores document URLs and dates so later document-derived edges can point back to a stable source document.
- Filing excerpts selected by deterministic dependency keywords are stored as `(:Evidence {evidence_id})` nodes and linked with `(:Filing)-[:CONTAINS_EVIDENCE]->(:Evidence)`. Evidence stores the source document accession number, URL, filing date, matched terms, excerpt text, and extraction method.
- Structured semantic proposals are stored as `(:RelationshipCandidate {candidate_id})` nodes linked with `(:Evidence)-[:SUPPORTS_CANDIDATE]->(:RelationshipCandidate)`. Candidates keep the subject CIK/name, exact object mention, proposed relationship, controlled role, supporting text, extraction method, and model name.
- Candidate object mentions can be resolved into internal `(:Supplier {supplier_id})` identities with `(:RelationshipCandidate)-[:RESOLVES_TO]->(:Supplier)`. Supplier identity is deliberately conservative: explicit aliases in the same Evidence are reused, exact aliases already known in the graph can be reused, and no external legal identifier is invented. The candidate role remains on `RelationshipCandidate`, so one Supplier can legitimately appear in multiple roles.
- Fully resolved candidates can be promoted deterministically into `(:Company)-[:DEPENDS_ON]->(:Supplier)` edges. Promotion is qualitative only. The edge stores controlled roles plus candidate, Evidence, and filing accession identifiers; the complete source excerpt and source URL remain on the provenance nodes upstream. Multiple candidates for the same Company/Supplier pair merge into one dependency edge while preserving all supporting candidate/evidence identifiers.

`OPERATES_IN` currently means the company's primary SEC SIC classification, not an inferred list of every industry in which it participates. `BASED_IN` currently means the country derived from the SEC business address, not geographic revenue exposure. U.S. state codes are normalized to EDGAR code `X1` (United States), and Canadian province codes to `Z4` (Canada).

Portfolio structural breakdowns aggregate sourced `OWNS` weights and one-level `OWNS * HOLDS` look-through weights by these structural classifications. The classification edges themselves do not add a numeric multiplier. `industry_coverage_pct` and `country_coverage_pct` are therefore the summed portfolio/look-through weights for assets whose canonical companies currently have the corresponding metadata.

Filing evidence extraction downloads source documents only in a bounded explicit sync step. The current extractor is deterministic and conservative: it records strong supply-chain terms directly, while supplier/vendor and generic dependency terms require manufacturing/supply context in the same sentence before becoming `dependency_candidate` evidence. Evidence is provenance, not a trusted dependency edge, and no supplier identity, confidence score, theme, or numeric impact is inferred at this milestone.

Semantic-candidate extraction is also bounded and best-effort. The graph/repository/service/provider contract exists independently of any LLM vendor. The optional Ollama implementation uses a local model with a constrained JSON schema and then deterministically rejects non-verbatim object mentions, non-verbatim supporting text, subject-company self references, and duplicates. When no semantic provider is configured or the local model is unavailable, unresolved evidence is left unmarked so it can be processed later.

Candidate-entity resolution is a separate deterministic step. It creates internal Supplier identities from exact object mentions, captures explicit filing aliases such as `Taiwan Semiconductor Manufacturing Company Limited, or TSMC`, and reuses exact aliases already stored in the graph. It does not collapse merely similar corporate names, assign CIK/LEI/ticker identifiers, or validate the proposed dependency itself. `RelationshipCandidate` therefore remains an intermediate proposal even after `RESOLVES_TO`; no `DEPENDS_ON` edge is created by this layer.

Dependency promotion is another explicit bounded step. A candidate is promotable only when it proposes `DEPENDS_ON`, resolves to a Supplier, uses a supported upstream role, keeps the object mention verbatim inside the supporting text, keeps the supporting text verbatim inside the source Evidence, and the object mention matches an exact Supplier alias. The graph path itself must tie that Evidence back to the same Company and Filing. Candidates with deterministic validation failures are marked rejected with a reason; unexpected technical failures remain unmarked so they can be retried. Promoted `DEPENDS_ON` edges are qualitative and do not create or imply a numeric exposure percentage.

Portfolio dependency paths traverse either `OWNS -> REPRESENTS -> DEPENDS_ON` or one-level `OWNS -> HOLDS -> REPRESENTS -> DEPENDS_ON`. Each returned path includes the dependent Company, canonical Supplier, controlled roles, promotion basis, and source-level candidate/Evidence/Filing provenance. The numeric `company_path_weight_pct` stops at the Company: it is sourced from `OWNS` or `OWNS * HOLDS` and must not be interpreted as a percentage dependency on the Supplier.

Company resolution is deliberately best-effort. A provider failure or an unresolved ETF constituent does not block portfolio graph sync; the asset remains in the graph and the sync response reports its ticker in `unresolved_company_assets`. Company metadata enrichment is also best-effort and runs in bounded batches so a large ETF does not cause hundreds of SEC requests in a single synchronous operation. Successfully enriched companies are marked with `sec_metadata_synced_at` and the SEC source URL so the shared graph can reuse the metadata across portfolios.
