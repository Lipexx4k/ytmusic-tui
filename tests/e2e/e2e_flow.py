"""Fluxo ponta a ponta real (L4) — roteiro do ``test_e2e.py`` (opt-in).

Não é um teste: o ``test_e2e.py`` roda este roteiro com o ``venv/bin/python``
do ambiente LIMPO instalado a partir do wheel — o ponto do L4 é provar o
artefato instalado, não o código-fonte. Também dá para rodar à mão num venv
instalado (ver ``tests/e2e/README.md``); sem isolar os ``YTMUSIC_*``, ele usa
os dados reais do usuário — cuidado.

Fluxo coberto (os mesmos caminhos que a TUI usa, por baixo dela):

1. busca real (``search_catalog``) e escolha de uma faixa tocável;
2. álbum real (``get_album``) e escolha de faixa tocável;
3. player real (mpv) — o critério é o STREAM ter carregado (evento
   ``duration``/``position``), não áudio audível;
4. download real (yt-dlp + ffmpeg) via ``DownloadManager``;
5. arquivo publicado válido + linha da faixa na biblioteca local.

Saída: progresso em pt-BR no stdout (o pytest mostra com ``-s``) e, no fim,
uma linha ``[e2e-json] {...}`` com os ids/caminhos — o teste usa de
evidência. Exit code 0 = fluxo completo; qualquer verificação falhando =
traceback e exit 1.
"""

import asyncio
import json
import os
import sys
import time

from ytmusic_tui.api import ytmusic
from ytmusic_tui.config import settings
from ytmusic_tui.download import download_manager
from ytmusic_tui.download.pipeline import validate_media_file
from ytmusic_tui.library import db_manager, library
from ytmusic_tui.player import TrackInfo, player

QUERY = os.environ.get("YTMUSIC_E2E_QUERY", "my dear melancholy")

#: Teto para o stream carregar no mpv (o yt-dlp do hook resolve dentro dele).
PLAYER_TIMEOUT = 60.0


def _passo(nome: str) -> None:
    print(f"[e2e] {nome}", flush=True)


def main() -> int:
    resumo: dict = {"query": QUERY, "download_dir": str(settings.download_dir)}

    _passo("migração da biblioteca local (isolada em tmp)")
    db_manager.migrate()

    _passo(f"busca real: {QUERY!r}")
    assert ytmusic.initialize(), f"cliente ytmusicapi não inicializou: {ytmusic.last_error}"
    resultado = ytmusic.search_catalog(QUERY)
    assert resultado.tracks, "a busca não devolveu músicas"
    faixa_busca = next((t for t in resultado.tracks if t.video_id and t.is_available), None)
    assert faixa_busca is not None, "nenhuma música tocável nos resultados"
    resumo["busca"] = {"titulo": faixa_busca.title, "video_id": faixa_busca.video_id}

    _passo("álbum real (detalhe e faixas tocáveis)")
    album = next((a for a in resultado.albums if a.browse_id), None)
    assert album is not None, "a busca não devolveu álbuns"
    detalhe = ytmusic.get_album(album.browse_id)
    tocaveis = [t for t in detalhe.tracks if t.video_id and t.is_available]
    assert tocaveis, "o álbum não tem faixas tocáveis"
    alvo = tocaveis[0]
    resumo["album"] = {
        "browse_id": album.browse_id,
        "titulo": detalhe.title,
        "faixas": len(detalhe.tracks),
    }

    _passo("player real (mpv) — sem exigir áudio audível")
    eventos: list[str] = []
    erros: list[str] = []

    def _observar(evento) -> None:
        eventos.append(evento.event)
        if evento.event == "error":
            erros.append(str(evento.data.get("message") or "erro sem detalhe"))

    player.on_event(_observar)
    assert player.start(), "player.start() falhou"
    fonte = ytmusic.get_stream_url(alvo.video_id)
    tocando = player.play(
        TrackInfo(
            video_id=alvo.video_id,
            title=alvo.title,
            artist=", ".join(alvo.artists),
            album=alvo.album_name,
            duration=float(alvo.duration_seconds or 0),
            thumbnail_url=alvo.thumbnail_url,
            source_url=fonte,
        )
    )
    assert tocando, f"player.play() recusou a faixa (eventos: {eventos[-4:]})"
    limite = time.monotonic() + PLAYER_TIMEOUT
    while time.monotonic() < limite:
        if erros or "duration" in eventos or "position" in eventos:
            break
        time.sleep(0.2)
    estado_final = player.state.value
    player.shutdown()  # antes dos asserts: o handle do mpv não sobrevive à falha
    assert not erros, f"o player falhou: {erros[-1]}"
    assert "duration" in eventos or "position" in eventos, (
        f"o stream não carregou em {PLAYER_TIMEOUT:.0f}s (eventos: {eventos[-6:]})"
    )
    resumo["player"] = {"estado_final": estado_final, "eventos": eventos[-6:]}

    _passo("download real (yt-dlp + ffmpeg)")
    tarefa = download_manager.queue_download(
        video_id=alvo.video_id,
        title=alvo.title,
        artist=", ".join(alvo.artists),
        album=alvo.album_name,
        thumbnail_url=alvo.thumbnail_url,
    )
    tarefa = asyncio.run(download_manager.download(tarefa))
    assert tarefa.status.value == "completed", (
        f"download terminou como {tarefa.status.value}: {tarefa.error or 'sem detalhe'}"
    )
    arquivo = tarefa.file_path
    assert arquivo is not None and arquivo.is_file(), f"arquivo final ausente: {arquivo}"
    validate_media_file(arquivo, arquivo.suffix.lstrip("."))
    resumo["download"] = {
        "status": tarefa.status.value,
        "arquivo": str(arquivo),
        "bytes": arquivo.stat().st_size,
    }

    _passo("linha na biblioteca local")
    linha = library.get_track_by_source_id(alvo.video_id)
    assert linha is not None, "a faixa não foi registrada na biblioteca"
    assert linha.is_downloaded, "a faixa consta na biblioteca, mas sem arquivo"
    resumo["biblioteca"] = {"track_id": linha.id, "caminho": str(linha.local_path)}

    download_manager.shutdown()
    _passo("fluxo completo")
    print("[e2e-json] " + json.dumps(resumo, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
