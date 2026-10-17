"""Monitor de contrato do serviço real (T10-R6).

O L3 (``tests/test_integration.py``, opt-in) usa este módulo para conferir,
com a rede real, o que o serviço devolve hoje contra o que os adaptadores
(``api/adapt.py``) consomem:

- campos ESSENCIAIS ausentes/vazios → problema (a busca filtraria tudo e a
  tela ficaria vazia "sem aviso" — o caso silencioso que queremos pegar);
- campos consumidos com tipo inesperado → problema (mudança de formato se
  detecta aqui, antes de chegar ao usuário);
- campos que não consumimos → linha informativa no relatório (não é
  problema: o serviço ganha campos novos o tempo todo).

O relatório é a saída principal: quando algo mudar, ele diz o que mudou, por
campo e por item — é o anexo da correção. Atualize as fixtures do L2 antes
de publicar o fix.
"""

__all__ = [
    "CONSUMED_ALBUM",
    "CONSUMED_ALBUM_DETAIL",
    "CONSUMED_TRACK",
    "ESSENTIAL_ALBUM",
    "ESSENTIAL_ALBUM_DETAIL",
    "ESSENTIAL_TRACK",
    "check_item",
    "inspect",
]

#: Campos que os adaptadores consomem, por tipo aceito (mudou aqui, adapte).
CONSUMED_TRACK: dict[str, tuple[type, ...]] = {
    "videoId": (str,),
    "title": (str,),
    "duration": (str,),
    "duration_seconds": (int,),
    "isAvailable": (bool,),
    "artists": (list,),
    "album": (dict, str),  # formato duplo (A2): dict {name,id} ou str
    "thumbnails": (list,),
}

CONSUMED_ALBUM: dict[str, tuple[type, ...]] = {
    "browseId": (str,),
    "title": (str,),
    "type": (str,),
    "year": (str, int),
    "trackCount": (int, str),
    "artists": (list,),
    "thumbnails": (list,),
}

CONSUMED_ALBUM_DETAIL: dict[str, tuple[type, ...]] = {
    **CONSUMED_ALBUM,
    "tracks": (list,),
}

#: Sem estes (presentes e não vazios), a operação degrada em silêncio.
ESSENTIAL_TRACK = ("videoId", "title")
ESSENTIAL_ALBUM = ("browseId", "title")
#: O ``get_album`` do ytmusicapi NÃO ecoa o ``browseId`` (o id é entrada da
#: chamada; o app já o tem) — conferido de 1.8.0 a 1.12.3 e flagrado na
#: primeira rodada real do L3 (T09). Cobrar o campo aqui acusaria mudança
#: onde não há; a busca (``ESSENTIAL_ALBUM``) essa sim o traz.
ESSENTIAL_ALBUM_DETAIL = ("title", "tracks")

#: Teto de problemas listados no relatório (o resto vira "... mais N").
PROBLEM_LIMIT = 20


def check_item(
    item: object,
    consumed: dict[str, tuple[type, ...]],
    *,
    where: str,
    essential: tuple[str, ...],
) -> list[str]:
    """Problemas de contrato de um item cru (lista vazia = em conformidade)."""
    if not isinstance(item, dict):
        return [f"{where}: esperado dict, veio {type(item).__name__}"]

    problems: list[str] = []
    for key in essential:
        if not item.get(key):
            problems.append(f"{where}: essencial '{key}' ausente/vazio")
    for key, accepted in consumed.items():
        if key not in item or item[key] is None:
            continue  # ausente é ausente (o adaptador tem regra; não é quebra)
        if not isinstance(item[key], accepted):
            expected = "/".join(kind.__name__ for kind in accepted)
            actual = type(item[key]).__name__
            problems.append(f"{where}: '{key}' veio {actual}, esperado {expected}")
    return problems


def inspect(
    scope: str,
    items: list,
    *,
    consumed: dict[str, tuple[type, ...]],
    essential: tuple[str, ...],
) -> tuple[list[str], str]:
    """Problemas + relatório legível de uma amostra crua do serviço."""
    problems: list[str] = []
    unknown: set[str] = set()
    for position, item in enumerate(items, start=1):
        where = f"{scope}[{position}]"
        problems.extend(check_item(item, consumed, where=where, essential=essential))
        if isinstance(item, dict):
            unknown.update(set(item) - set(consumed))

    lines = [f"{scope}: {len(items)} itens · {len(problems)} problema(s)"]
    for problem in problems[:PROBLEM_LIMIT]:
        lines.append(f"- {problem}")
    if len(problems) > PROBLEM_LIMIT:
        lines.append(f"- ... mais {len(problems) - PROBLEM_LIMIT} problema(s)")
    if unknown:
        lines.append("- campos não consumidos (informativo): " + ", ".join(sorted(unknown)))
    return problems, "\n".join(lines)
