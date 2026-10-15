"""Testes do pipeline de publicação (T03, §5.1–§5.2 do plano).

Cobrem os passos de disco fora do fluxo com yt-dlp: validação de entrada,
reserva exclusiva (O_CREAT|O_EXCL) contra a corrida exists()×replace(),
validação do arquivo final, publicação com fsync e anti-sobrescrita.
"""

import os
from pathlib import Path

import pytest

import ytmusic_tui.download.pipeline as pipeline_mod
from ytmusic_tui.download.pipeline import (
    DestinationBusy,
    InvalidInputError,
    MediaValidationError,
    OverwriteRefusedError,
    publish_file,
    release,
    reservation_key,
    reserve,
    validate_input,
    validate_media_file,
)


@pytest.fixture
def download_dir(tmp_path: Path) -> Path:
    target = tmp_path / "musicas"
    target.mkdir()
    return target


# ===== Passo 1: validação de entrada =====


def test_validate_input_accepts_valid_destination(download_dir):
    validate_input(
        video_id="abc123",
        audio_format="mp3",
        final_path=download_dir / "Artista" / "Álbum" / "Faixa - Artista.mp3",
        download_dir=download_dir,
    )


@pytest.mark.parametrize(
    ("video_id", "audio_format"),
    [
        ("", "mp3"),
        ("   ", "mp3"),
        ("abc", "wav"),  # formato não suportado
        ("abc", ""),
    ],
)
def test_validate_input_rejects_bad_entry(download_dir, video_id, audio_format):
    with pytest.raises(InvalidInputError):
        validate_input(
            video_id=video_id,
            audio_format=audio_format,
            final_path=download_dir / "Faixa.mp3",
            download_dir=download_dir,
        )


def test_validate_input_rejects_destination_outside_download_dir(download_dir, tmp_path):
    """Um destino fora de download_dir não pode ser publicado."""
    with pytest.raises(InvalidInputError):
        validate_input(
            video_id="abc",
            audio_format="mp3",
            final_path=tmp_path / "fora.mp3",
            download_dir=download_dir,
        )


@pytest.mark.parametrize("special", [".tmp", ".quarantine"])
def test_validate_input_rejects_special_directories(download_dir, special):
    with pytest.raises(InvalidInputError):
        validate_input(
            video_id="abc",
            audio_format="mp3",
            final_path=download_dir / special / "Faixa.mp3",
            download_dir=download_dir,
        )


# ===== Passo 2: reserva exclusiva =====


def test_reservation_key_is_deterministic_and_short(download_dir):
    final = download_dir / "Faixa.mp3"
    key = reservation_key(final)

    assert key == reservation_key(final)  # determinística
    assert len(key) == 16 and all(c in "0123456789abcdef" for c in key)
    assert key != reservation_key(download_dir / "Outra.mp3")


def test_reserve_creates_lock_and_exclusive_second_attempt(download_dir):
    """A reserva é exclusiva de verdade: O_CREAT|O_EXCL, não check-then-create."""
    final = download_dir / "A" / "Faixa.mp3"
    reservation = reserve(final, download_dir)

    assert reservation.lock_path.exists()
    assert reservation.temp_dir == download_dir / ".tmp"
    assert reservation.temp_template.startswith(str(download_dir / ".tmp"))
    assert "%(ext)s" in reservation.temp_template

    # Segunda tentativa no mesmo destino: recusada, sem tocar no lock alheio
    with pytest.raises(DestinationBusy):
        reserve(final, download_dir)

    release(reservation)
    assert not reservation.lock_path.exists()

    # Depois do release, o nome está livre de novo
    again = reserve(final, download_dir)
    release(again)


def test_release_removes_lock_and_leftovers_and_is_idempotent(download_dir):
    reservation = reserve(download_dir / "Faixa.mp3", download_dir)
    leftovers = [
        reservation.temp_dir / f"{reservation.key}.webm.part",
        reservation.temp_dir / f"{reservation.key}.webp",
    ]
    for leftover in leftovers:
        leftover.write_bytes(b"resto")

    release(reservation)

    assert not reservation.lock_path.exists()
    assert all(not leftover.exists() for leftover in leftovers)
    release(reservation)  # idempotente: segunda chamada não explode


def test_release_preserves_other_reservations(download_dir):
    """O release só toca o prefixo da própria reserva."""
    mine = reserve(download_dir / "Minha.mp3", download_dir)
    other = reserve(download_dir / "Outra.mp3", download_dir)
    stranger = other.temp_dir / f"{other.key}.mp3"
    stranger.write_bytes(b"em andamento")

    release(mine)

    assert not mine.lock_path.exists()
    assert other.lock_path.exists()
    assert stranger.exists()
    release(other)


# ===== Passo 5: validação do arquivo final =====


def test_validate_media_file_accepts_valid_file(download_dir):
    media = download_dir / "Faixa.mp3"
    media.write_bytes(b"audio")

    assert validate_media_file(media, "mp3") == media


def test_validate_media_file_rejects_none(download_dir):
    with pytest.raises(MediaValidationError, match="ausente"):
        validate_media_file(None, "mp3")


def test_validate_media_file_rejects_missing(download_dir):
    with pytest.raises(MediaValidationError, match="ausente"):
        validate_media_file(download_dir / "nada.mp3", "mp3")


def test_validate_media_file_rejects_empty(download_dir):
    empty = download_dir / "vazia.mp3"
    empty.write_bytes(b"")

    with pytest.raises(MediaValidationError, match="vazio"):
        validate_media_file(empty, "mp3")


def test_validate_media_file_rejects_wrong_extension(download_dir):
    media = download_dir / "Faixa.webm"
    media.write_bytes(b"audio")

    with pytest.raises(MediaValidationError, match="extensão"):
        validate_media_file(media, "mp3")


def test_validate_media_file_rejects_directory(download_dir):
    directory = download_dir / "pasta.mp3"
    directory.mkdir()

    with pytest.raises(MediaValidationError, match="ausente"):
        validate_media_file(directory, "mp3")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permissões de leitura")
def test_validate_media_file_rejects_unreadable(download_dir):
    media = download_dir / "sem-leitura.mp3"
    media.write_bytes(b"audio")
    media.chmod(0o000)
    try:
        with pytest.raises(MediaValidationError, match="ilegível"):
            validate_media_file(media, "mp3")
    finally:
        media.chmod(0o600)


# ===== Passo 6: publicação =====


def test_publish_file_moves_and_fsyncs(download_dir, monkeypatch):
    """Publicar = rename atômico com fsync do arquivo e do diretório."""
    temp = download_dir / ".tmp" / "abc123.mp3"
    temp.parent.mkdir(parents=True)
    temp.write_bytes(b"audio-publicado")
    final = download_dir / "Artista" / "Faixa.mp3"

    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def _record_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", _record_fsync)

    published = publish_file(temp, final)

    assert published == final
    assert final.read_bytes() == b"audio-publicado"
    assert not temp.exists()
    assert len(fsync_calls) == 2  # arquivo antes do replace + diretório depois


def test_publish_file_refuses_missing_temp(download_dir):
    with pytest.raises(FileNotFoundError, match="temporário ausente"):
        publish_file(download_dir / ".tmp" / "nada.mp3", download_dir / "Faixa.mp3")


def test_publish_file_refuses_empty_temp(download_dir):
    temp = download_dir / ".tmp" / "vazio.mp3"
    temp.parent.mkdir(parents=True)
    temp.write_bytes(b"")

    with pytest.raises(MediaValidationError, match="vazio"):
        publish_file(temp, download_dir / "Faixa.mp3")


def test_publish_file_refuses_existing_destination(download_dir):
    """Destino surgido após a reserva: recusa explícita, sem sobrescrita."""
    final = download_dir / "Faixa.mp3"
    final.write_bytes(b"arquivo-do-usuario")
    temp = download_dir / ".tmp" / "abc.mp3"
    temp.parent.mkdir(parents=True)
    temp.write_bytes(b"novo")

    with pytest.raises(OverwriteRefusedError):
        publish_file(temp, final)

    assert final.read_bytes() == b"arquivo-do-usuario"  # intacto
    assert temp.exists()  # o chamador decide a limpeza


def test_publish_file_propagates_enospc_and_keeps_temp(download_dir, monkeypatch):
    """Disco cheio: OSError sobe, nada é publicado e o temp fica para limpeza."""
    temp = download_dir / ".tmp" / "abc.mp3"
    temp.parent.mkdir(parents=True)
    temp.write_bytes(b"audio")
    final = download_dir / "Faixa.mp3"

    def _full(_src, _dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pipeline_mod.os, "replace", _full)

    with pytest.raises(OSError, match="No space left"):
        publish_file(temp, final)

    assert not final.exists()
    assert temp.exists()


def test_temp_dir_lives_inside_download_dir_same_filesystem(download_dir):
    """Temporário e destino no mesmo filesystem: o replace é só um rename."""
    reservation = reserve(download_dir / "A" / "B" / "Faixa.mp3", download_dir)
    assert reservation.temp_dir.parent == download_dir
    release(reservation)
