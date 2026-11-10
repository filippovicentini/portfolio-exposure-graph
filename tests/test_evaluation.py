import json
from pathlib import Path

import pytest

from portfolio_exposure_graph import cli
from portfolio_exposure_graph.domain.enums import CandidateRole
from portfolio_exposure_graph.evaluation import (
    EvalExample,
    ExpectedMention,
    Prediction,
    evaluate,
    format_report,
    load_dataset,
    score_example,
    write_report,
)
from portfolio_exposure_graph.providers.ollama_semantic_candidate_provider import (
    OllamaSemanticCandidateProvider,
    ProposedCandidate,
)

DATASET = Path(__file__).resolve().parents[1] / "evals" / "datasets" / "sec_supplier_mentions_v1.jsonl"


class ScriptedExtractor:
    """Proposes a fixed answer per excerpt; validates with the real pipeline rules."""

    model_name = "scripted"

    def __init__(self, answers=None, fail_ids=()):
        self.answers = answers or (lambda example: [])
        self.fail_ids = set(fail_ids)
        self._validator = OllamaSemanticCandidateProvider(base_url="http://unused")
        self._examples = {}

    def bind(self, examples):
        self._examples = {example.id: example for example in examples}
        return self

    def propose(self, evidence, limit):
        if evidence.evidence_id in self.fail_ids:
            raise RuntimeError("model timed out")
        return self.answers(self._examples[evidence.evidence_id])

    def validate(self, evidence, proposals, limit):
        return self._validator.validate(evidence, proposals, limit)


def oracle(example):
    """The labeled answer, with the whole excerpt as supporting text."""
    return [
        ProposedCandidate(object_mention=item.names[0], role=item.roles[0], supporting_text=example.text)
        for item in example.expected
    ]


def example(text, *expected, subject="NVIDIA CORP"):
    return EvalExample(
        id="ex",
        subject_cik="0001045810",
        subject_name=subject,
        accession_number="0001045810-26-000021",
        form="10-K",
        filing_date="2026-02-25",
        source_url="https://www.sec.gov/x",
        text=text,
        expected=list(expected),
    )


# --- the committed dataset ------------------------------------------------


def test_dataset_is_well_formed_and_labels_are_verbatim():
    examples = load_dataset(DATASET)

    assert len(examples) == 66
    assert len({item.id for item in examples}) == len(examples)
    positives = [item for item in examples if item.expected]
    assert len(positives) == 5
    assert sum(len(item.expected) for item in examples) == 36
    for item in examples:
        for mention in item.expected:
            for name in mention.names:
                assert name in item.text, (item.id, name)
    # Hard negatives are labeled explicitly.
    assert any("competitor" in (item.label_note or "") for item in examples)


def test_correct_answers_survive_the_pipeline_validation():
    """If validation rejected correct answers, recall would be capped below 100%."""
    examples = load_dataset(DATASET)
    report = evaluate(examples, ScriptedExtractor(oracle).bind(examples), limit=10)

    for stage in ("raw", "validated"):
        assert report.stages[stage].pair.recall == 1.0
        assert report.stages[stage].pair.precision == 1.0
        assert report.stages[stage].negative_excerpts_with_false_positives == 0
    assert report.proposals_rejected_by_validation == 0
    assert report.stages["validated"].negative_excerpts == 61


# --- scoring ---------------------------------------------------------------

TEXT = (
    "We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited, "
    "or TSMC, and Samsung Electronics Co., Ltd., or Samsung. We purchase memory from "
    "Samsung. Intel is our main competitor."
)
TSMC = ExpectedMention(names=["Taiwan Semiconductor Manufacturing Company Limited", "TSMC"], roles=["foundry"])
SAMSUNG_FOUNDRY = ExpectedMention(names=["Samsung Electronics Co., Ltd.", "Samsung"], roles=["foundry"])
SAMSUNG_MEMORY = ExpectedMention(
    names=["Samsung Electronics Co., Ltd.", "Samsung"], roles=["memory_supplier", "component_supplier"]
)


def predict(*pairs):
    return [Prediction(mention=mention, role=role) for mention, role in pairs]


def test_an_alias_and_a_legal_name_variant_both_match():
    item = example(TEXT, TSMC)

    entity, pair, fps, missed = score_example(
        item, predict(("TSMC", "foundry"), ("Taiwan Semiconductor Manufacturing Co., Ltd.", "foundry"))
    )

    assert (entity.true_positives, entity.false_positives, entity.false_negatives) == (1, 0, 0)
    assert pair.true_positives == 1 and fps == [] and missed == []


def test_one_organization_with_two_roles_is_one_entity_and_two_pairs():
    item = example(TEXT, SAMSUNG_FOUNDRY, SAMSUNG_MEMORY)

    entity, pair, _, missed = score_example(item, predict(("Samsung", "foundry")))

    assert (entity.true_positives, entity.false_negatives) == (1, 0)
    assert (pair.true_positives, pair.false_negatives) == (1, 1)
    assert missed == ["Samsung Electronics Co., Ltd. (memory_supplier/component_supplier)"]


def test_wrong_role_counts_at_pair_level_only():
    item = example(TEXT, TSMC)

    entity, pair, fps, _ = score_example(item, predict(("TSMC", "memory_supplier")))

    assert (entity.true_positives, entity.false_positives) == (1, 0)
    assert (pair.true_positives, pair.false_positives, pair.false_negatives) == (0, 1, 1)
    assert fps == []


def test_a_competitor_is_a_false_positive():
    item = example(TEXT, TSMC)

    entity, _, fps, _ = score_example(item, predict(("TSMC", "foundry"), ("Intel", "supplier")))

    assert (entity.true_positives, entity.false_positives) == (1, 1)
    assert entity.precision == 0.5
    assert fps == ["Intel"]


def test_optional_expectations_are_neither_required_nor_false_positives():
    optional = ExpectedMention(names=["Samsung"], roles=["foundry"], optional=True)
    item = example(TEXT, TSMC, optional)

    missed_optional = score_example(item, predict(("TSMC", "foundry")))
    predicted_optional = score_example(item, predict(("TSMC", "foundry"), ("Samsung", "foundry")))

    assert missed_optional[0].false_negatives == 0
    assert predicted_optional[0].false_positives == 0
    assert predicted_optional[1].false_positives == 0


# --- end to end ------------------------------------------------------------


def test_validation_removes_hallucinations_and_the_report_shows_it():
    supplier_text = example(TEXT, TSMC).model_copy(update={"id": "pos"})
    competitor_list = example("Intel and Broadcom are our competitors.").model_copy(update={"id": "neg"})

    def answers(item):
        if item.id == "pos":
            return [
                ProposedCandidate(object_mention="TSMC", role="foundry", supporting_text=item.text),
                # Not in the text at all: validation must drop it.
                ProposedCandidate(object_mention="GlobalFoundries", role="foundry", supporting_text="made up"),
            ]
        # A competitor list: verbatim, so validation keeps it (a genuine model error).
        return [ProposedCandidate(object_mention="Intel", role="supplier", supporting_text=item.text)]

    examples = [supplier_text, competitor_list]
    report = evaluate(examples, ScriptedExtractor(answers).bind(examples))

    raw, validated = report.stages["raw"], report.stages["validated"]
    assert raw.entity.false_positives == 2
    assert validated.entity.false_positives == 1
    assert validated.entity.precision == 0.5 and raw.entity.precision == pytest.approx(1 / 3)
    assert validated.negative_excerpts_with_false_positives == 1
    assert report.proposals == 3
    assert report.proposals_rejected_by_validation == 1
    text = format_report(report)
    assert "rejected by validation: 1" in text
    assert "1 of 1 supplier-free excerpts received a false positive" in text


def test_a_failing_call_is_reported_and_scored_as_no_output(tmp_path):
    examples = [example(TEXT, TSMC)]
    report = evaluate(examples, ScriptedExtractor(oracle, fail_ids={"ex"}).bind(examples))

    assert report.examples_with_errors == 1
    assert report.results[0].error == "RuntimeError: model timed out"
    assert report.stages["validated"].entity.false_negatives == 1

    out = tmp_path / "report.json"
    write_report(report, out)
    payload = json.loads(out.read_text())
    assert payload["stages"]["validated"]["entity"]["recall"] == 0.0
    assert payload["results"][0]["error"] == "RuntimeError: model timed out"


def test_cli_eval_runs_the_ollama_extractor(monkeypatch, tmp_path, capsys):
    from portfolio_exposure_graph.providers import ollama_semantic_candidate_provider as module

    monkeypatch.setattr(module.OllamaSemanticCandidateProvider, "propose", lambda self, evidence, limit: [])
    out = tmp_path / "report.json"

    code = cli.main(["eval", "--dataset", str(DATASET), "--model", "test-model", "--out", str(out)])

    assert code == 0
    printed = capsys.readouterr().out
    assert "Model:   test-model" in printed
    assert json.loads(out.read_text())["stages"]["validated"]["entity"]["recall"] == 0.0
