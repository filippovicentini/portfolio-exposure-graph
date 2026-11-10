"""Build an unlabeled evaluation dataset of real SEC filing excerpts.

Uses the same providers as the pipeline (SecFilingsProvider and
SecFilingEvidenceProvider), so the excerpts are exactly what the semantic
step would see. Output: one JSON object per excerpt with full provenance and
an empty ``expected`` list, to be labeled by hand.

    SEC_USER_AGENT="Your Name you@example.com" \\
        python evals/build_dataset.py --out evals/datasets/unlabeled.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from portfolio_exposure_graph.domain.models import FilingEvidenceTarget
from portfolio_exposure_graph.providers.sec_filing_evidence_provider import (
    SecFilingEvidenceProvider,
)
from portfolio_exposure_graph.providers.sec_filings_provider import SecFilingsProvider

# (CIK, name, forms to include, filings per form)
COMPANIES = [
    ("0001045810", "NVIDIA CORP", ("10-K", "10-Q"), 3),
    ("0000002488", "ADVANCED MICRO DEVICES INC", ("10-K",), 1),
    ("0000804328", "QUALCOMM INC/DE", ("10-K",), 1),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--evidence-per-filing", type=int, default=10)
    args = parser.parse_args()

    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        print("SEC_USER_AGENT is required (SEC fair-access policy).", file=sys.stderr)
        return 2

    filings_provider = SecFilingsProvider(user_agent=user_agent)
    evidence_provider = SecFilingEvidenceProvider(user_agent=user_agent)
    rows = []
    seen_texts: set[str] = set()

    for cik, name, forms, per_form in COMPANIES:
        recent = filings_provider.get_recent_filings(cik, limit=12)
        if recent is None:
            print(f"no filings for {name}", file=sys.stderr)
            continue
        for form in forms:
            for filing in [f for f in recent.filings if f.form == form][:per_form]:
                batch = evidence_provider.extract_evidence(
                    FilingEvidenceTarget(
                        accession_number=filing.accession_number,
                        cik=cik,
                        form=filing.form,
                        filing_date=filing.filing_date,
                        source_url=filing.source_url,
                    ),
                    limit=args.evidence_per_filing,
                )
                for item in batch.evidence if batch else []:
                    if item.evidence_text in seen_texts:  # repeated boilerplate
                        continue
                    seen_texts.add(item.evidence_text)
                    rows.append(
                        {
                            "id": item.evidence_id,
                            "subject_cik": cik,
                            "subject_name": name,
                            "accession_number": filing.accession_number,
                            "form": filing.form,
                            "filing_date": filing.filing_date.isoformat(),
                            "source_url": item.source_url,
                            "matched_terms": item.matched_terms,
                            "text": item.evidence_text,
                            "expected": [],
                        }
                    )
                print(f"{name} {filing.form} {filing.filing_date}: {len(batch.evidence) if batch else 0} excerpts", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} unique excerpts to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
