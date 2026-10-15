"""Modelos do banco de dados da biblioteca local."""
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime:
    """Agora em UTC, mas sem tzinfo (compatível com os dados já gravados).

    Substitui ``utcnow``, removido/depreciado no Python 3.12+.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class TrackSource(PyEnum):
    """Origem da faixa na biblioteca."""
    YOUTUBE_MUSIC = "youtube_music"
    LOCAL_FILE = "local_file"
    DOWNLOADED = "downloaded"


class Artist(Base):
    __tablename__ = "artists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(100), nullable=False, index=True)  # ID do YouTube Music
    name = Column(String(255), nullable=False, index=True)
    source = Column(SQLEnum(TrackSource), default=TrackSource.YOUTUBE_MUSIC, nullable=False)
    thumbnail_url = Column(String(500))
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relacionamentos
    albums = relationship("AlbumArtist", back_populates="artist", cascade="all, delete-orphan")
    tracks = relationship("TrackArtist", back_populates="artist", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source_id", "source", name="uq_artist_source"),
        Index("ix_artist_name_source", "name", "source"),
    )

    def __repr__(self):
        return f"<Artist(id={self.id}, name='{self.name}', source_id='{self.source_id}')>"


class Album(Base):
    __tablename__ = "albums"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(100), nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    source = Column(SQLEnum(TrackSource), default=TrackSource.YOUTUBE_MUSIC, nullable=False)
    release_year = Column(Integer)
    release_date = Column(String(20))  # YYYY-MM-DD
    thumbnail_url = Column(String(500))
    description = Column(Text)
    track_count = Column(Integer, default=0)
    duration_seconds = Column(Integer, default=0)
    is_compilation = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relacionamentos
    artists = relationship("AlbumArtist", back_populates="album", cascade="all, delete-orphan")
    tracks = relationship("Track", back_populates="album", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source_id", "source", name="uq_album_source"),
        Index("ix_album_title_source", "title", "source"),
    )

    def __repr__(self):
        return f"<Album(id={self.id}, title='{self.title}', source_id='{self.source_id}')>"


class AlbumArtist(Base):
    __tablename__ = "album_artists"

    album_id = Column(Integer, ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True)
    artist_id = Column(Integer, ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    is_primary = Column(Boolean, default=True)

    album = relationship("Album", back_populates="artists")
    artist = relationship("Artist", back_populates="albums")


class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(100), nullable=False, index=True)  # Video ID do YouTube
    title = Column(String(255), nullable=False, index=True)
    source = Column(SQLEnum(TrackSource), default=TrackSource.YOUTUBE_MUSIC, nullable=False)

    # Metadados
    duration_seconds = Column(Integer, default=0)
    track_number = Column(Integer)
    disc_number = Column(Integer, default=1)
    isrc = Column(String(20))
    explicit = Column(Boolean, default=False)
    lyrics = Column(Text)

    # Arquivo local (se baixado)
    local_path = Column(String(500))
    file_size = Column(Integer)
    file_format = Column(String(20))
    bitrate = Column(Integer)

    # Thumbnails
    thumbnail_url = Column(String(500))

    # Status
    is_liked = Column(Boolean, default=False, index=True)
    is_downloaded = Column(Boolean, default=False, index=True)
    play_count = Column(Integer, default=0)
    last_played = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    added_at = Column(DateTime, default=utcnow, index=True)

    # Relacionamentos
    album_id = Column(Integer, ForeignKey("albums.id", ondelete="SET NULL"), index=True)
    album = relationship("Album", back_populates="tracks")
    artists = relationship(
        "TrackArtist", back_populates="track", cascade="all, delete-orphan"
    )
    playlist_entries = relationship(
        "PlaylistTrack", back_populates="track", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "source", name="uq_track_source"),
        Index("ix_track_title_artist", "title", "album_id"),
        Index("ix_track_liked_added", "is_liked", "added_at"),
    )

    def __repr__(self):
        return f"<Track(id={self.id}, title='{self.title}', source_id='{self.source_id}')>"

    @property
    def primary_artist(self):
        """Retorna o artista principal (primeiro da lista)."""
        for ta in self.artists:
            if ta.is_primary:
                return ta.artist
        return self.artists[0].artist if self.artists else None

    @property
    def artist_names(self) -> list[str]:
        """Lista de nomes dos artistas."""
        return [ta.artist.name for ta in self.artists]


class TrackArtist(Base):
    __tablename__ = "track_artists"

    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    artist_id = Column(Integer, ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    is_primary = Column(Boolean, default=True)
    role = Column(String(50))  # "main", "featured", "remixer", etc.

    track = relationship("Track", back_populates="artists")
    artist = relationship("Artist", back_populates="tracks")


class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(100), nullable=True, index=True)  # ID do YT Music se sincronizada
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    source = Column(SQLEnum(TrackSource), default=TrackSource.LOCAL_FILE, nullable=False)
    thumbnail_url = Column(String(500))
    is_system = Column(Boolean, default=False)  # Playlists do sistema (liked, history, etc)
    track_count = Column(Integer, default=0)
    duration_seconds = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relacionamentos
    tracks = relationship("PlaylistTrack", back_populates="playlist", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source_id", "source", name="uq_playlist_source"),
    )

    def __repr__(self):
        return f"<Playlist(id={self.id}, name='{self.name}', source='{self.source.value}')>"


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    playlist_id = Column(Integer, ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True)
    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    position = Column(Integer, nullable=False, index=True)
    added_at = Column(DateTime, default=utcnow)
    added_by = Column(String(100))  # user ID ou "local"

    playlist = relationship("Playlist", back_populates="tracks")
    track = relationship("Track", back_populates="playlist_entries")

    __table_args__ = (
        Index("ix_playlist_track_position", "playlist_id", "position"),
    )


class PlaybackHistory(Base):
    __tablename__ = "playback_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    played_at = Column(DateTime, default=utcnow, index=True)
    duration_played = Column(Integer, default=0)  # segundos reproduzidos
    completed = Column(Boolean, default=False)  # reproduziu até o fim
    source = Column(String(50))  # "library", "playlist:1", "search", "radio"

    track = relationship("Track")

    __table_args__ = (
        Index("ix_history_track_played", "track_id", "played_at"),
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self):
        return f"<UserSetting(key='{self.key}', value='{self.value[:50]}')>"