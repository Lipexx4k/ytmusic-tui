"""Testes do monitor de contrato (T10-R6) — puro, sem rede.

Garante que o helper do L3 detecta o que promete detectar: campo essencial
ausente/vazio, tipo inesperado (incluindo o formato duplo do álbum, A2),
item não-dict, campos novos só como informativo e o teto de linhas.
"""

from tests import contract


def test_item_valido_nao_tem_problemas():
    item = {
        "videoId": "v1",
        "title": "Música",
        "duration": "1:00",
        "duration_seconds": 60,
        "isAvailable": True,
        "artists": [{"name": "A"}],
        "album": {"name": "Álbum", "id": "b1"},
        "thumbnails": [{"url": "https://i.ytimg.com/vi/v1/hq.jpg"}],
    }

    problems = contract.check_item(
        item,
        contract.CONSUMED_TRACK,
        where="faixa[1]",
        essential=contract.ESSENTIAL_TRACK,
    )

    assert problems == []


def test_essencial_ausente_ou_vazio_e_problema():
    quebrados = [
        {"title": "Sem id"},
        {"videoId": "", "title": "Id vazio"},
        {"videoId": "v1"},  # sem título
    ]

    for quebrado in quebrados:
        problems = contract.check_item(
            quebrado,
            contract.CONSUMED_TRACK,
            where="faixa[1]",
            essential=contract.ESSENTIAL_TRACK,
        )
        assert problems, f"esperava problema para {quebrado}"


def test_tipo_inesperado_e_problema():
    item = {"videoId": "v1", "title": "T", "duration_seconds": "60"}  # veio str

    problems = contract.check_item(
        item,
        contract.CONSUMED_TRACK,
        where="faixa[2]",
        essential=contract.ESSENTIAL_TRACK,
    )

    assert any("duration_seconds" in problem and "esperado int" in problem for problem in problems)


def test_album_aceita_as_duas_formas_do_campo():
    for album in ({"name": "Álbum", "id": "b1"}, "Álbum"):
        item = {"videoId": "v1", "title": "T", "album": album}
        assert (
            contract.check_item(
                item,
                contract.CONSUMED_TRACK,
                where="t",
                essential=contract.ESSENTIAL_TRACK,
            )
            == []
        )

    problems = contract.check_item(
        {"videoId": "v1", "title": "T", "album": 42},
        contract.CONSUMED_TRACK,
        where="t",
        essential=contract.ESSENTIAL_TRACK,
    )
    assert any("album" in problem for problem in problems)


def test_item_nao_dict_e_problema():
    problems = contract.check_item(
        "texto",
        contract.CONSUMED_TRACK,
        where="faixa[1]",
        essential=contract.ESSENTIAL_TRACK,
    )

    assert problems == ["faixa[1]: esperado dict, veio str"]


def test_inspect_relata_problemas_e_campos_novos_sem_confundir():
    items = [
        {"videoId": "v1", "title": "T", "campoNovo": 1},  # ok + campo novo
        {"videoId": "", "title": "T"},  # problema
    ]

    problems, report = contract.inspect(
        "faixa",
        items,
        consumed=contract.CONSUMED_TRACK,
        essential=contract.ESSENTIAL_TRACK,
    )

    assert len(problems) == 1
    assert "faixa: 2 itens · 1 problema(s)" in report
    assert "campoNovo" in report  # informativo, não problema
    assert "esperado dict" not in report


def test_inspect_limita_linhas_do_relatorio():
    items = [{"title": "T"}] * 30  # 30 itens, todos sem videoId

    problems, report = contract.inspect(
        "faixa",
        items,
        consumed=contract.CONSUMED_TRACK,
        essential=contract.ESSENTIAL_TRACK,
    )

    assert len(problems) == 30
    assert f"... mais {30 - contract.PROBLEM_LIMIT} problema(s)" in report


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
