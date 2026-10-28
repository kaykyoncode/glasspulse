# -*- coding: utf-8 -*-
"""Prepara os ícones a partir da arte gerada (assets/gerados/icone-<tema>.png):
limpa os pixels soltos do fundo transparente, grava o mestre 512 px (assets/icone-<tema>.png) e o .ico
multi-tamanho (assets/icone.ico para o glasspulse, assets/icone-<tema>.ico para os demais).

Uso:  python ferramentas/gerar_icone.py            (todos os que existirem em assets/gerados)
Sem arte em assets/gerados, cai no desenho em código (monitor/icone.py) para o ícone padrão."""
import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, ".libs"))
sys.path.insert(0, os.path.join(RAIZ, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

ASSETS = os.path.join(RAIZ, "assets")
GERADOS = os.path.join(ASSETS, "gerados")
TAMANHOS = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def limpar(img: Image.Image) -> Image.Image:
    """Tira respingos isolados fora do ícone (abertura morfológica no alfa) mantendo o brilho da borda."""
    img = img.convert("RGBA")
    a = img.getchannel("A")
    aberto = a.filter(ImageFilter.MinFilter(13)).filter(ImageFilter.MaxFilter(13))
    zona = aberto.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.GaussianBlur(3))
    img.putalpha(Image.fromarray(np.minimum(np.asarray(a), np.asarray(zona))))
    bbox = img.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:                                   # recentra e dá ~3% de respiro
        img = img.crop(bbox)
        lado = int(max(img.size) * 1.06)
        tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        tela.paste(img, ((lado - img.width) // 2, (lado - img.height) // 2))
        img = tela
    return img


def gerar(tema: str, img: Image.Image) -> None:
    mestre = img.resize((512, 512), Image.LANCZOS)
    mestre.save(os.path.join(ASSETS, f"icone-{tema}.png"), optimize=True)
    destino = "icone.ico" if tema == "glasspulse" else f"icone-{tema}.ico"
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(ASSETS, destino),
                                                sizes=[(t, t) for t in TAMANHOS])
    print("ok", tema, "->", destino)


def reserva() -> None:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication
    from monitor import icone
    app = QGuiApplication([])  # noqa: F841
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    icone.pixmap(512).save(buf, "PNG")
    gerar("glasspulse", Image.open(io.BytesIO(bytes(buf.data()))))


if __name__ == "__main__":
    os.makedirs(ASSETS, exist_ok=True)
    achou = False
    if os.path.isdir(GERADOS):
        for nome in sorted(os.listdir(GERADOS)):
            if nome.startswith("icone-") and nome.endswith(".png") and not nome.endswith("_orig.png"):
                gerar(nome[6:-4], limpar(Image.open(os.path.join(GERADOS, nome))))
                achou = True
    if not achou and not os.path.exists(os.path.join(ASSETS, "icone.ico")):
        reserva()          # só cai no desenho em código se não houver nenhum ícone pronto
