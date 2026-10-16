"""Modelos do banco de dados da biblioteca local."""

from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarativa dos modelos (estilo SQLAlchemy 2.0)."""


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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # ID do YouTube Music
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[TrackSource] = mapped_column(
        SQLEnum(TrackSource), default=TrackSource.YOUTUBE_MUSIC, nullable=False
    )
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    # Relacionamentos
    albums: Mapped[list["AlbumArtist"]] = relationship(
        back_populates="artist", cascade="all, delete-orphan"
    )
    tracks: Mapped[list["TrackArtist"]] = relationship(
        back_populates="artist", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "source", name="uq_artist_source"),
        Index("ix_artist_name_source", "name", "source"),
    )

    def __repr__(self) -> str:
        return f"<Artist(id={self.id}, name='{self.name}', source_id='{self.source_id}')>"


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[TrackSource] = mapped_column(
        SQLEnum(TrackSource), default=TrackSource.YOUTUBE_MUSIC, nullable=False
    )
    release_year: Mapped[int | None] = mapped_column(Integer)
    release_date: Mapped[str | None] = mapped_column(String(20))  # YYYY-MM-DD
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    track_count: Mapped[int | None] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, default=0)
    is_compilation: Mapped[bool | None] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    # Relacionamentos
    artists: Mapped[list["AlbumArtist"]] = relationship(
        back_populates="album", cascade="all, delete-orphan"
    )
    tracks: Mapped[list["Track"]] = relationship(
        back_populates="album", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "source", name="uq_album_source"),
        Index("ix_album_title_source", "title", "source"),
    )

    def __repr__(self) -> str:
        return f"<Album(id={self.id}, title='{self.title}', source_id='{self.source_id}')>"


class AlbumArtist(Base):
    __tablename__ = "album_artists"

    album_id: Mapped[int] = mapped_column(
        ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    is_primary: Mapped[bool | None] = mapped_column(Boolean, default=True)

    album: Mapped["Album"] = relationship(back_populates="artists")
    artist: Mapped["Artist"] = relationship(back_populates="albums")


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # Video ID do YouTube
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[TrackSource] = mapped_column(
        SQLEnum(TrackSource), default=TrackSource.YOUTUBE_MUSIC, nullable=False
    )

    # Metadados
    duration_seconds: Mapped[int | None] = mapped_column(Integer, default=0)
    track_number: Mapped[int | None] = mapped_column(Integer)
    disc_number: Mapped[int | None] = mapped_column(Integer, default=1)
    isrc: Mapped[str | None] = mapped_column(String(20))
    explicit: Mapped[bool | None] = mapped_column(Boolean, default=False)
    lyrics: Mapped[str | None] = mapped_column(Text)

    # Arquivo local (se baixado)
    local_path: Mapped[str | None] = mapped_column(String(500))
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_format: Mapped[str | None] = mapped_column(String(20))
    bitrate: Mapped[int | None] = mapped_column(Integer)

    # Thumbnails
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))

    # Status
    is_liked: Mapped[bool | None] = mapped_column(Boolean, default=False, index=True)
    is_downloaded: Mapped[bool | None] = mapped_column(Boolean, default=False, index=True)
    play_count: Mapped[int | None] = mapped_column(Integer, default=0)
    last_played: Mapped[datetime | None] = mapped_column(DateTime)

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    added_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, index=True)

    # Relacionamentos
    album_id: Mapped[int | None] = mapped_column(
        ForeignKey("albums.id", ondelete="SET NULL"), index=True
    )
    album: Mapped["Album | None"] = relationship(back_populates="tracks")
    artists: Mapped[list["TrackArtist"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )
    playlist_entries: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "source", name="uq_track_source"),
        Index("ix_track_title_artist", "title", "album_id"),
        Index("ix_track_liked_added", "is_liked", "added_at"),
    )

    def __repr__(self) -> str:
        return f"<Track(id={self.id}, title='{self.title}', source_id='{self.source_id}')>"

    @property
    def primary_artist(self) -> Artist | None:
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

    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    is_primary: Mapped[bool | None] = mapped_column(Boolean, default=True)
    role: Mapped[str | None] = mapped_column(String(50))  # "main", "featured", "remixer", etc.

    track: Mapped["Track"] = relationship(back_populates="artists")
    artist: Mapped["Artist"] = relationship(back_populates="tracks")


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str | None] = mapped_column(
        String(100), index=True
    )  # ID do YT Music se sincronizada
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[TrackSource] = mapped_column(
        SQLEnum(TrackSource), default=TrackSource.LOCAL_FILE, nullable=False
    )
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    is_system: Mapped[bool | None] = mapped_column(
        Boolean, default=False
    )  # Playlists do sistema (liked, history, etc)
    track_count: Mapped[int | None] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    # Relacionamentos
    tracks: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("source_id", "source", name="uq_playlist_source"),)

    def __repr__(self) -> str:
        return f"<Playlist(id={self.id}, name='{self.name}', source='{self.source.value}')>"


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    playlist_id: Mapped[int] = mapped_column(
        ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True
    )
    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    added_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    added_by: Mapped[str | None] = mapped_column(String(100))  # user ID ou "local"

    playlist: Mapped["Playlist"] = relationship(back_populates="tracks")
    track: Mapped["Track"] = relationship(back_populates="playlist_entries")

    __table_args__ = (Index("ix_playlist_track_position", "playlist_id", "position"),)


class PlaybackHistory(Base):
    __tablename__ = "playback_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track_id: Mapped[int | None] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), index=True
    )
    played_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, index=True)
    duration_played: Mapped[int | None] = mapped_column(Integer, default=0)  # segundos reproduzidos
    completed: Mapped[bool | None] = mapped_column(Boolean, default=False)  # reproduziu até o fim
    source: Mapped[str | None] = mapped_column(
        String(50)
    )  # "library", "playlist:1", "search", "radio"

    track: Mapped["Track | None"] = relationship()

    __table_args__ = (Index("ix_history_track_played", "track_id", "played_at"),)


class UserSettings(Base):
    __tablename__ = "user_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:
        return f"<UserSetting(key='{self.key}', value='{self.value[:50]}')>"


class DownloadTaskRecord(Base):
    """Espelho persistido das tarefas de download em voo/interrompidas (T04-R1).

    Tabela **nova** (a criação via ``create_all`` não exige migração — o
    versionamento de esquema entra no T05); nenhuma coluna é adicionada às
    tabelas existentes. A verdade da biblioteca continua em ``tracks``:
    aqui só vivem os campos necessários para (a) detectar na próxima
    execução que um trabalho ficou pela metade e (b) localizar os
    temporários da tarefa — ``download_dir`` + ``final_path`` permitem
    derivar ``.tmp/<chave>.*`` e ``<final>.part`` (§5.3/T04).

    ``track_id`` é um inteiro solto (sem FK): a linha pode sobreviver a um
    intervalo em que a faixa ainda não existe (registro é o passo 7 do
    §5.1) e não queremos cascata apagando a pista de recuperação.
    """

    __tablename__ = "download_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    video_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    artist: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    album: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    thumbnail_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    track_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Caminhos completos (Text: não são nomes limitados a 255 caracteres).
    final_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    download_dir: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Valores de ``DownloadStatus`` como string (StrEnum); não SQLEnum para
    # que novos estados da máquina não exijam migração de tipo.
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    retry_of: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:
        return f"<DownloadTaskRecord(task_id='{self.task_id}', status='{self.status}')>"
