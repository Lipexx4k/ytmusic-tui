"""Testes de integração — usam a rede de verdade e ficam desabilitados por padrão.

Para rodar (ex.: para conferir se o YouTube Music mudou algo que quebre o app):

    YTMUSIC_INTEGRATION=1 .venv/bin/python -m pytest tests/test_integration.py -v

Eles não entram no CI: existem para checar, quando desejado, se o que os mocks
prometem continua batendo com o serviço real (busca, álbuns e os campos que a
TUI usa — desde o T10-R1, os modelos internos ``video_id``, ``browse_id`` e
``is_available``).
"""

import os

import pytest

from ytmusic_tui.api import ytmusic

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("YTMUSIC_INTEGRATION") != "1",
        reason="integração: defina YTMUSIC_INTEGRATION=1 para rodar (usa a rede)",
    ),
]


def test_search_catalog_real():
    """A busca real devolve músicas e álbuns com os campos que a TUI usa."""
    assert ytmusic.initialize()

    result = ytmusic.search_catalog("my dear melancholy")

    assert result.tracks, "esperava músicas no resultado"
    assert result.albums, "esperava álbuns no resultado"
    assert all(track.video_id for track in result.tracks)
    assert all(album.browse_id for album in result.albums)


def test_get_album_real():
    """Abrir um álbum real devolve faixas tocáveis (como na aba 💿 Álbum)."""
    assert ytmusic.initialize()

    result = ytmusic.search_catalog("my dear melancholy")
    album = next(
        (a for a in result.albums if "Dear Melancholy" in a.title),
        result.albums[0],
    )
    details = ytmusic.get_album(album.browse_id)

    assert details.title
    playable = [track for track in details.tracks if track.video_id and track.is_available]
    assert playable, "esperava faixas disponíveis no álbum"
