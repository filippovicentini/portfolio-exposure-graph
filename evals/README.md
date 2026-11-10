# Extraction evaluation

Measures how well the LLM step finds the suppliers a filing names. The
question is the same one the pipeline asks the model: *which organizations
does this excerpt explicitly describe as an upstream supplier of the
company, and in what role?*

## Run

Needs a running Ollama with the model pulled (`ollama pull qwen3:4b-instruct`):

```bash
peg eval --out evals/report.json
```

`--model`, `--base-url` and `--dataset` override the defaults (`OLLAMA_MODEL`,
`OLLAMA_BASE_URL`, the v1 dataset). The command prints a summary and writes a
JSON report with every prediction, false positive and miss per excerpt.

## What is measured

For each excerpt the extractor runs once. Two stages are scored:

- **raw**: what the model proposed;
- **validated**: what survives the pipeline's deterministic checks (mention and
  supporting text must be verbatim spans of the excerpt, mention inside the
  supporting text, never the subject company itself).

Two levels:

- **entity**: was each expected organization found;
- **pair**: was it found with an acceptable role (Samsung as foundry and as
  memory supplier are two pairs).

Also reported:

- how many proposals validation rejected;
- how many supplier-free excerpts still received a prediction (hallucination
  rate on hard negatives).

A prediction matches an expected organization when its mention, normalized like
Supplier-to-company linking (case, punctuation, trailing legal forms), equals one
of the accepted names. "Taiwan Semiconductor Manufacturing Co., Ltd." therefore
matches "Taiwan Semiconductor Manufacturing Company Limited".

## Dataset: `datasets/sec_supplier_mentions_v1.jsonl`

| | |
|---|---|
| Excerpts | 66 real excerpts, produced by the pipeline's own evidence extractor |
| Sources | NVIDIA (10-K FY2024–FY2026, three 10-Qs), AMD 10-K (Feb 2026), Qualcomm 10-K (Nov 2026) |
| With suppliers | 5 excerpts, 36 expected organization–role pairs (1 optional) |
| Without suppliers | 61 excerpts, including hard negatives |

Hard negatives include a competitor list naming Broadcom, Intel, NXP and
others; regions where suppliers are located ("Taiwan and South Korea"); an
acquisition (Mellanox); a certification body (ISO); and a technology (CoWoS).

Each row keeps its provenance: CIK, accession number, form, filing date and
source URL. `evals/build_dataset.py` regenerates the unlabeled excerpts from
SEC EDGAR.

### Labeling rules

1. Label an organization only when the excerpt itself presents it as an upstream
   supplier of the subject company: foundry, memory or component supplier,
   contract manufacturer, assembly/test/packaging provider. Competitors,
   customers, regions, technologies and regulators are not suppliers.
2. Accepted `names` are spellings that appear verbatim in the excerpt (a full
   name plus an explicit alias such as "or TSMC"). The dataset test enforces this.
3. Accepted `roles`:
   - foundry: `foundry`;
   - memory: `memory_supplier` or `component_supplier`;
   - assembly, test, packaging and contract manufacturing:
     `contract_manufacturer` or `manufacturing_partner`.
4. One organization in two roles is two expectations (Samsung for NVIDIA).
5. A defensible but debatable case is `optional`: it never counts as a miss, and
   predicting it is not a false positive. Its `label_note` explains why. Example:
   Tongfu, AMD's joint-venture partner, where the text says the JVs, not Tongfu,
   provide the services.

### Review status

**Labels are pending human review.** They were drafted by an AI assistant
(Claude), which also wrote the code under evaluation, so they need an
independent check before the numbers are reported. Review the 5 positive
excerpts and the `label_note` entries, then update this section with the
reviewer and date.

### Known limitations

- Small: 35 required pairs from 5 excerpts, and three of those excerpts are the
  same NVIDIA paragraph in different years. That is a consistency check, not
  independent evidence.
- Only semiconductor companies, which name suppliers unusually explicitly.
- Excerpts are those the keyword-based evidence step selected, so this measures
  extraction given the evidence, not end-to-end discovery.
