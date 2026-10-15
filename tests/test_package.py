"""Consistência dos metadados do pacote."""

import tomllib
from pathlib import Path

import ytmusic_tui

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_do_pacote_e_do_pyproject_coincidem() -> None:
    """``__version__`` deve ser igual ao ``version`` do pyproject.toml.

    Guarda contra a divergência encontrada na auditoria T01 (metadados
    desatualizados em relação ao código publicado). A comparação é com o
    pyproject do repositório, não com o metadado do editable install — que
    só é regenerado no ``pip install``.
    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert ytmusic_tui.__version__ == data["project"]["version"]
