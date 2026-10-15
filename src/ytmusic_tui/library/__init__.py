"""Pacote da biblioteca local."""
from ytmusic_tui.library.database import db_manager
from ytmusic_tui.library.models import (
    Album,
    AlbumArtist,
    Artist,
    Base,
    PlaybackHistory,
    Playlist,
    PlaylistTrack,
    Track,
    TrackArtist,
    TrackSource,
    UserSettings,
)
from ytmusic_tui.library.service import LibraryService, library

__all__ = [
    "library",
    "LibraryService",
    "db_manager",
    "Base",
    "Artist",
    "Album",
    "Track",
    "Playlist",
    "PlaylistTrack",
    "TrackArtist",
    "AlbumArtist",
    "PlaybackHistory",
    "UserSettings",
    "TrackSource",
]