"""Testes do logging em arquivo (JSON Lines — §13.1/T13).

O log nunca vai ao stderr (sujaria a TUI) e, desde o T13, cada linha é um
objeto JSON com campos fixos e privacidade mascarada pelo formatter
(§13.2). A rotação 0600 tem prova própria em
``tests/security/test_permissions.py``; aqui ela aparece para provar que
as linhas continuam JSON também nos arquivos rotacionados.
"""

import json
import logging
import stat
from datetime import datetime
from pathlib import Path

import pytest

import ytmusic_tui.log as log_module

#: Campos fixos de todo registro (§13.1); ``detail`` só com ``exc_info``.
_BASE_FIELDS = {
    "ts",
    "level",
    "component",
    "operation_id",
    "event",
    "error_code",
    "message",
}


@pytest.fixture
def log_env(tmp_path, monkeypatch):
    """Log configurado num tmp, sem handlers prévios (como o app configura)."""
    monkeypatch.setattr(log_module, "user_log_dir", lambda appname: str(tmp_path))
    package_logger = logging.getLogger("ytmusic_tui")
    monkeypatch.setattr(package_logger, "handlers", [])
    path = log_module.setup_logging()
    yield package_logger, path
    for handler in package_logger.handlers:
        handler.close()


def _flush(package_logger: logging.Logger) -> None:
    for handler in package_logger.handlers:
        handler.flush()


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_jsonl_com_campos_fixos_e_idempotencia(log_env):
    """Toda linha é JSON com os 7 campos; exc_info vira detail; setup é idempotente."""
    package_logger, path = log_env
    assert log_module.setup_logging() == path  # idempotente
    assert len(package_logger.handlers) == 1  # sem duplicar handler

    try:
        raise ValueError("falha de teste")
    except ValueError:
        logging.getLogger("ytmusic_tui.tui.app").exception("Falha ao abrir")

    _flush(package_logger)
    records = _lines(path)
    assert len(records) == 1
    record = records[0]
    assert set(record) == _BASE_FIELDS | {"detail"}
    assert record["level"] == "ERROR"
    assert record["component"] == "tui.app"
    assert record["message"] == "Falha ao abrir"
    assert record["operation_id"] is None
    assert record["event"] is None
    assert record["error_code"] is None
    assert "ValueError: falha de teste" in record["detail"]
    # ts é ISO-8601 com offset local (não UTC "pelado").
    assert datetime.fromisoformat(record["ts"]).utcoffset() is not None


def test_log_event_leva_operation_id_e_error_code(log_env):
    """Evento estruturado: campos extras presentes; sem exceção não tem detail."""
    package_logger, path = log_env

    log_module.log_event(
        "download",
        "download_failed",
        "download falhou",
        operation_id="task-1",
        error_code="FFMPEG_EXIT_1",
        level=logging.ERROR,
    )

    _flush(package_logger)
    record = _lines(path)[0]
    assert set(record) == _BASE_FIELDS
    assert record["component"] == "download"
    assert record["event"] == "download_failed"
    assert record["operation_id"] == "task-1"
    assert record["error_code"] == "FFMPEG_EXIT_1"
    assert record["level"] == "ERROR"
    assert record["message"] == "download falhou"


def test_mascara_payloads_sensiveis(log_env):
    """§13.2: HOME → ~, URL assinada sem token, headers de credencial redigidos."""
    package_logger, path = log_env
    home = str(Path.home())
    logger = logging.getLogger("ytmusic_tui.teste")

    logger.warning("arquivo em %s", Path(home) / "Musica" / "x.mp3")
    logger.warning("stream https://exemplo.com/a?sig=SEGREDO#frag falhou")
    logger.warning("Authorization: Bearer abc\nCookie: sess=xyz; a=b")
    try:
        raise RuntimeError(f"pasta {home}/segredo inacessível")
    except RuntimeError:
        logger.exception("erro de teste")

    _flush(package_logger)
    text = path.read_text(encoding="utf-8")
    records = _lines(path)

    assert home not in text
    assert records[0]["message"] == "arquivo em ~/Musica/x.mp3"
    assert "SEGREDO" not in text
    assert records[1]["message"] == "stream https://exemplo.com/a?… falhou"
    assert records[2]["message"] == "Authorization: [REDACTED]\nCookie: [REDACTED]"
    assert home not in records[3]["detail"]
    assert "~/segredo" in records[3]["detail"]


def test_cache_hit_nao_registra_a_consulta(tmp_path, caplog):
    """O log do cache hit é só o fato — a consulta do usuário não aparece (§13.2)."""
    from ytmusic_tui.api import YTMusicAPI, cache_key
    from ytmusic_tui.api.cache import ResponseCache
    from ytmusic_tui.api.models import SearchResult

    cache = ResponseCache(tmp_path / "api-cache")
    cache.put("search", cache_key("SEGREDO_QUERY", 25, 15), SearchResult().to_payload())
    api = YTMusicAPI(cache=cache, sleep=lambda _seconds: None)

    with caplog.at_level(logging.DEBUG, logger="ytmusic_tui.api"):
        api.search_catalog("SEGREDO_QUERY")

    assert any("cache hit" in record.getMessage() for record in caplog.records)
    assert "SEGREDO_QUERY" not in caplog.text


def test_rotacao_mantem_json_e_0600(tmp_path, monkeypatch):
    """Rotação preservada (§13.1): linhas continuam JSON; modos seguem 0600."""
    monkeypatch.setattr(log_module, "user_log_dir", lambda appname: str(tmp_path))
    monkeypatch.setattr(log_module, "_MAX_BYTES", 200)
    package_logger = logging.getLogger("ytmusic_tui")
    monkeypatch.setattr(package_logger, "handlers", [])
    path = log_module.setup_logging()
    try:
        logger = logging.getLogger("ytmusic_tui.teste")
        # Duas linhas: o CPython 3.13 nunca rotaciona arquivo VAZIO (gh-116263).
        logger.info("linha de teste " + "x" * 400)
        logger.info("segunda linha " + "y" * 400)
        _flush(package_logger)

        rotated = path.with_name(path.name + ".1")
        assert rotated.exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(rotated.stat().st_mode) == 0o600
        for candidate in (path, rotated):
            records = _lines(candidate)
            assert records, f"{candidate.name} deveria ter registros JSON"
            assert {record["component"] for record in records} == {"teste"}
    finally:
        for handler in package_logger.handlers:
            handler.close()
