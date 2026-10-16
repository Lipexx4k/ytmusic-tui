#!/usr/bin/env python3
"""Ponto de entrada principal do ytmusic-tui."""

import sys
from pathlib import Path

# Adicionar src ao path para desenvolvimento
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

# Import tardio de propósito: precisa vir DEPOIS do ajuste de sys.path acima
# para funcionar rodando o app direto do código-fonte.
from ytmusic_tui.tui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
