"""Testes do logging em arquivo (nunca no stderr, que sujaria a TUI)."""
import logging

import ytmusic_tui.log as log_module


def test_setup_logging_writes_to_file(tmp_path, monkeypatch):
    """Configura o arquivo de log, é idempotente e grava as mensagens."""
    monkeypatch.setattr(log_module, "user_log_dir", lambda appname: str(tmp_path))
    package_logger = logging.getLogger("ytmusic_tui")
    monkeypatch.setattr(package_logger, "handlers", [])

    path = log_module.setup_logging()

    assert path == tmp_path / "ytmusic-tui.log"
    assert path.parent.is_dir()
    # Idempotente: chamar de novo não duplica handlers
    assert log_module.setup_logging() == path
    assert len(package_logger.handlers) == 1

    try:
        logging.getLogger("ytmusic_tui.tui.app").exception("falha de teste")
        for handler in package_logger.handlers:
            handler.flush()
        contents = path.read_text(encoding="utf-8")
        assert "ERROR" in contents
        assert "ytmusic_tui.tui.app" in contents
        assert "falha de teste" in contents
    finally:
        for handler in package_logger.handlers:
            handler.close()
