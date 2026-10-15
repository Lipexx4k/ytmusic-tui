"""Testes da reconciliação de arquivos/registros (T03, §5.3 do plano).

Cobrem as quatro situações do §5.3: arquivo sem registro (importa se válido,
quarentena se inválido), registro sem arquivo (relata, nunca apaga),
temporários/`.part` antigos (política de idade + prefixo próprio) e a
garantia de que arquivo final do usuário nunca é apagado.
"""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ytmusic_tui.library.database import DatabaseManager
from ytmusic_tui.library.recovery import (
    STALE_TEMP_AGE_HOURS,
    ReconciliationReport,
    reconcile,
    scan_media_files,
)
from ytmusic_tui.library.service import LibraryService


@pytest.fixture
def temp_db():
    """Banco temporário (mesmo padrão de test_library.py)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = Path(handle.name)

    db_manager = DatabaseManager(db_path)
    db_manager.create_all()

    yield db_manager

    db_manager.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def service(temp_db) -> LibraryService:
    instance = LibraryService()
    instance.db = temp_db
    return instance


@pytest.fixture
def download_dir(tmp_path: Path) -> Path:
    target = tmp_path / "musicas"
    target.mkdir()
    return target


def _make_old(path: Path, hours: float = STALE_TEMP_AGE_HOURS + 1) -> None:
    """Envelhece a mtime do arquivo (para a política de limpeza)."""
    past = datetime.now(UTC).timestamp() - hours * 3600
    os.utime(path, (past, past))


# ===== Situação 1: arquivo final sem registro =====


def test_reconcile_imports_orphan_with_album_directory(service, download_dir):
    """Órfão válido em Artista/Álbum/ é importado com metadados do caminho."""
    media = download_dir / "Artista A" / "Álbum X" / "Faixa - Artista A.mp3"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"audio-valido")

    report = reconcile(download_dir, service)

    assert report.imported_files == [media]
    assert report.quarantined_files == []
    tracks = service.get_downloaded_tracks()
    assert len(tracks) == 1
    track = tracks[0]
    assert track.local_path == str(media)
    assert track.title == "Faixa"
    assert track.file_format == "mp3"
    assert track.bitrate == 0  # desconhecido no import (documentado)
    assert [link.artist.name for link in track.artists] == ["Artista A"]
    assert track.album is not None and track.album.title == "Álbum X"


def test_reconcile_imports_orphan_without_album_directory(service, download_dir):
    """Sem diretório de álbum, o artista vem do diretório e o álbum fica vazio."""
    media = download_dir / "Artista B" / "Outra - Artista B.mp3"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"audio-valido")

    report = reconcile(download_dir, service)

    assert report.imported_files == [media]
    track = service.get_downloaded_tracks()[0]
    assert track.title == "Outra"
    assert [link.artist.name for link in track.artists] == ["Artista B"]
    assert track.album is None


def test_reconcile_is_idempotent_for_registered_files(service, download_dir):
    """Depois de importado, o arquivo é reconhecido e não é duplicado."""
    media = download_dir / "A" / "B" / "T - A.mp3"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"audio")

    first = reconcile(download_dir, service)
    second = reconcile(download_dir, service)

    assert first.imported_files == [media]
    assert second.has_findings is False
    assert len(service.get_downloaded_tracks()) == 1


# ===== Situação 2: registro sem arquivo =====


def test_reconcile_reports_missing_record_without_deleting(service, download_dir):
    """Registro apontando para arquivo inexistente: relatório, sem apagar nada."""
    track_id = service.ensure_track(source_id="vid1", title="T", artist="A", album="B")
    assert track_id is not None
    missing = download_dir / "A" / "B" / "T - A.mp3"  # nunca criado no disco
    service.update_track_file(track_id, missing, 123, "mp3", 320)

    report = reconcile(download_dir, service)

    assert report.missing_records == [missing]
    # O registro continua intacto (persistência de "ausente" fica para o T05)
    track = service.get_track_by_source_id("vid1")
    assert track is not None
    assert track.local_path == str(missing)


# ===== Situação 3: temporários/`.part` antigos =====


def test_reconcile_removes_only_stale_own_temps(service, download_dir):
    """Limpeza só com idade mínima E prefixo próprio; recentes são preservados."""
    tmp_dir = download_dir / ".tmp"
    tmp_dir.mkdir()
    old_lock = tmp_dir / "0123456789abcdef.reserva"
    old_media = tmp_dir / "fedcba9876543210.opus"
    recent_lock = tmp_dir / "abcdefabcdefabcd.reserva"
    foreign = tmp_dir / "arquivo-comum.mp3"
    for path in (old_lock, old_media, recent_lock, foreign):
        path.write_bytes(b"x")
    for path in (old_lock, old_media, foreign):
        _make_old(path)

    album = download_dir / "A" / "B"
    album.mkdir(parents=True)
    old_part = album / "T - A.mp3.part"
    old_ytdl = album / "T - A.ytdl"
    recent_part = album / "U - A.mp3.part"
    for path in (old_part, old_ytdl, recent_part):
        path.write_bytes(b"x")
    for path in (old_part, old_ytdl):
        _make_old(path)

    report = reconcile(download_dir, service)

    assert set(report.removed_temps) == {old_lock, old_media, old_part, old_ytdl}
    assert not old_lock.exists() and not old_media.exists()
    assert not old_part.exists() and not old_ytdl.exists()
    # Recentes (podem estar em uso) e nomes fora do padrão são preservados
    assert recent_lock.exists() and foreign.exists() and recent_part.exists()
    # Arquivos de mídia nunca são tocados pela limpeza de temporários
    assert report.imported_files == []


# ===== Situação 4: arquivo final inválido =====


def test_reconcile_quarantines_invalid_orphan(service, download_dir):
    """Órfão de 0 byte vai para .quarantine (0700) e não é registrado."""
    broken = download_dir / "A" / "B" / "Quebrada - A.mp3"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"")

    report = reconcile(download_dir, service)

    assert report.quarantined_files == [broken]
    quarantine_dir = download_dir / ".quarantine"
    moved = quarantine_dir / broken.name
    assert moved.exists() and moved.read_bytes() == b""
    assert not broken.exists()
    assert os.stat(quarantine_dir).st_mode & 0o777 == 0o700
    assert service.get_downloaded_tracks() == []


def test_quarantine_renames_on_collision(service, download_dir):
    """Nome já ocupado na quarentena não é sobrescrito: ganha sufixo."""
    quarantine_dir = download_dir / ".quarantine"
    quarantine_dir.mkdir()
    (quarantine_dir / "Quebrada - A.mp3").write_bytes(b"antiga")

    broken = download_dir / "A" / "B" / "Quebrada - A.mp3"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"")

    report = reconcile(download_dir, service)

    assert report.quarantined_files == [broken]
    assert (quarantine_dir / "Quebrada - A-1.mp3").read_bytes() == b""
    assert (quarantine_dir / "Quebrada - A.mp3").read_bytes() == b"antiga"


# ===== Varredura e áreas especiais =====


def test_scan_media_files_filters_extensions_and_special_dirs(download_dir):
    """.tmp/ e .quarantine/ ficam fora; só extensão suportada entra."""
    good = download_dir / "A" / "B" / "T - A.flac"
    good.parent.mkdir(parents=True)
    good.write_bytes(b"audio")
    (download_dir / "A" / "capa.jpg").write_bytes(b"imagem")
    tmp_media = download_dir / ".tmp" / "0123456789abcdef.mp3"
    tmp_media.parent.mkdir(parents=True)
    tmp_media.write_bytes(b"audio")
    quarantine_media = download_dir / ".quarantine" / "ruim.mp3"
    quarantine_media.parent.mkdir()
    quarantine_media.write_bytes(b"audio")

    assert scan_media_files(download_dir) == [good]


def test_reconcile_ignores_tmp_and_quarantine_directories(service, download_dir):
    """Nada dentro de .tmp/ ou .quarantine/ é importado, movido ou removido."""
    tmp_media = download_dir / ".tmp" / "0123456789abcdef.mp3"
    tmp_media.parent.mkdir(parents=True)
    tmp_media.write_bytes(b"temporario-recente")
    quarantined = download_dir / ".quarantine" / "antiga.mp3"
    quarantined.parent.mkdir(parents=True)
    quarantined.write_bytes(b"audio")

    report = reconcile(download_dir, service)

    assert not report.has_findings
    assert tmp_media.exists()
    assert quarantined.exists()
    assert service.get_downloaded_tracks() == []


def test_reconcile_missing_download_dir_is_noop(service, tmp_path):
    """Diretório de downloads inexistente não é criado nem varrido."""
    report = reconcile(tmp_path / "nao-existe", service)
    assert not report.has_findings


def test_report_summary_lists_only_findings():
    """O resumo menciona apenas o que aconteceu."""
    empty = ReconciliationReport()
    assert not empty.has_findings
    assert empty.summary() == "nada a reconciliar"

    partial = ReconciliationReport(missing_records=[Path("/x")])
    assert partial.summary() == "1 registro(s) sem arquivo"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
