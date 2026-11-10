"""Evaluate supplier-candidate extraction against a hand-labeled dataset.

Each dataset row is a real SEC filing excerpt with the supplier mentions a
careful reader would extract (``expected``). The evaluated extractor is run
twice per excerpt, conceptually:

- ``raw``: what the model proposed, before any deterministic check;
- ``validated``: what survives the pipeline's validation (verbatim spans,
  mention inside supporting text, not the subject company).

Comparing the two shows how much the deterministic layer improves precision
and what it costs in recall.

Scoring:

- **entity level**: was each expected organization found at all;
- **pair level**: was it found with an acceptable role (Samsung as a foundry
  and as a memory supplier are two pairs);
- a prediction matches an expected organization when its mention, normalized
  like Supplier-to-company linking does (case, punctuation, trailing legal
  forms), equals one of that organization's accepted names;
- ``optional`` expectations never count as misses, and predicting them is not
  a false positive;
- ``negative_excerpts_with_false_positives`` counts excerpts that name no
  supplier but still received at least one prediction: the hallucination rate
  on hard negatives such as competitor lists.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from portfolio_exposure_graph.domain.enums import CandidateRole
from portfolio_exposure_graph.domain.models import (
    EvidenceSemanticTarget,
    RelationshipCandidate,
)
from portfolio_exposure_graph.providers.ollama_semantic_candidate_provider import (
    ProposedCandidate,
)
from portfolio_exposure_graph.services.supplier_company_linker import (
    normalize_entity_name,
)

STAGES = ("raw", "validated")


class ExpectedMention(BaseModel):
    names: list[str] = Field(min_length=1)
    roles: list[CandidateRole] = Field(min_length=1)
    optional: bool = False


class EvalExample(BaseModel):
    id: str
    subject_cik: str
    subject_name: str
    accession_number: str
    form: str
    filing_date: date
    source_url: str
    text: str
    expected: list[ExpectedMention] = Field(default_factory=list)
    label_note: str | None = None

    def target(self) -> EvidenceSemanticTarget:
        return EvidenceSemanticTarget(
            evidence_id=self.id,
            subject_cik=self.subject_cik,
            subject_name=self.subject_name,
            accession_number=self.accession_number,
            evidence_text=self.text,
            source_url=self.source_url,
            source_date=self.filing_date,
        )


class Prediction(BaseModel):
    mention: str
    role: CandidateRole


class Metrics(BaseModel):
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float | None:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)

    def add(self, other: "Metrics") -> None:
        self.true_positives += other.true_positives
        self.false_positives += other.false_positives
        self.false_negatives += other.false_negatives

    def summary(self) -> dict:
        def rounded(value: float | None) -> float | None:
            return None if value is None else round(value, 4)

        return {
            "precision": rounded(self.precision),
            "recall": rounded(self.recall),
            "f1": rounded(self.f1),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
        }


class ExampleResult(BaseModel):
    id: str
    predictions: dict[str, list[Prediction]]
    false_positives: dict[str, list[str]]
    missed: dict[str, list[str]]
    error: str | None = None


class StageReport(BaseModel):
    entity: Metrics
    pair: Metrics
    negative_excerpts: int
    negative_excerpts_with_false_positives: int


class EvalReport(BaseModel):
    dataset: str
    model: str
    examples: int
    examples_with_errors: int
    proposals: int
    proposals_rejected_by_validation: int
    stages: dict[str, StageReport]
    results: list[ExampleResult]

    def summary(self) -> dict:
        return {
            "dataset": self.dataset,
            "model": self.model,
            "examples": self.examples,
            "examples_with_errors": self.examples_with_errors,
            "proposals": self.proposals,
            "proposals_rejected_by_validation": self.proposals_rejected_by_validation,
            "stages": {
                name: {
                    "entity": stage.entity.summary(),
                    "pair": stage.pair.summary(),
                    "negative_excerpts": stage.negative_excerpts,
                    "negative_excerpts_with_false_positives": (
                        stage.negative_excerpts_with_false_positives
                    ),
                }
                for name, stage in self.stages.items()
            },
        }


class CandidateExtractor(Protocol):
    """What the evaluation needs; OllamaSemanticCandidateProvider satisfies it."""

    model_name: str

    def propose(
        self, evidence: EvidenceSemanticTarget, limit: int
    ) -> list[ProposedCandidate] | None: ...

    def validate(
        self,
        evidence: EvidenceSemanticTarget,
        proposals: list[ProposedCandidate],
        limit: int,
    ) -> list[RelationshipCandidate]: ...


def load_dataset(path: str | Path) -> list[EvalExample]:
    with open(path, encoding="utf-8") as handle:
        return [EvalExample.model_validate_json(line) for line in handle if line.strip()]


def score_example(
    example: EvalExample,
    predictions: Iterable[Prediction],
) -> tuple[Metrics, Metrics, list[str], list[str]]:
    """Return entity metrics, pair metrics, false-positive mentions, misses."""
    expected = example.expected
    names = [{normalize_entity_name(name) for name in item.names} for item in expected]

    entity_of: dict[str, int] = {}  # normalized name -> entity id
    entities: list[set[str]] = []
    for item_names in names:
        entity_id = next(
            (entity_of[name] for name in item_names if name in entity_of), None
        )
        if entity_id is None:
            entity_id = len(entities)
            entities.append(set())
        entities[entity_id] |= item_names
        for name in item_names:
            entity_of[name] = entity_id
    item_entity = [entity_of[next(iter(item_names))] for item_names in names]
    required_entities = {
        item_entity[i] for i, item in enumerate(expected) if not item.optional
    }

    predicted_entities: set[int] = set()
    matched_items: set[int] = set()
    false_positive_mentions: list[str] = []
    false_positive_pairs: set[tuple[str, CandidateRole]] = set()
    seen_unmatched: set[str] = set()

    for prediction in predictions:
        key = normalize_entity_name(prediction.mention)
        entity_id = entity_of.get(key)
        if entity_id is None:
            if key not in seen_unmatched:
                seen_unmatched.add(key)
                false_positive_mentions.append(prediction.mention)
            false_positive_pairs.add((key, prediction.role))
            continue
        predicted_entities.add(entity_id)
        role_matches = [
            i
            for i, item in enumerate(expected)
            if item_entity[i] == entity_id and prediction.role in item.roles
        ]
        if role_matches:
            matched_items.update(role_matches)
        else:
            false_positive_pairs.add((key, prediction.role))

    entity = Metrics(
        true_positives=len(predicted_entities & required_entities),
        false_positives=len(false_positive_mentions),
        false_negatives=len(required_entities - predicted_entities),
    )
    required_items = {i for i, item in enumerate(expected) if not item.optional}
    pair = Metrics(
        true_positives=len(matched_items & required_items),
        false_positives=len(false_positive_pairs),
        false_negatives=len(required_items - matched_items),
    )
    missed = [
        f"{expected[i].names[0]} ({'/'.join(role.value for role in expected[i].roles)})"
        for i in sorted(required_items - matched_items)
    ]
    return entity, pair, false_positive_mentions, missed


def evaluate(
    examples: list[EvalExample],
    extractor: CandidateExtractor,
    dataset_name: str = "",
    limit: int = 10,
) -> EvalReport:
    stages = {
        name: StageReport(
            entity=Metrics(),
            pair=Metrics(),
            negative_excerpts=0,
            negative_excerpts_with_false_positives=0,
        )
        for name in STAGES
    }
    results: list[ExampleResult] = []
    proposals_total = 0
    rejected_total = 0
    errors = 0

    for example in examples:
        target = example.target()
        error = None
        try:
            proposals = extractor.propose(target, limit) or []
            validated = extractor.validate(target, proposals, limit)
        except Exception as exc:  # a failed call is scored as "no output"
            error = f"{type(exc).__name__}: {exc}"
            errors += 1
            proposals, validated = [], []

        proposals_total += len(proposals)
        rejected_total += len(proposals) - len(validated)
        predictions = {
            "raw": [Prediction(mention=p.object_mention, role=p.role) for p in proposals],
            "validated": [
                Prediction(mention=c.object_mention, role=c.role) for c in validated
            ],
        }

        is_negative = not any(not item.optional for item in example.expected)
        false_positives: dict[str, list[str]] = {}
        missed: dict[str, list[str]] = {}
        for name in STAGES:
            entity, pair, fp_mentions, misses = score_example(example, predictions[name])
            stage = stages[name]
            stage.entity.add(entity)
            stage.pair.add(pair)
            if is_negative:
                stage.negative_excerpts += 1
                if fp_mentions:
                    stage.negative_excerpts_with_false_positives += 1
            false_positives[name] = fp_mentions
            missed[name] = misses

        results.append(
            ExampleResult(
                id=example.id,
                predictions=predictions,
                false_positives=false_positives,
                missed=missed,
                error=error,
            )
        )

    return EvalReport(
        dataset=dataset_name,
        model=getattr(extractor, "model_name", "unknown"),
        examples=len(examples),
        examples_with_errors=errors,
        proposals=proposals_total,
        proposals_rejected_by_validation=rejected_total,
        stages=stages,
        results=results,
    )


def format_report(report: EvalReport) -> str:
    def pct(value: float | None) -> str:
        return "  n/a" if value is None else f"{value * 100:5.1f}%"

    lines = [
        f"Dataset: {report.dataset}",
        f"Model:   {report.model}",
        f"Excerpts: {report.examples} ({report.examples_with_errors} with errors)",
        f"Proposals: {report.proposals}, rejected by validation: "
        f"{report.proposals_rejected_by_validation}",
        "",
        f"{'stage':<10} {'level':<7} {'precision':>9} {'recall':>7} {'f1':>7}   tp  fp  fn",
    ]
    for name, stage in report.stages.items():
        for level, metrics in (("entity", stage.entity), ("pair", stage.pair)):
            lines.append(
                f"{name:<10} {level:<7} {pct(metrics.precision):>9} {pct(metrics.recall):>7} "
                f"{pct(metrics.f1):>7}  {metrics.true_positives:3} {metrics.false_positives:3} "
                f"{metrics.false_negatives:3}"
            )
    lines.append("")
    for name, stage in report.stages.items():
        lines.append(
            f"{name}: {stage.negative_excerpts_with_false_positives} of "
            f"{stage.negative_excerpts} supplier-free excerpts received a false positive"
        )
    return "\n".join(lines)


def write_report(report: EvalReport, path: str | Path) -> None:
    payload = {**report.summary(), "results": [r.model_dump(mode="json") for r in report.results]}
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
