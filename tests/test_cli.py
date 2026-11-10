import sys

import pytest

from portfolio_exposure_graph import __version__, cli


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"peg {__version__}"


def test_a_command_is_required(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == 2


def test_serve_runs_uvicorn_with_the_app(monkeypatch):
    calls = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "9000", "--reload"]) == 0

    [(args, kwargs)] = calls
    assert args == ("portfolio_exposure_graph.main:app",)
    assert kwargs == {"host": "0.0.0.0", "port": 9000, "reload": True, "log_level": "info"}


def test_serve_defaults_to_localhost(monkeypatch):
    calls = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))

    cli.main(["serve"])

    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8000
    assert calls[0]["reload"] is False


def test_postgres_store_without_driver_explains_the_extra(monkeypatch):
    from portfolio_exposure_graph import dependencies

    monkeypatch.setitem(sys.modules, "psycopg", None)  # makes `import psycopg` fail

    with pytest.raises(RuntimeError, match=r"portfolio-exposure-graph\[postgres\]"):
        dependencies._require_postgres_driver()
