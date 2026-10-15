"""Ponto de entrada do pacote ``ytmusic_tui``.

Permite iniciar a aplicação via console script (``ytmusic-tui``) ou com
``python -m ytmusic_tui.main``. Delega para :func:`ytmusic_tui.tui.app.main`.
"""
from ytmusic_tui.tui.app import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
