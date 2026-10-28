# -*- coding: utf-8 -*-
"""Janela do widget: vidro acrílico, cantos redondos, gráficos e barras animados."""
from __future__ import annotations

import ctypes
import os
import time
from collections import deque
from ctypes import wintypes as wt
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from . import temas, winapi

# ---- medidas (as cores vêm do tema ativo: temas.py)
RAIO_JANELA = 8        # o DWM arredonda com 8 px; desenhamos igual
RAIO_CARD = 12
MARGEM = 14
GAP = 10
INT = 14               # respiro interno dos cartões
LARG_CARD = 352
DURACAO = 0.7          # segundos de animação a cada amostra
QUADRO_MS = 40         # 25 quadros/s só durante a animação; no resto o widget fica parado
PONTOS = 62            # histórico (~1 min a 1 amostra/s)

VIDROS = {"leve": 70, "medio": 108, "fosco": 178}
TINTA_ACRILICO = {"leve": 0x1E, "medio": 0x2C, "fosco": 0x58}

SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def cor(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


def misturar(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


def calor(base: str | QColor, pct: float, t) -> QColor:
    """Acento normal até ~72%; muda para a cor 'médio' e depois 'crítico' do tema conforme o uso aperta."""
    c = QColor(base)
    medio, critico = QColor(t.medio), QColor(t.critico)
    if pct < 72:
        return c
    if pct < 78:
        return misturar(c, medio, (pct - 72) / 6)
    if pct < 88:
        return medio
    if pct < 94:
        return misturar(medio, critico, (pct - 88) / 6)
    return critico


def mais_claro(c: QColor, t: float = 0.28) -> QColor:
    return misturar(c, QColor(255, 255, 255), t)


def suave(t: float) -> float:
    return 1 - (1 - t) ** 3


def num(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def cap(b: float) -> str:
    g = b / 1024 ** 3
    if g >= 1000:
        return num(g / 1024, 2) + " TB"
    return (num(g, 0) if g >= 100 else num(g, 1)) + " GB"


def taxa_bits(bps: float) -> tuple[str, str]:
    if bps >= 1e9:
        g = num(bps / 1e9, 2)
        return (g[:-1] if g.endswith("0") else g), "Gb/s"
    if bps >= 1e6:
        return num(bps / 1e6, 1), "Mb/s"
    return num(bps / 1e3, 0), "Kb/s"


def taxa_bytes(bps: float) -> str:
    if bps >= 1024 ** 3:
        return num(bps / 1024 ** 3, 2) + " GB/s"
    if bps >= 1024 ** 2:
        return num(bps / 1024 ** 2, 1) + " MB/s"
    return num(bps / 1024, 0) + " KB/s"


def duracao(seg: float) -> str:
    d, resto = divmod(int(seg), 86400)
    h, resto = divmod(resto, 3600)
    m = resto // 60
    return f"{d} d {h:02d} h" if d else f"{h} h {m:02d} min"


class Tween:
    __slots__ = ("a", "b", "v")

    def __init__(self, v: float = 0.0) -> None:
        self.a = self.b = self.v = v

    def para(self, alvo: float) -> None:
        self.a, self.b = self.v, alvo

    def passo(self, e: float) -> None:
        self.v = self.a + (self.b - self.a) * e


class MonitorWidget(QWidget):
    def __init__(self, cfg, coletor, processos, criar_menu) -> None:
        flags = (Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnBottomHint
                 | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.cfg, self.coletor, self.processos, self.criar_menu = cfg, coletor, processos, criar_menu
        self.setWindowTitle(winapi.TITULO_JANELA)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_MacShowFocusRect, False)

        self.t = temas.obter(cfg.get("tema"))
        self._cores_do_tema()
        self.d: dict | None = None
        self.procs: list = []
        self.tw: dict[str, Tween] = {}
        self.h_cpu = deque([0.0] * PONTOS, maxlen=PONTOS)
        self.h_gpu = deque([0.0] * PONTOS, maxlen=PONTOS)
        self.h_down = deque([0.0] * PONTOS, maxlen=PONTOS)
        self.h_up = deque([0.0] * PONTOS, maxlen=PONTOS)
        self.pico_rede = 0.0
        self.t0 = 0.0
        self.e = 1.0
        self._fontes: dict[tuple, QFont] = {}
        self._arrasto: QPointF | None = None
        self._hwnd = 0
        self.teste_topo = False
        self._cache: QPixmap | None = None     # camada estática: vidro, cartões e textos
        self._cache_dpr = 0.0
        self._cache_sujo = True                # refeita a cada amostra (1x/s), não a cada quadro

        self.anim = QTimer(self)
        self.anim.setTimerType(Qt.CoarseTimer)
        self.anim.setInterval(QUADRO_MS)
        self.anim.timeout.connect(self._quadro)

        self.recalcular_layout()

    # ------------------------------------------------------------------ tema

    def _cores_do_tema(self) -> None:
        for nome, alfa in (("T1", 240), ("T2", 158), ("T3", 98)):
            setattr(self, nome, cor(self.t.texto, alfa))
        arte = self.t.caminho_icone()
        self._arte = QPixmap(arte) if arte and os.path.exists(arte) else None
        self._arte_cache: dict[float, QPixmap] = {}

    def definir_tema(self, tema) -> None:
        self.t = tema
        self._cores_do_tema()
        self.aplicar_vidro()                  # refaz o acrílico com a tinta nova e a camada estática

    # ------------------------------------------------------------------ layout

    def recalcular_layout(self) -> None:
        c = self.cfg
        n_discos = max(1, len(self.d["discos"])) if self.d else 2
        mostrar_nuc, mostrar_proc = c["mostrar_nucleos"], c["mostrar_processos"]
        alt = {
            "cpu": 152 if mostrar_nuc else 114,
            "ram": 106,
            "gpu": 140,
            "rede": 148,
            "disco": 38 + 54 * n_discos + 2,
            "proc": 36 + 26 * 5 + 4,
        }
        if not self.coletor.nvml:
            alt["gpu"] = 0
        if not mostrar_proc:
            alt["proc"] = 0
        topo = MARGEM + 54 + GAP
        self.rects: dict[str, QRectF] = {}
        if c["layout"] == "painel":
            colunas = [["cpu", "ram", "disco"], ["gpu", "rede", "proc"]]
            larg = MARGEM * 2 + LARG_CARD * 2 + GAP
            base = 0
            for i, col in enumerate(colunas):
                y = topo
                for k in col:
                    if alt[k]:
                        self.rects[k] = QRectF(MARGEM + i * (LARG_CARD + GAP), y, LARG_CARD, alt[k])
                        y += alt[k] + GAP
                base = max(base, y)
            altura = int(base - GAP + MARGEM)
        else:
            larg = MARGEM * 2 + LARG_CARD
            y = topo
            for k in ("cpu", "ram", "gpu", "rede", "disco", "proc"):
                if alt[k]:
                    self.rects[k] = QRectF(MARGEM, y, LARG_CARD, alt[k])
                    y += alt[k] + GAP
            altura = int(y - GAP + MARGEM)
        self._larg_header = larg - 2 * MARGEM
        self.setFixedSize(larg, altura)
        self.pedir_completo()

    # ------------------------------------------------------------------ dados

    def aplicar(self, d: dict, procs: list) -> None:
        primeira = self.d is None
        n_antes = len(self.d["discos"]) if self.d else -1
        self.d, self.procs = d, procs
        if primeira or len(d["discos"]) != n_antes:
            self.recalcular_layout()
            if self._hwnd:
                self.reposicionar_depois_de_redimensionar()
        cpu, ram, gpu, rede = d["cpu"], d["ram"], d["gpu"], d["rede"]
        self._alvo("cpu", cpu["total"])
        for i, v in enumerate(cpu["nucleos"]):
            self._alvo(f"n{i}", v)
        self._alvo("ram", ram["pct"])
        self._alvo("ram_gb", ram["usada"])
        self.h_cpu.append(cpu["total"])
        if gpu:
            self._alvo("gpu", gpu["uso"])
            self._alvo("vram", gpu["vram_usada"] * 100.0 / max(1, gpu["vram_total"]))
            self.h_gpu.append(gpu["uso"])
        self.h_down.append(rede["down_bps"])
        self.h_up.append(rede["up_bps"])
        self._alvo("down", rede["down_bps"])
        self._alvo("up", rede["up_bps"])
        pico = max(max(self.h_down), max(self.h_up), 10e6)
        self._alvo("escala_rede", pico * 1.18)
        for dk in d["discos"]:
            self._alvo("d_" + dk["letra"], dk["pct"])
        maior = max((p[2] for p in procs), default=1)
        for i, p in enumerate(procs):
            self._alvo(f"p{i}", p[2] * 100.0 / maior)
        self.t0 = time.monotonic()
        self.e = 0.0
        if not self.anim.isActive():
            self.anim.start()
        self.pedir_completo()

    def _alvo(self, chave: str, valor: float) -> None:
        t = self.tw.get(chave)
        if t is None:
            self.tw[chave] = Tween(valor)
        else:
            t.para(valor)

    def _v(self, chave: str, padrao: float = 0.0) -> float:
        t = self.tw.get(chave)
        return t.v if t else padrao

    def _quadro(self) -> None:
        if time.monotonic() - self.t0 >= DURACAO:
            self.anim.stop()
        self.update()

    def pedir_completo(self) -> None:
        """Dados, layout ou aparência mudaram: refaz a camada estática no próximo quadro."""
        self._cache_sujo = True
        self.update()

    # ------------------------------------------------------------------ janela nativa

    def preparar_nativo(self) -> None:
        self._hwnd = int(self.winId())
        winapi.aplicar_estilo_widget(self._hwnd)
        self.aplicar_vidro()
        if not self.teste_topo:
            winapi.fixar_ao_desktop(self._hwnd)

    def aplicar_vidro(self) -> None:
        if self._hwnd:
            nivel = self.cfg["vidro"]
            tinta = QColor(self.t.tinta)
            winapi.aplicar_vidro(self._hwnd, (tinta.red(), tinta.green(), tinta.blue(),
                                              TINTA_ACRILICO.get(nivel, 0x3A)))
        self._cache = None
        self.pedir_completo()

    def reposicionar_depois_de_redimensionar(self) -> None:
        QTimer.singleShot(0, self.posicionar)

    def nativeEvent(self, tipo, mensagem):
        try:
            msg = wt.MSG.from_address(int(mensagem))
        except Exception:
            return False, 0
        m = msg.message
        if m == winapi.WM_WINDOWPOSCHANGING and not self.teste_topo:
            wp = winapi.WINDOWPOS.from_address(msg.lParam)
            wp.hwndInsertAfter = winapi.HWND_BOTTOM
            wp.flags &= ~winapi.SWP_NOZORDER
        elif m == winapi.WM_MOUSEACTIVATE:
            return True, winapi.MA_NOACTIVATE
        elif m == winapi.MSG_MOSTRAR:
            self.show()
            winapi.enviar_para_o_fundo(self._hwnd)
            return True, 0
        elif m == winapi.MSG_SAIR:
            pop = QApplication.activePopupWidget()   # menu aberto prende o laço de eventos
            if pop is not None:
                pop.close()
            QTimer.singleShot(0, QApplication.quit)
            return True, 0
        return False, 0

    # ------------------------------------------------------------------ posição

    def tela_configurada(self):
        nome = self.cfg.get("monitor")
        for t in QGuiApplication.screens():
            if t.name() == nome:
                return t
        return QGuiApplication.primaryScreen()

    def posicionar(self) -> None:
        tela = self.tela_configurada()
        g = tela.geometry()
        larg, alt = self.width(), self.height()
        margem = 24
        if self.cfg["livre"]:
            x, y = g.x() + self.cfg["x_rel"], g.y() + self.cfg["y_rel"]
        else:
            ancora = self.cfg["ancora"]
            x = g.x() + (margem if "esq" in ancora else g.width() - larg - margem)
            y = g.y() + (margem if ancora.startswith("sup") else g.height() - alt - margem)
            if ancora == "centro":
                x, y = g.x() + (g.width() - larg) // 2, g.y() + (g.height() - alt) // 2
        x = max(g.x(), min(x, g.x() + g.width() - larg))
        y = max(g.y(), min(y, g.y() + g.height() - alt))
        self.move(int(x), int(y))

    def _salvar_posicao_livre(self) -> None:
        centro = self.frameGeometry().center()
        tela = QGuiApplication.screenAt(centro) or self.tela_configurada()
        g = tela.geometry()
        x, y = self.x(), self.y()
        margem = 24
        # ímã nas bordas: gruda a 28 px do canto/margem
        if abs(x - (g.x() + margem)) < 28:
            x = g.x() + margem
        if abs(x - (g.x() + g.width() - self.width() - margem)) < 28:
            x = g.x() + g.width() - self.width() - margem
        if abs(y - (g.y() + margem)) < 28:
            y = g.y() + margem
        if abs(y - (g.y() + g.height() - self.height() - margem)) < 28:
            y = g.y() + g.height() - self.height() - margem
        self.move(x, y)
        self.cfg.update(monitor=tela.name(), livre=True, x_rel=x - g.x(), y_rel=y - g.y())
        self.cfg.salvar()

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and not self.cfg["travado"]:
            self._arrasto = ev.globalPosition() - QPointF(self.pos())
            self.setCursor(Qt.SizeAllCursor)

    def mouseMoveEvent(self, ev) -> None:
        if self._arrasto is not None:
            p = ev.globalPosition() - self._arrasto
            self.move(int(p.x()), int(p.y()))

    def mouseReleaseEvent(self, ev) -> None:
        if self._arrasto is not None:
            self._arrasto = None
            self.unsetCursor()
            self._salvar_posicao_livre()
            winapi.enviar_para_o_fundo(self._hwnd)

    def contextMenuEvent(self, ev) -> None:
        self.criar_menu().exec(ev.globalPos())

    # ------------------------------------------------------------------ pintura

    def _f(self, px: float, peso=QFont.Weight.Medium, espaco: float = 0.0) -> QFont:
        chave = (px, peso, espaco)
        f = self._fontes.get(chave)
        if f is None:
            f = QFont("Inter")
            f.setPointSizeF(px * 0.75)
            f.setWeight(peso)
            f.setFeature(QFont.Tag("tnum"), 1)
            f.setKerning(True)
            if espaco:
                f.setLetterSpacing(QFont.AbsoluteSpacing, espaco)
            self._fontes[chave] = f
        return f

    def _t(self, p: QPainter, x: float, y: float, w: float, h: float, s: str, fonte: QFont,
           c: QColor, alinh=Qt.AlignLeft) -> None:
        p.setFont(fonte)
        p.setPen(c)
        p.drawText(QRectF(x, y, w, h), alinh | Qt.AlignVCenter, s)

    def _larg(self, s: str, fonte: QFont) -> float:
        return QFontMetricsF(fonte).horizontalAdvance(s)

    def paintEvent(self, _ev) -> None:
        self.e = suave(min(1.0, (time.monotonic() - self.t0) / DURACAO)) if self.t0 else 1.0
        for t in self.tw.values():
            t.passo(self.e)
        self._garantir_cache()
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawPixmap(0, 0, self._cache)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if self.d is not None:
            for chave, r in self.rects.items():
                getattr(self, f"_c_{chave}")(p, r, False)
        p.end()

    def _garantir_cache(self) -> None:
        dpr = self.devicePixelRatioF()
        if self._cache is not None and self._cache_dpr == dpr and not self._cache_sujo:
            return
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self._fundo(q)
        for r in self.rects.values():
            self._cartao(q, r)
        self._cabecalho(q)
        if self.d is not None:
            for chave, r in self.rects.items():
                getattr(self, f"_c_{chave}")(q, r, True)
        q.end()
        self._cache, self._cache_dpr, self._cache_sujo = pm, dpr, False

    def _b(self, chave: str, padrao: float = 0.0) -> float:
        """Valor-alvo (sem animação) para o que só muda a cada amostra."""
        t = self.tw.get(chave)
        return t.b if t else padrao

    # ---- peças comuns

    def _fundo(self, p: QPainter) -> None:
        t = self.t
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(cor(t.tinta, VIDROS.get(self.cfg["vidro"], 150)))
        p.drawRoundedRect(r, RAIO_JANELA, RAIO_JANELA)
        # lavagem de cor suave nos cantos (dá profundidade ao vidro)
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, RAIO_JANELA, RAIO_JANELA)
        p.setClipPath(clip)
        g1 = QRadialGradient(r.left() + 40, r.top() + 20, 330)
        g1.setColorAt(0, cor(t.lavagem1, t.lavagem1_alpha))
        g1.setColorAt(1, cor(t.lavagem1, 0))
        p.setBrush(g1)
        p.drawRect(r)
        g2 = QRadialGradient(r.right() - 20, r.bottom() - 10, 360)
        g2.setColorAt(0, cor(t.lavagem2, t.lavagem2_alpha))
        g2.setColorAt(1, cor(t.lavagem2, 0))
        p.setBrush(g2)
        p.drawRect(r)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(cor(t.borda, 52), 1))
        p.drawRoundedRect(r, RAIO_JANELA, RAIO_JANELA)

    def _cartao(self, p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.NoPen)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, cor(self.t.cartao, 24))
        g.setColorAt(1, cor(self.t.cartao, 10))
        p.setBrush(g)
        p.drawRoundedRect(r, RAIO_CARD, RAIO_CARD)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(cor(self.t.cartao, 24), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), RAIO_CARD, RAIO_CARD)

    def _rotulo(self, p: QPainter, x: float, y: float, titulo: str, acento: str, sub: str = "") -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(cor(acento))
        p.drawEllipse(QPointF(x + 3.5, y + 8), 3.5, 3.5)
        f = self._f(10.5, QFont.Weight.Bold, 1.4)
        self._t(p, x + 13, y, 200, 16, titulo, f, self.T1)
        if sub:
            self._t(p, x + 13 + self._larg(titulo, f) + 8, y, 220, 16, sub,
                    self._f(11, QFont.Weight.Medium), self.T3)

    def _pct_grande(self, p: QPainter, x_dir: float, y: float, valor: float, acento: str) -> None:
        c = calor(acento, valor, self.t) if acento else self.T1
        c = mais_claro(c, 0.18)
        s = f"{valor:.0f}"
        fg, fp = self._f(30, QFont.Weight.DemiBold), self._f(14, QFont.Weight.Medium)
        wp = self._larg("%", fp)
        wn = self._larg(s, fg)
        self._t(p, x_dir - wp - wn - 2, y, wn + 2, 36, s, fg, c, Qt.AlignRight)
        self._t(p, x_dir - wp, y + 7, wp, 22, "%", fp, self.T2, Qt.AlignRight)

    def _barra(self, p: QPainter, r: QRectF, pct: float, acento: str, aquecer: bool = True) -> None:
        raio = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(cor(self.t.cartao, 22))
        p.drawRoundedRect(r, raio, raio)
        frac = max(0.0, min(1.0, pct / 100.0))
        if frac <= 0.001:
            return
        w = max(r.height(), r.width() * frac)
        cheio = QRectF(r.x(), r.y(), w, r.height())
        base = calor(acento, pct, self.t) if aquecer else QColor(acento)
        g = QLinearGradient(cheio.topLeft(), cheio.topRight())
        g.setColorAt(0, base)
        g.setColorAt(1, mais_claro(base, 0.32))
        p.setBrush(g)
        p.drawRoundedRect(cheio, raio, raio)

    def _grafico(self, p: QPainter, r: QRectF, series, vmax: float, acento: str, preencher=True,
                 largura: float = 1.7) -> None:
        n = len(series)
        if n < 3:
            return
        passo = r.width() / (PONTOS - 2)
        deslocamento = (1 - self.e) * passo
        pts = []
        for i, v in enumerate(series):
            x = r.right() - (n - 1 - i) * passo + deslocamento
            y = r.bottom() - 2 - max(0.0, min(1.0, v / vmax)) * (r.height() - 5)
            pts.append((x, y))
        linha = QPainterPath(QPointF(*pts[0]))
        for i in range(1, n - 1):
            mx, my = (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2
            linha.quadTo(pts[i][0], pts[i][1], mx, my)
        linha.lineTo(*pts[-1])
        p.save()
        p.setClipRect(r.adjusted(-1, -2, 1, 2))
        if preencher:
            area = QPainterPath(linha)
            area.lineTo(pts[-1][0], r.bottom() + 2)
            area.lineTo(pts[0][0], r.bottom() + 2)
            area.closeSubpath()
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            g.setColorAt(0, cor(acento, 110))
            g.setColorAt(1, cor(acento, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawPath(area)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(cor(acento, 46), largura + 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(linha)
        p.setPen(QPen(mais_claro(QColor(acento), 0.12), largura, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(linha)
        p.restore()

    def _grade(self, p: QPainter, r: QRectF) -> None:
        p.setPen(QPen(cor(self.t.cartao, 13), 1))
        for f in (0.25, 0.5, 0.75):
            y = r.top() + r.height() * f
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))

    # ---- cabeçalho

    def _cabecalho(self, p: QPainter) -> None:
        x, y = MARGEM, MARGEM
        if self._arte is not None and not self._arte.isNull():
            dpr = self.devicePixelRatioF()
            pm = self._arte_cache.get(dpr)
            if pm is None:                     # reduz 1x com filtro suave para o tamanho real em pixels
                lado = int(40 * dpr)
                pm = self._arte.scaled(lado, lado, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
                self._arte_cache[dpr] = pm
            p.drawPixmap(int(x - 3), int(y + 3), pm)
        else:
            ic = QRectF(x, y + 6, 34, 34)
            g = QLinearGradient(ic.topLeft(), ic.bottomRight())
            g.setColorAt(0, cor(self.t.marca[0]))
            g.setColorAt(1, cor(self.t.marca[1]))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(ic, 10, 10)
            p.setBrush(QColor(255, 255, 255, 235))
            for i, h in enumerate((10, 18, 13)):
                p.drawRoundedRect(QRectF(ic.x() + 9 + i * 6.5, ic.bottom() - 8 - h, 4, h), 2, 2)
        self._t(p, x + 44, y + 4, 200, 22, "Monitor do PC", self._f(15, QFont.Weight.DemiBold), self.T1)
        sub = f"Ligado há {duracao(self.d['uptime'])}" if self.d else "Iniciando…"
        self._t(p, x + 44, y + 24, 220, 18, sub, self._f(11.5, QFont.Weight.Medium), self.T2)
        agora = datetime.now()
        direita = x + self._larg_header
        self._t(p, direita - 120, y + 2, 120, 26, agora.strftime("%H:%M"),
                self._f(21, QFont.Weight.DemiBold), self.T1, Qt.AlignRight)
        data = f"{SEMANA[agora.weekday()]}, {agora.day} {MESES[agora.month - 1]}"
        self._t(p, direita - 120, y + 26, 120, 16, data, self._f(11.5, QFont.Weight.Medium), self.T2,
                Qt.AlignRight)

    # ---- cartões: cada um desenha a parte estática (texto, 1x/s) ou a dinâmica (todo quadro)

    def _c_cpu(self, p: QPainter, r: QRectF, estatico: bool) -> None:
        cpu = self.d["cpu"]
        x, w = r.x() + INT, r.width() - 2 * INT
        if estatico:
            self._rotulo(p, x, r.y() + 14, "CPU", self.t.cpu, self.coletor.cpu_nome)
            info = f"{self.coletor.cpu_threads} threads"
            if cpu["ghz"]:
                info = f"{num(cpu['ghz'], 2)} GHz  ·  " + info
            self._t(p, x, r.y() + 33, w - 70, 16, info, self._f(11.5), self.T2)
            self._grade(p, QRectF(x, r.y() + 56, w, 44))
            return
        self._pct_grande(p, r.right() - INT, r.y() + 10, self._v("cpu"), self.t.cpu)
        self._grafico(p, QRectF(x, r.y() + 56, w, 44), self.h_cpu, 100.0, self.t.cpu)
        if self.cfg["mostrar_nucleos"]:
            n = len(cpu["nucleos"])
            area = QRectF(x, r.y() + 110, w, 28)
            esp = 3.0
            lb = (area.width() - esp * (n - 1)) / n
            p.setPen(Qt.NoPen)
            for i in range(n):
                v = self._v(f"n{i}")
                bx = area.x() + i * (lb + esp)
                p.setBrush(cor(self.t.cartao, 20))
                p.drawRoundedRect(QRectF(bx, area.y(), lb, area.height()), 2, 2)
                h = max(2.0, area.height() * min(100.0, v) / 100.0)
                p.setBrush(calor(mais_claro(QColor(self.t.cpu), 0.1), v, self.t))
                p.drawRoundedRect(QRectF(bx, area.bottom() - h, lb, h), 2, 2)

    def _c_ram(self, p: QPainter, r: QRectF, estatico: bool) -> None:
        ram = self.d["ram"]
        x, w = r.x() + INT, r.width() - 2 * INT
        if estatico:
            self._rotulo(p, x, r.y() + 14, "MEMÓRIA", self.t.ram, "RAM")
            f = self._f(22, QFont.Weight.DemiBold)
            usada = cap(ram["usada"])
            self._t(p, x, r.y() + 34, 140, 28, usada, f, self.T1)
            self._t(p, x + self._larg(usada, f) + 6, r.y() + 40, 140, 20, "de " + cap(ram["total"]),
                    self._f(12), self.T2)
            self._t(p, x, r.y() + 82, w, 16, f"{cap(ram['livre'])} livres", self._f(11.5), self.T2)
            return
        self._pct_grande(p, r.right() - INT, r.y() + 10, self._v("ram"), self.t.ram)
        self._barra(p, QRectF(x, r.y() + 70, w, 8), self._v("ram"), self.t.ram)

    def _c_gpu(self, p: QPainter, r: QRectF, estatico: bool) -> None:
        gpu = self.d["gpu"]
        x, w = r.x() + INT, r.width() - 2 * INT
        if estatico:
            self._rotulo(p, x, r.y() + 14, "GPU", self.t.gpu, gpu["nome"])
            partes = []
            if gpu["temp"] is not None:
                partes.append(f"{gpu['temp']} °C")
            if gpu["watts"] is not None:
                partes.append(f"{gpu['watts']:.0f} W")
            if gpu["clock_mhz"]:
                partes.append(f"{num(gpu['clock_mhz'] / 1000, 2)} GHz")
            self._t(p, x, r.y() + 33, w - 70, 16, "  ·  ".join(partes), self._f(11.5), self.T2)
            self._grade(p, QRectF(x, r.y() + 56, w, 38))
            self._t(p, x, r.y() + 100, 100, 16, "VRAM", self._f(10.5, QFont.Weight.Bold, 1.2), self.T2)
            self._t(p, x, r.y() + 100, w, 16, f"{cap(gpu['vram_usada'])} de {cap(gpu['vram_total'])}",
                    self._f(11.5), self.T2, Qt.AlignRight)
            return
        self._pct_grande(p, r.right() - INT, r.y() + 10, self._v("gpu"), self.t.gpu)
        self._grafico(p, QRectF(x, r.y() + 56, w, 38), self.h_gpu, 100.0, self.t.gpu)
        self._barra(p, QRectF(x, r.y() + 120, w, 8), self._v("vram"), self.t.gpu)

    def _c_rede(self, p: QPainter, r: QRectF, estatico: bool) -> None:
        rede = self.d["rede"]
        x, w = r.x() + INT, r.width() - 2 * INT
        g = QRectF(x, r.y() + 98, w, 36)
        if estatico:
            sub = rede["tipo"]
            if rede["link_bps"]:
                v, u = taxa_bits(rede["link_bps"])
                sub += f"  ·  {v} {u}"
            self._rotulo(p, x, r.y() + 14, "REDE", self.t.down, sub)
            metade = w / 2
            plano = float(self.cfg.get("plano_mbps", 700)) * 1e6
            for i, (chave, titulo, acento, seta) in enumerate(
                    (("down", "Download", self.t.down, "↓"), ("up", "Upload", self.t.up, "↑"))):
                cx = x + i * metade
                bps = max(0.0, self._b(chave))
                valor, unidade = taxa_bits(bps)
                self._t(p, cx, r.y() + 34, metade, 14, f"{seta}  {titulo}",
                        self._f(11, QFont.Weight.Medium), cor(acento))
                f = self._f(22, QFont.Weight.DemiBold)
                self._t(p, cx, r.y() + 48, metade, 28, valor, f, self.T1)
                self._t(p, cx + self._larg(valor, f) + 5, r.y() + 55, 60, 20, unidade, self._f(12), self.T2)
                extra = taxa_bytes(bps / 8)
                if chave == "down" and plano > 0:
                    extra += f"  ·  {bps * 100 / plano:.0f}% do plano"
                self._t(p, cx, r.y() + 76, metade, 14, extra, self._f(11), self.T3)
            self._grade(p, g)
            return
        escala = max(10e6, self._v("escala_rede", 10e6))
        self._grafico(p, g, self.h_down, escala, self.t.down)
        self._grafico(p, g, self.h_up, escala, self.t.up, preencher=False, largura=1.5)

    def _c_disco(self, p: QPainter, r: QRectF, estatico: bool) -> None:
        if not estatico:
            return
        x, w = r.x() + INT, r.width() - 2 * INT
        self._rotulo(p, x, r.y() + 14, "ARMAZENAMENTO", self.t.disco)
        y = r.y() + 38
        for dk in self.d["discos"]:
            letra = dk["letra"]
            self._t(p, x, y, 40, 18, letra, self._f(13, QFont.Weight.DemiBold), self.T1)
            if dk["rotulo"]:
                self._t(p, x + 28, y, 130, 18, dk["rotulo"], self._f(11), self.T3)
            self._t(p, x, y, w, 18, f"{cap(dk['usado'])} de {cap(dk['total'])}", self._f(11.5), self.T2,
                    Qt.AlignRight)
            self._barra(p, QRectF(x, y + 22, w, 6), self._b("d_" + letra), self.t.disco)
            self._t(p, x, y + 31, w, 14, f"{cap(dk['livre'])} livres", self._f(11), self.T2)
            ativ = f"Leitura {taxa_bytes(dk['leitura'])}  ·  Gravação {taxa_bytes(dk['escrita'])}"
            self._t(p, x + 70, y + 31, w - 70, 14, ativ, self._f(11), self.T3, Qt.AlignRight)
            y += 54

    def _c_proc(self, p: QPainter, r: QRectF, estatico: bool) -> None:
        if not estatico:
            return
        x, w = r.x() + INT, r.width() - 2 * INT
        self._rotulo(p, x, r.y() + 14, "MAIORES USOS DE RAM", self.t.neutro)
        y = r.y() + 38
        fonte = self._f(12, QFont.Weight.Medium)
        fm = QFontMetricsF(fonte)
        for i, (nome, qtd, bytes_) in enumerate(self.procs[:5]):
            rotulo = nome + (f"  ×{qtd}" if qtd > 1 else "")
            self._t(p, x, y, w - 70, 16, fm.elidedText(rotulo, Qt.ElideRight, w - 80), fonte, self.T1)
            self._t(p, x, y, w, 16, cap(bytes_), self._f(12, QFont.Weight.DemiBold), self.T2, Qt.AlignRight)
            self._barra(p, QRectF(x, y + 19, w, 3), self._b(f"p{i}"), self.t.neutro, aquecer=False)
            y += 26
