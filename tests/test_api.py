"""Testes para o wrapper da API em modo anônimo (sem login)."""

import pytest

import ytmusic_tui.api as api_module
from ytmusic_tui.api import SearchResult, YTMusicAPI
from ytmusic_tui.errors import InvalidResponseError


class _FakeYTMusic:
    """Substituto de YTMusic que não toca a rede."""

    def __init__(self, *args, **kwargs):
        self.searches = []

    def search(self, query, filter=None, limit=None, ignore_spelling=False):
        self.searches.append(filter)
        result_type = {
            "songs": "song",
            "artists": "artist",
            "albums": "album",
            "playlists": "playlist",
            "videos": "video",
        }.get(filter, "song")
        item = {"resultType": result_type, "title": f"{filter}-{query}"}
        if result_type == "song":
            item["videoId"] = f"vid-{query}"
        elif result_type == "album":
            item["browseId"] = f"MPREb-{query}"
        return [item]

    def get_song(self, video_id):
        return {"videoId": video_id}


@pytest.fixture
def fake_ytmusic(monkeypatch):
    monkeypatch.setattr(api_module, "YTMusic", _FakeYTMusic)


def test_initialize_anonymous_returns_true(fake_ytmusic):
    """Sem credenciais, o cliente é criado anônimo e inicializado."""
    api = YTMusicAPI()
    assert api.initialize() is True
    assert isinstance(api.client, _FakeYTMusic)

    # reentrância: já inicializado
    assert api.initialize() is True

    api.reset()
    assert api._client is None


def test_client_requires_initialize(monkeypatch):
    """Se a inicialização falhar, acessar o cliente deve levantar erro claro."""
    monkeypatch.setattr(
        api_module,
        "YTMusic",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    api = YTMusicAPI()
    assert api.initialize() is False

    with pytest.raises(RuntimeError):
        _ = api.client


def test_initialize_failure_returns_false(monkeypatch):
    """Se YTMusic() falhar, initialize() deve retornar False, não quebrar."""
    monkeypatch.setattr(
        api_module,
        "YTMusic",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    api = YTMusicAPI()
    assert api.initialize() is False
    assert api._client is None


def test_search_catalog_parallel_songs_and_albums(fake_ytmusic):
    """search_catalog busca músicas e álbuns (2 requisições) e filtra por tipo."""
    api = YTMusicAPI()
    assert api.initialize() is True

    result = api.search_catalog("coldplay", songs_limit=5, albums_limit=3)

    assert isinstance(result, SearchResult)
    assert len(result.tracks) == 1 and result.tracks[0]["resultType"] == "song"
    assert result.tracks[0]["videoId"] == "vid-coldplay"
    assert len(result.albums) == 1 and result.albums[0]["resultType"] == "album"
    assert result.albums[0]["browseId"] == "MPREb-coldplay"
    assert result.artists == [] and result.playlists == [] and result.videos == []
    assert sorted(api.client.searches) == ["albums", "songs"]


def test_methods_delegate_to_client(fake_ytmusic):
    """Métodos pontuais delegam para o cliente subjacente."""
    api = YTMusicAPI()
    api.initialize()

    assert api.get_song("X") == {"videoId": "X"}
    assert api.get_stream_url("X") == "https://music.youtube.com/watch?v=X"

    results = api.search("coldplay", filter="songs", limit=3)
    assert results[0]["resultType"] == "song"
    assert results[0]["title"] == "songs-coldplay"


def _client_factory(songs: object, albums: object):
    """Cliente falso que devolve formas controladas por filtro (T08)."""

    class _ShapedClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, query, filter=None, limit=None, ignore_spelling=False):
            return {"songs": songs, "albums": albums}[filter]

    return _ShapedClient


def test_search_catalog_rejects_non_list_songs(monkeypatch):
    """Músicas fora do contrato (dict) → InvalidResponseError (T08 · §10.1)."""
    monkeypatch.setattr(api_module, "YTMusic", _client_factory({"videoId": "x"}, []))
    api = YTMusicAPI()
    assert api.initialize() is True

    with pytest.raises(InvalidResponseError, match="esperado lista, recebido dict"):
        api.search_catalog("q")


def test_search_catalog_rejects_non_list_albums(monkeypatch):
    """Álbuns fora do contrato (None) → InvalidResponseError (T08 · §10.1)."""
    monkeypatch.setattr(api_module, "YTMusic", _client_factory([], None))
    api = YTMusicAPI()
    api.initialize()

    with pytest.raises(InvalidResponseError, match="esperado lista, recebido NoneType"):
        api.search_catalog("q")


def test_search_catalog_rejects_non_dict_item(monkeypatch):
    """Item não-dict na lista → InvalidResponseError (T08 · §10.1)."""
    monkeypatch.setattr(api_module, "YTMusic", _client_factory([{"videoId": "ok"}, "lixo"], []))
    api = YTMusicAPI()
    api.initialize()

    with pytest.raises(InvalidResponseError, match="esperado dict, recebido str"):
        api.search_catalog("q")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
