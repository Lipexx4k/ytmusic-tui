"""Configuração global dos testes: nenhum teste aponta para o banco real.

O ``DatabaseManager`` global (``db_manager``) é criado no import com
``settings.library_db_path`` — o banco de verdade do usuário. A fixture
abaixo o redireciona para um banco temporário em TODOS os testes: sem ela,
o ``on_mount`` da TUI chamaria ``db_manager.migrate()`` no banco real (e,
desde a T05, migraria/backupearia de verdade). Testes que constroem o
próprio ``DatabaseManager`` com um caminho temporário não são afetados.
"""

import pytest

from ytmusic_tui.library.database import db_manager


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
