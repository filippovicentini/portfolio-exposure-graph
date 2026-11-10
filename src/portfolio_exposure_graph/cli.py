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
    return parser


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
