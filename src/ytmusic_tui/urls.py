"""URLs externas compartilhadas (T11-R1) — módulo-folha, sem imports do app.

Único lugar do ``src/`` onde o literal da URL de watch existe: a montagem
fica atrás de :func:`watch_url`; ``api.get_stream_url`` (seam público, Q-A)
e o pipeline de download (``WATCH_URL``) delegam para cá. Um teste de fonte
varre o ``src/`` e falha se o literal reaparecer em outro módulo (com
controles +/−) — a rede única evita drift entre player e download.
"""

__all__ = ["WATCH_URL_TEMPLATE", "watch_url"]

#: Template da URL de watch do YouTube Music (``format(video_id=...)``).
WATCH_URL_TEMPLATE = "https://music.youtube.com/watch?v={video_id}"


def watch_url(video_id: str) -> str:
    """URL de watch do YouTube Music para o vídeo."""
    return WATCH_URL_TEMPLATE.format(video_id=video_id)
