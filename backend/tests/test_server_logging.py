"""The server's own notes and vendor warnings reach the output (docker logs)."""

import logging
import sys


def test_serve_sets_up_logging(client, db, monkeypatch, capsys):
    from scripts import serve

    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["serve.py"])
    monkeypatch.setattr(logging.getLogger(), "handlers", [])
    assert serve.main() == 0
    assert logging.getLogger("app").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("pycync").getEffectiveLevel() == logging.WARNING
    logging.getLogger("app.refresh").info("Cync refresh skipped for a home: test")
    logging.getLogger("pycync.tcp").debug("not shown")
    err = capsys.readouterr().err
    assert "INFO app.refresh: Cync refresh skipped for a home: test" in err
    assert "not shown" not in err
