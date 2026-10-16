"""Permissões dos dados da aplicação (§8.3/§8.4 · T06).

Checklist coberta aqui:

- **criação estrita e umask-agnóstica**: diretórios internos 0700 e arquivos
  0600 MESMO com ``umask 0`` (o chmod pós-criação é que garante, não o modo
  do ``mkdir``);
- **existente só aperta**: pasta 0755 vira 0700 (com log no arquivo);
  modo já mais restrito (0500/0400) é respeitado — nunca adicionamos
  permissão a nada;
- **``download_dir`` é mídia do usuário**: o modo pré-existente nunca é
  alterado (nem para apertar) — só ``.tmp``/``.quarantine`` e os dados da
  aplicação recebem modo privado;
- banco da biblioteca, sidecars do WAL, backups, ``config.toml`` e o log
  rotacionado ficam 0600;
- falha de diretório vira ``ConfigError`` com contexto — e a entrada do app
  (`main`) imprime mensagem curta com exit 1, sem traceback;
- defaults do app nunca apontam para diretórios de sistema (nunca root).
"""

import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text

import ytmusic_tui.log as log_module
from ytmusic_tui.config import Settings
from ytmusic_tui.download import pipeline
from ytmusic_tui.errors import ConfigError
from ytmusic_tui.library import migrations, recovery
from ytmusic_tui.library.database import DatabaseManager
from ytmusic_tui.permissions import secure_directory, secure_file, tighten_mode

REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = REPO_ROOT / "src"


def _isolated_settings(toml_file: Path):
    """Settings com TOML isolado — nunca o config.toml real do usuário."""

    class IsolatedSettings(Settings):
        model_config = SettingsConfigDict(
            env_prefix="YTMUSIC_",
            case_sensitive=False,
            extra="ignore",
            toml_file=toml_file,
        )

    return IsolatedSettings


def _point_env(monkeypatch, tmp_path: Path, *, download_dir: Path | None = None) -> Path:
    """Aponta os diretórios do app para ``tmp_path`` (nada do usuário real)."""
    music = download_dir or (tmp_path / "music")
    monkeypatch.setenv("YTMUSIC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("YTMUSIC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("YTMUSIC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("YTMUSIC_DOWNLOAD_DIR", str(music))
    return music


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_umask_agnostic_creation_keeps_download_dir_untouched(tmp_path, monkeypatch):
    """0700 nos diretórios internos mesmo com ``umask 0``; download_dir não.

    O chmod pós-mkdir é o que garante o modo (não o umask do processo).
    ``download_dir`` é mídia do usuário: fica com o modo do ``mkdir`` — com
    umask 0 nasce 0777 e assim permanece (prova de que não o chmodamos).
    """
    music = _point_env(monkeypatch, tmp_path)

    old_umask = os.umask(0)
    try:
        settings = _isolated_settings(tmp_path / "ausente.toml")()
    finally:
        os.umask(old_umask)

    assert _mode(settings.config_dir) == 0o700
    assert _mode(settings.data_dir) == 0o700
    assert _mode(settings.cache_dir) == 0o700
    assert _mode(music) == 0o777


def test_existing_dirs_are_only_tightened_with_log(tmp_path, monkeypatch, caplog):
    """Pasta existente frouxa vira 0700 (com log); modo restrito é respeitado."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    os.chmod(cfg, 0o755)
    cache = tmp_path / "cache"
    cache.mkdir()
    os.chmod(cache, 0o500)
    _point_env(monkeypatch, tmp_path)

    with caplog.at_level(logging.INFO, logger="ytmusic_tui.permissions"):
        _isolated_settings(tmp_path / "ausente.toml")()

    assert _mode(cfg) == 0o700  # apertada
    assert _mode(cache) == 0o500  # nunca afrouxada (dono sem write continua)
    assert any(
        "Permissões apertadas" in record.getMessage() and str(cfg) in record.getMessage()
        for record in caplog.records
    )


def test_tmp_workdir_and_lock_are_private(tmp_path):
    """``.tmp`` nasce 0700 e o lock 0600 (mesmo com umask 0); mídia intocada."""
    download_dir = tmp_path / "library"
    download_dir.mkdir()
    os.chmod(download_dir, 0o755)
    final = download_dir / "Artista" / "Faixa - Artista.mp3"

    old_umask = os.umask(0)
    try:
        reservation = pipeline.reserve(final, download_dir)
    finally:
        os.umask(old_umask)

    try:
        assert _mode(download_dir / pipeline.TMP_DIR_NAME) == 0o700
        assert _mode(reservation.lock_path) == 0o600
        assert _mode(download_dir) == 0o755  # mídia do usuário: intocada
    finally:
        pipeline.release(reservation)


def test_quarantine_directory_is_private(tmp_path):
    """``.quarantine`` nasce 0700 (mesmo com umask 0)."""
    download_dir = tmp_path / "library"
    download_dir.mkdir()
    broken = download_dir / "quebrada.mp3"
    broken.write_bytes(b"nao e audio")

    old_umask = os.umask(0)
    try:
        moved = recovery._quarantine(download_dir, broken)
    finally:
        os.umask(old_umask)

    assert moved.parent == download_dir / pipeline.QUARANTINE_DIR_NAME
    assert _mode(moved.parent) == 0o700
    assert not broken.exists()


def test_library_db_and_sidecars_are_private(tmp_path):
    """Banco e sidecars do WAL ficam 0600 mesmo criados com umask 0."""
    db = tmp_path / "library.db"

    old_umask = os.umask(0)
    try:
        manager = DatabaseManager(db)
        try:
            manager.migrate()
            with manager.session() as session:
                session.execute(text("CREATE TABLE IF NOT EXISTS _perm_probe (x INTEGER)"))

            # Ainda aberto: o WAL está vivo (o close limpo o remove).
            wal = Path(f"{db}-wal")
            assert wal.exists()
            assert _mode(wal) == 0o600
        finally:
            manager.close()
    finally:
        os.umask(old_umask)

    assert _mode(db) == 0o600


def _make_legacy_db(path: Path) -> None:
    """Banco no esquema T01–T04 (mesmo formato dos testes de migração)."""
    manager = DatabaseManager(path)
    manager.create_all()
    with manager.engine.begin() as connection:
        connection.execute(text("ALTER TABLE tracks DROP COLUMN is_missing"))
        connection.execute(text("DROP TABLE download_tasks"))
        connection.execute(
            text(
                "INSERT INTO artists (source_id, name, source) "
                "VALUES ('art1', 'Artista', 'youtube_music')"
            )
        )
    manager.close()


def test_backup_artifacts_are_private(tmp_path):
    """Backup pré-migração: arquivo 0600 e pasta 0700 (mesmo com umask 0)."""
    db = tmp_path / "library.db"
    _make_legacy_db(db)

    old_umask = os.umask(0)
    try:
        manager = DatabaseManager(db)
        try:
            outcome = manager.migrate()
        finally:
            manager.close()
    finally:
        os.umask(old_umask)

    assert outcome.backup_path is not None
    assert _mode(tmp_path / migrations.BACKUP_DIR_NAME) == 0o700
    assert _mode(outcome.backup_path) == 0o600


def test_config_toml_is_private(tmp_path, monkeypatch):
    """O config.toml persistido é 0600 (mesmo com umask 0)."""
    toml = tmp_path / "cfg" / "config.toml"
    _point_env(monkeypatch, tmp_path)
    instance = _isolated_settings(toml)()

    old_umask = os.umask(0)
    try:
        instance.update_and_save(mpv_volume=33)
    finally:
        os.umask(old_umask)

    assert _mode(toml) == 0o600


def test_log_file_and_rotations_are_private(tmp_path, monkeypatch):
    """Log, rotações e diretório de log ficam 0700/0600 (mesmo com umask 0)."""
    log_root = tmp_path / "logs"
    monkeypatch.setattr(log_module, "user_log_dir", lambda appname: str(log_root))
    monkeypatch.setattr(log_module, "_MAX_BYTES", 200)
    package_logger = logging.getLogger("ytmusic_tui")
    monkeypatch.setattr(package_logger, "handlers", [])

    old_umask = os.umask(0)
    try:
        path = log_module.setup_logging()
        # Duas linhas: o CPython 3.13 nunca rotaciona arquivo VAZIO
        # (gh-116263) — a segunda escrita é a que estoura o limite.
        logging.getLogger("ytmusic_tui.teste").info("linha de teste " + "x" * 400)
        logging.getLogger("ytmusic_tui.teste").info("segunda linha " + "y" * 400)
        for handler in package_logger.handlers:
            handler.flush()
    finally:
        os.umask(old_umask)

    try:
        assert _mode(log_root) == 0o700
        rotated = path.with_name(path.name + ".1")
        assert rotated.exists()  # a rotação aconteceu de fato
        assert _mode(path) == 0o600
        assert _mode(rotated) == 0o600
    finally:
        for handler in package_logger.handlers:
            handler.close()


def test_secure_file_only_tightens(tmp_path):
    """0600 em arquivo frouxo; modo mais restrito é respeitado; ausente é no-op."""
    loose = tmp_path / "frouxo"
    loose.write_bytes(b"x")
    os.chmod(loose, 0o644)
    strict = tmp_path / "restrito"
    strict.write_bytes(b"x")
    os.chmod(strict, 0o400)

    secure_file(loose, label="teste")
    secure_file(strict, label="teste")
    secure_file(tmp_path / "ausente", label="teste")

    assert _mode(loose) == 0o600
    assert _mode(strict) == 0o400
    assert tighten_mode(0o644) == 0o600


def test_directory_failures_are_config_errors_not_tracebacks(tmp_path):
    """Falha de diretório vira ``ConfigError`` com contexto (§8.3)."""
    if os.geteuid() == 0:
        pytest.skip("root ignora permissões de escrita")

    blocked = tmp_path / "bloqueado"
    blocked.mkdir()
    os.chmod(blocked, 0o500)
    try:
        with pytest.raises(ConfigError, match="não foi possível criar"):
            secure_directory(blocked / "sub", label="diretório de teste")
    finally:
        os.chmod(blocked, 0o700)

    file_path = tmp_path / "nao_e_diretorio"
    file_path.write_text("sou um arquivo", encoding="utf-8")
    with pytest.raises(ConfigError, match="não é um diretório"):
        secure_directory(file_path, label="diretório de teste")


def test_main_reports_config_errors_without_traceback(tmp_path):
    """A entrada do app traduz ConfigError em mensagem + exit 1 (sem traceback)."""
    if os.geteuid() == 0:
        pytest.skip("root ignora permissões de escrita")

    blocked = tmp_path / "bloqueado"
    blocked.mkdir()
    os.chmod(blocked, 0o500)

    env = {
        **os.environ,
        "PYTHONPATH": str(_SRC_DIR)
        + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
        "YTMUSIC_CONFIG_DIR": str(tmp_path / "cfg"),
        "YTMUSIC_CACHE_DIR": str(tmp_path / "cache"),
        "YTMUSIC_DOWNLOAD_DIR": str(tmp_path / "music"),
        "YTMUSIC_DATA_DIR": str(blocked / "data"),  # falha aqui
    }
    try:
        process = subprocess.run(
            [sys.executable, "-c", "from ytmusic_tui.main import main; main()"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd=REPO_ROOT,
        )
    finally:
        os.chmod(blocked, 0o700)

    assert process.returncode == 1
    assert "não conseguiu preparar os diretórios" in process.stderr
    assert "Traceback" not in process.stderr


def test_default_directories_are_never_system_locations():
    """§8.3: defaults do app vivem em diretórios de USUÁRIO; nunca de sistema."""
    forbidden = ("/etc", "/usr", "/bin", "/sbin", "/boot", "/dev", "/proc", "/sys")
    for field_name in ("config_dir", "data_dir", "cache_dir", "download_dir"):
        field = Settings.model_fields[field_name]
        factory = field.default_factory
        assert factory is not None
        candidate = Path(factory())
        for root in forbidden:
            assert not candidate.is_relative_to(root), f"{field_name} em {root}: {candidate}"
