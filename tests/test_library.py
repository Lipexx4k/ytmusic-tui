"""Testes para o serviço da biblioteca."""

import tempfile
from pathlib import Path

import pytest

from ytmusic_tui.library.database import DatabaseManager
from ytmusic_tui.library.models import TrackSource
from ytmusic_tui.library.service import LibraryService


@pytest.fixture
def temp_db():
    """Cria banco temporário para testes."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db_manager = DatabaseManager(db_path)
    db_manager.create_all()

    yield db_manager

    db_manager.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def library_service(temp_db):
    """Cria serviço de biblioteca com DB temporário."""
    # Criar serviço que usa o db temporário
    service = LibraryService()
    service.db = temp_db
    return service


def test_create_artist(library_service):
    """Testa criação de artista."""
    with library_service.db.session() as session:
        artist = library_service.get_or_create_artist(
            session, "UC123", "Test Artist", TrackSource.YOUTUBE_MUSIC
        )
        assert artist.id is not None
        assert artist.name == "Test Artist"
        assert artist.source_id == "UC123"


def test_create_album_with_artist(library_service):
    """Testa criação de álbum com artista."""
    with library_service.db.session() as session:
        artist = library_service.get_or_create_artist(
            session, "UC123", "Test Artist", TrackSource.YOUTUBE_MUSIC
        )
        album = library_service.get_or_create_album(
            session, "ALB123", "Test Album", TrackSource.YOUTUBE_MUSIC, release_year=2024
        )
        library_service.link_album_artist(session, album, artist)

        # Verificar relacionamento
        session.refresh(album)
        assert len(album.artists) == 1
        assert album.artists[0].artist.name == "Test Artist"


def test_create_track_with_artist_and_album(library_service):
    """Testa criação de faixa com artista e álbum."""
    track_id = None
    album_id = None

    with library_service.db.session() as session:
        artist = library_service.get_or_create_artist(
            session, "UC123", "Test Artist", TrackSource.YOUTUBE_MUSIC
        )
        album = library_service.get_or_create_album(
            session, "ALB123", "Test Album", TrackSource.YOUTUBE_MUSIC
        )
        album_id = album.id
        library_service.link_album_artist(session, album, artist)

        track = library_service.get_or_create_track(
            session, "VID123", "Test Track", TrackSource.YOUTUBE_MUSIC, duration_seconds=180
        )
        track_id = track.id
        library_service.link_track_artist(session, track, artist)
        library_service.link_track_album(session, track, album)

        session.flush()
        session.refresh(track)
        assert track.primary_artist.name == "Test Artist"
        assert track.album_id == album.id
        assert track.duration_seconds == 180

    # Verificar relacionamento em nova sessão
    track = library_service.get_track(track_id)
    assert track is not None
    assert track.album_id == album_id
    assert track.album.title == "Test Album"


def test_playlist_operations(library_service):
    """Testa operações de playlist."""
    playlist = library_service.create_playlist("Minha Playlist", "Descrição")
    assert playlist.id is not None
    assert playlist.name == "Minha Playlist"

    with library_service.db.session() as session:
        # Criar faixas
        artist = library_service.get_or_create_artist(
            session, "UC1", "Artist 1", TrackSource.YOUTUBE_MUSIC
        )
        track1 = library_service.get_or_create_track(
            session, "VID1", "Track 1", TrackSource.YOUTUBE_MUSIC
        )
        track2 = library_service.get_or_create_track(
            session, "VID2", "Track 2", TrackSource.YOUTUBE_MUSIC
        )
        library_service.link_track_artist(session, track1, artist)
        library_service.link_track_artist(session, track2, artist)

    # Adicionar à playlist
    library_service.add_track_to_playlist(playlist.id, track1.id)
    library_service.add_track_to_playlist(playlist.id, track2.id)

    # Verificar
    pl = library_service.get_playlist(playlist.id)
    assert pl is not None
    assert pl.track_count == 2
    assert len(pl.tracks) == 2


def test_like_toggle(library_service):
    """Testa toggle de like."""
    with library_service.db.session() as session:
        artist = library_service.get_or_create_artist(
            session, "UC1", "Artist", TrackSource.YOUTUBE_MUSIC
        )
        track = library_service.get_or_create_track(
            session, "VID1", "Track", TrackSource.YOUTUBE_MUSIC
        )
        library_service.link_track_artist(session, track, artist)
        track_id = track.id

    # Sessões independentes: toggles só após o commit do bloco acima.
    assert library_service.toggle_like(track_id) is True
    assert library_service.toggle_like(track_id) is False


def test_search_tracks(library_service):
    """Testa busca de faixas."""
    with library_service.db.session() as session:
        artist = library_service.get_or_create_artist(
            session, "UC1", "The Beatles", TrackSource.YOUTUBE_MUSIC
        )
        track1 = library_service.get_or_create_track(
            session, "VID1", "Hey Jude", TrackSource.YOUTUBE_MUSIC
        )
        track2 = library_service.get_or_create_track(
            session, "VID2", "Let It Be", TrackSource.YOUTUBE_MUSIC
        )
        library_service.link_track_artist(session, track1, artist)
        library_service.link_track_artist(session, track2, artist)

    # Buscar por título
    results = library_service.search_tracks("Hey Jude")
    assert len(results) == 1
    assert results[0].title == "Hey Jude"

    # Buscar por artista
    results = library_service.search_tracks("Beatles")
    assert len(results) == 2

    # Buscar inexistente
    results = library_service.search_tracks("Inexistente")
    assert len(results) == 0


def test_stats(library_service):
    """Testa estatísticas."""
    with library_service.db.session() as session:
        artist = library_service.get_or_create_artist(
            session, "UC1", "Artist", TrackSource.YOUTUBE_MUSIC
        )
        track = library_service.get_or_create_track(
            session, "VID1", "Track", TrackSource.YOUTUBE_MUSIC, duration_seconds=200
        )
        library_service.link_track_artist(session, track, artist)

    stats = library_service.get_stats()
    assert stats["tracks"] == 1
    assert stats["artists"] == 1
    assert stats["total_duration"] == 200


def test_ensure_track_creates_artist_album_and_is_idempotent(library_service):
    """ensure_track registra faixa + artistas + álbum antes do download."""
    track_id = library_service.ensure_track(
        source_id="VIDX",
        title="Música Nova",
        artist="Artista A, Artista B",
        album="Álbum Z",
        thumbnail_url="http://example.com/x.jpg",
        duration_seconds=210,
    )
    assert track_id is not None

    track = library_service.get_track_by_source_id("VIDX")
    assert track is not None
    assert track.title == "Música Nova"
    assert set(track.artist_names) == {"Artista A", "Artista B"}
    assert track.album is not None
    assert track.album.title == "Álbum Z"

    # Idempotente: chamar de novo não duplica nem muda o ID
    again = library_service.ensure_track(
        source_id="VIDX",
        title="Música Nova",
        artist="Artista A, Artista B",
        album="Álbum Z",
    )
    assert again == track_id
    stats = library_service.get_stats()
    assert stats["tracks"] == 1
    assert stats["artists"] == 2


def test_get_local_paths_returns_only_registered_files(library_service, tmp_path):
    """get_local_paths lista os caminhos registrados (insumo da reconciliação)."""
    assert library_service.get_local_paths() == set()

    track_id = library_service.ensure_track(source_id="VIDY", title="Com Arquivo")
    assert track_id is not None
    media = tmp_path / "Com Arquivo.mp3"
    media.write_bytes(b"audio")
    library_service.update_track_file(track_id, media, 5, "mp3", 320)

    assert library_service.get_local_paths() == {str(media)}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
