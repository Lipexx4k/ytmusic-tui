"""Smoke test headless da TUI: navegação entre abas e render da busca."""
import pytest
from textual.widgets import Checkbox, Collapsible, Input, Label, Static, TabbedContent, Tabs

import ytmusic_tui.tui.app as app_module
from ytmusic_tui.api import SearchResult
from ytmusic_tui.player import PlayerEvent, TrackInfo
from ytmusic_tui.tui.app import (
    AlbumListView,
    MainScreen,
    SongListView,
    TrackListView,
    YTMusicTUI,
)


def _song(video_id: str, title: str, artist: str = "Artista") -> dict:
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": artist}],
        "duration": "3:20",
        "duration_seconds": 200,
        "album": {"name": "Álbum Y"},
        "thumbnails": [{"url": "http://example.com/x.jpg"}],
    }


def _album_item(
    browse_id: str = "MPREb1",
    title: str = "Álbum Teste",
    artist: str = "Artista X",
    year: str = "2019",
    kind: str = "Album",
) -> dict:
    return {
        "resultType": "album",
        "browseId": browse_id,
        "title": title,
        "type": kind,
        "year": year,
        "artists": [{"name": artist}],
    }


def _album_details(browse_id: str = "MPREb1") -> dict:
    title, artist = "Álbum Teste", "Artista X"
    return {
        "browseId": browse_id,
        "title": title,
        "type": "Album",
        "year": "2019",
        "trackCount": 2,
        "artists": [{"name": artist}],
        "tracks": [
            {
                "videoId": "t1",
                "title": "Faixa 1",
                "artists": [{"name": artist}],
                "album": title,
                "duration": "3:00",
                "duration_seconds": 180,
                "trackNumber": 1,
                "isAvailable": True,
            },
            {
                "videoId": "t2",
                "title": "Faixa 2",
                "artists": [{"name": artist}],
                "album": title,
                "duration": "4:00",
                "duration_seconds": 240,
                "trackNumber": 2,
                "isAvailable": True,
            },
            {
                "videoId": "t3",
                "title": "Faixa Indisponível",
                "artists": [{"name": artist}],
                "album": title,
                "isAvailable": False,
            },
        ],
    }


@pytest.mark.asyncio
async def test_switch_tabs_and_render_search():
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)
        screen = app.screen

        # Troca por todas as abas principais sem erro
        for tab_id in (
            "tab-search",
            "tab-library",
            "tab-downloads",
            "tab-settings",
            "tab-home",
        ):
            screen.query_one("#main-tabs", TabbedContent).active = tab_id
            await pilot.pause()

        # Renderiza resultados de busca e confere a lista navegável
        screen.query_one("#main-tabs", TabbedContent).active = "tab-search"
        await pilot.pause()

        results = SearchResult(
            tracks=[
                {
                    "videoId": "abc123",
                    "title": "Teste",
                    "artists": [{"name": "Artista X"}],
                    "duration": "3:20",
                    "duration_seconds": 200,
                    "album": {"name": "Álbum Y"},
                    "thumbnails": [{"url": "http://example.com/x.jpg"}],
                }
            ],
            artists=[],
            albums=[],
            playlists=[],
            videos=[],
        )
        screen.display_search_results(results)
        await pilot.pause()

        view = screen.query_one("#search-songs", SongListView)
        assert len(view.songs) == 1
        assert view.songs[0]["videoId"] == "abc123"
        # C1: o item precisa existir de fato no DOM (antes: 0 ListItems)
        assert len(view.children) == 1


@pytest.mark.asyncio
async def test_second_search_does_not_raise_duplicate_ids():
    """Regressão C2: uma segunda busca quebrava com DuplicateIds."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        view = screen.query_one("#search-songs", SongListView)

        screen.display_search_results([_song("v1", "Um")])
        await pilot.pause()
        assert len(view.children) == 1

        screen.display_search_results([_song("v2", "Dois"), _song("v3", "Três")])
        await pilot.pause()
        assert len(view.children) == 2

        # Títulos reais contêm colchetes; não podem ser interpretados como
        # markup do Rich (o texto sumia ou quebrava com MarkupError).
        screen.display_search_results([_song("v4", "Hit [prod. Y] [/b]")])
        await pilot.pause()
        assert len(view.children) == 1
        rendered = str(view.children[0].query_one(Label).render())
        assert "Hit [prod. Y] [/b]" in rendered


@pytest.mark.asyncio
async def test_search_message_accepts_brackets():
    """Mensagens de erro da busca podem conter [colchetes]."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen._render_search_message("Erro na busca: [Errno 5] falha de rede")
        await pilot.pause()
        message = screen.query_one("#search-message", Static)
        assert message.display is True
        assert screen.query_one("#search-songs").display is False


@pytest.mark.asyncio
async def test_search_shows_albums_with_type_marker(monkeypatch):
    """A busca exibe álbuns junto das músicas, marcados com tipo e ano."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen

        monkeypatch.setattr(
            app_module.ytmusic,
            "search_catalog",
            lambda *args, **kwargs: SearchResult(
                tracks=[_song("v1", "Música")],
                artists=[],
                albums=[_album_item()],
                playlists=[],
                videos=[],
            ),
        )

        await screen.perform_search("album teste")
        await pilot.pause()

        albums = screen.query_one("#search-albums", AlbumListView)
        songs = screen.query_one("#search-songs", SongListView)
        assert songs.display and len(songs.songs) == 1
        assert albums.display and len(albums.albums) == 1
        assert screen.query_one("#search-albums-title", Static).display

        label = str(albums.children[0].query_one(Label).render())
        assert "Álbum Teste" in label
        assert "Album" in label and "2019" in label  # marcador do tipo

        # Sem álbuns, a seção some e a lista de músicas ocupa o espaço
        screen.display_search_results(
            SearchResult(tracks=[_song("v2", "Só música")], artists=[], albums=[],
                         playlists=[], videos=[])
        )
        await pilot.pause()
        assert not albums.display
        assert songs.display and len(songs.songs) == 1


@pytest.mark.asyncio
async def test_selecting_album_opens_tab_with_tracks(monkeypatch):
    """Enter num álbum abre a aba 💿 Álbum com artista e faixas; Esc volta."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        tabs = screen.query_one("#main-tabs", TabbedContent)

        monkeypatch.setattr(
            app_module.ytmusic,
            "search_catalog",
            lambda *args, **kwargs: SearchResult(
                tracks=[], artists=[], albums=[_album_item()], playlists=[], videos=[]
            ),
        )
        monkeypatch.setattr(app_module.ytmusic, "get_album", _album_details)

        await screen.perform_search("album teste")
        await pilot.pause()

        albums = screen.query_one("#search-albums", AlbumListView)
        albums.focus()
        albums.index = 0
        await pilot.press("enter")

        for _ in range(100):
            await pilot.pause(0.02)
            if screen._current_album is not None:
                break

        assert tabs.active == "tab-album"
        view = screen.query_one("#album-songs", SongListView)
        assert view.display
        # Faixa indisponível é filtrada
        assert [t["videoId"] for t in view.songs] == ["t1", "t2"]

        header = str(screen.query_one("#album-header", Static).render())
        assert "Álbum Teste" in header
        assert "Artista X" in header
        assert "2 faixas" in header

        # Esc na aba de álbum volta para a busca
        await pilot.press("escape")
        await pilot.pause()
        assert tabs.active == "tab-search"


@pytest.mark.asyncio
async def test_focusing_list_highlights_first_item_for_enter(monkeypatch):
    """Tab numa lista deve destacar o primeiro item para o Enter funcionar.

    Regressão: ao ganhar foco pelo teclado, o ``ListView`` ficava com
    ``index=None`` e o Enter não selecionava nada.
    """
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        monkeypatch.setattr(
            app_module.ytmusic,
            "search_catalog",
            lambda *args, **kwargs: SearchResult(
                tracks=[_song("v1", "Música 1")],
                artists=[],
                albums=[_album_item()],
                playlists=[],
                videos=[],
            ),
        )
        monkeypatch.setattr(app_module.ytmusic, "get_album", _album_details)
        await screen.perform_search("álbum teste")
        await pilot.pause()

        screen.query_one("#search-input", Input).focus()
        await pilot.pause()
        await pilot.press("tab")
        songs = screen.focused
        assert isinstance(songs, SongListView)
        assert songs.index == 0
        await pilot.press("tab")
        albums = screen.focused
        assert isinstance(albums, AlbumListView)
        assert albums.index == 0

        # Enter abre o álbum destacado (sem clique nem ↓ antes)
        await pilot.press("enter")
        for _ in range(100):
            await pilot.pause(0.02)
            if screen._current_album is not None:
                break
        assert screen.query_one("#main-tabs", TabbedContent).active == "tab-album"
        assert screen._current_album is not None


@pytest.mark.asyncio
async def test_clicking_album_result_opens_album(monkeypatch):
    """Clique do mouse num resultado de álbum abre a aba 💿 Álbum."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        monkeypatch.setattr(
            app_module.ytmusic,
            "search_catalog",
            lambda *args, **kwargs: SearchResult(
                tracks=[], artists=[], albums=[_album_item()], playlists=[], videos=[]
            ),
        )
        monkeypatch.setattr(app_module.ytmusic, "get_album", _album_details)
        await screen.perform_search("álbum teste")
        await pilot.pause()

        # Muda para a aba de busca: painéis ocultos não têm geometria
        # (region 0x0) e o clique do mouse cairia na posição errada.
        screen._switch_tab("tab-search")
        await pilot.pause()

        albums = screen.query_one("#search-albums", AlbumListView)
        item = albums.children[0]
        assert item.region.width > 0  # item realmente na tela
        await pilot.click(offset=(item.region.x + 2, item.region.y))

        for _ in range(100):
            await pilot.pause(0.02)
            if screen._current_album is not None:
                break
        assert screen.query_one("#main-tabs", TabbedContent).active == "tab-album"
        assert screen._current_album is not None
        assert len(screen.query_one("#album-songs", SongListView).songs) == 2


@pytest.mark.asyncio
async def test_keyboard_tab_switch_with_focus_inside_album_pane(monkeypatch):
    """Trocar de aba (Ctrl+L/Ctrl+S) com o foco dentro do painel do álbum.

    Regressão: ao esconder o painel com foco, o Textual transfere o foco para
    outro widget do mesmo painel, que reativa a aba via TabPane.Focused —
    a troca se desfazia (aba ficava presa no álbum).
    """
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        tabs = screen.query_one("#main-tabs", TabbedContent)

        screen.display_album(_album_details())
        screen._switch_tab("tab-album")
        screen.query_one("#album-songs", SongListView).focus()
        await pilot.pause()
        assert tabs.active == "tab-album"

        # Ctrl+L com o foco dentro do painel do álbum
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert tabs.active == "tab-library"

        # E de novo de volta ao álbum (com foco na lista) + Ctrl+S
        tabs.active = "tab-album"
        await pilot.pause()
        screen.query_one("#album-songs", SongListView).focus()
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert tabs.active == "tab-search"


@pytest.mark.asyncio
async def test_album_tab_hidden_until_first_album(monkeypatch):
    """A aba 💿 Álbum fica oculta até algo ser aberto; o rótulo vira o nome."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        tabs = app.screen.query_one("#main-tabs", TabbedContent)
        assert "-hidden" in tabs.get_tab("tab-album").classes

        app.screen.display_album(_album_details())
        await pilot.pause()
        tab = tabs.get_tab("tab-album")
        assert "-hidden" not in tab.classes
        assert "Álbum Teste" in tab.label_text


@pytest.mark.asyncio
async def test_download_album_queues_tracks_and_skips_downloaded(monkeypatch):
    """Botão e tecla "a" baixam o álbum inteiro; o que já foi baixado é pulado."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen

        queued: list[dict] = []
        monkeypatch.setattr(app_module.library, "ensure_track", lambda **kwargs: 1)
        monkeypatch.setattr(app_module.library, "get_track_by_source_id", lambda video_id: None)
        monkeypatch.setattr(
            app_module.download_manager,
            "queue_download",
            lambda **kwargs: queued.append(kwargs) or object(),
        )

        async def _noop(task):  # noqa: ANN001 - worker fake
            return None

        monkeypatch.setattr(screen, "_run_download", _noop)
        toasts: list[str] = []
        monkeypatch.setattr(screen, "_toast", toasts.append)

        screen.display_album(_album_details())
        screen.query_one("#main-tabs", TabbedContent).active = "tab-album"
        await pilot.pause()

        # Botão "Baixar álbum inteiro"
        await pilot.click("#btn-download-album")
        await pilot.pause()
        assert [q["video_id"] for q in queued] == ["t1", "t2"]
        assert all(q["album"] == "Álbum Teste" for q in queued)
        assert any("2 faixa(s) enfileirada(s)" in t for t in toasts)

        # Tecla "a" (com foco na lista, fora de um Input), pulando a t1
        class _Downloaded:
            is_downloaded = True

        monkeypatch.setattr(
            app_module.library,
            "get_track_by_source_id",
            lambda video_id: _Downloaded() if video_id == "t1" else None,
        )
        queued.clear()
        screen.query_one("#album-songs", SongListView).focus()
        await pilot.press("a")
        await pilot.pause()
        assert [q["video_id"] for q in queued] == ["t2"]
        assert any("1 já baixada(s)" in t for t in toasts)

        # Sem álbum aberto: avisa e não enfileira nada
        queued.clear()
        screen._current_album = None
        await pilot.press("a")
        await pilot.pause()
        assert queued == []
        assert any("Nenhum álbum aberto" in t for t in toasts)


@pytest.mark.asyncio
async def test_library_refresh_twice_with_tracks(monkeypatch):
    """Regressão: atualizar a biblioteca duas vezes criava DuplicateIds."""

    class _FakeTrack:
        id = 1
        source_id = "vid1"
        title = "Faixa [ao vivo]"
        artist_names = ["Artista"]
        is_downloaded = False
        local_path = None
        album = None

    class _FakeLibrary:
        def get_recent_tracks(self, limit=500):
            return [_FakeTrack(), _FakeTrack()]

    monkeypatch.setattr(app_module, "library", _FakeLibrary())
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, MainScreen)

        screen.refresh_library()
        await pilot.pause()
        screen.refresh_library()
        await pilot.pause()

        view = screen.query_one("#library-list", TrackListView)
        assert len(view.children) == 2
        assert view.display  # lista visível
        assert not screen.query_one("#library-message", Static).display


def test_bindings_resolve_to_actions():
    """Todo atalho anunciado deve ter uma action correspondente."""
    for binding in MainScreen.BINDINGS:
        action = f"action_{binding.action}"
        assert hasattr(MainScreen, action) or hasattr(YTMusicTUI, action), binding.key


@pytest.mark.asyncio
async def test_queue_next_previous_and_auto_play(monkeypatch):
    """Regressão C4: next/previous/track_ended devem mover a fila tocada."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen

        played: list[TrackInfo] = []

        def _fake_play(info: TrackInfo) -> bool:
            played.append(info)
            return True

        monkeypatch.setattr(app_module.player, "play", _fake_play)

        screen._play_queue = [TrackInfo(video_id=str(i), title=f"F{i}") for i in range(3)]
        screen._play_index = 0

        assert screen._play_relative(1) is True
        assert played[-1].video_id == "1"
        assert screen._play_relative(1) is True
        assert screen._play_relative(1) is False  # fim da fila
        assert screen._play_relative(-1) is True
        assert played[-1].video_id == "1"

        # Evento "next" emitido pelo player (atalho/botão) avança a fila
        app._on_player_event(PlayerEvent(event="next", data={}))
        assert played[-1].video_id == "2"

        # Fim da faixa (eof) com auto-play ligado
        screen._play_index = 0
        screen._last_auto_next = 0.0
        app._on_player_event(PlayerEvent(event="track_ended", data={}))
        assert played[-1].video_id == "1"

        # Debounce: "ended"/"track_ended" duplicado não avança de novo
        count = len(played)
        app._on_player_event(PlayerEvent(event="track_ended", data={}))
        assert len(played) == count


@pytest.mark.asyncio
async def test_settings_inputs_apply(monkeypatch, tmp_path):
    """Campos da aba Config devem aplicar e persistir (antes: decorativos)."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen

        saved: dict = {}
        monkeypatch.setattr(
            type(app_module.settings),
            "update_and_save",
            lambda self, **kwargs: saved.update(kwargs),
        )

        screen._apply_text_setting("setting-volume", "30")
        assert saved["mpv_volume"] == 30

        screen._apply_text_setting("setting-concurrent", "2")
        assert saved["download_concurrent"] == 2

        target = tmp_path / "downloads"
        screen._apply_text_setting("setting-download-dir", str(target))
        assert saved["download_dir"] == target
        assert target.exists()

        # Valor inválido não quebra a UI
        saved.clear()
        screen._apply_text_setting("setting-volume", "abc")
        assert "mpv_volume" not in saved


@pytest.mark.asyncio
async def test_config_tab_widgets_apply_on_interaction(monkeypatch):
    """Wiring real: Enter no input de volume e toggle do checkbox salvam."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen.query_one("#main-tabs", TabbedContent).active = "tab-settings"
        await pilot.pause()

        saved: dict = {}
        monkeypatch.setattr(
            type(app_module.settings),
            "update_and_save",
            lambda self, **kwargs: saved.update(kwargs),
        )

        volume = screen.query_one("#setting-volume", Input)
        volume.query_ancestor(Collapsible).collapsed = False
        await pilot.pause()
        volume.focus()
        volume.value = "35"
        await pilot.press("enter")
        await pilot.pause()
        assert saved.get("mpv_volume") == 35

        autoplay = screen.query_one("#setting-autoplay", Checkbox)
        autoplay.value = not autoplay.value
        await pilot.pause()
        assert "auto_play_next" in saved


@pytest.mark.asyncio
async def test_app_starts_directly_on_main_screen():
    """Sem login, o app deve abrir direto na tela principal, sem modal de login."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)
        # Topo da pilha é a MainScreen (a base _default fica abaixo)
        assert app.screen is app.screen_stack[-1]


@pytest.mark.asyncio
async def test_quit_does_not_hang():
    """Regressão: shutdown do download manager bloqueava o Ctrl+Q."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+q")
        await pilot.pause()
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_tabs_are_clickable_with_mouse():
    """Regressão: a regra catch-all `*:focus { border: ... }` do app.tcss dava
    borda ao `Tabs` quando ele ganhava foco com o clique; a borda estourava as
    2 linhas internas (rótulos + underline), o Underline caía por baixo do
    TabPane e as abas ficavam inalcançáveis ("barra azul sobrepondo o menu")."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        tabbed = screen.query_one("#main-tabs", TabbedContent)
        tabs = tabbed.query_one(Tabs)

        labels_row = tabs.query("Tab").first().region.y
        underline = tabs.query_one("Underline")
        underline_before = underline.region
        # O underline deve ficar imediatamente abaixo dos rótulos
        assert underline_before.y == labels_row + 1

        for tab_id, fragment in (
            ("tab-library", "Biblioteca"),
            ("tab-downloads", "Downloads"),
            ("tab-home", "Início"),
        ):
            tab = [t for t in tabs.query("Tab") if t.id and tab_id in t.id][0]
            await pilot.click(offset=(tab.region.x + 2, labels_row))
            await pilot.pause()
            assert tabbed.active == tab_id, fragment

        # Nenhum clique pode ter deformado a geometria das abas
        assert tabs.query_one("Underline").region == underline_before


@pytest.mark.asyncio
async def test_ctrl_d_downloads_even_with_search_input_focused(monkeypatch):
    """Regressão: o `Input` do Textual captura `ctrl+d` (`delete_right`); o
    binding de download precisa de `priority` para disparar mesmo com o foco
    na busca (era o caso de uso real: buscar → tocar → Ctrl+D)."""
    app = YTMusicTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen

        # Pipeline de download de verdade, mas sem rede/banco
        monkeypatch.setattr(app_module.library, "ensure_track", lambda **kwargs: 1)
        queued: list[dict] = []
        monkeypatch.setattr(
            app_module.download_manager,
            "queue_download",
            lambda **kwargs: queued.append(kwargs) or object(),
        )

        async def _noop(task):  # noqa: ANN001 - worker fake
            return None

        monkeypatch.setattr(screen, "_run_download", _noop)
        toasts: list[str] = []
        monkeypatch.setattr(screen, "_toast", toasts.append)

        monkeypatch.setattr(
            app_module.player,
            "_current_track",
            TrackInfo(video_id="abc123", title="Faixa", artist="Artista"),
        )

        search = screen.query_one("#search-input", Input)
        search.focus()
        search.value = "abc"
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        assert len(queued) == 1
        assert queued[0]["video_id"] == "abc123"
        assert any("Iniciando download" in msg for msg in toasts)
        # O atalho tem prioridade: o Input não deve apagar caractere algum
        assert search.value == "abc"

        # Sem faixa em reprodução: avisa em vez de ignorar em silêncio
        monkeypatch.setattr(app_module.player, "_current_track", None)
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert len(queued) == 1
        assert "Nenhuma faixa em reprodução" in toasts


if __name__ == "__main__":
    pytest.main([__file__, "-v"])