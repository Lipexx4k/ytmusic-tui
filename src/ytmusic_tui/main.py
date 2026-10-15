"""Ponto de entrada do pacote ``ytmusic_tui``.

Permite iniciar a aplicação via console script (``ytmusic-tui``), com
``python -m ytmusic_tui`` ou ``python main.py``. Delega para
:func:`ytmusic_tui.tui.app.main`.
"""
import sys


def main() -> None:
    """Inicia a TUI; sem o mpv instalado, mostra um erro amigável.

    O import de ``mpv`` (python-mpv) carrega a libmpv do sistema e falha com
    ``OSError`` se ela não existir — o melhor primeiro contato possível com
    quem acabou de instalar o app é uma mensagem clara, não um traceback.
    """
    try:
        from ytmusic_tui.tui.app import main as run
    except OSError as exc:  # pragma: no cover - depende do sistema
        print(
            "ytmusic-tui precisa do player mpv instalado (pacote `mpv` da sua "
            "distro, que inclui a libmpv — no macOS: `brew install mpv`).\n"
            f"Detalhe técnico: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    run()


__all__ = ["main"]


if __name__ == "__main__":
    main()
