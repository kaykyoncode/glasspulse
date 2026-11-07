# -*- coding: utf-8 -*-
"""Janela do widget no padrão dos widgets do Thiago: cards pretos em formato de pasta, números finos e
condensados, um único painel neon (amarelo) e gráficos/barras animados a cada amostra."""
from __future__ import annotations

import math
import os
import time
from collections import deque
from ctypes import wintypes as wt
from datetime import datetime

from PySide6.QtCore import QByteArray, QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QCursor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

from . import temas, winapi

# ---- cores do guia (docs/estilo-widgets.md do Luna Token Monitor)
NEON = QColor("#ffe83a")          # Monitor do PC: amarelo (como o card "Nvidia" da referência)
TINTA = QColor("#0b0b0c")         # texto e traços por cima do neon
T1, T2, T3 = QColor("#f1f1f2"), QColor("#a3a3aa"), QColor("#6c6c74")
FIO = QColor(255, 255, 255, 18)   # linhas divisórias (.07)

# ---- medidas (px lógicos)
LARG = 352                        # largura de cada card
PX, PT, PB = 22, 30, 18           # respiro interno: lados, topo, base
CONTEUDO = LARG - 2 * PX
BORDA = 3                         # a janela termina 3 px depois dos cards (cabe o "•••", nada além)
GAP = 12
RAIO, DEGRAU, RECORTE, CURVA = 22, 18, 104, 15
DURACAO = 0.7                     # segundos de animação a cada amostra
QUADRO_MS = 40                    # 25 quadros/s só durante a animação; no resto o widget fica parado
PONTOS = 62                       # histórico (~1 min a 1 amostra/s)

SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

# Ícones em traço (viewBox 24), desenhados como SVG na cor pedida. {c} = cor.
SVG = {
    "pulso": '<path d="M2.5 12.5h4l2.6-6.5 4.2 12.5 2.7-6h5.5"/>',
    "gpu": ('<rect x="2.5" y="6.5" width="19" height="11" rx="2"/><circle cx="9.5" cy="12" r="2.6"/>'
            '<path d="M15 10.2h3.5M15 13.8h3.5M6 17.5V20M10 17.5V20"/>'),
    "rede": '<path d="M8 4v15M4.5 15.5 8 19l3.5-3.5"/><path d="M16 20V5M12.5 8.5 16 5l3.5 3.5"/>',
    "disco": ('<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.66 3.58 3 8 3s8-1.34 8-3V6"/>'
              '<path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3"/>'),
    "fixar": '<path d="M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6z"/><path d="M12 15v6"/>',
    "fixado": '<path d="M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6z" fill="{c}"/><path d="M12 15v6"/>',
    "baixar": '<path d="M12 4v15M6 13l6 6 6-6"/>',
    "subir": '<path d="M12 20V5M6 11l6-6 6 6"/>',
    "plano": '<path d="M4.5 17.5a8.5 8.5 0 1 1 15 0"/><path d="m12 13 4-4.5"/>',
    "link": ('<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/>'
             '<path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>'),
    "vram": ('<rect x="4" y="7" width="16" height="10" rx="1.5"/>'
             '<path d="M8 7V4.5M12 7V4.5M16 7V4.5M8 19.5V17M12 19.5V17M16 19.5V17"/>'),
    "temp": '<path d="M14 14.76V5a2 2 0 0 0-4 0v9.76a4 4 0 1 0 4 0z"/>',
    "energia": '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6z"/>',
    "jogo": ('<path d="M7 8h10a4 4 0 0 1 4 4.4l-.6 3.5a2.4 2.4 0 0 1-4.1 1.2L14.5 15h-5l-1.8 2.1a2.4 2.4 0 0 '
             '1-4.1-1.2L3 12.4A4 4 0 0 1 7 8z"/><path d="M8 10.5v3.5M6.25 12.25h3.5"/>'
             '<circle cx="15.6" cy="11.4" r="1" fill="{c}" stroke="none"/>'
             '<circle cx="17.6" cy="13.4" r="1" fill="{c}" stroke="none"/>'),
}

BARLOW = {300: "Barlow Semi Condensed Light", 400: "Barlow Semi Condensed", 500: "Barlow Semi Condensed Medium"}
BAHNSCHRIFT = {300: "Light SemiCondensed", 400: "SemiLight SemiCondensed", 500: "SemiCondensed"}


class _Paleta:
    """Cores do diálogo do Modo Jogo no mesmo padrão do widget."""
    tinta = "#111113"
    texto = "#F1F1F2"
    cartao = "#FFFFFF"
    medio = "#FFE83A"
    marca = ["#FFE83A", "#FFE83A"]
    texto_botao = "#0B0B0C"


PALETA_DIALOGO = _Paleta()


def cor(c: QColor | str, a: float) -> QColor:
    """Cor com opacidade a (0..1)."""
    q = QColor(c)
    q.setAlphaF(max(0.0, min(1.0, a)))
    return q


def misturar(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


def suave(t: float) -> float:
    return 1 - (1 - t) ** 3


CINZA_BARRA = QColor("#7d7d86")


def cor_carga(frac: float) -> QColor:
    """Barras ficam cinza no uso normal e só acendem no neon quando apertam (80% → 95%)."""
    return misturar(CINZA_BARRA, NEON, (frac - 0.8) / 0.15) if frac > 0.8 else CINZA_BARRA


def num(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def cap_partes(b: float) -> tuple[str, str]:
    g = b / 1024 ** 3
    if g >= 1000:
        return num(g / 1024, 2), "TB"
    return (num(g, 0) if g >= 100 else num(g, 1)), "GB"


def cap(b: float) -> str:
    v, u = cap_partes(b)
    return f"{v} {u}"


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


def retangulo(r: QRectF, raio: float) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(r, raio, raio)
    return p


def caminho_pasta(r: QRectF) -> QPainterPath:
    """Contorno do card em formato de pasta: aba alta à esquerda, recorte mais baixo à direita."""
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    rr, d, c = RAIO, DEGRAU, CURVA
    aba = w - RECORTE
    p = QPainterPath(QPointF(x + rr, y))
    p.lineTo(x + aba - c, y)
    p.cubicTo(x + aba, y, x + aba, y + d, x + aba + c, y + d)
    p.lineTo(x + w - rr, y + d)
    p.arcTo(QRectF(x + w - 2 * rr, y + d, 2 * rr, 2 * rr), 90, -90)
    p.lineTo(x + w, y + h - rr)
    p.arcTo(QRectF(x + w - 2 * rr, y + h - 2 * rr, 2 * rr, 2 * rr), 0, -90)
    p.lineTo(x + rr, y + h)
    p.arcTo(QRectF(x, y + h - 2 * rr, 2 * rr, 2 * rr), 270, -90)
    p.lineTo(x, y + rr)
    p.arcTo(QRectF(x, y, 2 * rr, 2 * rr), 180, -90)
    p.closeSubpath()
    return p


class Tween:
    __slots__ = ("a", "b", "v")

    def __init__(self, v: float = 0.0) -> None:
        self.a = self.b = self.v = v

    def para(self, alvo: float) -> None:
        self.a, self.b = self.v, alvo

    def passo(self, e: float) -> None:
        self.v = self.a + (self.b - self.a) * e


class Fontes:
    """Números em Barlow Semi Condensed (Bahnschrift SemiCondensed se faltar); interface em Inter."""

    def __init__(self) -> None:
        fams = set(QFontDatabase.families())
        self.barlow = all(f in fams for f in BARLOW.values())
        self._cache: dict[tuple, QFont] = {}
        self._fm: dict[tuple, QFontMetricsF] = {}

    def _base(self, f: QFont, px: float, espaco: float) -> QFont:
        f.setPointSizeF(px * 0.75)
        f.setKerning(True)
        f.setFeature(QFont.Tag("tnum"), 1)
        if espaco:
            f.setLetterSpacing(QFont.AbsoluteSpacing, espaco)
        return f

    def num(self, px: float, peso: int = 300, espaco_em: float = 0.0) -> QFont:
        chave = ("n", px, peso, espaco_em)
        f = self._cache.get(chave)
        if f is None:
            if self.barlow:
                f = QFont(BARLOW[peso])
            else:
                f = QFont("Bahnschrift")
                f.setStyleName(BAHNSCHRIFT[peso])
            f.setHintingPreference(QFont.PreferNoHinting)
            f = self._cache[chave] = self._base(f, px, espaco_em * px)
        return f

    def ui(self, px: float, peso: int = 400, espaco_em: float = 0.0) -> QFont:
        chave = ("u", px, peso, espaco_em)
        f = self._cache.get(chave)
        if f is None:
            f = QFont("Inter")
            f.setWeight(QFont.Weight(peso))
            f.setHintingPreference(QFont.PreferVerticalHinting)
            f = self._cache[chave] = self._base(f, px, espaco_em * px)
        return f

    def medidas(self, f: QFont) -> QFontMetricsF:
        chave = (f.family(), f.styleName(), f.pointSizeF(), f.weight(), f.letterSpacing())
        m = self._fm.get(chave)
        if m is None:
            m = self._fm[chave] = QFontMetricsF(f)
        return m


class MonitorWidget(QWidget):
    def __init__(self, cfg, coletor, processos, criar_menu) -> None:
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint
        super().__init__(None, flags)
        self.cfg, self.coletor, self.processos, self.criar_menu = cfg, coletor, processos, criar_menu
        self.setWindowTitle(winapi.TITULO_JANELA)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_MacShowFocusRect, False)

        self.t = temas.obter(cfg.get("tema"))    # só define a arte do ícone da bandeja
        self.paleta = PALETA_DIALOGO
        self.fontes = Fontes()
        self._svgs: dict[tuple, QSvgRenderer] = {}
        self.d: dict | None = None
        self.procs: list = []
        self.tw: dict[str, Tween] = {}
        self.h_cpu = deque([0.0] * PONTOS, maxlen=PONTOS)
        self.h_gpu = deque([0.0] * PONTOS, maxlen=PONTOS)
        self.h_down = deque([0.0] * PONTOS, maxlen=PONTOS)
        self.h_up = deque([0.0] * PONTOS, maxlen=PONTOS)
        self.amostras = 0
        self.t0 = 0.0
        self.e = 1.0
        self._arrasto: QPoint | None = None
        self._apertado: str | None = None
        self._hover: str | None = None
        self._hwnd = 0
        self.teste_topo = False                # --teste-topo: sempre por cima, sem salvar nada
        self.suspenso = False                  # jogo em tela cheia no mesmo monitor: sai de cima dele
        self.no_topo = False
        # Aberto de propósito (bandeja / 2ª instância) com o alfinete desligado: fica na frente dos
        # apps até o foco mudar para outra janela, e então volta para trás deles.
        self._na_frente = False
        self._frente_desde = 0.0
        self._fg_frente = 0
        self._com_foco = False
        self._aviso: tuple[str, float] | None = None
        self._fundo: QPixmap | None = None     # cards, logos e painel neon (muda só com layout/escala)
        self._cache: QPixmap | None = None     # fundo + textos (refeito a cada amostra)
        self._cache_dpr = 0.0
        self._cache_sujo = True
        self.estado_jogo = {"ativo": False, "ocupado": "", "linha": ""}
        self.ao_modo_jogo = None               # o app liga ao controle do Modo Jogo
        self.L: dict[str, QRectF] = {}
        self.cartoes: dict[str, QRectF] = {}
        self.layout_efetivo = cfg["layout"]
        self.setMouseTracking(True)

        self.anim = QTimer(self)
        self.anim.setTimerType(Qt.CoarseTimer)
        self.anim.setInterval(QUADRO_MS)
        self.anim.timeout.connect(self._quadro)

        # Movimento que não veio do arraste (Windows, troca de monitor/escala): confere logo depois.
        self._vigia = QTimer(self)
        self._vigia.setSingleShot(True)
        self._vigia.setInterval(600)
        self._vigia.timeout.connect(self.garantir_visivel)

        self._frente = QTimer(self)
        self._frente.setInterval(400)
        self._frente.timeout.connect(self._vigiar_frente)

        self.recalcular_layout()

    # ------------------------------------------------------------------ layout

    def _montar_sis(self, x: float, y: float, L: dict) -> float:
        c = self.cfg
        cx, yy = x + PX, y + PT
        L["sis.cab"] = QRectF(cx, yy, CONTEUDO, 38)
        L["sis.pin"] = QRectF(x + LARG - PX - 30, yy, 30, 30)
        yy += 38 + 14
        L["sis.heroi"] = QRectF(cx, yy, CONTEUDO, 86)
        yy += 86
        if c["mostrar_nucleos"]:
            yy += 14
            L["sis.nucleos"] = QRectF(cx, yy, CONTEUDO, 24)
            yy += 24
        yy += 18
        L["sis.mem_cab"] = QRectF(cx, yy, CONTEUDO, 13)
        yy += 13 + 7
        L["sis.neon"] = QRectF(cx, yy, CONTEUDO, 80)
        yy += 80
        if c["mostrar_processos"]:
            yy += 20
            L["sis.proc_cab"] = QRectF(cx, yy, CONTEUDO, 13)
            yy += 13 + 4
            L["sis.procs"] = QRectF(cx, yy, CONTEUDO, 5 * 25)
            yy += 5 * 25
        if c["mostrar_modo_jogo"]:
            yy += 16
            L["sis.jogo"] = QRectF(cx, yy, CONTEUDO, 42)
            yy += 42
        yy += 14
        L["sis.nota"] = QRectF(cx, yy, CONTEUDO, 23)
        yy += 23 + PB
        return yy - y

    def _montar_gpu(self, x: float, y: float, L: dict) -> float:
        cx, yy = x + PX, y + PT
        L["gpu.cab"] = QRectF(cx, yy, CONTEUDO, 38)
        yy += 38 + 14
        L["gpu.heroi"] = QRectF(cx, yy, CONTEUDO, 86)
        yy += 86 + 20
        L["gpu.stats"] = QRectF(cx, yy, CONTEUDO, 70)
        yy += 70 + PB
        return yy - y

    def _montar_rede(self, x: float, y: float, L: dict) -> float:
        cx, yy = x + PX, y + PT
        L["rede.cab"] = QRectF(cx, yy, CONTEUDO, 38)
        yy += 38 + 18
        L["rede.stats"] = QRectF(cx, yy, CONTEUDO, 70)
        yy += 70 + 14
        L["rede.graf"] = QRectF(cx, yy, CONTEUDO, 44)
        yy += 44 + PB
        return yy - y

    def _montar_disco(self, x: float, y: float, L: dict) -> float:
        cx, yy = x + PX, y + PT
        L["disco.cab"] = QRectF(cx, yy, CONTEUDO, 38)
        yy += 38 + 18
        n = max(1, len(self.d["discos"])) if self.d else 2
        for i in range(n):
            if i:
                yy += 16
            L[f"disco.{i}"] = QRectF(cx, yy, CONTEUDO, 46)
            yy += 46
        yy += PB
        return yy - y

    def _ordem(self) -> list[str]:
        ordem = ["sis"]
        if self.coletor.nvml:
            ordem.append("gpu")
        return ordem + ["rede", "disco"]

    def _medir(self, layout: str) -> tuple[int, int, dict[str, tuple[float, float]]]:
        """Tamanho da janela e canto de cada card para o layout pedido."""
        alt = {k: getattr(self, f"_montar_{k}")(0, 0, {}) for k in self._ordem()}
        pos: dict[str, tuple[float, float]] = {}
        if layout == "painel":
            colunas = [["sis"], [k for k in self._ordem() if k != "sis"]]
            base = 0.0
            for i, col in enumerate(colunas):
                y = BORDA
                for k in col:
                    pos[k] = (BORDA + i * (LARG + GAP), y)
                    y += alt[k] + GAP
                base = max(base, y - GAP)
            return 2 * BORDA + 2 * LARG + GAP, int(math.ceil(base + BORDA)), pos
        y = BORDA
        for k in self._ordem():
            pos[k] = (BORDA, y)
            y += alt[k] + GAP
        return 2 * BORDA + LARG, int(math.ceil(y - GAP + BORDA)), pos

    def recalcular_layout(self) -> None:
        layout = self.cfg["layout"]
        w, h, pos = self._medir(layout)
        # Empilhado não coube na altura do monitor: usa lado a lado (e vice-versa), sem mexer na escolha.
        a = self._tela_atual().availableGeometry()
        outro = "painel" if layout == "coluna" else "coluna"
        if h > a.height() or w > a.width():
            w2, h2, pos2 = self._medir(outro)
            if h2 <= a.height() and w2 <= a.width():
                layout, w, h, pos = outro, w2, h2, pos2
        self.layout_efetivo = layout
        L: dict[str, QRectF] = {}
        self.cartoes = {}
        for k, (x, y) in pos.items():
            altura = getattr(self, f"_montar_{k}")(x, y, L)
            self.cartoes[k] = QRectF(x, y, LARG, altura)
        self.L = L
        self._fundo = None
        # Múltiplo de 4: em 125/150/175% o tamanho em pixels físicos fica inteiro e o widget não passa
        # nem 1 pixel da borda do monitor por arredondamento (a sobra é transparente e não pega clique).
        self.setFixedSize((w + 3) // 4 * 4, (h + 3) // 4 * 4)
        self.pedir_completo()

    # ------------------------------------------------------------------ dados

    def aplicar(self, d: dict, procs: list) -> None:
        primeira = self.d is None
        n_antes = len(self.d["discos"]) if self.d else -1
        self.d, self.procs = d, procs
        if primeira or len(d["discos"]) != n_antes:
            self.recalcular_layout()
            if self._hwnd:
                QTimer.singleShot(0, self.posicionar)
        cpu, ram, gpu, rede = d["cpu"], d["ram"], d["gpu"], d["rede"]
        self.amostras += 1
        self._alvo("cpu", cpu["total"])
        for i, v in enumerate(cpu["nucleos"]):
            self._alvo(f"n{i}", v)
        self._alvo("ram", ram["pct"])
        self.h_cpu.append(cpu["total"])
        self._alvo("esc_cpu", self._escala(self.h_cpu))
        if gpu:
            self._alvo("gpu", gpu["uso"])
            self.h_gpu.append(gpu["uso"])
            self._alvo("esc_gpu", self._escala(self.h_gpu))
        self.h_down.append(rede["down_bps"])
        self.h_up.append(rede["up_bps"])
        self._alvo("down", rede["down_bps"])
        self._alvo("up", rede["up_bps"])
        pico = max(max(self.h_down), max(self.h_up), 10e6)
        self._alvo("escala_rede", pico * 1.18)
        maior = max((p[2] for p in procs), default=1)
        for i, p in enumerate(procs):
            self._alvo(f"p{i}", p[2] * 100.0 / maior)
        self.t0 = time.monotonic()
        self.e = 0.0
        if not self.anim.isActive():
            self.anim.start()
        self.pedir_completo()

    def _escala(self, serie) -> float:
        reais = list(serie)[-max(1, min(self.amostras, PONTOS)):]
        return max(10.0, max(reais) * 1.15)

    def _media(self, serie) -> float:
        reais = list(serie)[-max(1, min(self.amostras, 60)):]
        return sum(reais) / len(reais)

    def _alvo(self, chave: str, valor: float) -> None:
        t = self.tw.get(chave)
        if t is None:
            self.tw[chave] = Tween(valor)
        else:
            t.para(valor)

    def _v(self, chave: str, padrao: float = 0.0) -> float:
        t = self.tw.get(chave)
        return t.v if t else padrao

    def _b(self, chave: str, padrao: float = 0.0) -> float:
        """Valor-alvo (sem animação) para o que só muda a cada amostra."""
        t = self.tw.get(chave)
        return t.b if t else padrao

    def _quadro(self) -> None:
        if time.monotonic() - self.t0 >= DURACAO:
            self.anim.stop()
        self.update()

    def pedir_completo(self) -> None:
        """Dados, layout ou aparência mudaram: refaz a camada estática no próximo quadro."""
        self._cache_sujo = True
        self.update()

    def avisar(self, texto: str) -> None:
        """Aviso curto no rodapé do card principal."""
        self._aviso = (texto, time.monotonic() + 2.6)
        self.pedir_completo()
        QTimer.singleShot(2700, self.pedir_completo)

    # ------------------------------------------------------------------ janela nativa

    def preparar_nativo(self) -> None:
        self._hwnd = int(self.winId())
        winapi.aplicar_estilo_widget(self._hwnd)
        winapi.preparar_transparente(self._hwnd)
        self.aplicar_fixacao()
        h = self.windowHandle()
        if h is not None:
            h.screenChanged.connect(lambda *_: (self.pedir_completo(), self._vigia.start()))

    def quer_topo(self) -> bool:
        return bool(self.cfg["fixado"]) or self.teste_topo

    def fixado_efetivo(self) -> bool:
        return self.quer_topo() and not self.suspenso

    def aplicar_fixacao(self) -> None:
        """Fixado: sempre por cima das janelas (HWND_TOPMOST). Solto (padrão): atrás de todos os apps,
        logo acima da área de trabalho (HWND_NOTOPMOST e depois HWND_BOTTOM)."""
        self._na_frente = False
        self._frente.stop()
        if not self._hwnd:
            return
        self.no_topo = self.fixado_efetivo()
        if self.no_topo:
            winapi.soltar_do_desktop(self._hwnd)
            winapi.trazer_ao_topo(self._hwnd)
        else:
            winapi.tirar_do_topo(self._hwnd)
            winapi.fixar_ao_desktop(self._hwnd)
            winapi.enviar_para_o_fundo(self._hwnd)

    def _reforcar_ordem(self) -> None:
        """O Windows traz para a frente a janela ativada/clicada: devolve o widget ao lugar dele."""
        if not self._hwnd or not self.isVisible():
            return
        if self.no_topo:
            winapi.trazer_ao_topo(self._hwnd)
        elif not self._na_frente:
            winapi.enviar_para_o_fundo(self._hwnd)

    def mostrar_na_frente(self) -> None:
        """Aberto de propósito (ícone da bandeja ou 2ª instância). Fixado: só garante o topo. Solto:
        aparece na frente dos apps e volta para trás deles quando o foco muda de janela."""
        if not self.isVisible():
            self.show()
        self.aplicar_fixacao()
        if not self._hwnd or self.no_topo:
            return
        self._na_frente = True
        self._frente_desde = time.monotonic()
        self._fg_frente = 0
        winapi.soltar_do_desktop(self._hwnd)   # dona = área de trabalho prenderia o widget no fundo
        winapi.trazer_a_frente(self._hwnd)
        # Com o foco no widget, qualquer clique em outro app (inclusive no que já estava em uso)
        # conta como "perdeu o foco". Sem permissão do Windows, vale a troca de janela em foco.
        self._com_foco = winapi.tomar_foco(self._hwnd)
        self._frente.start()

    def esta_na_frente(self) -> bool:
        return self.isVisible() and (self.no_topo or self._na_frente)

    def _vigiar_frente(self) -> None:
        if not self._na_frente:
            self._frente.stop()
            return
        fg, pid = winapi.primeiro_plano()
        if not fg:                               # foco em trânsito
            return
        nosso = pid == os.getpid()               # o widget ou um menu dele
        if self._com_foco:
            if not nosso:
                self.aplicar_fixacao()           # perdeu o foco: volta para trás dos apps
            return
        if nosso:
            return
        if time.monotonic() - self._frente_desde < 0.8:
            self._fg_frente = fg                 # o clique na bandeja ainda está assentando o foco
            return
        if not self._fg_frente:
            self._fg_frente = fg
        elif fg != self._fg_frente:
            self.aplicar_fixacao()               # foco foi para outra janela: volta para trás dos apps

    def alternar_fixado(self) -> None:
        self.cfg["fixado"] = not self.cfg["fixado"]
        self.cfg.salvar()
        self.aplicar_fixacao()
        self.avisar("Fixado sobre outras janelas." if self.cfg["fixado"] else "Atrás dos seus apps de novo.")

    def suspender(self, sim: bool) -> None:
        """Jogo/app em tela cheia no monitor do widget: sai de cima enquanto ele estiver aberto."""
        if sim != self.suspenso:
            self.suspenso = sim
            self.aplicar_fixacao()

    def nativeEvent(self, tipo, mensagem):
        try:
            msg = wt.MSG.from_address(int(mensagem))
        except Exception:
            return False, 0
        m = msg.message
        if m == winapi.WM_WINDOWPOSCHANGING and not self.no_topo and not self._na_frente:
            # Solto: qualquer mudança de Z-order (clique, ativação, arraste, Qt) vira "para o fundo".
            wp = winapi.WINDOWPOS.from_address(msg.lParam)
            wp.hwndInsertAfter = winapi.HWND_BOTTOM
            wp.flags &= ~winapi.SWP_NOZORDER
            wp.flags |= winapi.SWP_NOOWNERZORDER
        elif m == winapi.WM_MOUSEACTIVATE:
            return True, winapi.MA_NOACTIVATE
        elif m == winapi.MSG_MOSTRAR:             # 2ª instância aberta: mostra na frente por um momento
            self.mostrar_na_frente()
            return True, 0
        elif m == winapi.MSG_MODO_JOGO:
            if self.ao_modo_jogo:
                QTimer.singleShot(0, self.ao_modo_jogo)
            return True, 0
        elif m == winapi.MSG_SAIR:
            pop = QApplication.activePopupWidget()   # menu aberto prende o laço de eventos
            if pop is not None:
                pop.close()
            QTimer.singleShot(0, QApplication.quit)
            return True, 0
        return False, 0

    def changeEvent(self, ev) -> None:
        super().changeEvent(ev)
        if ev.type() == QEvent.ActivationChange:
            self._reforcar_ordem()

    def event(self, ev) -> bool:
        if ev.type() == QEvent.WindowActivate:
            QTimer.singleShot(0, self._reforcar_ordem)
        return super().event(ev)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        QTimer.singleShot(0, self._reforcar_ordem)

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self._na_frente = False
        self._frente.stop()

    # ------------------------------------------------------------------ posição

    def tela_configurada(self):
        nome = self.cfg.get("monitor")
        for t in QGuiApplication.screens():
            if t.name() == nome:
                return t
        return QGuiApplication.primaryScreen()

    def _tela_atual(self):
        if self.isVisible():
            r = self.geometry()
            melhor, area = None, 0
            for t in QGuiApplication.screens():
                i = t.availableGeometry().intersected(r)
                if i.width() * i.height() > area:
                    melhor, area = t, i.width() * i.height()
            if melhor is not None:
                return melhor
        return self.tela_configurada()

    def _dentro(self, x: int, y: int, a) -> tuple[int, int]:
        """(x, y) ajustado para o widget inteiro caber na área útil `a` do monitor."""
        larg, alt = self.width(), self.height()
        x = a.x() if larg >= a.width() else max(a.x(), min(int(x), a.x() + a.width() - larg))
        y = a.y() if alt >= a.height() else max(a.y(), min(int(y), a.y() + a.height() - alt))
        return x, y

    def posicionar(self) -> None:
        tela = self.tela_configurada()
        g, a = tela.geometry(), tela.availableGeometry()
        larg, alt = self.width(), self.height()
        margem = 24
        if self.cfg["livre"]:
            x, y = g.x() + self.cfg["x_rel"], g.y() + self.cfg["y_rel"]
        else:
            ancora = self.cfg["ancora"]
            x = a.x() + (margem if "esq" in ancora else a.width() - larg - margem)
            y = a.y() + (margem if ancora.startswith("sup") else a.height() - alt - margem)
            if ancora == "centro":
                x, y = a.x() + (a.width() - larg) // 2, a.y() + (a.height() - alt) // 2
        self.move(*self._dentro(x, y, a))

    def reposicionar(self) -> None:
        """Monitor ligado/desligado, resolução ou escala nova: refaz o layout e volta para dentro."""
        self.recalcular_layout()
        self.posicionar()
        self.garantir_visivel()

    def garantir_visivel(self) -> None:
        """Se qualquer parte do widget estiver fora da área útil, traz para dentro do monitor
        com que ele mais se sobrepõe (ou do configurado, se estiver fora de todos)."""
        if self._arrasto is not None or not self.isVisible():
            return
        r = self.geometry()
        a = self._tela_atual().availableGeometry()
        x, y = self._dentro(r.x(), r.y(), a)
        if (x, y) != (r.x(), r.y()):
            self.move(x, y)

    def moveEvent(self, ev) -> None:
        super().moveEvent(ev)
        if self._arrasto is None and self._hwnd:
            self._vigia.start()

    def _salvar_posicao_livre(self) -> None:
        tela = self._tela_atual()
        g, a = tela.geometry(), tela.availableGeometry()
        x, y = self.x(), self.y()
        margem = 24
        # ímã nas bordas: gruda a 24 px da borda da área útil quando chega perto
        if abs(x - (a.x() + margem)) < 28:
            x = a.x() + margem
        if abs(x - (a.x() + a.width() - self.width() - margem)) < 28:
            x = a.x() + a.width() - self.width() - margem
        if abs(y - (a.y() + margem)) < 28:
            y = a.y() + margem
        if abs(y - (a.y() + a.height() - self.height() - margem)) < 28:
            y = a.y() + a.height() - self.height() - margem
        x, y = self._dentro(x, y, a)
        self.move(x, y)
        self.cfg.update(monitor=tela.name(), livre=True, x_rel=x - g.x(), y_rel=y - g.y())
        self.cfg.salvar()

    # ------------------------------------------------------------------ mouse

    def _alvo_em(self, pos) -> str | None:
        r = self.L.get("sis.pin")
        if r is not None and r.contains(pos):
            return "fixar"
        for k, c in self.cartoes.items():
            if self._pilula(c).adjusted(-4, -3, 4, 4).contains(pos):
                return "menu:" + k
        r = self.L.get("sis.jogo")
        if r is not None and r.contains(pos):
            return "jogo"
        return None

    def _dica(self, alvo: str | None) -> str:
        if alvo == "fixar":
            return ("Soltar: voltar para trás dos apps" if self.cfg["fixado"]
                    else "Fixar sobre outras janelas")
        if alvo and alvo.startswith("menu:"):
            return "Menu"
        if alvo == "jogo":
            return "Desativar Modo Jogo" if self.estado_jogo["ativo"] else "Ativar Modo Jogo"
        return ""

    def _cursor(self) -> None:
        if self._arrasto is not None:
            self.setCursor(Qt.ClosedHandCursor)
        elif self._hover:
            self.setCursor(Qt.PointingHandCursor)
        elif not self.cfg["travado"]:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def _marcar_hover(self, alvo: str | None) -> None:
        if alvo != self._hover:
            self._hover = alvo
            self.setToolTip(self._dica(alvo))
            self._cursor()
            self.pedir_completo()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return
        alvo = self._alvo_em(ev.position())
        if alvo:
            self._apertado = alvo
            return
        if not self.cfg["travado"]:
            self._arrasto = QCursor.pos() - self.pos()
            self._cursor()

    def arrastar_para(self, cursor: QPoint) -> None:
        """O widget segue o mouse e fica inteiro dentro da área útil do monitor onde está o cursor."""
        tela = QGuiApplication.screenAt(cursor) or self._tela_atual()
        x, y = self._dentro(cursor.x() - self._arrasto.x(), cursor.y() - self._arrasto.y(),
                            tela.availableGeometry())
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def mouseMoveEvent(self, ev) -> None:
        if self._arrasto is not None:
            self.arrastar_para(QCursor.pos())
        elif not self._apertado:
            self._marcar_hover(self._alvo_em(ev.position()))

    def leaveEvent(self, ev) -> None:
        if self._arrasto is None:
            self._marcar_hover(None)

    def mouseReleaseEvent(self, ev) -> None:
        if self._apertado:
            alvo, self._apertado = self._apertado, None
            if self._alvo_em(ev.position()) == alvo:
                self._acionar(alvo)
            return
        if self._arrasto is not None:
            self._arrasto = None
            self._cursor()
            self._salvar_posicao_livre()
            self._reforcar_ordem()               # solto: de volta para trás dos apps (fixado: no topo)

    def _acionar(self, alvo: str) -> None:
        if alvo == "fixar":
            self.alternar_fixado()
        elif alvo == "jogo":
            if self.ao_modo_jogo:
                self.ao_modo_jogo()
        elif alvo.startswith("menu:"):
            pil = self._pilula(self.cartoes[alvo[5:]])
            menu = self.criar_menu()
            canto = self.mapToGlobal(QPoint(int(pil.right()), int(pil.bottom()) + 6))
            menu.exec(QPoint(canto.x() - menu.sizeHint().width(), canto.y()))
            self._reforcar_ordem()

    def contextMenuEvent(self, ev) -> None:
        self.criar_menu().exec(ev.globalPos())
        self._reforcar_ordem()

    # ------------------------------------------------------------------ pintura: utilidades

    def _tx(self, p: QPainter, x: float, base: float, s: str, f: QFont, c: QColor, alinh: str = "e") -> float:
        """Texto com a linha de base em `base`; alinh: e (esquerda), d (direita), c (centro)."""
        w = self.fontes.medidas(f).horizontalAdvance(s)
        if alinh == "d":
            x -= w - f.letterSpacing()       # o avanço inclui o espaçamento depois da última letra
        elif alinh == "c":
            x -= w / 2
        p.setFont(f)
        p.setPen(c)
        p.drawText(QPointF(x, base), s)
        return w

    def _larg(self, s: str, f: QFont) -> float:
        return self.fontes.medidas(f).horizontalAdvance(s)

    def _cortar(self, s: str, f: QFont, larg: float) -> str:
        return self.fontes.medidas(f).elidedText(s, Qt.ElideRight, larg)

    def _icone(self, p: QPainter, nome: str, r: QRectF, c: QColor, traco: float = 2.0) -> None:
        chave = (nome, c.rgba(), traco)
        ren = self._svgs.get(chave)
        if ren is None:
            hexa = c.name()
            corpo = SVG[nome].replace("{c}", hexa)
            xml = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{hexa}" '
                   f'stroke-opacity="{c.alphaF():.3f}" stroke-width="{traco}" stroke-linecap="round" '
                   f'stroke-linejoin="round">{corpo}</svg>')
            ren = self._svgs[chave] = QSvgRenderer(QByteArray(xml.encode("utf-8")))
        ren.render(p, r)

    @staticmethod
    def _pilula(c: QRectF) -> QRectF:
        return QRectF(c.right() - 26 - 40, c.top() - 2, 40, 15)

    def _rotulo(self, p: QPainter, r: QRectF, esq: str, dir_: str = "", cor_dir: QColor = T1) -> None:
        """Linha de rótulo acima de um bloco (caixa alta 10,5 px)."""
        f = self.fontes.ui(10.5, 600, 0.1)
        base = r.top() + 10
        self._tx(p, r.x() + 2, base, esq.upper(), f, T2)
        if dir_:
            self._tx(p, r.right() - 2, base, dir_.upper(), f, cor_dir, "d")

    # ------------------------------------------------------------------ pintura: camadas

    def paintEvent(self, _ev) -> None:
        self.e = suave(min(1.0, (time.monotonic() - self.t0) / DURACAO)) if self.t0 else 1.0
        for t in self.tw.values():
            t.passo(self.e)
        self._garantir_cache()
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawPixmap(0, 0, self._cache)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if self.d is not None:
            self._d_sis(p)
            if "gpu" in self.cartoes and self.d["gpu"]:
                self._d_gpu(p)
            self._d_rede(p)
        p.end()

    def _garantir_fundo(self, dpr: float) -> QPixmap:
        if self._fundo is not None and self._fundo.devicePixelRatio() == dpr:
            return self._fundo
        pm = QPixmap(int(math.ceil(self.width() * dpr)), int(math.ceil(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        logos = {"sis": "pulso", "gpu": "gpu", "rede": "rede", "disco": "disco"}
        for k, c in self.cartoes.items():
            forma = self._cartao(q, c)
            self._logo(q, self.L[f"{k}.cab"], logos[k])
            if k == "sis":
                self._painel_neon(q, self.L["sis.neon"], forma, dpr)
        q.end()
        self._fundo = pm
        return pm

    def _garantir_cache(self) -> None:
        dpr = self.devicePixelRatioF()
        if self._cache is not None and self._cache_dpr == dpr and not self._cache_sujo:
            return
        fundo = self._garantir_fundo(dpr)
        pm = QPixmap(fundo.size())
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.drawPixmap(0, 0, fundo)
        q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        for k, c in self.cartoes.items():
            self._pontos(q, k, c)
        self._e_sis(q)
        if "gpu" in self.cartoes:
            self._e_gpu(q)
        self._e_rede(q)
        self._e_disco(q)
        q.end()
        self._cache, self._cache_dpr, self._cache_sujo = pm, dpr, False

    # ------------------------------------------------------------------ peças fixas

    def _cartao(self, p: QPainter, c: QRectF) -> QPainterPath:
        forma = caminho_pasta(c)
        g = QLinearGradient(0, c.top(), 0, c.bottom())
        g.setColorAt(0, QColor("#1f1f23"))
        g.setColorAt(0.35, QColor("#111113"))
        g.setColorAt(1, QColor("#09090a"))
        p.fillPath(forma, g)
        borda = caminho_pasta(QRectF(c.x() + 0.5, c.y() + 0.5, c.width() - 1, c.height() - 1))
        gb = QLinearGradient(0, c.top(), 0, c.bottom())
        gb.setColorAt(0, cor("#ffffff", 0.18))
        gb.setColorAt(0.3, cor("#ffffff", 0.10))
        gb.setColorAt(1, cor("#ffffff", 0.08))
        p.strokePath(borda, QPen(gb, 1))
        # "•••" no recorte (os pontos vão na camada de textos, que muda no hover)
        pil = self._pilula(c)
        g = QLinearGradient(0, pil.top(), 0, pil.bottom())
        g.setColorAt(0, QColor("#232327"))
        g.setColorAt(1, QColor("#151517"))
        p.fillPath(retangulo(pil, 7.5), g)
        p.strokePath(retangulo(pil.adjusted(0.5, 0.5, -0.5, -0.5), 7), QPen(cor("#ffffff", 0.1), 1))
        return forma

    def _logo(self, p: QPainter, cab: QRectF, glifo: str) -> None:
        r = QRectF(cab.x(), cab.y(), 38, 38)
        p.setPen(Qt.NoPen)
        for i, a in enumerate((0.16, 0.10, 0.05)):       # sombra curta embaixo (0 2px 6px)
            p.setBrush(cor("#000000", a))
            p.drawEllipse(r.adjusted(-i, 2 - i * 0.3, i, 2 + i))
        g = QRadialGradient(QPointF(r.x() + r.width() * 0.32, r.y() + r.height() * 0.28), 37.6)
        g.setColorAt(0, QColor("#4a4a50"))
        g.setColorAt(0.55, QColor("#26262a"))
        g.setColorAt(1, QColor("#18181b"))
        circ = QPainterPath()
        circ.addEllipse(r)
        p.fillPath(circ, g)
        p.fillPath(circ.subtracted(circ.translated(0, 1)), cor("#ffffff", 0.14))
        self._icone(p, glifo, QRectF(r.center().x() - 10, r.center().y() - 10, 20, 20), NEON, 2.2)

    def _painel_neon(self, p: QPainter, r: QRectF, forma: QPainterPath, dpr: float) -> None:
        """Painel neon: brilho na cor do widget (só dentro do card), aro de 1 px, reflexo branco em cima."""
        m = 50
        img = QImage(int(math.ceil((r.width() + 2 * m) * dpr)), int(math.ceil((r.height() + 2 * m) * dpr)),
                     QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        q.setCompositionMode(QPainter.CompositionMode_Source)
        q.setPen(Qt.NoPen)
        base = QRectF(m, m, r.width(), r.height())
        # box-shadow 0 0 18px neon@55%, 0 0 46px neon@28%: desfoque gaussiano (sigma = raio/2) da borda
        passo = 0.5
        d = m - 1.0
        while d >= 0:
            a1 = 0.55 * 0.5 * math.erfc(d / (9 * math.sqrt(2)))
            a2 = 0.28 * 0.5 * math.erfc(d / (23 * math.sqrt(2)))
            q.setBrush(cor(NEON, 1 - (1 - a1) * (1 - a2)))
            q.drawRoundedRect(base.adjusted(-d, -d, d, d), 15 + d, 15 + d)
            d -= passo
        q.end()
        p.save()
        p.setClipPath(forma)
        p.drawImage(QPointF(r.x() - m, r.y() - m), img)
        p.restore()
        p.strokePath(retangulo(r.adjusted(-0.5, -0.5, 0.5, 0.5), 15.5), QPen(cor(NEON, 0.9), 1))
        corpo = retangulo(r, 15)
        p.fillPath(corpo, NEON)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, cor("#ffffff", 0.22))
        g.setColorAt(0.55, cor("#ffffff", 0))
        p.fillPath(corpo, g)
        p.fillPath(corpo.subtracted(corpo.translated(0, 1)), cor("#ffffff", 0.45))

    def _pontos(self, p: QPainter, k: str, c: QRectF) -> None:
        pil = self._pilula(c)
        p.setPen(Qt.NoPen)
        p.setBrush(NEON if self._hover == "menu:" + k else QColor("#e9e9ec"))
        for i in (-1, 0, 1):
            p.drawEllipse(QPointF(pil.center().x() + i * 8, pil.center().y()), 2, 2)

    def _titulo(self, p: QPainter, cab: QRectF, titulo: str, sub: str, reserva: float = 0) -> None:
        x = cab.x() + 38 + 12
        larg = cab.right() - x - reserva
        f = self.fontes.ui(17, 500, -0.01)
        self._tx(p, x, cab.top() + 17, self._cortar(titulo, f, larg), f, T1)
        f = self.fontes.ui(11.5, 400)
        self._tx(p, x, cab.top() + 34, self._cortar(sub, f, larg), f, T2)

    def _botao(self, p: QPainter, r: QRectF, icone: str, ligado: bool, hover: bool) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(cor("#000000", 0.35))
        p.drawRoundedRect(r.translated(0, 1), 9, 9)
        corpo = retangulo(r, 9)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor("#2a2a2e"))
        g.setColorAt(1, QColor("#1c1c1f"))
        p.fillPath(corpo, g)
        p.fillPath(corpo.subtracted(corpo.translated(0, 1)), cor("#ffffff", 0.08))
        if ligado:
            p.strokePath(retangulo(r.adjusted(0.5, 0.5, -0.5, -0.5), 8.5), QPen(cor(NEON, 0.45), 1))
        c = NEON if (ligado or hover) else T2
        self._icone(p, icone, QRectF(r.center().x() - 7.5, r.center().y() - 7.5, 15, 15), c, 2.0)

    def _mini(self, p: QPainter, heroi: QRectF, valor: str, unidade: str, rotulo: str) -> None:
        """Dado secundário médio à direita do número grande (o gráfico vai na camada animada)."""
        xd = heroi.right()
        topo_graf = heroi.bottom() - 34
        base_k = topo_graf - 4.5
        self._tx(p, xd, base_k, rotulo.upper(), self.fontes.ui(10, 400, 0.08), T3, "d")
        base_v = base_k - 14
        fu = self.fontes.num(15, 300)
        wu = self._tx(p, xd, base_v, unidade, fu, T2, "d")
        self._tx(p, xd - wu - 2, base_v, valor, self.fontes.num(30, 300), T1, "d")

    def _stats(self, p: QPainter, r: QRectF, itens: list) -> None:
        """Linha de estatísticas: até 3 colunas com divisória de 1 px."""
        n = len(itens)
        larg = r.width() / n
        fk = self.fontes.ui(10, 600, 0.09)
        fv = self.fontes.num(27, 300)
        fu = self.fontes.num(13, 400)
        fd = self.fontes.ui(13, 500)
        for i, (icone, rotulo, valor, unidade, destaque) in enumerate(itens):
            x0 = r.x() + i * larg
            if i:
                p.fillRect(QRectF(x0, r.top(), 1, r.height()), FIO)
            x = x0 + (12 if i else 2)
            disp = larg - (x - x0) - 4
            self._icone(p, icone, QRectF(x, r.top() + 0.5, 11, 11), NEON, 2.4)
            self._tx(p, x + 16, r.top() + 9.5, self._cortar(rotulo.upper(), fk, disp - 16), fk, T3)
            wv = self._tx(p, x, r.top() + 44, valor, fv, T1)
            if unidade:
                self._tx(p, x + wv + 3, r.top() + 44, unidade, fu, T2)
            if destaque:
                self._tx(p, x, r.top() + 66, self._cortar(destaque, fd, disp), fd, NEON)

    # ------------------------------------------------------------------ camada de textos (1x por amostra)

    def _e_sis(self, p: QPainter) -> None:
        L, d = self.L, self.d
        sub = f"{self.coletor.cpu_nome} · {self.coletor.cpu_threads} threads"
        self._titulo(p, L["sis.cab"], "Monitor do PC", sub, reserva=40)
        self._botao(p, L["sis.pin"], "fixado" if self.cfg["fixado"] else "fixar", bool(self.cfg["fixado"]),
                    self._hover == "fixar")
        self._nota(p, L["sis.nota"])
        if "sis.jogo" in L:
            self._botao_jogo(p, L["sis.jogo"])
        if d is None:
            return
        # média do último minuto, ao lado do gráfico
        self._mini(p, L["sis.heroi"], f"{self._media(self.h_cpu):.0f}", "%", "média · 1 min")
        # memória (painel neon)
        ram = d["ram"]
        pct = ram["pct"]
        estado = "quase cheia" if pct >= 90 else ("alta" if pct >= 75 else "normal")
        self._rotulo(p, L["sis.mem_cab"], "Memória RAM", estado)
        r = L["sis.neon"]
        x0, x1 = r.x() + 14, r.right() - 14
        self._tx(p, x0, r.top() + 29, "EM USO", self.fontes.ui(11, 600, 0.04), TINTA)
        self._tx(p, x1, r.top() + 29, f"{cap(ram['usada'])} · {pct:.0f}%", self.fontes.num(17, 500), TINTA, "d")
        fr = self.fontes.ui(10.5, 500, 0.02)
        tinta = cor(TINTA, 0.78)
        self._tx(p, x0, r.top() + 65, f"{cap(ram['livre'])} livres", fr, tinta)
        self._tx(p, x1, r.top() + 65, f"de {cap(ram['total'])}", fr, tinta, "d")
        # maiores usos de RAM
        if "sis.procs" in L:
            soma = sum(b for _, _, b in self.procs[:5])
            self._rotulo(p, L["sis.proc_cab"], "Maiores usos de RAM", cap(soma) if soma else "")
            r = L["sis.procs"]
            fn, fq, fv = self.fontes.ui(12, 500), self.fontes.ui(11.5, 400), self.fontes.num(16, 400)
            for i, (nome, qtd, bytes_) in enumerate(self.procs[:5]):
                base = r.top() + 14 + i * 25
                valor = cap(bytes_)
                wv = self._tx(p, r.right() - 2, base, valor, fv, T1, "d")
                extra = f"  ×{qtd}" if qtd > 1 else ""
                we = self._larg(extra, fq)
                texto = self._cortar(nome, fn, r.width() - wv - we - 18)
                w = self._tx(p, r.x() + 2, base, texto, fn, T1)
                if extra:
                    self._tx(p, r.x() + 2 + w, base, extra, fq, T3)
                barra = QRectF(r.x() + 2, base + 5, r.width() - 4, 2)
                p.fillRect(barra, FIO)
                frac = max(0.0, min(1.0, self._b(f"p{i}") / 100.0))
                p.fillRect(QRectF(barra.x(), barra.y(), max(2.0, barra.width() * frac), 2), cor(T2, 0.55))

    def _nota(self, p: QPainter, r: QRectF) -> None:
        p.fillRect(QRectF(r.x(), r.top(), r.width(), 1), FIO)
        f = self.fontes.ui(10.5, 400)
        base = r.top() + 20
        agora = datetime.now()
        hora = f"{agora:%H:%M} · {SEMANA[agora.weekday()]}, {agora.day} {MESES[agora.month - 1]}"
        wh = self._tx(p, r.right(), base, hora, f, T3, "d")
        if self._aviso and time.monotonic() < self._aviso[1]:
            self._tx(p, r.x(), base, self._cortar(self._aviso[0], f, r.width() - wh - 10), f, NEON)
        elif self.d is not None:
            self._tx(p, r.x(), base, f"Ligado há {duracao(self.d['uptime'])}", f, T3)
        else:
            self._tx(p, r.x(), base, "Iniciando…", f, T3)

    def _botao_jogo(self, p: QPainter, r: QRectF) -> None:
        ej = self.estado_jogo
        ativo, ocupado, hover = ej["ativo"], ej["ocupado"], self._hover == "jogo"
        p.setPen(Qt.NoPen)
        p.setBrush(cor("#000000", 0.35))
        p.drawRoundedRect(r.translated(0, 1), 12, 12)
        corpo = retangulo(r, 12)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor("#2e2e33" if hover else "#2a2a2e"))
        g.setColorAt(1, QColor("#1f1f23" if hover else "#1c1c1f"))
        p.fillPath(corpo, g)
        p.fillPath(corpo.subtracted(corpo.translated(0, 1)), cor("#ffffff", 0.08))
        if ativo or hover:
            p.strokePath(retangulo(r.adjusted(0.5, 0.5, -0.5, -0.5), 11.5), QPen(cor(NEON, 0.6 if ativo else 0.4), 1))
        self._icone(p, "jogo", QRectF(r.x() + 13, r.center().y() - 9, 18, 18), NEON if (ativo or hover) else T2, 1.9)
        x = r.x() + 42
        larg = r.width() - 42 - 60
        self._tx(p, x, r.top() + 17, "MODO JOGO ATIVO" if ativo else "MODO JOGO", self.fontes.ui(10.5, 600, 0.08),
                 T1)
        sub = ocupado or ej["linha"] or "Fecha o que está aberto e foca no jogo"
        f = self.fontes.ui(11, 400)
        self._tx(p, x, r.top() + 32, self._cortar(sub, f, larg), f, T1 if ativo else T2)
        s = QRectF(r.right() - 14 - 34, r.center().y() - 9, 34, 18)
        if ativo:
            p.setPen(Qt.NoPen)
            p.setBrush(NEON)
            p.drawRoundedRect(s, 9, 9)
        else:
            p.setPen(QPen(cor("#ffffff", 0.1), 1))
            p.setBrush(TINTA)
            p.drawRoundedRect(s.adjusted(0.5, 0.5, -0.5, -0.5), 8.5, 8.5)
        p.setPen(Qt.NoPen)
        if ocupado:
            bx, bola = s.center().x(), T2
        elif ativo:
            bx, bola = s.right() - 9, TINTA
        else:
            bx, bola = s.x() + 9, T2
        p.setBrush(bola)
        p.drawEllipse(QPointF(bx, s.center().y()), 6, 6)

    def _e_gpu(self, p: QPainter) -> None:
        L = self.L
        gpu = self.d["gpu"] if self.d else None
        nome = gpu["nome"] if gpu else "GPU"
        self._titulo(p, L["gpu.cab"], nome, "Placa de vídeo NVIDIA")
        if not gpu:
            return
        self._mini(p, L["gpu.heroi"], f"{self._media(self.h_gpu):.0f}", "%", "média · 1 min")
        v, u = cap_partes(gpu["vram_usada"])
        itens = [("vram", "VRAM", v, u, f"de {cap(gpu['vram_total'])}")]
        temp = "—" if gpu["temp"] is None else f"{gpu['temp']}"
        fan = gpu.get("ventoinha")
        itens.append(("temp", "Temp.", temp, "°C" if gpu["temp"] is not None else "",
                      f"cooler {fan}%" if fan is not None else ""))   # "ventoinha 30%" não cabe na coluna
        watts = "—" if gpu["watts"] is None else f"{gpu['watts']:.0f}"
        clock = f"{num(gpu['clock_mhz'] / 1000, 2)} GHz" if gpu["clock_mhz"] else ""
        itens.append(("energia", "Energia", watts, "W" if gpu["watts"] is not None else "", clock))
        self._stats(p, L["gpu.stats"], itens)

    def _e_rede(self, p: QPainter) -> None:
        L = self.L
        rede = self.d["rede"] if self.d else None
        sub = "Medindo…"
        if rede:
            sub = rede["tipo"]
            if rede["link_bps"]:
                v, u = taxa_bits(rede["link_bps"])
                sub += f" · {v} {u}"
        self._titulo(p, L["rede.cab"], "Rede", sub)
        if not rede:
            return
        itens = []
        for chave, icone, rotulo in (("down", "baixar", "Download"), ("up", "subir", "Upload")):
            bps = max(0.0, self._b(chave))
            v, u = taxa_bits(bps)
            itens.append((icone, rotulo, v, u, taxa_bytes(bps / 8)))
        plano = float(self.cfg.get("plano_mbps", 0) or 0) * 1e6
        if plano > 0:
            pct = max(0.0, self._b("down")) * 100 / plano
            itens.append(("plano", "Do plano", f"{pct:.0f}", "%", f"de {num(plano / 1e6, 0)} Mb/s"))
        elif rede["link_bps"]:
            v, u = taxa_bits(rede["link_bps"])
            itens.append(("link", "Link", v, u, rede["tipo"]))
        self._stats(p, L["rede.stats"], itens)
        g = L["rede.graf"]
        p.fillRect(QRectF(g.x(), g.bottom() - 1, g.width(), 1), FIO)
        p.fillRect(QRectF(g.x(), g.top() + g.height() / 2, g.width(), 1), cor("#ffffff", 0.035))

    def _e_disco(self, p: QPainter) -> None:
        L = self.L
        discos = self.d["discos"] if self.d else []
        total = sum(dk["total"] for dk in discos)
        sub = f"{len(discos)} disco{'s' if len(discos) != 1 else ''} · {cap(total)}" if discos else "Lendo…"
        self._titulo(p, L["disco.cab"], "Armazenamento", sub)
        fl, fr, fs, fa = (self.fontes.num(20, 400), self.fontes.ui(11, 400), self.fontes.ui(11.5, 400),
                          self.fontes.ui(11, 400))
        for i, dk in enumerate(discos):
            r = L.get(f"disco.{i}")
            if r is None:
                break
            wl = self._tx(p, r.x() + 2, r.top() + 14, dk["letra"], fl, T1)
            ws = self._tx(p, r.right() - 2, r.top() + 14, f"{cap(dk['usado'])} de {cap(dk['total'])}", fs, T2, "d")
            if dk["rotulo"]:
                self._tx(p, r.x() + 2 + wl + 8, r.top() + 14,
                         self._cortar(dk["rotulo"], fr, r.width() - wl - ws - 24), fr, T3)
            barra = QRectF(r.x() + 2, r.top() + 22, r.width() - 4, 5)
            p.setPen(Qt.NoPen)
            p.setBrush(FIO)
            p.drawRoundedRect(barra, 2.5, 2.5)
            frac = max(0.0, min(1.0, dk["pct"] / 100.0))
            if frac > 0:
                p.setBrush(cor_carga(frac))
                p.drawRoundedRect(QRectF(barra.x(), barra.y(), max(5.0, barra.width() * frac), 5), 2.5, 2.5)
            wv = self._tx(p, r.x() + 2, r.top() + 43, f"{cap(dk['livre'])} livres", fs, T2)
            ativ = f"Leitura {taxa_bytes(dk['leitura'])} · Gravação {taxa_bytes(dk['escrita'])}"
            self._tx(p, r.right() - 2, r.top() + 43, self._cortar(ativ, fa, r.width() - wv - 16), fa, T3, "d")

    # ------------------------------------------------------------------ camada animada (todo quadro)

    def _heroi(self, p: QPainter, r: QRectF, valor: float, linha1: str, linha2: str) -> None:
        s = f"{max(0.0, valor):.0f}"
        px = 72 if len(s) >= 3 else 82
        f = self.fontes.num(px, 300, -0.02)
        base = r.bottom()
        w = self._tx(p, r.x(), base, s, f, T1)
        topo = base - self.fontes.medidas(f).capHeight()
        fs = self.fontes.num(26, 300)
        ws = self._tx(p, r.x() + w + 3, topo - 1 + self.fontes.medidas(fs).capHeight(), "%", fs, T2)
        x = r.x() + w + 3 + ws + 8
        self._tx(p, x, base - 17.5, linha1, self.fontes.ui(11, 500), T1)
        self._tx(p, x, base - 3.5, linha2, self.fontes.ui(11, 400), T2)

    def _linha(self, p: QPainter, r: QRectF, serie, vmax: float, c: QColor, preencher: bool = True,
               largura: float = 1.6, ponto: bool = True) -> None:
        n = len(serie)
        if n < 3 or vmax <= 0:
            return
        passo = r.width() / (PONTOS - 2)
        desl = (1 - self.e) * passo
        alt = r.height() - 4
        pts = [QPointF(r.right() - (n - 1 - i) * passo + desl, r.bottom() - 2 - max(0.0, min(1.0, v / vmax)) * alt)
               for i, v in enumerate(serie)]
        linha = QPainterPath(pts[0])
        for a, b in zip(pts, pts[1:]):
            mx = (a.x() + b.x()) / 2
            linha.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
        p.save()
        p.setClipRect(QRectF(r.x(), r.top() - 4, r.width(), r.height() + 8))   # o histórico desliza por baixo
        if preencher:
            area = QPainterPath(linha)
            area.lineTo(pts[-1].x(), r.bottom())
            area.lineTo(pts[0].x(), r.bottom())
            area.closeSubpath()
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            g.setColorAt(0, cor(c, 0.45))
            g.setColorAt(1, cor(c, 0))
            p.fillPath(area, g)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(c, largura, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(linha)
        p.restore()
        if ponto:
            # bolinha na ponta, sempre na borda direita (a curva desliza por baixo dela)
            a, b = pts[-2], pts[-1]
            mx = (a.x() + b.x()) / 2
            lo, hi = 0.0, 1.0
            for _ in range(18):              # acha t com x(t) = borda direita na última curva
                t = (lo + hi) / 2
                u = 1 - t
                x = a.x() * u ** 3 + 3 * mx * u * u * t + 3 * mx * u * t * t + b.x() * t ** 3
                lo, hi = (t, hi) if x < r.right() else (lo, t)
            t = (lo + hi) / 2
            u = 1 - t
            y = a.y() * (u ** 3 + 3 * u * u * t) + b.y() * (3 * u * t * t + t ** 3)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(r.right(), y), 2.6, 2.6)

    def _d_sis(self, p: QPainter) -> None:
        L, cpu = self.L, self.d["cpu"]
        ghz = f"{num(cpu['ghz'], 2)} GHz" if cpu["ghz"] else "em uso"
        self._heroi(p, L["sis.heroi"], self._v("cpu"), "da CPU", ghz)
        h = L["sis.heroi"]
        self._linha(p, QRectF(h.right() - 118, h.bottom() - 34, 118, 34), self.h_cpu,
                    max(10.0, self._v("esc_cpu", 10.0)), NEON)
        r = L.get("sis.nucleos")
        if r is not None:
            n = len(cpu["nucleos"])
            if n:
                esp = 3.0 if n <= 40 else 2.0
                lb = (r.width() - esp * (n - 1)) / n
                p.setPen(Qt.NoPen)
                for i in range(n):
                    v = max(0.0, min(100.0, self._v(f"n{i}")))
                    bx = r.x() + i * (lb + esp)
                    p.setBrush(cor("#ffffff", 0.05))
                    p.drawRoundedRect(QRectF(bx, r.y(), lb, r.height()), 1.5, 1.5)
                    hh = max(2.0, r.height() * v / 100.0)
                    p.setBrush(cor_carga(v / 100.0))
                    p.drawRoundedRect(QRectF(bx, r.bottom() - hh, lb, hh), 1.5, 1.5)
        # trilho do painel neon: barra preta até o uso e bolinha com anel neon
        r = L["sis.neon"]
        x0, x1 = r.x() + 14, r.right() - 14
        frac = max(0.0, min(1.0, self._v("ram") / 100.0))
        meio = r.top() + 44
        p.setPen(Qt.NoPen)
        p.setBrush(cor(TINTA, 0.75))
        p.drawRoundedRect(QRectF(x0, meio - 0.75, x1 - x0, 1.5), 0.75, 0.75)
        p.setBrush(TINTA)
        p.drawRoundedRect(QRectF(x0, meio - 3, max(6.0, (x1 - x0) * frac), 6), 3, 3)
        kx = x0 + (x1 - x0) * frac
        p.setBrush(NEON)
        p.drawEllipse(QPointF(kx, meio), 8.5, 8.5)
        p.setBrush(TINTA)
        p.drawEllipse(QPointF(kx, meio), 6, 6)

    def _d_gpu(self, p: QPainter) -> None:
        h = self.L["gpu.heroi"]
        self._heroi(p, h, self._v("gpu"), "da GPU", "em uso")
        self._linha(p, QRectF(h.right() - 118, h.bottom() - 34, 118, 34), self.h_gpu,
                    max(10.0, self._v("esc_gpu", 10.0)), NEON)

    def _d_rede(self, p: QPainter) -> None:
        g = self.L["rede.graf"]
        escala = max(10e6, self._v("escala_rede", 10e6))
        self._linha(p, g, self.h_down, escala, NEON)
        self._linha(p, g, self.h_up, escala, cor(T2, 0.9), preencher=False, largura=1.3, ponto=True)
