"""Command line entry point: ``peg``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from portfolio_exposure_graph import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="peg",
        description="Portfolio Exposure Graph: explainable portfolio exposures.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser(
        "serve",
        help="Run the API and web UI.",
        description=(
            "Run the API and web UI. Configuration (SEC_USER_AGENT, NEO4J_URI, "
            "PORTFOLIO_STORE, ...) is read from environment variables; see the README."
        ),
    )
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    serve.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    serve.add_argument("--reload", action="store_true", help="Reload on code changes (development).")
    serve.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug"],
    )

    evaluate = commands.add_parser(
        "eval",
        help="Evaluate LLM supplier extraction against a labeled dataset.",
        description=(
            "Run the semantic-candidate extractor on every excerpt of a labeled "
            "dataset and report precision/recall before and after deterministic "
            "validation. Needs a running Ollama server."
        ),
    )
    evaluate.add_argument(
        "--dataset",
        default="evals/datasets/sec_supplier_mentions_v1.jsonl",
        help="Labeled JSONL dataset (default: %(default)s).",
    )
    evaluate.add_argument("--model", default=None, help="Ollama model (default: OLLAMA_MODEL).")
    evaluate.add_argument("--base-url", default=None, help="Ollama URL (default: OLLAMA_BASE_URL).")
    evaluate.add_argument("--limit", type=int, default=10, help="Max candidates per excerpt.")
    evaluate.add_argument("--out", default=None, help="Write the full JSON report here.")
    return parser


def run_eval(args: argparse.Namespace) -> int:
    from portfolio_exposure_graph.core.config import settings
    from portfolio_exposure_graph.evaluation import (
        evaluate,
        format_report,
        load_dataset,
        write_report,
    )
    from portfolio_exposure_graph.providers.ollama_semantic_candidate_provider import (
        OllamaSemanticCandidateProvider,
    )

    extractor = OllamaSemanticCandidateProvider(
        base_url=args.base_url or settings.ollama_base_url,
        model_name=args.model or settings.ollama_model,
    )
    examples = load_dataset(args.dataset)
    report = evaluate(examples, extractor, dataset_name=args.dataset, limit=args.limit)
    print(format_report(report))
    if args.out:
        write_report(report, args.out)
        print(f"\nFull report: {args.out}")
    return 1 if report.examples_with_errors == report.examples else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "portfolio_exposure_graph.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level,
        )
    if args.command == "eval":
        return run_eval(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
