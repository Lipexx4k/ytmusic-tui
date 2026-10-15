"""Reconciliação de arquivos e registros da biblioteca (§5.3/T03).

Roda na inicialização (gancho na TUI, via worker) para detectar as quatro
situações do §5.3:

1. arquivo final sem registro → importa para a biblioteca (``ensure_track`` +
   ``update_track_file`` com ``bitrate=0`` — desconhecido no import);
2. registro sem arquivo → apenas relata/loga: o ``Track`` não tem coluna de
   "ausente" e criar uma sem migração quebraria bancos antigos — a
   persistência fica para o T05 (nota registrada no plano);
3. ``.part``/temporário antigo sem tarefa ativa → remove **somente** com
   política explícita (idade > ``STALE_TEMP_AGE_HOURS`` E prefixo próprio);
4. arquivo final inválido → move para ``download_dir/.quarantine`` (modo
   0700), nunca apaga.

Garantias: nunca apaga arquivos finais; a varredura de mídia é recursiva
(Artista/Álbum/arquivo), exclui ``.tmp/`` e ``.quarantine/`` e considera só
arquivos regulares com extensão suportada. A associação de um temporário a
uma tarefa ``INTERRUPTED`` exige a persistência das tarefas (T04-R1): aqui
fica só detecção, limpeza por política e log.
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
        if self.removed_temps:
            parts.append(f"{len(self.removed_temps)} temporário(s) antigo(s) removido(s)")
        return "; ".join(parts) if parts else "nada a reconciliar"


def reconcile(
    download_dir: Path | None = None,
    service: LibraryService | None = None,
    *,
    now: datetime | None = None,
) -> ReconciliationReport:
    """Executa a reconciliação completa (§5.3) e devolve o relatório.

    ``download_dir``/``service`` são injetáveis para testes; ``now`` fixa a
    referência de idade da limpeza de temporários.
    """
    download_dir = download_dir if download_dir is not None else settings.download_dir
    service = service if service is not None else library
    reference = now if now is not None else datetime.now(UTC)
    report = ReconciliationReport()
    if not download_dir.is_dir():
        return report

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

    # Situação 2: registro sem arquivo — só relatório/log (persistência → T05).
    for raw_path in sorted(registered):
        path = Path(raw_path)
        if not path.exists():
            report.missing_records.append(path)
            logger.warning("Registro sem arquivo no disco: %s", path)

    # Situação 3: temporários/`.part` antigos (idade + prefixo próprio).
    report.removed_temps.extend(_cleanup_stale_temps(download_dir, reference))

    if report.has_findings:
        logger.info("Reconciliação concluída: %s", report.summary())
    return report


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
    # `local:…`); a unificação do caminho de import é T05-R6/Q3.
    track_id = service.ensure_track(
        source_id=source_id,
        title=title,
        artist=artist,
        album=album,
    )
    if not track_id:
        raise RuntimeError(f"não foi possível criar a faixa para {path}")
    # bitrate=0: desconhecido sem reanalisar o arquivo (`update_track_file`
    # exige o argumento; a inferência fica para o T05).
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


def _cleanup_stale_temps(download_dir: Path, now: datetime) -> list[Path]:
    """Remove temporários antigos com prefixo próprio (política explícita).

    Em ``.tmp/`` só remove arquivos com o nome próprio do pipeline
    (``chave.…``, incluindo ``.reserva``); no restante da árvore só sufixos
    de artefato do yt-dlp (``.part``/``.ytdl``). ``.quarantine/`` nunca é
    varrida. Recentes são preservados: podem pertencer a um download em
    andamento — a associação com a tarefa é T04.
    """
    removed: list[Path] = []
    cutoff = now.timestamp() - STALE_TEMP_AGE_HOURS * 3600

    temp_dir = download_dir / TMP_DIR_NAME
    if temp_dir.is_dir():
        for path in sorted(temp_dir.iterdir()):
            if not path.is_file() or not _OWN_TEMP_NAME_RE.match(path.name):
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
        if _is_stale(path, cutoff):
            removed_path = _remove_stale_temp(path)
            if removed_path is not None:
                removed.append(removed_path)

    return removed


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
