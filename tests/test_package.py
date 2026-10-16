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


def test_css_do_app_acompanha_o_modulo() -> None:
    """``app.tcss`` precisa existir ao lado de ``app.py`` (T06.1).

    O Textual resolve ``CSS_PATH`` relativo ao módulo do app: num pacote
    instalado sem o arquivo, o startup morre com ``StylesheetError``. Esta
    guarda pega o descuido no próprio fonte; o job "pacote" do CI confere o
    artefato construído (wheel e sdist) antes de instalar.
    """
    # Import local: mantém o collect leve (o `app` puxa textual/player).
    from ytmusic_tui.tui import app as app_module

    module_file = app_module.__file__
    assert module_file is not None
    tui_dir = Path(module_file).resolve().parent

    css_path = app_module.YTMusicTUI.CSS_PATH
    assert isinstance(css_path, str)
    assert (tui_dir / "app.tcss").is_file()
    assert (tui_dir / css_path).is_file()
