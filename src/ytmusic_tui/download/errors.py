"""Erros tipados dos fluxos de download (T06 · §8.1).

Extraído de ``pipeline.py`` para que a normalização/contenção de caminhos e
o gerenciador importem os erros sem depender do pipeline (quebra o ciclo de
import); o pipeline re-exporta os mesmos nomes — os imports existentes não
mudam. ``PathEscapeError`` herda de ``InvalidInputError``: quem já captura a
classe genérica (o worker do download) continua funcionando, e quem precisa
distinguir escape de diretório captura a específica (INV-5).
"""

__all__ = [
    "DestinationBusy",
    "InvalidInputError",
    "MediaValidationError",
    "OverwriteRefusedError",
    "PathEscapeError",
    "PipelineError",
]


class PipelineError(Exception):
    """Erro do pipeline de publicação (base)."""


class InvalidInputError(PipelineError, ValueError):
    """Entrada inválida (passo 1 do §5.1)."""


class PathEscapeError(InvalidInputError):
    """Caminho resolvido fica fora de ``download_dir`` (§8.1/T06 · INV-5)."""


class DestinationBusy(PipelineError, RuntimeError):
    """O nome final já está reservado por outra tarefa."""


class MediaValidationError(PipelineError):
    """Arquivo de mídia ausente, vazio, ilegível ou com extensão errada."""


class OverwriteRefusedError(PipelineError, FileExistsError):
    """O destino apareceu depois da reserva; sobrescrever seria silencioso."""
