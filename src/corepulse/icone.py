# -*- coding: utf-8 -*-
"""Ícone do widget (bandeja e atalhos): arte gerada do tema, ou desenho em código como reserva."""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap


def pixmap(tam: int, cor1: str = "#8E7CFF", cor2: str = "#27D3F0") -> QPixmap:
    """Reserva: quadrado arredondado em gradiente com 3 barras."""
    pm = QPixmap(tam, tam)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, tam, tam)
    g.setColorAt(0, QColor(cor1))
    g.setColorAt(1, QColor(cor2))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    raio = tam * 0.28
    p.drawRoundedRect(QRectF(0, 0, tam, tam), raio, raio)
    p.setBrush(QColor(255, 255, 255, 240))
    larg = tam * 0.15
    for i, h in enumerate((0.30, 0.54, 0.40)):
        x = tam * 0.24 + i * tam * 0.2
        alt = tam * h
        p.drawRoundedRect(QRectF(x, tam * 0.76 - alt, larg, alt), larg / 2.4, larg / 2.4)
    p.end()
    return pm


def icone(tema=None) -> QIcon:
    """Usa a arte do tema (campo "icone") quando existir; senão, o desenho em código nas cores da marca."""
    ic = QIcon()
    arte = tema.caminho_icone() if tema is not None else ""
    if arte and os.path.exists(arte):
        base = QPixmap(arte)
        if not base.isNull():
            for t in (16, 20, 24, 32, 48, 64, 128, 256):
                ic.addPixmap(base.scaled(t, t, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            return ic
    c1, c2 = (tema.marca if tema is not None else ("#8E7CFF", "#27D3F0"))
    for t in (16, 20, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(pixmap(t, c1, c2))
    return ic
