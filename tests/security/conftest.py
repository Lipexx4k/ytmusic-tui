"""Fixtures da suíte de segurança (§8.4/T06) — nenhum dado real é tocado.

Todo download vai para ``tmp_path/root/library``; o espelho de tarefas fica
em ``tmp_path/db``. Qualquer arquivo criado FORA de ``download_dir`` é
detectável por varredura — é exatamente o que os testes afirmam.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import ytmusic_tui.download as download_mod
from tests.security._fakes import FakeYoutubeDL, fake_yt_dlp, install_settings
from ytmusic_tui.download.store import DownloadTaskStore
from ytmusic_tui.library.database import DatabaseManager


@pytest.fixture
def make_store(tmp_path):
    """Fábrica de espelhos de tarefas isolados (um banco por chamada)."""
    managers: list[DatabaseManager] = []

    def _make() -> DownloadTaskStore:
        db_dir = tmp_path / "db"
        db_dir.mkdir(exist_ok=True)
        db = DatabaseManager(db_dir / "tasks.db")
        db.migrate()
        managers.append(db)
        return DownloadTaskStore(db=db)

    yield _make
    for db in managers:
        db.close()


@pytest.fixture
def make_security_env(monkeypatch, make_store):
    """Fábrica de ambientes isolados (settings falsos + yt-dlp falso + store)."""

    def _make(download_dir: Path, *, ydl_cls: type = FakeYoutubeDL) -> SimpleNamespace:
        download_dir.mkdir(parents=True, exist_ok=True)
        install_settings(monkeypatch, download_dir)
        monkeypatch.setattr(download_mod, "_load_yt_dlp", lambda: fake_yt_dlp(ydl_cls))
        store = make_store()
        manager = download_mod.DownloadManager(store=store)
        managers.append(manager)
        return SimpleNamespace(manager=manager, store=store, download_dir=download_dir)

    managers: list[download_mod.DownloadManager] = []
    yield _make
    for manager in managers:
        manager.shutdown()


@pytest.fixture
def security_env(make_security_env, tmp_path) -> SimpleNamespace:
    """Ambiente padrão: ``tmp_path/root/library`` + ``root`` para varredura."""
    root = tmp_path / "root"
    root.mkdir()
    env = make_security_env(root / "library")
    env.root = root
    return env
