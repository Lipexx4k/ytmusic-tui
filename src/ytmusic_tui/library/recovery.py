"""Reconciliação de arquivos e registros da biblioteca (§5.3/T03).

Roda na inicialização (gancho na TUI, via worker) para detectar as quatro
situações do §5.3:

1. arquivo final sem registro → importa para a biblioteca (``ensure_track`` +
   ``update_track_file`` com ``bitrate=0`` — desconhecido no import);
2. registro sem arquivo → marca ``Track.is_missing`` (Q8/T05, coluna da
   migração v2) e relata/loga; quando o arquivo reaparece, a marca é limpa;
3. ``.part``/temporário antigo **sem dono** → remove somente com política
   explícita (idade > ``STALE_TEMP_AGE_HOURS`` E prefixo próprio). Com o
   espelho de tarefas (T04), temporário de tarefa aguardando decisão
   (PENDING/RUNNING/VALIDATING/INTERRUPTED) fica **retido** mesmo acima da
   idade: o usuário decide na TUI (r/d) e a limpeza explícita da tarefa
   cuida dos arquivos — a idade volta a valer quando não há dono;
4. arquivo final inválido → move para ``download_dir/.quarantine`` (modo
   0700), nunca apaga.

Garantias: nunca apaga arquivos finais; a varredura de mídia é recursiva
(Artista/Álbum/arquivo), exclui ``.tmp/`` e ``.quarantine/`` e considera só
arquivos regulares com extensão suportada. A associação de um temporário a
uma tarefa usa o espelho persistido (T04-R1); falha ao lê-lo reduz a
proteção à política de idade e fica no log.
"""

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ytmusic_tui.config import settings
from ytmusic_tui.download.pipeline import (
    QUARANTINE_DIR_NAME,
    SUPPORTED_FORMATS,
    TMP_DIR_NAME,
    MediaValidationError,
    validate_media_file,
)
from ytmusic_tui.download.store import DownloadTaskStore, PendingTaskFiles
from ytmusic_tui.library.service import LibraryService, library

logger = logging.getLogger(__name__)

#: Idade mínima para limpar temporários/`.part` de execuções anteriores.
#: Trabalho recém-iniciado nunca é removido (pode estar em uso).
STALE_TEMP_AGE_HOURS = 24

_MEDIA_SUFFIXES = frozenset(f".{fmt}" for fmt in SUPPORTED_FORMATS)
_TEMP_SUFFIXES = frozenset({".part", ".ytdl"})
#: Nome próprio do pipeline: chave de 16 hex + "." (ex.: `…reserva`, `….mp3`).
_OWN_TEMP_NAME_RE = re.compile(r"^[0-9a-f]{16}\.")


@dataclass
class ReconciliationReport:
    """Resumo da reconciliação (log/toast; nunca apaga dados por si)."""

    imported_files: list[Path] = field(default_factory=list)
    quarantined_files: list[Path] = field(default_factory=list)
    missing_records: list[Path] = field(default_factory=list)
    removed_temps: list[Path] = field(default_factory=list)
    #: Retidos por terem dono (tarefa aguardando decisão — r/d na TUI): não é
    #: achado, é a política de 24 h refinada pelo T04 (fica só no log).
    retained_temps: list[Path] = field(default_factory=list)
    #: Quantas faixas tiveram ``is_missing`` marcado/limpo nesta passagem
    #: (Q8/T05): marcar é o "registro sem arquivo"; limpar é o arquivo que
    #: voltou. Conta só mudanças reais de estado.
    missing_marked: int = 0
    missing_cleared: int = 0

    @property
    def has_findings(self) -> bool:
        """True se algo foi encontrado (importado, isolado, relatado ou limpo)."""
        return bool(
            self.imported_files
            or self.quarantined_files
            or self.missing_records
            or self.removed_temps
        )

    def summary(self) -> str:
        """Resumo curto em pt-BR (só o que aconteceu)."""
        parts: list[str] = []
        if self.imported_files:
            parts.append(f"{len(self.imported_files)} arquivo(s) importado(s)")
        if self.quarantined_files:
            parts.append(f"{len(self.quarantined_files)} em quarentena")
        if self.missing_records:
            parts.append(f"{len(self.missing_records)} registro(s) sem arquivo")
        if self.missing_cleared:
            parts.append(f"{self.missing_cleared} registro(s) com arquivo de volta")
        if self.removed_temps:
            parts.append(f"{len(self.removed_temps)} temporário(s) antigo(s) removido(s)")
        return "; ".join(parts) if parts else "nada a reconciliar"


def reconcile(
    download_dir: Path | None = None,
    service: LibraryService | None = None,
    *,
    now: datetime | None = None,
    store: DownloadTaskStore | None = None,
) -> ReconciliationReport:
    """Executa a reconciliação completa (§5.3) e devolve o relatório.

    ``download_dir``/``service`` são injetáveis para testes; ``now`` fixa a
    referência de idade da limpeza de temporários. ``store`` injeta o
    espelho de tarefas (T04): temporários de tarefas aguardando decisão são
    preservados mesmo acima da idade — a limpeza de idade só vale para
    órfãos sem dono. O padrão usa o banco **do service** (mesmo arquivo),
    nunca outro banco.
    """
    download_dir = download_dir if download_dir is not None else settings.download_dir
    service = service if service is not None else library
    store = store if store is not None else DownloadTaskStore(db=service.db)
    reference = now if now is not None else datetime.now(UTC)
    report = ReconciliationReport()
    if not download_dir.is_dir():
        return report

    # Donos (§5.3/T04): chaves/destinos de tarefas aguardando decisão — os
    # seus temporários ficam retidos até o usuário retomar/descartar na TUI.
    pending_files = _awaiting_decision_files(store)
    referenced_keys = {item.key for item in pending_files}
    referenced_finals = {item.final_path for item in pending_files}

    registered = service.get_local_paths()

    # Situações 1 e 4: arquivos finais sem registro — importa o válido,
    # isola o inválido (nunca apaga).
    for path in scan_media_files(download_dir):
        if str(path) in registered:
            continue
        try:
            validate_media_file(path, path.suffix.lower().lstrip("."))
            _import_file(service, download_dir, path)
        except MediaValidationError as error:
            quarantine = _quarantine(download_dir, path)
            report.quarantined_files.append(path)
            logger.warning("Arquivo inválido isolado em quarentena (%s): %s", error, quarantine)
        except Exception:
            logger.exception("Falha ao importar arquivo órfão %s", path)
        else:
            report.imported_files.append(path)
            logger.info("Arquivo órfão importado para a biblioteca: %s", path)

    # Situação 2: registro sem arquivo — marca ``is_missing`` (Q8/T05) e
    # relata/loga; registro cujo arquivo existe tem a marca limpa (o arquivo
    # "voltou" — ou nunca sumiu e a marca era resíduo de uma passagem
    # anterior). Só conta mudanças reais de estado.
    missing_paths: list[Path] = []
    present_paths: list[Path] = []
    for raw_path in sorted(registered):
        path = Path(raw_path)
        if path.exists():
            present_paths.append(path)
        else:
            missing_paths.append(path)
            report.missing_records.append(path)
            logger.warning("Registro sem arquivo no disco: %s", path)
    if missing_paths:
        report.missing_marked = service.set_missing(missing_paths, missing=True)
    if present_paths:
        report.missing_cleared = service.set_missing(present_paths, missing=False)

    # Situação 3: temporários/`.part` antigos **sem dono** (idade + prefixo).
    removed, retained = _cleanup_stale_temps(
        download_dir,
        reference,
        referenced_keys=referenced_keys,
        referenced_finals=referenced_finals,
    )
    report.removed_temps.extend(removed)
    report.retained_temps.extend(retained)

    if report.has_findings:
        logger.info("Reconciliação concluída: %s", report.summary())
    return report


def _awaiting_decision_files(store: DownloadTaskStore) -> list[PendingTaskFiles]:
    """Temporários com dono (tarefa aguardando decisão); falha → lista vazia.

    Falha de leitura do espelho reduz a proteção (a política de idade volta
    a valer para todos), então fica no log — nunca em silêncio.
    """
    try:
        return store.awaiting_decision_files()
    except Exception:
        logger.warning(
            "Falha ao ler tarefas aguardando decisão: limpeza por idade vale para todos",
            exc_info=True,
        )
        return []


def scan_media_files(download_dir: Path) -> list[Path]:
    """Arquivos finais candidatos à reconciliação.

    Varredura recursiva (o template gera ``Artista/Álbum/arquivo``), apenas
    arquivos regulares com extensão suportada, excluindo ``.tmp/`` e
    ``.quarantine/``.
    """
    files: list[Path] = []
    for path in download_dir.rglob("*"):
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        relative = path.relative_to(download_dir)
        if TMP_DIR_NAME in relative.parts[:-1] or QUARANTINE_DIR_NAME in relative.parts[:-1]:
            continue
        if path.suffix.lower() in _MEDIA_SUFFIXES:
            files.append(path)
    return sorted(files)


def _import_metadata(download_dir: Path, path: Path) -> tuple[str, str, str]:
    """(título, artista, álbum) derivados do caminho do arquivo.

    O template de saída gera ``Artista/Álbum/Título - Artista.ext`` (ou
    ``Artista/Título - Artista.ext`` sem álbum): os nomes de diretório são a
    melhor fonte de artista/álbum disponível na varredura; o título é a
    parte do nome do arquivo antes do `` - ``.
    """
    relative = path.relative_to(download_dir)
    directories = relative.parts[:-1]
    artist = directories[0] if len(directories) >= 1 else ""
    album = directories[1] if len(directories) >= 2 else ""
    stem = relative.stem
    title = stem.split(" - ", 1)[0].strip() or stem
    if not artist and " - " in stem:
        artist = stem.split(" - ", 1)[1].strip()
    return title, artist, album


def _import_file(service: LibraryService, download_dir: Path, path: Path) -> None:
    """Importa um arquivo válido sem registro (situação 1 do §5.3)."""
    title, artist, album = _import_metadata(download_dir, path)
    source_id = f"local:{hashlib.sha1(str(path).encode('utf-8')).hexdigest()[:24]}"
    # Nota: reutiliza `ensure_track` (fonte YOUTUBE_MUSIC + id sintético
    # `local:…`); a identidade da faixa é (source_id, source) e o formato é
    # atributo (`file_format`) — sem linha duplicada por formato (T05-R6).
    track_id = service.ensure_track(
        source_id=source_id,
        title=title,
        artist=artist,
        album=album,
    )
    if not track_id:
        raise RuntimeError(f"não foi possível criar a faixa para {path}")
    # bitrate=0: desconhecido sem reanalisar o arquivo (`update_track_file`
    # exige o argumento); 0 fica documentado como "desconhecido".
    service.update_track_file(
        track_id,
        path,
        path.stat().st_size,
        path.suffix.lower().lstrip("."),
        0,
    )


def _quarantine(download_dir: Path, path: Path) -> Path:
    """Move um arquivo inválido para ``.quarantine`` (0700), sem colisão."""
    quarantine_dir = download_dir / QUARANTINE_DIR_NAME
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    try:
        # mkdir respeita umask; o chmod garante 0700 também se já existia.
        os.chmod(quarantine_dir, 0o700)
    except OSError:
        logger.warning(
            "Não foi possível ajustar o modo de %s para 0700", quarantine_dir, exc_info=True
        )

    target = quarantine_dir / path.name
    counter = 1
    while target.exists():
        target = quarantine_dir / f"{path.stem}-{counter}{path.suffix}"
        counter += 1
    os.replace(path, target)
    return target


def _cleanup_stale_temps(
    download_dir: Path,
    now: datetime,
    *,
    referenced_keys: frozenset[str] | set[str] = frozenset(),
    referenced_finals: frozenset[Path] | set[Path] = frozenset(),
) -> tuple[list[Path], list[Path]]:
    """Remove temporários antigos **sem dono** (política explícita do §5.3).

    Em ``.tmp/`` só remove arquivos com o nome próprio do pipeline
    (``chave.…``, incluindo ``.reserva``); no restante da árvore só sufixos
    de artefato do yt-dlp (``.part``/``.ytdl``). ``.quarantine/`` nunca é
    varrida.

    **Com dono fica retido** (T04): chave/destino de tarefa aguardando
    decisão não é removido(a) nem acima da idade — a decisão é do usuário
    (r/d na TUI), e é a limpeza explícita da tarefa que cuida dos arquivos.
    Recentes também são preservados: podem pertencer a um download em
    andamento. Devolve ``(removidos, retidos-por-dono)``.
    """
    removed: list[Path] = []
    retained: list[Path] = []
    cutoff = now.timestamp() - STALE_TEMP_AGE_HOURS * 3600

    temp_dir = download_dir / TMP_DIR_NAME
    if temp_dir.is_dir():
        for path in sorted(temp_dir.iterdir()):
            if not path.is_file() or not _OWN_TEMP_NAME_RE.match(path.name):
                continue
            key = path.name.split(".", 1)[0]
            if key in referenced_keys:
                retained.append(path)
                logger.info("Temporário preservado (tarefa aguardando decisão): %s", path)
                continue
            if _is_stale(path, cutoff):
                removed_path = _remove_stale_temp(path)
                if removed_path is not None:
                    removed.append(removed_path)

    for path in sorted(download_dir.rglob("*")):
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        relative = path.relative_to(download_dir)
        if relative.parts[0] in (TMP_DIR_NAME, QUARANTINE_DIR_NAME):
            continue
        if path.suffix.lower() not in _TEMP_SUFFIXES:
            continue
        if path.with_suffix("") in referenced_finals:
            retained.append(path)
            logger.info("Temporário preservado (tarefa aguardando decisão): %s", path)
            continue
        if _is_stale(path, cutoff):
            removed_path = _remove_stale_temp(path)
            if removed_path is not None:
                removed.append(removed_path)

    return removed, retained


def _is_stale(path: Path, cutoff: float) -> bool:
    """True se a mtime é anterior ao corte; erro de acesso → preserva."""
    try:
        return path.stat().st_mtime <= cutoff
    except OSError:
        logger.warning("Não foi possível ler a data de %s (preservado)", path, exc_info=True)
        return False


def _remove_stale_temp(path: Path) -> Path | None:
    """Remove um temporário antigo; ausência/falha ficam no log, nunca em silêncio."""
    try:
        size = path.stat().st_size
        path.unlink()
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("Falha ao remover temporário antigo %s", path, exc_info=True)
        return None
    logger.info("Temporário antigo removido: %s (%d bytes)", path, size)
    return path
