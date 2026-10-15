"""Wrapper para API do YouTube Music usando ytmusicapi.

Cliente anônimo (sem login): apenas os métodos que funcionam sem
autenticação são expostos. Funções de conta (músicas curtidas, biblioteca
remota, rate_song, playlists remotas) são intencionalmente omitidas — com
o cliente anônimo o ytmusicapi responde ``YTMusicUserError: Please provide
authentication``. A biblioteca do app é local (SQLite).
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ytmusicapi import YTMusic


@dataclass
class SearchResult:
    """Resultado de busca padronizado."""
    tracks: list[dict[str, Any]]
    artists: list[dict[str, Any]]
    albums: list[dict[str, Any]]
    playlists: list[dict[str, Any]]
    videos: list[dict[str, Any]]


class YTMusicAPI:
    """Cliente para API do YouTube Music."""

    def __init__(self):
        self._client: YTMusic | None = None
        self._initialized = False
        self.last_error: str = ""

    def initialize(self) -> bool:
        """Inicializa o cliente YTMusic em modo anônimo (sem login).

        A autenticação OAuth do ``ytmusicapi`` está quebrada no lado do Google
        desde ago/2025 (sigma67/ytmusicapi#813): os tokens OAuth são rejeitados
        pelos endpoints internos do YouTube Music com ``HTTP 400 - invalid
        argument``. O cliente anônimo cobre busca, reprodução e download; a
        biblioteca local continua em SQLite.
        """
        if self._initialized:
            return True

        try:
            # YTMusic() anônimo não faz chamadas de rede no construtor; o
            # visitor id só é obtido de forma lazy na primeira requisição.
            self._client = YTMusic()
            self._initialized = True
            self.last_error = ""
            return True
        except Exception as e:  # noqa: BLE001
            self._initialized = False
            self._client = None
            self.last_error = str(e)
            return False

    def reset(self) -> None:
        """Descarta o cliente atual para permitir reinicialização."""
        self._client = None
        self._initialized = False

    @property
    def client(self) -> YTMusic:
        if not self._initialized:
            self.initialize()
        if not self._client:
            raise RuntimeError("YTMusic não inicializado.")
        return self._client

    def search(
        self,
        query: str,
        filter: str = "songs",
        limit: int = 20,
        ignore_spelling: bool = False,
    ) -> list[dict[str, Any]]:
        """Busca geral no YouTube Music."""
        return self.client.search(
            query, filter=filter, limit=limit, ignore_spelling=ignore_spelling
        )

    def search_catalog(
        self,
        query: str,
        songs_limit: int = 25,
        albums_limit: int = 15,
    ) -> SearchResult:
        """Busca músicas e álbuns em paralelo (duas requisições concorrentes).

        A busca sem filtro capa cada categoria em ~5 itens (ruim para a lista
        de músicas) e a versão sequencial custaria o dobro da latência; em
        paralelo o tempo total é o de uma requisição só (~2s, medido).
        """
        # Resolver o cliente antes de paralelizar: o visitor id anônimo é
        # inicializado de forma lazy na primeira requisição.
        client = self.client

        with ThreadPoolExecutor(max_workers=2) as pool:
            tracks_future = pool.submit(
                client.search, query, filter="songs", limit=songs_limit
            )
            albums_future = pool.submit(
                client.search, query, filter="albums", limit=albums_limit
            )
            songs = tracks_future.result()
            albums = albums_future.result()

        tracks = [
            s for s in songs if s.get("resultType") == "song" and s.get("videoId")
        ]
        albums = [
            a for a in albums if a.get("resultType") == "album" and a.get("browseId")
        ]
        return SearchResult(
            tracks=tracks, artists=[], albums=albums, playlists=[], videos=[]
        )

    def get_song(self, video_id: str) -> dict[str, Any]:
        """Obtém detalhes completos de uma música."""
        return self.client.get_song(video_id)

    def get_artist(self, browse_id: str) -> dict[str, Any]:
        """Obtém detalhes de um artista."""
        return self.client.get_artist(browse_id)

    def get_album(self, browse_id: str) -> dict[str, Any]:
        """Obtém detalhes de um álbum."""
        return self.client.get_album(browse_id)

    def get_playlist(self, playlist_id: str, limit: int = 100) -> dict[str, Any]:
        """Obtém detalhes de uma playlist."""
        return self.client.get_playlist(playlist_id, limit=limit)

    def get_watch_playlist(self, video_id: str, limit: int = 25) -> list[dict[str, Any]]:
        """Obtém playlist de reprodução (radio/watch) para uma música."""
        return self.client.get_watch_playlist(video_id, limit=limit)

    def get_home(self) -> list[dict[str, Any]]:
        """Obtém página inicial (recomendações)."""
        return self.client.get_home()

    def get_mood_categories(self) -> list[dict[str, Any]]:
        """Obtém categorias de humor/gênero."""
        return self.client.get_mood_categories()

    def get_mood_playlists(self, params: str) -> list[dict[str, Any]]:
        """Obtém playlists de um humor/categoria."""
        return self.client.get_mood_playlists(params)

    def get_stream_url(self, video_id: str) -> str:
        """URL de watch para reprodução/download via yt-dlp.

        O ytmusicapi não expõe uma URL de stream direta; a resolução é
        delegada ao yt-dlp, embutido no mpv, a partir da URL de watch.
        """
        return f"https://music.youtube.com/watch?v={video_id}"


# Instância global
ytmusic = YTMusicAPI()