"""Processos e limites de rede (§8.2/§8.4 · R1/R2): sem shell, sem travamento.

Checklist coberta aqui:

- R1: ``src/`` sem shell=True, ``os.system``/``os.popen``/``os.exec*``/
  ``os.spawn*``/``pty.spawn`` e sem lançar processos externos — guarda
  estática por AST, restrita a src/, com controles positivos (cada padrão
  proibido é realmente pego) e negativo (menção em string/comentário não é
  falso positivo);
- R2: as opções do yt-dlp carregam limites reais de rede (constantes
  documentadas 30/3/3, sem configuração de usuário) e um socket que estola
  NÃO trava o worker para sempre: o download falha com erro claro, o
  temporário do pipeline é limpo e nada é publicado;
- "processo com código de erro" (DownloadError) e crash inesperado do
  downloader → FAILED com mensagem, nunca exceção vazando nem parcial
  publicado (INV-1);
- yt-dlp/ffmpeg ausentes → erro de dependência claro ANTES de reservar,
  sem crash e sem sobras.
"""

import ast
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

import ytmusic_tui.download as download_mod
from tests.security._fakes import FakeDownloadError, FakeYoutubeDL
from ytmusic_tui.download import DownloadStatus, DownloadTask

SRC_DIR = Path(__file__).resolve().parents[2] / "src"

#: Lançadores de processo proibidos por módulo (R1): a decisão do projeto é
#: consumir yt-dlp/mpv como biblioteca; se um dia for preciso lançar um
#: processo, a guarda obriga uma decisão consciente (mudar o teste), com
#: ``shell=False`` e ``timeout``.
_FORBIDDEN_LAUNCHERS = {
    "subprocess": {
        "Popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
    },
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}


def _forbidden_in_tree(tree: ast.AST) -> list[str]:
    """Padrões proibidos da R1 num módulo já parseado (AST, não regex)."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in ("pty", "subprocess"):
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in ("pty", "subprocess"):
                found.append(f"from {node.module} import ...")
            elif root == "os":
                for alias in node.names:
                    if alias.name in ("system", "popen") or alias.name.startswith(
                        ("exec", "spawn")
                    ):
                        found.append(f"from os import {alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                module, attr = func.value.id, func.attr
                if module == "os" and (
                    attr in ("system", "popen") or attr.startswith(("exec", "spawn"))
                ):
                    found.append(f"os.{attr}")
                if module == "pty" and attr.startswith("spawn"):
                    found.append(f"pty.{attr}")
                if attr in _FORBIDDEN_LAUNCHERS.get(module, set()):
                    found.append(f"{module}.{attr}")
            for keyword in node.keywords:
                # shell=True em QUALQUER chamada (pega import com alias).
                if (
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    found.append("shell=True")
    return found


def _scan_forbidden_processes(paths: list[Path]) -> list[str]:
    """Varre arquivos ``.py`` e devolve violações no formato ``arquivo: padrão``."""
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(f"{path}: {pattern}" for pattern in _forbidden_in_tree(tree))
    return violations


def test_src_uses_no_shell_exec_or_pty():
    """R1 (§8.2): o código de produção não lança processos externos.

    A varredura é restrita a ``src/`` (testes podem usar subprocess quando
    fizer sentido); o mínimo de arquivos barra um falso verde por diretório
    errado.
    """
    sources = sorted(SRC_DIR.rglob("*.py"))
    assert len(sources) >= 10, "varredura vazia não prova nada"

    assert _scan_forbidden_processes(sources) == []


def test_guard_flags_every_forbidden_pattern(tmp_path):
    """Controle positivo: cada padrão da lista proibida é realmente pego."""
    samples = {
        "shell_true.py": "import subprocess\nsubprocess.run(['ls'], shell=True)\n",
        "popen.py": "import subprocess\nsubprocess.Popen(['ls'])\n",
        "os_system.py": "import os\nos.system('ls')\n",
        "os_popen.py": "import os\nos.popen('ls')\n",
        "os_exec.py": "import os\nos.execv('/bin/ls', ['ls'])\n",
        "os_spawn.py": "import os\nos.spawnl(os.P_NOWAIT, '/bin/ls')\n",
        "pty_spawn.py": "import pty\npty.spawn('/bin/sh')\n",
        "from_subprocess.py": "from subprocess import run\nrun(['ls'])\n",
        "from_os.py": "from os import system\nsystem('ls')\n",
        "asyncio_shell.py": "import asyncio\nasyncio.create_subprocess_shell('ls')\n",
    }
    for name, source in samples.items():
        path = tmp_path / name
        path.write_text(source)
        assert _scan_forbidden_processes([path]), f"o scan não pegou {name}"


def test_guard_has_no_false_positive_on_mentions(tmp_path):
    """Controle negativo: menção em string/comentário e código comum passam."""
    source = (
        '"""Decisão: nada de subprocess.run(..., shell=True) — ver §8.2."""\n'
        "# os.system e pty.spawn também estão fora (comentário não é código)\n"
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def caminho() -> Path:\n"
        "    return Path(os.sep) / 'musicas'\n"
        "\n"
        "\n"
        "TEXTO = 'shell=True'\n"
    )
    path = tmp_path / "benigno.py"
    path.write_text(source)

    assert _scan_forbidden_processes([path]) == []


def test_ydl_options_carry_the_documented_network_limits(security_env):
    """R2: as opções levam timeouts/retries finitos (contrato congelado)."""
    env = security_env
    opts = env.manager._get_ydl_options(DownloadTask(video_id="v"))

    assert (
        download_mod.YDL_SOCKET_TIMEOUT,
        download_mod.YDL_RETRIES,
        download_mod.YDL_FRAGMENT_RETRIES,
    ) == (30, 3, 3)
    assert opts["socket_timeout"] == download_mod.YDL_SOCKET_TIMEOUT
    assert opts["retries"] == download_mod.YDL_RETRIES
    assert opts["fragment_retries"] == download_mod.YDL_FRAGMENT_RETRIES


def test_network_limits_are_code_constants_not_user_config():
    """Aprovado no T06: limites são decisão de código, sem campo de config."""
    from ytmusic_tui.config import Settings

    assert {"socket_timeout", "retries", "fragment_retries"}.isdisjoint(Settings.model_fields)


@pytest.fixture
def stalling_server():
    """Socket local que aceita conexões e NUNCA responde (estol de rede)."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    server.settimeout(0.2)
    held: list[socket.socket] = []
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            held.append(conn)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield server.getsockname()[1]
    finally:
        stop.set()
        server.close()
        for conn in held:
            conn.close()
        worker.join(timeout=2)


def test_stalled_network_is_bounded_and_fails_cleanly(security_env, monkeypatch, stalling_server):
    """R2/§8.4: servidor que estola não prende o worker para sempre.

    Usa o yt-dlp REAL contra um socket local que aceita e não responde; as
    constantes são reduzidas para o teste ficar rápido (o contrato 30/3/3 é
    congelado no teste acima). Critério da checklist: erro claro, temporário
    do pipeline limpo e nada publicado.
    """
    yt_dlp = pytest.importorskip("yt_dlp")
    env = security_env
    monkeypatch.setattr(download_mod, "_load_yt_dlp", lambda: yt_dlp)
    monkeypatch.setattr(download_mod, "YDL_SOCKET_TIMEOUT", 2)
    monkeypatch.setattr(download_mod, "YDL_RETRIES", 1)
    monkeypatch.setattr(download_mod, "YDL_FRAGMENT_RETRIES", 1)
    monkeypatch.setattr(
        download_mod,
        "WATCH_URL",
        f"http://127.0.0.1:{stalling_server}/audio",
    )

    task = env.manager.queue_download(video_id="v", title="T", artist="A", album="Alb")

    started = time.monotonic()
    result = env.manager._download_task(task)
    elapsed = time.monotonic() - started

    assert result.status is DownloadStatus.FAILED
    assert result.error is not None
    message = result.error.lower()
    assert "timed out" in message or "timeout" in message
    # Limite superior folgado: ~2s × poucas tentativas (não 30s+ nem infinito).
    assert elapsed < 20
    assert not list(env.download_dir.rglob("*.mp3"))  # nada publicado
    temp_dir = env.download_dir / ".tmp"
    assert not temp_dir.exists() or list(temp_dir.iterdir()) == []  # sem sobras


def test_real_libmpv_lifecycle_leaves_no_process_behind(monkeypatch):
    """R3: com libmpv de verdade, start/shutdown não deixam processo para trás.

    O app usa libmpv EM PROCESSO (não o binário ``mpv``); o único processo
    que o player pode lançar é o yt-dlp do hook ytdl, e só ao tocar stream.
    O teste cria e encerra o handle duas vezes (prova o reinício) e exige
    que nenhum processo novo com "mpv"/"yt-dlp" no cmdline apareça.
    """
    pytest.importorskip("mpv")
    if sys.platform != "linux":
        pytest.skip("varredura de /proc exige Linux")

    from ytmusic_tui.player import MPVPlayer

    player_mod = sys.modules["ytmusic_tui.player"]
    monkeypatch.setattr(player_mod.settings, "mpv_volume", 20)
    monkeypatch.setattr(player_mod.settings, "mpv_audio_quality", "low")
    monkeypatch.setattr(MPVPlayer, "_find_yt_dlp", staticmethod(lambda: None))

    def snapshot() -> set[str]:
        found: set[str] = set()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_text(errors="ignore")
            except OSError:
                continue
            if "mpv" in cmdline or "yt-dlp" in cmdline:
                found.add(entry.name)
        return found

    before = snapshot()
    player = MPVPlayer()
    try:
        if not player.start():
            pytest.skip("libmpv indisponível neste ambiente")
        assert player._mpv is not None

        player.shutdown()
        assert player._mpv is None

        assert player.start() is True  # reinício após shutdown (R3)
        assert player._mpv is not None
    finally:
        player.shutdown()

    assert snapshot() - before == set()


def test_download_error_midway_fails_cleanly_without_partial(make_security_env, tmp_path):
    """ "Processo com código de erro": DownloadError → FAILED, sem parcial.

    O yt-dlp real escreveria um ``.part`` no temporário antes de estourar;
    o pipeline libera a reserva e NUNCA publica parcial (INV-1).
    """

    class _FailMidway(FakeYoutubeDL):
        def download(self, urls: list[str]) -> None:
            template = self.opts["outtmpl"]
            partial = Path(template.replace("%(ext)s", "mp3"))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"parcial")
            raise FakeDownloadError("queda de rede no meio do stream")

    download_dir = tmp_path / "library"
    env = make_security_env(download_dir, ydl_cls=_FailMidway)
    task = env.manager.queue_download(video_id="v", title="T", artist="A", album="Alb")

    result = env.manager._download_task(task)

    assert result.status is DownloadStatus.FAILED
    assert result.error is not None and "queda de rede" in result.error
    assert not list(download_dir.rglob("*.mp3"))  # nada publicado
    temp_dir = download_dir / ".tmp"
    assert not temp_dir.exists() or list(temp_dir.iterdir()) == []  # sem parcial


def test_unexpected_downloader_crash_does_not_leak_or_crash(make_security_env, tmp_path):
    """Crash inesperado do downloader também vira FAILED claro (sem vazar)."""

    class _Explode(FakeYoutubeDL):
        def download(self, urls: list[str]) -> None:
            raise RuntimeError("bug interno do downloader")

    download_dir = tmp_path / "library"
    env = make_security_env(download_dir, ydl_cls=_Explode)
    task = env.manager.queue_download(video_id="v", title="T", artist="A", album="Alb")

    result = env.manager._download_task(task)

    assert result.status is DownloadStatus.FAILED
    assert result.error is not None and "Erro inesperado" in result.error
    assert not list(download_dir.rglob("*.mp3"))
    temp_dir = download_dir / ".tmp"
    assert not temp_dir.exists() or list(temp_dir.iterdir()) == []


def test_missing_yt_dlp_is_a_clear_failure_not_a_crash(security_env, monkeypatch):
    """§8.4: yt-dlp ausente do ambiente → erro de dependência claro."""
    env = security_env

    def _explode() -> None:
        raise ImportError("No module named 'yt_dlp'")

    monkeypatch.setattr(download_mod, "_load_yt_dlp", _explode)
    task = env.manager.queue_download(video_id="v", title="T", artist="A", album="Alb")

    result = env.manager._download_task(task)

    assert result.status is DownloadStatus.FAILED
    assert result.error is not None
    assert "yt-dlp não está instalado" in result.error
    assert "pip install yt-dlp" in result.error
    # Falhou ANTES de reservar: nenhuma sobra e nada publicado.
    assert not (env.download_dir / ".tmp").exists()
    assert not list(env.download_dir.rglob("*.mp3"))


def test_missing_ffmpeg_is_a_clear_failure_not_a_crash(security_env, monkeypatch):
    """§8.4: ffmpeg ausente do PATH → erro de dependência claro."""
    env = security_env
    monkeypatch.setattr(download_mod, "_which_ffmpeg", lambda: None)

    task = env.manager.queue_download(video_id="v", title="T", artist="A", album="Alb")
    result = env.manager._download_task(task)

    assert result.status is DownloadStatus.FAILED
    assert result.error is not None and "ffmpeg" in result.error
    assert not (env.download_dir / ".tmp").exists()


def test_existing_file_is_adopted_even_without_dependencies(security_env, monkeypatch):
    """Adotar arquivo existente (Q2(a)) não baixa: não exige yt-dlp/ffmpeg."""
    env = security_env
    first = env.manager.queue_download(video_id="v1", title="T", artist="A", album="Alb")
    assert env.manager._download_task(first).status is DownloadStatus.COMPLETED

    monkeypatch.setattr(download_mod, "_which_ffmpeg", lambda: None)

    def _explode() -> None:
        raise ImportError("No module named 'yt_dlp'")

    monkeypatch.setattr(download_mod, "_load_yt_dlp", _explode)
    second = env.manager.queue_download(video_id="v2", title="T", artist="A", album="Alb")
    result = env.manager._download_task(second)

    assert result.status is DownloadStatus.COMPLETED
    assert result.file_path == first.file_path
