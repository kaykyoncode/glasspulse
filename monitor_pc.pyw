# -*- coding: utf-8 -*-
"""Ponto de entrada do Monitor do PC (rodar com pythonw.exe: sem janela de console)."""
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(RAIZ, ".libs"))
sys.path.insert(0, os.path.join(RAIZ, "src"))

from monitor.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
