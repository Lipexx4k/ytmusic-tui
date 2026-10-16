"""Wrapper para API do YouTube Music usando ytmusicapi (T10-R1).

Cliente anônimo (sem login): apenas os métodos que o app usa são expostos —
``search_catalog``, ``get_album`` e ``get_stream_url``. Os métodos sem
consumidor (``search`` genérico, get_song/artist/playlist/watch_playlist,
home e moods) foram removidos no T10-R1 (Q-A): se um recurso precisar deles,
eles voltam tipados, dirigidos pelo uso real.

Nenhuma camada acima de ``api/`` vê objeto do ytmusicapi: as respostas cruas
viram modelos internos (``api.models``) nos adaptadores (``api.adapt``) —
um teste de fonte garante a fronteira. Funções de conta (curtidas,
biblioteca remota, playlists remotas) seguem omitidas — com o cliente
anônimo o ytmusicapi responde ``YTMusicUserError: Please provide
authentication``; a biblioteca do app é local (SQLite).

``get_stream_url`` é o único ponto público de URL de watch; o player e o
pipeline de download ainda montam a própria URL internamente (a dedup fica
no T11 — seam documentado no plano).
"""

from concurrent.futures import ThreadPoolExecutor

from ytmusicapi import YTMusic

from ytmusic_tui.api.adapt import album_detail_from_raw, search_result_from_raws
from ytmusic_tui.api.models import AlbumDetail, SearchResult
from ytmusic_tui.errors import InvalidResponseError

__all__ = ["AlbumDetail", "SearchResult", "YTMusicAPI", "ytmusic"]


class YTMusicAPI:
    """Cliente para API do YouTube Music (fronteira tipada do T10-R1)."""

    def __init__(self) -> None:
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

    def _require_client(self) -> YTMusic:
        """Cliente subjacente — privado: objeto do ytmusicapi não sai daqui."""
        if not self._initialized:
            self.initialize()
        if not self._client:
            raise RuntimeError("YTMusic não inicializado.")
        return self._client

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

        A saída é sempre ``SearchResult`` com modelos internos (T10-R1); a
        validação de forma do T08 roda dentro de ``search_result_from_raws``.
        """
        # Resolver o cliente antes de paralelizar: o visitor id anônimo é
        # inicializado de forma lazy na primeira requisição.
        client = self._require_client()

        with ThreadPoolExecutor(max_workers=2) as pool:
            tracks_future = pool.submit(client.search, query, filter="songs", limit=songs_limit)
            albums_future = pool.submit(client.search, query, filter="albums", limit=albums_limit)
            return search_result_from_raws(tracks_future.result(), albums_future.result())

    def get_album(self, browse_id: str) -> AlbumDetail:
        """Obtém detalhes do álbum como modelo interno (T10-R1)."""
        raw = self._require_client().get_album(browse_id)
        if not isinstance(raw, dict):
            raise InvalidResponseError(
                f"resposta inesperada da API: esperado dict, recebido {type(raw).__name__}"
            )
        return album_detail_from_raw(raw)

    def get_stream_url(self, video_id: str) -> str:
        """URL de watch para reprodução/download via yt-dlp.

        O ytmusicapi não expõe uma URL de stream direta; a resolução é
        delegada ao yt-dlp, embutido no mpv, a partir da URL de watch.
        """
        return f"https://music.youtube.com/watch?v={video_id}"


# Instância global
ytmusic = YTMusicAPI()
