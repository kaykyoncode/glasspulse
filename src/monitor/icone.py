# -*- coding: utf-8 -*-
"""Ícone do widget (barra de bandeja e atalhos), desenhado em código."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap


def pixmap(tam: int) -> QPixmap:
    pm = QPixmap(tam, tam)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, tam, tam)
    g.setColorAt(0, QColor("#8E7CFF"))
    g.setColorAt(1, QColor("#27D3F0"))
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


def icone() -> QIcon:
    ic = QIcon()
    for t in (16, 20, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(pixmap(t))
    return ic
