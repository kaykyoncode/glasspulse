# -*- coding: utf-8 -*-
"""Gera assets/icone.ico a partir do mesmo desenho usado na bandeja (monitor/icone.py)."""
import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, ".libs"))
sys.path.insert(0, os.path.join(RAIZ, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from monitor import icone  # noqa: E402

app = QGuiApplication([])
tamanhos = [16, 24, 32, 48, 64, 128, 256]
imagens = []
for t in tamanhos:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    icone.pixmap(t).save(buf, "PNG")
    imagens.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
destino = os.path.join(RAIZ, "assets")
os.makedirs(destino, exist_ok=True)
imagens[-1].save(os.path.join(destino, "icone.ico"), sizes=[(t, t) for t in tamanhos])
imagens[-1].save(os.path.join(destino, "icone.png"))
print("gerado em", destino)
