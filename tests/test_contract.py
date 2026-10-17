"""Testes do monitor de contrato (T10-R6) — puro, sem rede.

Garante que o helper do L3 detecta o que promete detectar: campo essencial
ausente/vazio, tipo inesperado (incluindo o formato duplo do álbum, A2),
item não-dict, campos novos só como informativo e o teto de linhas.

Fixa também, offline, a regra de ruído zero do L3 (T09/Q12): falha
inconclusiva (rede/serviço/rate-limit) vira skip com motivo; resposta fora do
contrato do ytmusicapi falha (não pode virar skip verde).
"""

import pytest
import requests

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


def test_album_detalhe_valido_sem_browse_id():
    """O ``get_album`` não ecoa o browseId: detalhe sem o campo é conforme (T09).

    O id é entrada da chamada, não campo da resposta (ytmusicapi 1.8–1.12.3);
    cobrá-lo como essencial do detalhe acusaria mudança onde não há — a
    primeira rodada real do L3 pegou exatamente isso.
    """
    item = {
        "title": "My Dear Melancholy,",
        "type": "EP",
        "artists": [{"name": "The Weeknd"}],
        "thumbnails": [],
        "tracks": [{"videoId": "v1", "title": "T"}],
    }

    assert (
        contract.check_item(
            item,
            contract.CONSUMED_ALBUM_DETAIL,
            where="álbum",
            essential=contract.ESSENTIAL_ALBUM_DETAIL,
        )
        == []
    )


def test_l3_inconclusivo_vira_skip_com_motivo():
    """Falha de rede no L3 é inconclusiva: skip explícito, nunca veredito (T09/Q12)."""
    from tests import test_integration

    def sem_rede():
        raise requests.exceptions.ConnectionError("rede fora do ar")

    with pytest.raises(
        pytest.skip.Exception,
        match="inconclusivo: NetworkError — sem veredito de contrato",
    ):
        test_integration._rede(sem_rede, context="teste offline")


def test_l3_contrato_quebrado_falha_em_vez_de_skip():
    """Resposta fora do contrato do ytmusicapi FALHA (não pode virar skip)."""
    from tests import test_integration
    from ytmusic_tui.errors import InvalidResponseError

    def formato_mudou():
        raise KeyError("videoId")

    with pytest.raises(InvalidResponseError, match="possível mudança de formato"):
        test_integration._rede(formato_mudou, context="teste offline")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
