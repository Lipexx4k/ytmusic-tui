"""Pipeline de publicação de arquivos baixados (§5/T03).

Ordem fixa do §5.1: validar entrada → reservar nome/temporário → yt-dlp →
validar → publicar → registrar → ``COMPLETED`` (a marcação final fica no
gerenciador; aqui vivem os passos de disco). ``COMPLETED`` só depois de
publicar **e** registrar — falha no meio vira "arquivo sem registro",
recuperável pela reconciliação; o inverso é proibido (INV-2).

Garantias principais:

- **Reserva exclusiva** do nome final (``O_CREAT|O_EXCL`` em
  ``download_dir/.tmp/<chave>.reserva``): fecha a corrida
  ``exists()×replace()`` entre tarefas do app — a janela residual TOCTOU
  só existe contra escritores **externos** ao app e está documentada;
- **Temporário no mesmo filesystem** do destino (``.tmp/`` dentro de
  ``download_dir``), com sufixo determinístico por destino: o ``os.replace``
  final é um rename atômico, sem cópia entre dispositivos;
- **fsync**: o temporário é sincronizado antes do ``replace`` (o rename só
  garante visibilidade, não persistência) e o diretório depois, de forma
  best-effort (nem todo filesystem suporta; falha fica no log);
- **Nunca sobrescrever**: destino existente → política Q2(a) no chamador
  (pular com aviso); se o destino aparecer entre a reserva e o ``replace``,
  a publicação é recusada (``OverwriteRefusedError``).
- **Normalização única e contenção pós-resolve** (§8.1/T06 · INV-5): todo
  caminho de download nasce de ``final_path_for``/``build_output_template``
  (uma única função de normalização, com os limites históricos congelados)
  e a contenção em ``download_dir`` é validada DEPOIS do ``resolve``
  (``resolve_within``/``PathEscapeError``) — inclusive antes de publicar e
  ao ler caminhos persistidos (T04), que podem estar adulterados.
"""

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ytmusic_tui.download.errors import (
    DestinationBusy,
    InvalidInputError,
    MediaValidationError,
    OverwriteRefusedError,
    PathEscapeError,
    PipelineError,
)

__all__ = [
    "FALLBACK_ALBUM",
    "FALLBACK_ARTIST",
    "FALLBACK_TITLE",
    "QUARANTINE_DIR_NAME",
    "SUPPORTED_FORMATS",
    "TMP_DIR_NAME",
    "DestinationBusy",
    "InvalidInputError",
    "MediaValidationError",
    "OverwriteRefusedError",
    "PathEscapeError",
    "PipelineError",
    "Reservation",
    "build_output_template",
    "discard_task_files",
    "final_path_for",
    "normalize_component",
    "publish_file",
    "release",
    "reserve",
    "reservation_key",
    "resolve_within",
    "truncate_bytes",
    "validate_input",
    "validate_media_file",
]

logger = logging.getLogger(__name__)

#: Diretório de trabalho do pipeline (reserva + temporário), dentro de
#: ``download_dir`` para garantir o mesmo filesystem do destino.
TMP_DIR_NAME = ".tmp"

#: Diretório de quarentena da reconciliação (T03; modo 0700).
QUARANTINE_DIR_NAME = ".quarantine"

#: Formatos de saída suportados (espelha o ``format_map`` do gerenciador).
SUPPORTED_FORMATS = frozenset({"mp3", "opus", "m4a", "flac"})

#: Fallbacks de metadados vazios (§8.1/T06) — nomes históricos, congelados:
#: mudar qualquer um renomearia arquivos já persistidos (T04/Q2).
FALLBACK_ARTIST = "Unknown Artist"
FALLBACK_ALBUM = "Unknown Album"
FALLBACK_TITLE = "Unknown Title"


@dataclass(frozen=True)
class Reservation:
    """Reserva exclusiva do nome final e do espaço temporário (§5.2)."""

    key: str
    final_path: Path
    temp_dir: Path
    lock_path: Path

    @property
    def temp_template(self) -> str:
        """Template de saída do yt-dlp apontando para o temporário."""
        return str(self.temp_dir / f"{self.key}.%(ext)s")


def reservation_key(final_path: Path) -> str:
    """Chave determinística (16 hex) do destino — nome do lock/temporário."""
    return hashlib.sha256(str(final_path).encode("utf-8")).hexdigest()[:16]


def truncate_bytes(name: str, max_bytes: int) -> str:
    """Corta ``name`` para caber em ``max_bytes`` (UTF-8) sem quebrar caractere.

    O limite de 255 bytes por componente de caminho (ext4, APFS, NTFS...)
    conta bytes, não caracteres: 100 caracteres CJK ocupam 300 bytes, então
    um corte apenas por caracteres não basta para nomes multibyte.
    """
    encoded = name.encode("utf-8")
    if len(encoded) <= max_bytes:
        return name
    return encoded[:max_bytes].decode("utf-8", errors="ignore").strip(" .")


def normalize_component(
    raw: str,
    *,
    default: str,
    max_chars: int,
    max_bytes: int | None = None,
) -> str:
    """Normaliza UM componente de caminho de download (§8.1/T06).

    Função única usada por todos os fluxos (via ``final_path_for``/
    ``build_output_template``): separadores (``/``, ``\\``), caracteres
    proibidos em outros sistemas (``<>:"|?*``) e de controle (``\\x00-\\x1f``,
    incluindo DEL ``\\x7f`` — endurecimento intencional do T06) viram ``_``;
    espaços/pontos das pontas somem (nada de ``..``, nomes ocultos ou
    componentes de caminho vindos de metadados).

    O corte é primeiro em caracteres e depois em BYTES (``max_bytes``): o
    limite real do filesystem (255 bytes/componente) não é o mesmo que 255
    caracteres com multibyte. ``default`` cobre a entrada vazia — como no
    comportamento histórico, um valor que vira vazio SÓ depois da
    sanitização não recebe o default aqui; o fallback final (artista/álbum/
    stem) é do compositor ``_normalized_components``.
    """
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", raw or default)
    name = name.strip(" .")[:max_chars]
    if max_bytes is not None:
        name = truncate_bytes(name, max_bytes)
    return name


def _destination_dir(download_dir: Path, artist: str, album: str) -> Path:
    """``Artista/Álbum`` — ou só ``Artista`` quando o álbum é desconhecido."""
    if album == FALLBACK_ALBUM:
        return download_dir / artist
    return download_dir / artist / album


def _normalized_components(artist: str, title: str, album: str) -> tuple[str, str, str]:
    """(artista, álbum, stem) normalizados, com os limites históricos.

    Os cortes (60/100/60 caracteres; 120/120/240 bytes) são os mesmos desde
    a T01/T02: mudá-los renomearia arquivos já persistidos (T04/Q2 e adotados
    pelo Q2(a)). Qualquer alteração exige migração de caminhos + decisão de
    produto — a prova de não-regressão é o corpus congelado nos testes.
    """
    artist_name = (
        normalize_component(artist, default=FALLBACK_ARTIST, max_chars=60, max_bytes=120)
        or FALLBACK_ARTIST
    )
    album_name = (
        normalize_component(album, default=FALLBACK_ALBUM, max_chars=60, max_bytes=120)
        or FALLBACK_ALBUM
    )
    title_name = normalize_component(title, default=FALLBACK_TITLE, max_chars=100)
    stem = truncate_bytes(f"{title_name} - {artist_name}", 240) or FALLBACK_TITLE
    return artist_name, album_name, stem


def build_output_template(*, download_dir: Path, artist: str, title: str, album: str) -> str:
    """Template de saída do yt-dlp (``%(ext)s``) para uma faixa (§8.1/T06).

    Estrutura histórica: ``Artista/Álbum/Faixa - Artista.ext`` — ou
    ``Artista/Faixa - Artista.ext`` quando o álbum é desconhecido.
    """
    artist_name, album_name, stem = _normalized_components(artist, title, album)
    return str(_destination_dir(download_dir, artist_name, album_name) / f"{stem}.%(ext)s")


def final_path_for(
    *, download_dir: Path, artist: str, title: str, album: str, extension: str
) -> Path:
    """Caminho final publicado (extensão real) — mesma composição do template."""
    artist_name, album_name, stem = _normalized_components(artist, title, album)
    return _destination_dir(download_dir, artist_name, album_name) / f"{stem}.{extension}"


def resolve_within(candidate: Path, base: Path) -> Path:
    """Resolve ``candidate`` e exige que o resultado fique DENTRO de ``base``.

    Contrato do §8.1: a validação é feita **depois** do ``resolve``, nunca
    antes — symlinks e ``..`` são resolvidos primeiro e não driblam a
    contenção por comparação textual. ``resolve`` sem ``strict`` (padrão)
    não exige que o destino exista: resolve o que existe no caminho e mantém
    o resto. Devolve o caminho resolvido; quem precisa da forma original
    (chave de reserva estável) usa o valor de entrada.
    """
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise PathEscapeError(f"caminho fora de download_dir: {candidate}")
    return resolved


def validate_input(
    *,
    video_id: str,
    audio_format: str,
    final_path: Path,
    download_dir: Path,
) -> None:
    """Valida a entrada do pipeline (passo 1 do §5.1).

    Defesa em profundidade contra destinos fora de ``download_dir``
    (INV-5): a contenção é validada **depois** do resolve (``resolve_within``
    → ``PathEscapeError``), então symlinks no caminho não escapam; o destino
    também não pode ficar nos diretórios de trabalho do pipeline
    (``.tmp``/``.quarantine``).
    """
    if not video_id or not video_id.strip():
        raise InvalidInputError("video_id vazio")
    if audio_format.lower() not in SUPPORTED_FORMATS:
        raise InvalidInputError(f"formato não suportado: {audio_format!r}")

    resolved_final = resolve_within(final_path, download_dir)
    resolved_dir = download_dir.resolve()
    for special in (TMP_DIR_NAME, QUARANTINE_DIR_NAME):
        if resolved_final.is_relative_to(resolved_dir / special):
            raise InvalidInputError(f"destino não pode ficar em {special}/: {final_path}")


def reserve(final_path: Path, download_dir: Path) -> Reservation:
    """Reserva o nome final com exclusividade real (§5.2).

    A criação do lock com ``O_CREAT|O_EXCL`` é atômica no filesystem: duas
    tarefas não podem achar que reservaram o mesmo destino. Lock existente
    → ``DestinationBusy`` (pode ser reserva ativa ou lixo antigo; a limpeza
    de reservas antigas é da reconciliação, por idade).
    """
    temp_dir = download_dir / TMP_DIR_NAME
    temp_dir.mkdir(parents=True, exist_ok=True)
    key = reservation_key(final_path)
    lock_path = temp_dir / f"{key}.reserva"
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise DestinationBusy(f"destino já reservado: {lock_path}") from exc
    os.close(handle)
    return Reservation(key=key, final_path=final_path, temp_dir=temp_dir, lock_path=lock_path)


def release(reservation: Reservation) -> None:
    """Remove o lock e temporários ``<chave>.*`` da reserva (idempotente).

    Chamado no fim de cada tentativa (sucesso ou falha). Falhas de limpeza
    ficam no log — nunca mascaradas — e sobras antigas são tratadas pela
    reconciliação (§5.3, idade + prefixo).
    """
    for leftover in sorted(reservation.temp_dir.glob(f"{reservation.key}.*")):
        try:
            leftover.unlink()
            logger.info("Temporário removido: %s", leftover)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Não foi possível remover temporário %s", leftover, exc_info=True)


def discard_task_files(*, temp_dir: Path, final_path: Path) -> list[Path]:
    """Remove temporários/locks DESTA tarefa (retomar/descartar — T04-R3).

    Política própria e mais estreita que a limpeza por idade (§5.3): apenas
    ``<chave>.*`` dentro do ``.tmp`` da tarefa e os sufixos legados
    ``<final>.part``/``<final>.ytdl`` ao lado do destino. O arquivo final
    **nunca** é tocado, e a limpeza só acontece em decisão explícita do
    usuário (retomar/descartar) — a automática continua sendo só por idade
    com dono desconhecido. Cada remoção e cada falha é logada (nunca em
    silêncio); devolve os caminhos efetivamente removidos.
    """
    removed: list[Path] = []
    key = reservation_key(final_path)
    candidates = sorted(temp_dir.glob(f"{key}.*"))
    candidates += [Path(f"{final_path}.part"), Path(f"{final_path}.ytdl")]
    for path in candidates:
        try:
            if not path.is_file():
                continue
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("Falha ao descartar temporário %s", path, exc_info=True)
            continue
        removed.append(path)
        logger.info("Temporário de tarefa descartado: %s", path)
    return removed


def validate_media_file(path: Path | None, expected_format: str) -> Path:
    """Valida o arquivo final (passo 5 do §5.1) e devolve o caminho.

    Existe · tamanho > 0 · legível · extensão == formato configurado. Uma
    validação fraca aqui deixaria passar "sucesso falso" (INV-1): o que
    publica e registra precisa passar por todos os quatro critérios.
    """
    if path is None:
        raise MediaValidationError("arquivo final não capturado pelo post_hook (ausente)")
    if not path.is_file():
        raise MediaValidationError(f"arquivo final ausente: {path}")

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MediaValidationError(f"arquivo final ilegível: {path}") from exc
    if size == 0:
        raise MediaValidationError(f"arquivo final vazio: {path}")
    if path.suffix.lower().lstrip(".") != expected_format.lower():
        raise MediaValidationError(
            f"extensão {path.suffix!r} diferente do formato configurado {expected_format!r}"
        )

    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        raise MediaValidationError(f"arquivo final ilegível: {path}") from exc

    return path


def publish_file(temp: Path, final: Path) -> Path:
    """Publica ``temp`` → ``final`` com fsync e anti-sobrescrita (§5.2)."""
    if not temp.is_file():
        raise FileNotFoundError(f"temporário ausente na publicação: {temp}")
    if temp.stat().st_size == 0:
        raise MediaValidationError(f"arquivo temporário vazio: {temp}")

    # (1) Dados no disco ANTES do rename: os.replace garante visibilidade,
    # não persistência física — sem isto, um corte de energia poderia deixar
    # um arquivo "publicado" com dados parciais.
    with temp.open("rb") as handle:
        os.fsync(handle.fileno())

    final.parent.mkdir(parents=True, exist_ok=True)

    # (2) Última re-checagem: um destino que apareceu depois da reserva não
    # é sobrescrito em silêncio. A janela residual entre esta checagem e o
    # replace é inerente ao os.replace e só pode ser explorada por escritores
    # externos ao app (entre tarefas do app a reserva O_EXCL é definitiva).
    if final.exists():
        raise OverwriteRefusedError(f"destino já existe; não sobrescrevemos: {final}")

    os.replace(temp, final)
    _fsync_directory(final.parent)
    return final


def _fsync_directory(directory: Path) -> None:
    """Sincroniza o diretório após o rename (best-effort, sempre logado)."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        logger.warning("Não foi possível abrir %s para fsync", directory, exc_info=True)
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        # Alguns filesystems não suportam fsync de diretório; a perda do
        # rename num crash cai na reconciliação (registro sem arquivo).
        logger.warning("fsync do diretório %s falhou", directory, exc_info=True)
    finally:
        os.close(dir_fd)
