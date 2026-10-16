"""App morto durante o download (T08 · §10.1): SIGKILL real + recuperação.

A L1 simula a morte semeando a linha e os órfãos; aqui um PROCESSO de
verdade baixa (worker real, stub lento) e leva SIGKILL no meio — a linha
fica RUNNING, o lock e o parcial ficam no disco sem dono. A sessão
seguinte recupera pelo caminho REAL do worker: ``recover_interrupted`` →
INTERRUPTED; ``retry_interrupted`` descarta os órfãos e completa.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time

import ytmusic_tui.download as download_mod
from tests.integration_local._fakes import install_fake_ffmpeg, install_settings, install_yt_dlp
from ytmusic_tui.download import DownloadStatus
from ytmusic_tui.download.store import DownloadTaskStore
from ytmusic_tui.library.database import DatabaseManager

#: Script do filho: baixa devagar (teto de 60 s) até o pai matar com SIGKILL.
#: Pina as settings no próprio processo — a config real do usuário não entra.
CHILD_SCRIPT = '''"""Filho do teste "app morto" (T08) — morto de propósito pelo pai."""

import asyncio
import os
import time
from pathlib import Path

import ytmusic_tui.download as download_mod
from ytmusic_tui.config import settings
from ytmusic_tui.download.store import DownloadTaskStore
from ytmusic_tui.library.database import DatabaseManager

settings.download_dir = Path(os.environ["YTMUSIC_DOWNLOAD_DIR"])
settings.download_format = "mp3"
settings.download_quality = "320"
settings.embed_metadata = True


class DownloadError(RuntimeError):
    pass


class SlowYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download(self, urls):
        for hook in self.opts.get("progress_hooks", []):
            hook({"status": "downloading", "_percent_str": "1.0%"})
        template = self.opts["outtmpl"]
        partial = Path(template.replace("%(ext)s", "webm.part"))
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"parcial-do-filho")
        Path(os.environ["L2_SENTINEL"]).write_text("baixando")
        deadline = time.monotonic() + 60  # teto duro; o pai mata bem antes
        while time.monotonic() < deadline:
            time.sleep(0.05)


download_mod._load_yt_dlp = lambda: type(
    "Stub",
    (),
    {
        "utils": type("U", (), {"DownloadError": DownloadError}),
        "YoutubeDL": SlowYoutubeDL,
    },
)()

db = DatabaseManager(Path(os.environ["L2_TASKS_DB"]))
db.migrate()
manager = download_mod.DownloadManager(store=DownloadTaskStore(db=db))
task = manager.queue_download(video_id="vid-morto", title="T", artist="A", album="Alb")
asyncio.run(manager.download(task))
'''


async def test_process_killed_mid_download_is_recovered_by_real_worker(tmp_path, monkeypatch):
    download_dir = tmp_path / "library"
    download_dir.mkdir()
    install_fake_ffmpeg(tmp_path, monkeypatch)  # vale para o filho (PATH) e para o retry
    install_settings(monkeypatch, download_dir)
    install_yt_dlp(monkeypatch, "ok")  # stub rápido para a retomada AQUI

    tasks_db = tmp_path / "tasks.db"
    db = DatabaseManager(tasks_db)
    db.migrate()
    manager = download_mod.DownloadManager(store=DownloadTaskStore(db=db))

    sentinel = tmp_path / "child-downloading"
    script = tmp_path / "child_app.py"
    script.write_text(CHILD_SCRIPT, encoding="utf-8")

    try:
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            env={
                **os.environ,
                "YTMUSIC_DOWNLOAD_DIR": str(download_dir),
                "YTMUSIC_DATA_DIR": str(tmp_path / "child-data"),
                "L2_SENTINEL": str(sentinel),
                "L2_TASKS_DB": str(tasks_db),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not sentinel.exists():
                if proc.poll() is not None:
                    _, err = proc.communicate(timeout=5)
                    raise AssertionError(f"filho morreu cedo ({proc.returncode}): {err}")
                if time.monotonic() >= deadline:
                    raise AssertionError("filho não começou o download a tempo")
                await asyncio.sleep(0.02)

            proc.kill()  # SIGKILL: sem chance de limpar nada (kill -9)
            proc.wait(timeout=5)
            _, err = proc.communicate(timeout=5)
        finally:
            if proc.poll() is None:  # nunca deixar filho pendurado
                proc.kill()
                proc.wait(timeout=5)
        assert proc.returncode == -signal.SIGKILL, err

        # Evidência da morte no meio: linha em voo persiste + órfãos no disco.
        tmp_dir = download_dir / ".tmp"
        locks = list(tmp_dir.glob("*.reserva"))
        partials = list(tmp_dir.glob("*.part"))
        assert locks and partials, "o filho deveria ter deixado lock e parcial"

        # Sessão 2 (esta): recuperação pelo caminho real do worker.
        assert manager.recover_interrupted() == 1
        recovered = manager.get_queue()[0]
        assert recovered.status is DownloadStatus.INTERRUPTED
        assert recovered.video_id == "vid-morto"

        new_task = manager.retry_interrupted(recovered.id)
        assert new_task is not None and new_task.retry_of == recovered.id

        result = await asyncio.wait_for(manager.download(new_task), timeout=15)
        assert result.status is DownloadStatus.COMPLETED
        assert result.file_path is not None and result.file_path.exists()
        assert result.file_path.read_bytes() == b"audio-intermediario-webm"
        # Órfãos do processo morto descartados; nada pendurado no temporário.
        assert not locks[0].exists() and not partials[0].exists()
        assert list(tmp_dir.iterdir()) == []
    finally:
        manager.shutdown()
        db.close()
