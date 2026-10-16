"""Testes do diagnóstico de versões (T10-R5) — puro, sem rede.

Inclui o teste que amarra a constante "testada" ao ambiente que o CI instala
do ``uv.lock`` (``uv sync --locked``): se ele ficar vermelho, ou o venv está
velho (rode ``uv sync``) ou o lock mudou e as constantes de ``versions.py``
precisam ser confirmadas — o "testado" é uma afirmação, não um chute.
"""

import pytest

from ytmusic_tui.versions import (
    DEPENDENCIES,
    check_dependencies,
    parse_version,
    render_dependencies,
    status_for,
)


def test_parse_version_variantes():
    assert parse_version("1.12.3") == (1, 12, 3)
    assert parse_version("2026.8.19") == (2026, 8, 19)
    assert parse_version("1.0") == (1, 0)
    assert parse_version("1.12.3rc1") == (1, 12, 3)  # sufixo ignorado
    assert parse_version("1.x") == (1,)  # para no componente inválido
    assert parse_version("desconhecida") == (0,)


@pytest.mark.parametrize(
    "installed, state",
    [
        ("1.12.3", "ok"),
        ("1.13.0", "newer"),
        ("1.11.9", "older"),
        (None, "missing"),
    ],
)
def test_status_for_estados(installed, state):
    status = status_for("ytmusicapi", "1.12.3", installed)

    assert status.state == state
    assert status.needs_update == (state in {"older", "missing"})


def test_describe_orienta_quando_apropriado():
    assert "atualize" in status_for("yt-dlp", "1.0", "0.9").describe()
    assert "não instalada" in status_for("yt-dlp", "1.0", None).describe()
    assert "mais nova" in status_for("yt-dlp", "1.0", "2.0").describe()
    ok = status_for("yt-dlp", "1.0", "1.0").describe()
    assert ok == "yt-dlp 1.0 (testada: 1.0)"


def test_check_dependencies_cobre_o_ambiente():
    statuses = check_dependencies()

    assert {status.name for status in statuses} == set(DEPENDENCIES)
    assert all(status.installed for status in statuses)  # instaladas de verdade


def test_versao_testada_bate_com_o_ambiente():
    """R5: a constante ``testada`` é a versão que o CI instala do lock.

    Vermelho aqui? Rode ``uv sync`` (venv velho) — ou o ``uv.lock`` mudou
    (Dependabot) e as constantes de ``versions.py`` precisam ser atualizadas
    junto, com a suíte verde confirmando a versão nova.
    """
    for status in check_dependencies():
        assert status.state == "ok", (
            f"{status.name}: instalada {status.installed} × testada {status.tested} — "
            "sincronize o ambiente (uv sync) ou atualize as constantes de versions.py"
        )


def test_render_dependencies_lista_o_bloco():
    rendered = render_dependencies()

    for name in DEPENDENCIES:
        assert name in rendered


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
