"""Configuração global dos testes: nenhum teste aponta para o banco real.

O ``DatabaseManager`` global (``db_manager``) é criado no import com
``settings.library_db_path`` — o banco de verdade do usuário. A fixture
abaixo o redireciona para um banco temporário em TODOS os testes: sem ela,
o ``on_mount`` da TUI chamaria ``db_manager.migrate()`` no banco real (e,
desde a T05, migraria/backupearia de verdade). Testes que constroem o
próprio ``DatabaseManager`` com um caminho temporário não são afetados.
"""

import pytest

from ytmusic_tui.api import ytmusic
from ytmusic_tui.config import settings
from ytmusic_tui.library.database import db_manager


@pytest.fixture(autouse=True)
def _ffmpeg_on_path(monkeypatch):
    """Aponta um ffmpeg fictício: a suíte não depende do host (§8.4/T06).

    O worker checa yt-dlp/ffmpeg antes de reservar; sem isso, máquinas sem
    ffmpeg instalado quebrariam dezenas de testes sem relação com o assunto.
    O caso "ffmpeg ausente" é testado explicitamente em ``tests/security``.
    """
    import ytmusic_tui.download as download_mod

    monkeypatch.setattr(download_mod, "_which_ffmpeg", lambda: "/usr/bin/ffmpeg")


@pytest.fixture(autouse=True)
def _isolated_library_db(tmp_path, monkeypatch):
    """Redireciona o banco global para ``tmp_path``, migrado, e zera o engine.

    Migrado (como em produção depois do ``on_mount``): caminhos que usam os
    serviços globais — ex.: o passo 7 do download chama
    ``library.ensure_track`` — encontram um banco válido em vez de um
    arquivo vazio (ou, pior, o banco real do usuário).
    """
    db_manager.close()
    monkeypatch.setattr(db_manager, "db_path", tmp_path / "global-library.db")
    db_manager.migrate()
    yield
    db_manager.close()


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    """Redireciona o cache da API para ``tmp_path`` (T10-R4).

    Sem isto, os testes que exercitam ``search_catalog``/``get_album`` de
    verdade (transportes falsos) gravariam no cache real do usuário — e um
    teste poderia "acertar" cache deixado por outro. O singleton é resetado
    para reconstruir o cache a partir do diretório isolado na 1ª leitura.
    """
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(ytmusic, "_cache", None)
