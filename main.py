#!/usr/bin/env python3
"""Ponto de entrada principal do ytmusic-tui."""
import sys
from pathlib import Path

# Adicionar src ao path para desenvolvimento
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

from ytmusic_tui.tui.app import main

if __name__ == "__main__":
    main()