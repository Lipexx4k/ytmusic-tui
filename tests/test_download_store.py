"""Testes do espelho persistido das tarefas de download (T04-R1).

A tabela ``download_tasks`` é uma **pista de recuperação**, não a verdade da
biblioteca. Os testes cobrem o ciclo de vida (save/update/find/delete), a
conversão da inicialização (``mark_active_as_interrupted``) e o contrato do
§5.3/T04: ``awaiting_decision_files`` devolve ``(chave, temp_dir, final_path)``
de tudo que "aguarda decisão" — incluindo ``INTERRUPTED``, que é terminal
para a máquina (§4.2) mas nunca para a persistência.
"""

import tempfile
from pathlib import Path

import pytest

from ytmusic_tui.download.pipeline import TMP_DIR_NAME, reservation_key
from ytmusic_tui.download.store import (
    AWAITING_DECISION_STATUSES,
    DownloadTaskStore,
    hydrate_interrupted,
)
from ytmusic_tui.download.task import DownloadStatus, DownloadTask
from ytmusic_tui.library.database import DatabaseManager
from ytmusic_tui.library.models import DownloadTaskRecord


@pytest.fixture
def temp_db():
    """Banco temporário — os testes nunca tocam o banco real do usuário."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = Path(handle.name)

    db_manager = DatabaseManager(db_path)
    db_manager.create_all()

    yield db_manager

    db_manager.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def store(temp_db) -> DownloadTaskStore:
    return DownloadTaskStore(db=temp_db)


def _task(**overrides) -> DownloadTask:
    fields: dict = {
        "video_id": "vid1",
        "title": "Faixa",
        "artist": "Artista",
        "album": "Álbum",
        "thumbnail_url": "http://example.com/x.jpg",
        "track_id": 42,
        "id": "task-aaa111",
    }
    fields.update(overrides)
    return DownloadTask(**fields)


def _final(tmp_path: Path, name: str = "Faixa - Artista.mp3") -> Path:
    return tmp_path / "Artista" / "Álbum" / name


def _walk(task: DownloadTask, target: DownloadStatus) -> DownloadTask:
    """Leva a tarefa ao estado pedido só por transições válidas da máquina."""
    steps = {
        DownloadStatus.PENDING: [],
        DownloadStatus.RUNNING: [DownloadStatus.RUNNING],
        DownloadStatus.VALIDATING: [DownloadStatus.RUNNING, DownloadStatus.VALIDATING],
        DownloadStatus.INTERRUPTED: [DownloadStatus.RUNNING, DownloadStatus.INTERRUPTED],
        DownloadStatus.COMPLETED: [
            DownloadStatus.RUNNING,
            DownloadStatus.VALIDATING,
            DownloadStatus.COMPLETED,
        ],
        DownloadStatus.FAILED: [DownloadStatus.RUNNING, DownloadStatus.FAILED],
    }[target]
    for step in steps:
        task.transition_to(step)
    return task


def test_save_creates_row_with_all_fields(store, tmp_path):
    """A linha guarda tudo que a recuperação precisa, inclusive os caminhos."""
    task = _task()
    final = _final(tmp_path)

    store.save(task, download_dir=tmp_path, final_path=final)

    row = store.find("task-aaa111")
    assert row is not None
    assert row.video_id == "vid1"
    assert row.title == "Faixa"
    assert row.artist == "Artista"
    assert row.album == "Álbum"
    assert row.thumbnail_url == "http://example.com/x.jpg"
    assert row.track_id == 42
    assert row.final_path == str(final)
    assert row.download_dir == str(tmp_path)
    assert row.status == DownloadStatus.PENDING.value
    assert row.retry_of == ""
    assert row.created_at is not None and row.updated_at is not None


def test_save_upserts_by_task_id(store, tmp_path):
    """Salvar duas vezes a mesma tarefa atualiza a linha — nunca duplica."""
    task = _task()
    store.save(task, download_dir=tmp_path, final_path=_final(tmp_path))

    task.transition_to(DownloadStatus.RUNNING)
    task.progress = 50.0
    store.save(task, download_dir=tmp_path, final_path=_final(tmp_path))

    with store.db.session() as session:
        rows = session.query(DownloadTaskRecord).all()
    assert len(rows) == 1
    assert rows[0].status == DownloadStatus.RUNNING.value


def test_update_status_changes_only_status(store, tmp_path):
    """update_status altera o status e preserva o resto da linha."""
    task = _task()
    store.save(task, download_dir=tmp_path, final_path=_final(tmp_path))

    store.update_status(task.id, DownloadStatus.INTERRUPTED)

    row = store.find(task.id)
    assert row is not None
    assert row.status == DownloadStatus.INTERRUPTED.value
    assert row.video_id == "vid1"
    assert row.final_path == str(_final(tmp_path))


def test_update_status_of_missing_row_is_noop(store):
    """Atualizar linha inexistente não cria nada nem explode."""
    store.update_status("task-fantasma", DownloadStatus.RUNNING)
    assert store.find("task-fantasma") is None


def test_delete_is_idempotent(store, tmp_path):
    """Apagar remove a linha; apagar de novo (ou linha ausente) não é erro."""
    task = _task()
    store.save(task, download_dir=tmp_path, final_path=_final(tmp_path))

    store.delete(task.id)
    store.delete(task.id)

    assert store.find(task.id) is None


def test_find_returns_none_when_missing(store):
    assert store.find("task-inexistente") is None


def test_mark_active_as_interrupted_only_converts_inflight(store, tmp_path):
    """PENDING/RUNNING/VALIDATING → INTERRUPTED; já-interrompidas e terminais não.

    É a conversão da inicialização: a próxima execução encontra a pista do
    trabalho que ficou pela metade. Idempotente (segunda chamada converte 0).
    """
    pending = _task(id="task-p")
    running = _walk(_task(id="task-r"), DownloadStatus.RUNNING)
    validating = _walk(_task(id="task-v"), DownloadStatus.VALIDATING)
    interrupted = _walk(_task(id="task-i"), DownloadStatus.INTERRUPTED)
    completed = _walk(_task(id="task-c"), DownloadStatus.COMPLETED)
    for task in (pending, running, validating, interrupted, completed):
        store.save(task, download_dir=tmp_path, final_path=_final(tmp_path))

    assert store.mark_active_as_interrupted() == 3

    expected = {
        "task-p": DownloadStatus.INTERRUPTED.value,
        "task-r": DownloadStatus.INTERRUPTED.value,
        "task-v": DownloadStatus.INTERRUPTED.value,
        "task-i": DownloadStatus.INTERRUPTED.value,
        "task-c": DownloadStatus.COMPLETED.value,
    }
    for task_id, status in expected.items():
        row = store.find(task_id)
        assert row is not None and row.status == status

    assert store.mark_active_as_interrupted() == 0  # idempotente


def test_load_interrupted_returns_only_interrupted(store, tmp_path):
    """A inicialização lista só as linhas INTERRUPTED, em ordem estável."""
    for task_id in ("task-i1", "task-i2"):
        task = _task(id=task_id)
        task.transition_to(DownloadStatus.RUNNING)
        task.transition_to(DownloadStatus.INTERRUPTED)
        store.save(task, download_dir=tmp_path, final_path=_final(tmp_path))
    store.save(_task(id="task-p"), download_dir=tmp_path, final_path=_final(tmp_path))

    rows = store.load_interrupted()

    assert [row.task_id for row in rows] == ["task-i1", "task-i2"]


def test_awaiting_decision_files_covers_all_four_states(store, tmp_path):
    """O contrato do §5.3: ``(chave, temp_dir, final_path)`` de quem aguarda decisão.

    INTERRUPTED conta (terminal para a máquina, decisão pendente para a
    persistência) e os estados em voo contam — seus temporários não podem
    ser recolhidos pela limpeza de idade antes da conversão na inicialização.
    """
    states = {
        "task-p": DownloadStatus.PENDING,
        "task-r": DownloadStatus.RUNNING,
        "task-v": DownloadStatus.VALIDATING,
        "task-i": DownloadStatus.INTERRUPTED,
    }
    finals = {}
    for task_id, status in states.items():
        task = _walk(_task(id=task_id), status)
        final = _final(tmp_path, f"{task_id}.mp3")
        finals[task_id] = final
        store.save(task, download_dir=tmp_path, final_path=final)

    items = {item.task_id: item for item in store.awaiting_decision_files()}

    assert set(items) == set(states)
    assert {status.value for status in AWAITING_DECISION_STATUSES} == {
        "pending",
        "running",
        "validating",
        "interrupted",
    }
    for task_id, final in finals.items():
        item = items[task_id]
        assert item.key == reservation_key(final)
        assert item.temp_dir == tmp_path / TMP_DIR_NAME
        assert item.final_path == final
        assert item.legacy_parts == (Path(f"{final}.part"), Path(f"{final}.ytdl"))


def test_awaiting_decision_files_excludes_terminals(store, tmp_path):
    """Terminais (completas/descartadas) não retêm temporário nenhum."""
    completed = _walk(_task(id="task-c"), DownloadStatus.COMPLETED)
    store.save(completed, download_dir=tmp_path, final_path=_final(tmp_path))
    failed = _walk(_task(id="task-f"), DownloadStatus.FAILED)
    store.save(failed, download_dir=tmp_path, final_path=_final(tmp_path, "x.mp3"))

    assert store.awaiting_decision_files() == []


def test_hydrate_interrupted_rebuilds_task_without_transition(store, tmp_path):
    """Hidratação: linha vira tarefa já em INTERRUPTED (construtor, não máquina).

    PENDING→INTERRUPTED não existe na §4.2; reconstruir o passado não é uma
    transição — todos os campos voltam, com erro explicativo e ``retry_of``.
    """
    task = _task(retry_of="task-original")
    store.save(task, download_dir=tmp_path, final_path=_final(tmp_path))
    store.mark_active_as_interrupted()
    row = store.find(task.id)
    assert row is not None

    hydrated = hydrate_interrupted(row)

    assert hydrated.status is DownloadStatus.INTERRUPTED
    assert hydrated.id == "task-aaa111"
    assert hydrated.video_id == "vid1"
    assert hydrated.title == "Faixa"
    assert hydrated.artist == "Artista"
    assert hydrated.album == "Álbum"
    assert hydrated.thumbnail_url == "http://example.com/x.jpg"
    assert hydrated.track_id == 42
    assert hydrated.retry_of == "task-original"
    assert "Interrompido" in hydrated.error


def test_awaiting_decision_files_skips_rows_without_paths(store, tmp_path):
    """Linha sem caminhos persistidos não contribui com um par falso."""
    with store.db.session() as session:
        session.add(
            DownloadTaskRecord(
                task_id="task-x",
                status=DownloadStatus.INTERRUPTED.value,
                final_path="",
                download_dir="",
            )
        )

    assert store.awaiting_decision_files() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
