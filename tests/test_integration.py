"""Integração real (L3) com monitor de contrato (T10-R6) — opt-in.

Para rodar (ex.: para conferir se o YouTube Music mudou algo que quebre o app):

    YTMUSIC_INTEGRATION=1 .venv/bin/python -m pytest tests/test_integration.py -v -s

O ``-s`` mostra o relatório do contrato (ele também vai na mensagem quando um
teste falha). Cada teste de contrato compara a resposta CRUA do serviço com o
que os adaptadores consomem (``tests/contract.py``) e depois adapta de verdade
(``search_result_from_raws``/``album_detail_from_raw``): mudou o formato? O
relatório diz o quê, por campo e por item — atualize as fixtures do L2 antes
de publicar a correção.

Eles não entram no CI: existem para checar, quando desejado, se o que os
mocks prometem continua batendo com o serviço real (busca, álbuns e os campos
que a TUI usa — desde o T10-R1, os modelos internos ``video_id``,
``browse_id`` e ``is_available``).
"""

import os

import pytest

from tests import contract
from ytmusic_tui.api import ytmusic
from ytmusic_tui.api.adapt import album_detail_from_raw, search_result_from_raws

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("YTMUSIC_INTEGRATION") != "1",
        reason="integração: defina YTMUSIC_INTEGRATION=1 para rodar (usa a rede)",
    ),
]

QUERY = "my dear melancholy"


def _raw_search() -> tuple[list, list]:
    """Resposta crua da busca (sem adaptadores) para o monitor de contrato.

    Usa o cliente do transporte de propósito: o contrato é entre o SERVIÇO e
    os adaptadores — o caminho público (``search_catalog``) já os aplica.
    """
    assert ytmusic.initialize()
    client = ytmusic._require_client()
    songs = client.search(QUERY, filter="songs", limit=10)
    albums = client.search(QUERY, filter="albums", limit=10)
    return songs, albums


def _assert_contract(scope, items, consumed, essential) -> None:
    """Falha com o relatório completo se houver problema de contrato."""
    problems, report = contract.inspect(scope, items, consumed=consumed, essential=essential)
    print("\n" + report)
    assert not problems, f"formato mudou ({scope}) — relatório:\n{report}"


def test_contrato_e_adaptacao_da_busca_real():
    """A busca real devolve o que os adaptadores consomem — e eles adaptam."""
    songs, albums = _raw_search()
    _assert_contract("faixa de busca", songs, contract.CONSUMED_TRACK, contract.ESSENTIAL_TRACK)
    _assert_contract("álbum de busca", albums, contract.CONSUMED_ALBUM, contract.ESSENTIAL_ALBUM)

    result = search_result_from_raws(songs, albums)
    assert result.tracks, "esperava músicas no resultado"
    assert result.albums, "esperava álbuns no resultado"
    assert all(track.video_id for track in result.tracks)
    assert all(album.browse_id for album in result.albums)


def test_contrato_e_adaptacao_do_album_real():
    """Abrir um álbum real devolve faixas tocáveis (como na aba 💿 Álbum)."""
    songs, albums = _raw_search()
    result = search_result_from_raws(songs, albums)
    album = next(
        (item for item in result.albums if "Dear Melancholy" in item.title),
        result.albums[0],
    )

    raw = ytmusic._require_client().get_album(album.browse_id)
    _assert_contract(
        "álbum (detalhe)",
        [raw],
        contract.CONSUMED_ALBUM_DETAIL,
        contract.ESSENTIAL_ALBUM_DETAIL,
    )
    _assert_contract(
        "faixa do álbum",
        raw.get("tracks") or [],
        contract.CONSUMED_TRACK,
        contract.ESSENTIAL_TRACK,
    )

    details = album_detail_from_raw(raw)
    assert details.title
    playable = [track for track in details.tracks if track.video_id and track.is_available]
    assert playable, "esperava faixas disponíveis no álbum"


def test_fluxo_publico_real():
    """Smoke dos caminhos públicos (retry + cache + modelos) com a rede real."""
    result = ytmusic.search_catalog(QUERY)

    assert result.tracks, "esperava músicas no resultado"
    assert result.albums, "esperava álbuns no resultado"
    assert all(track.video_id for track in result.tracks)
    assert all(album.browse_id for album in result.albums)

    album = next(
        (item for item in result.albums if "Dear Melancholy" in item.title),
        result.albums[0],
    )
    details = ytmusic.get_album(album.browse_id)

    assert details.title
    playable = [track for track in details.tracks if track.video_id and track.is_available]
    assert playable, "esperava faixas disponíveis no álbum"
