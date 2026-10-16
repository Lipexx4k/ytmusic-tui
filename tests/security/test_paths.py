"""Segurança de caminhos (§8.1/§8.4): entrada externa não redireciona gravação.

Checklist do §8.4 coberta aqui (ponta a ponta, com arquivo de verdade):

- título com ``/``, ``\\``, ``..``, NUL/caracteres de controle, emoji, CJK e
  300 bytes → nada é criado fora de ``download_dir``;
- nome que gera colisão com arquivo existente → nunca sobrescreve (INV-3);
- symlink apontando para fora → recusado na validação E na revalidação
  imediatamente antes de publicar (diretório trocado durante a operação);
- linha persistida adulterada → log + fallback, nunca opera fora.

A normalização em si (corpus congelado de nomes) vive em
``tests/test_pipeline.py``; aqui o critério é o efeito no disco.
"""

import logging
from pathlib import Path

import pytest

from tests.security._fakes import FakeYoutubeDL
from ytmusic_tui.download import DownloadStatus, DownloadTask
from ytmusic_tui.download.pipeline import reservation_key


def _assert_nothing_outside(root: Path, download_dir: Path) -> None:
    """Toda entrada criada sob ``root`` precisa estar (lexicalmente) no download_dir.

    Comparação lexical de propósito: um symlink DENTRO de download_dir
    apontando para fora é o ataque testado (a prova física é o diretório de
    fora continuar vazio, verificada em cada teste). ``rglob`` não segue
    symlinks de diretório, então nenhuma varredura escapa da árvore.
    """
    for path in root.rglob("*"):
        assert path.is_relative_to(download_dir), f"escapou: {path}"


HOSTILE_TITLES = [
    "a/b",
    "a\\b",
    "..",
    "../evil",
    "a\x00b",
    "a\x1fb",
    "emoji 🎵🎶",
    "音" * 150,  # 450 bytes — acima do limite de 255 por componente
    "x" * 300,
]


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_hostile_title_never_writes_outside_download_dir(security_env, title):
    env = security_env
    task = env.manager.queue_download(
        video_id="v-hostil", title=title, artist="Art/ist", album="Alb\\um"
    )

    result = env.manager._download_task(task)

    assert result.status is DownloadStatus.COMPLETED
    assert result.file_path is not None
    assert result.file_path.is_relative_to(env.download_dir)
    resolved = result.file_path.resolve()
    assert resolved.is_relative_to(env.download_dir.resolve())
    assert resolved.is_file()
    _assert_nothing_outside(env.root, env.download_dir)


def test_colliding_names_are_deterministic_and_never_overwrite(security_env):
    """Três títulos distintos com o MESMO nome sanitizado → um arquivo só.

    A colisão é determinística (mesmo caminho final, mesma reserva); o
    segundo download adota o existente (Q2(a)) sem sobrescrever nada
    (INV-3) — o conteúdo original permanece byte a byte.
    """
    env = security_env
    titles = ["a/b", "a_b", "a?b"]

    paths = set()
    for title in titles:
        task = DownloadTask(video_id="v", title=title, artist="Art", album="")
        paths.add(env.manager._final_path_for(task))
    assert len(paths) == 1

    first = env.manager.queue_download(video_id="v1", title=titles[0], artist="Art", album="")
    assert env.manager._download_task(first).status is DownloadStatus.COMPLETED
    assert first.file_path is not None
    original = first.file_path.read_bytes()

    second = env.manager.queue_download(video_id="v2", title=titles[1], artist="Art", album="")
    result = env.manager._download_task(second)

    assert result.status is DownloadStatus.COMPLETED  # adota o existente
    assert result.file_path == first.file_path
    assert first.file_path.read_bytes() == original  # nunca sobrescreveu
    assert len(list(env.download_dir.rglob("*.mp3"))) == 1


@pytest.mark.parametrize("level", ["artist", "album"])
def test_symlinked_destination_directory_is_refused(security_env, tmp_path, level):
    """``Artista`` (ou ``Artista/Álbum``) como symlink para fora: recusa."""
    env = security_env
    outside = tmp_path / "outside"
    outside.mkdir()
    if level == "artist":
        (env.download_dir / "Artista").symlink_to(outside)
    else:
        (env.download_dir / "Artista").mkdir()
        (env.download_dir / "Artista" / "Álbum").symlink_to(outside)

    task = env.manager.queue_download(video_id="v", title="T", artist="Artista", album="Álbum")
    result = env.manager._download_task(task)

    assert result.status is DownloadStatus.FAILED
    assert "fora de download_dir" in result.error
    assert list(outside.iterdir()) == []  # nada foi escrito fora
    _assert_nothing_outside(env.root, env.download_dir)


def test_directory_swapped_during_download_is_not_published(make_security_env, tmp_path):
    """Symlink criado DURANTE a operação: a revalidação pré-publish recusa.

    A validação de entrada passou (o diretório ainda não existia); o ataque
    troca ``Artista`` por um symlink enquanto o yt-dlp "baixa". O temporário
    é gravado no ``.tmp`` (dentro de download_dir, seguro), mas a publicação
    é recusada — nada aparece do lado de fora e o temporário é limpo.
    """
    root = tmp_path / "root"
    root.mkdir()
    download_dir = root / "library"
    outside = tmp_path / "outside"
    outside.mkdir()

    class _SwapDuringDownload(FakeYoutubeDL):
        def download(self, urls: list[str]) -> None:
            (download_dir / "Artista").symlink_to(outside)
            super().download(urls)

    env = make_security_env(download_dir, ydl_cls=_SwapDuringDownload)
    task = env.manager.queue_download(video_id="v", title="T", artist="Artista", album="Álbum")

    result = env.manager._download_task(task)

    assert result.status is DownloadStatus.FAILED
    assert "Falha na publicação" in result.error
    assert "fora de download_dir" in result.error
    assert (download_dir / "Artista").is_symlink()  # a troca aconteceu de fato
    assert list(outside.iterdir()) == []
    temp_dir = download_dir / ".tmp"
    assert not temp_dir.exists() or list(temp_dir.iterdir()) == []  # liberado
    _assert_nothing_outside(root, download_dir)


def test_tampered_persisted_row_never_operates_outside(security_env, tmp_path, caplog):
    """Linha adulterada (r/d): log + fallback — nada fora de download_dir.

    Um espelho comprometido aponta para um arquivo do usuário fora da árvore
    de downloads; a chave da reserva é derivada desse caminho — se o
    gerenciador confiasse na linha, o descarte removeria ``<alvo>.part`` e o
    lock ``.tmp/<chave>.*`` de terceiros. A contenção pós-resolve corta
    isso: aviso no log e operação cai para o template atual.
    """
    env = security_env
    outside = tmp_path / "outside"
    outside.mkdir()

    vital = outside / "importante.mp3"
    vital.write_bytes(b"dados-do-usuario")
    part = Path(f"{vital}.part")
    part.write_bytes(b"parcial")
    key = reservation_key(vital)
    outside_tmp = outside / ".tmp"
    outside_tmp.mkdir()
    lock_decoy = outside_tmp / f"{key}.reserva"
    lock_decoy.write_bytes(b"")

    task = DownloadTask(video_id="v", title="T", artist="Art", id="task-adulterada")
    task.status = DownloadStatus.INTERRUPTED  # hidratação simulada (sem transição)
    env.manager._queue.append(task)
    env.store.save(task, download_dir=outside, final_path=vital)

    with caplog.at_level(logging.WARNING, logger="ytmusic_tui.download"):
        new_task = env.manager.retry_interrupted("task-adulterada")

    assert new_task is not None
    assert vital.exists() and part.exists() and lock_decoy.exists()
    assert any("fora de download_dir" in record.getMessage() for record in caplog.records)
    # O caminho novo é o do TEMPLATE (contido), não o da linha adulterada.
    row = env.store.find(new_task.id)
    assert row is not None
    assert row.final_path == str(env.manager._final_path_for(new_task))

    # E o fallback funciona de ponta a ponta: a retomada completa no contido.
    assert env.manager._download_task(new_task).status is DownloadStatus.COMPLETED

    # Descarte de outra linha adulterada: devolve vazio e não toca em nada.
    task2 = DownloadTask(video_id="v2", title="T2", artist="Art", id="task-adulterada-2")
    task2.status = DownloadStatus.INTERRUPTED
    env.manager._queue.append(task2)
    env.store.save(task2, download_dir=outside, final_path=vital)

    removed = env.manager.discard_interrupted("task-adulterada-2")

    assert removed == []
    assert vital.exists() and part.exists() and lock_decoy.exists()


def test_symlinked_download_dir_is_not_a_containment_violation(make_security_env, tmp_path):
    """Música em outro disco via symlink: a contenção resolve os DOIS lados.

    Um usuário aponta ``download_dir`` para um atalho (ex.: disco externo);
    a contenção compara caminhos resolvidos — o atalho não vira falso
    positivo e o arquivo sai no alvo físico, não em um caminho paralelo.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "minha-musica"
    link.symlink_to(real)

    env = make_security_env(link)
    task = env.manager.queue_download(video_id="v", title="T", artist="A", album="Alb")

    result = env.manager._download_task(task)

    assert result.status is DownloadStatus.COMPLETED
    assert result.file_path is not None
    resolved = result.file_path.resolve()
    assert resolved.is_relative_to(real.resolve())  # físico
    assert resolved.is_relative_to(link.resolve())  # lógico (mesma árvore)
    assert resolved.is_file()
