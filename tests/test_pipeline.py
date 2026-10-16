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
    PathEscapeError,
    build_output_template,
    final_path_for,
    normalize_component,
    publish_file,
    release,
    reservation_key,
    reserve,
    resolve_within,
    truncate_bytes,
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
    """Um destino fora de download_dir não pode ser publicado (INV-5)."""
    with pytest.raises(PathEscapeError, match="fora de download_dir"):
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


# ===== Normalização única de caminhos e contenção (§8.1/T06) =====


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a/b", "a_b"),
        ("a\\b", "a_b"),
        ('a:b*c?d"e<f>g|h', "a_b_c_d_e_f_g_h"),
        ("a\x00b", "a_b"),
        ("a\x1fb", "a_b"),
        ("a\tb", "a_b"),
        ("a\x7fb", "a_b"),  # DEL: endurecimento intencional do T06 (§1.1h)
        ("  nome  ", "nome"),
        ("..nome..", "nome"),
        ("...", ""),  # só pontos/espaços vira vazio (comportamento histórico)
    ],
)
def test_normalize_component_removes_separators_and_control_chars(raw, expected):
    assert normalize_component(raw, default="Default", max_chars=60) == expected


def test_normalize_component_default_covers_empty_input_only():
    """O default cobre a ENTRADA vazia; valor esvaziado pela sanitização não.

    É o comportamento histórico (fonte do corpus congelado): quem aplica o
    fallback final ao artista/álbum/stem é o compositor, não a sanitização.
    """
    assert normalize_component("", default="Fallback", max_chars=60) == "Fallback"
    assert normalize_component("...", default="Fallback", max_chars=60) == ""


def test_normalize_component_limits_chars_then_bytes():
    assert normalize_component("x" * 500, default="D", max_chars=100) == "x" * 100
    assert normalize_component("音" * 100, default="D", max_chars=100, max_bytes=240) == "音" * 80
    # O corte por bytes não quebra caractere multibyte no meio
    assert normalize_component("a🎵", default="D", max_chars=10, max_bytes=4) == "a"


def test_truncate_bytes_keeps_short_names_and_strips_edges():
    assert truncate_bytes("nome", 10) == "nome"
    assert truncate_bytes("ab ..", 3) == "ab"  # cortou e limpou as pontas
    assert truncate_bytes("音" * 3, 7) == "音" * 2  # corte em fronteira de caractere


#: Corpus congelado da implementação ANTERIOR ao T06 (capturado antes do
#: refactor): entrada ``(artist, title, album)`` → partes relativas do
#: caminho final. O DEL ``\x7f`` é a única divergência intencional (a matriz
#: acima o cobre); renomear qualquer um destes arquivos seria regressão de
#: produto (arquivos já baixados/persistidos na T04 e a adoção Q2(a)).
FROZEN_CORPUS: list[tuple[tuple[str, str, str], tuple[str, ...]]] = [
    (("Artista", "Faixa", "Álbum"), ("Artista", "Álbum", "Faixa - Artista.mp3")),
    (
        ("AC/DC", "Back in Black", "Back in Black"),
        ("AC_DC", "Back in Black", "Back in Black - AC_DC.mp3"),
    ),
    (("A/B", "C\\D", "E:F"), ("A_B", "E_F", "C_D - A_B.mp3")),
    (("", "", ""), ("Unknown Artist", "Unknown Title - Unknown Artist.mp3")),
    (("...", "..", "."), ("Unknown Artist", " - Unknown Artist.mp3")),
    (("a\x00b", "c\x1fd", "e\tf"), ("a_b", "e_f", "c_d - a_b.mp3")),
    (
        ("T" * 500, "A" * 500, "L" * 500),
        ("T" * 60, "L" * 60, "A" * 100 + " - " + "T" * 60 + ".mp3"),
    ),
    (
        ("音" * 500, "歌" * 500, "🎵" * 500),
        ("音" * 40, "🎵" * 30, "歌" * 80 + ".mp3"),
    ),
    (
        ("🎵" * 80, "アーティスト", "アルバム"),
        ("🎵" * 30, "アルバム", "アーティスト - " + "🎵" * 30 + ".mp3"),
    ),
    (("Artista ", " Título ", " Álbum "), ("Artista", "Álbum", "Título - Artista.mp3")),
    (("Artista.", ".Título.", "Álbum."), ("Artista", "Álbum", "Título - Artista.mp3")),
    (("Artista", "音" * 100, "Álbum"), ("Artista", "Álbum", "音" * 80 + ".mp3")),
    (("Artista", "x" * 300, "Álbum"), ("Artista", "Álbum", "x" * 100 + " - Artista.mp3")),
    (
        ("Artista", 'a?b:*c"d<e>f|g', "Álbum"),
        ("Artista", "Álbum", "a_b__c_d_e_f_g - Artista.mp3"),
    ),
    (
        ("Artista", "Unknown Album", "Unknown Album"),
        ("Artista", "Unknown Album - Artista.mp3"),
    ),
    (("Artista", "  .. . ", "..."), ("Artista", " - Artista.mp3")),
    (("A B", "C  D", "E   F"), ("A B", "E   F", "C  D - A B.mp3")),
    (
        ("🎵" * 500, "🎵" * 80, "歌" * 500),
        ("🎵" * 30, "歌" * 40, "🎵" * 60 + ".mp3"),
    ),
]


@pytest.mark.parametrize(("entrada", "partes"), FROZEN_CORPUS)
def test_normalization_matches_frozen_corpus(entrada, partes):
    """A unificação do T06 não renomeia NADA do que existe (T04/Q2 congelados).

    Caminho final E template do yt-dlp saem da mesma normalização; todo
    componente fica abaixo de 255 bytes.
    """
    artist, title, album = entrada

    final = final_path_for(
        download_dir=Path("/d"), artist=artist, title=title, album=album, extension="mp3"
    )
    expected = Path("/d").joinpath(*partes)
    assert final == expected

    template = build_output_template(
        download_dir=Path("/d"), artist=artist, title=title, album=album
    )
    assert template == str(expected).removesuffix(".mp3") + ".%(ext)s"

    for part in partes:
        assert len(part.encode("utf-8")) <= 255


def test_resolve_within_accepts_contained_or_nonexistent(download_dir):
    """Contenção usa o resolve (não exige existir) e devolve o resolvido."""
    candidate = download_dir / "A" / "nao-existe.mp3"

    resolved = resolve_within(candidate, download_dir)

    assert resolved == candidate.resolve()
    assert resolved.is_relative_to(download_dir.resolve())


def test_resolve_within_rejects_dotdot_escape(download_dir):
    with pytest.raises(PathEscapeError, match="fora de download_dir"):
        resolve_within(download_dir / ".." / "fora.mp3", download_dir)


def test_resolve_within_rejects_symlink_escape(download_dir, tmp_path):
    outside = tmp_path / "fora"
    outside.mkdir()
    (download_dir / "link").symlink_to(outside)

    with pytest.raises(PathEscapeError, match="fora de download_dir"):
        resolve_within(download_dir / "link" / "arquivo.mp3", download_dir)


def test_resolve_within_allows_symlinked_base(tmp_path):
    """download_dir que é symlink (música em outro disco) não é violação."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "atalho"
    link.symlink_to(real)

    resolved = resolve_within(link / "A.mp3", link)

    assert resolved == (real / "A.mp3").resolve()


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
