# -*- coding: utf-8 -*-
"""Botão Modo Jogo: a lista do que vai fechar (para confirmar) e o controle que liga/desliga tudo
fora da thread da interface, mostrando o andamento no próprio botão."""
from __future__ import annotations

import os
import threading
import traceback

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from . import config, modo_jogo, winapi
from .widget import cap


def _rgba(hexa: str, a: int) -> str:
    c = QColor(hexa)
    return f"rgba({c.red()},{c.green()},{c.blue()},{a})"


def _tamanho(b: int) -> str:
    return cap(b) if b >= 1024 ** 3 else f"{max(1, round(b / 1024 ** 2))} MB"


class DialogoAtivar(QDialog):
    """Lista o que está aberto, um item por app, marcado = vai fechar. Launchers e jogos abertos
    vêm desmarcados; as escolhas ficam salvas para a próxima vez."""

    ROTULOS = {"launcher": "launcher de jogos", "jogo": "jogo aberto", "wsl": "máquina virtual"}

    def __init__(self, plano: modo_jogo.Plano, tema, escolhas: dict, precisa_uac: bool) -> None:
        super().__init__(None, Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.plano = plano
        self.setWindowTitle("Modo Jogo")
        self.setFixedWidth(520)
        t = tema
        texto, fraco, apagado = _rgba(t.texto, 236), _rgba(t.texto, 160), _rgba(t.texto, 112)
        self.setStyleSheet(f"""
            QDialog {{ background: {t.tinta}; }}
            QLabel {{ color: {texto}; font-family: Inter; font-size: 13px; }}
            QLabel#titulo {{ font-size: 21px; font-weight: 600; }}
            QLabel#sub, QLabel#total {{ color: {fraco}; }}
            QLabel#nota {{ color: {apagado}; font-size: 12px; }}
            QLabel#aviso {{ color: {t.medio}; font-size: 12px; }}
            QListWidget {{ background: {_rgba(t.cartao, 12)}; border: 1px solid {_rgba(t.cartao, 30)};
                           border-radius: 10px; color: {texto}; font-family: Inter; font-size: 13px;
                           padding: 4px; outline: none; }}
            QListWidget::item {{ padding: 5px 4px; border-radius: 6px; }}
            QListWidget::item:hover, QListWidget::item:selected {{ background: {_rgba(t.cartao, 20)}; color: {texto}; }}
            QCheckBox {{ color: {fraco}; font-family: Inter; font-size: 12px; }}
            QPushButton {{ font-family: Inter; font-size: 13px; padding: 8px 18px; border-radius: 8px;
                           color: {texto}; background: {_rgba(t.cartao, 18)}; border: 1px solid {_rgba(t.cartao, 40)}; }}
            QPushButton:hover {{ background: {_rgba(t.cartao, 30)}; }}
            QPushButton#ativar {{ border: none; color: {getattr(t, 'texto_botao', '#FFFFFF')}; font-weight: 600;
                                  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.marca[1]}, stop:1 {t.marca[0]}); }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        titulo = QLabel("Modo Jogo")
        titulo.setObjectName("titulo")
        lay.addWidget(titulo)
        sub = QLabel("Fecha o que está aberto e deixa o PC só para o jogo. Apps que você abrir depois "
                     "ficam abertos. Clique no botão de novo para voltar tudo ao normal.")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.NoSelection)
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lista.setTextElideMode(Qt.ElideMiddle)
        for g in plano.grupos:
            rot = g.nome + (f"   ·   {_tamanho(g.ram)}" if g.ram else "")
            if g.categoria in self.ROTULOS:
                rot += f"   ({self.ROTULOS[g.categoria]})"
            item = QListWidgetItem(rot)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if escolhas.get(g.chave, g.sugestao()) else Qt.Unchecked)
            item.setToolTip(f"{len(g.pids)} processo(s)" if g.pids else "Desliga o WSL e o Docker (wsl --shutdown)")
            item.setData(Qt.UserRole, g)
            self.lista.addItem(item)
        self.lista.setFixedHeight(min(300, 31 * max(3, len(plano.grupos)) + 12))
        self.lista.itemChanged.connect(self._somar)
        self.lista.itemClicked.connect(self._alternar_item)
        lay.addWidget(self.lista)

        self.total = QLabel()
        self.total.setObjectName("total")
        lay.addWidget(self.total)

        tambem = QLabel("Também: pausa serviços em segundo plano (Windows Update, indexação, telemetria, "
                        "atualizadores), põe a energia em Desempenho Máximo, esvazia a memória em espera e dá "
                        "prioridade ao jogo em tela cheia.")
        tambem.setObjectName("nota")
        tambem.setWordWrap(True)
        lay.addWidget(tambem)
        if plano.mantidos:
            mais = len(plano.mantidos) - 8
            ficam = QLabel("Ficam sempre: " + ", ".join(plano.mantidos[:8]) + (f" e mais {mais}" if mais > 0 else "")
                           + " — além do Windows, drivers e áudio.")
            ficam.setObjectName("nota")
            ficam.setWordWrap(True)
            lay.addWidget(ficam)
        aviso = QLabel("Salve o que estiver aberto. App que perguntar se quer salvar continua aberto; "
                       "os outros fecham.")
        aviso.setObjectName("aviso")
        aviso.setWordWrap(True)
        lay.addWidget(aviso)
        if precisa_uac:
            uac = QLabel("Nesta primeira vez o Windows pede permissão de administrador (para pausar os "
                         "serviços). Depois não pede mais.")
            uac.setObjectName("nota")
            uac.setWordWrap(True)
            lay.addWidget(uac)

        self._direto = QCheckBox("Nas próximas vezes, ativar direto com estas escolhas (sem esta lista)")
        lay.addWidget(self._direto)

        botoes = QHBoxLayout()
        botoes.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        ativar = QPushButton("Ativar Modo Jogo")
        ativar.setObjectName("ativar")
        ativar.setDefault(True)
        ativar.clicked.connect(self.accept)
        botoes.addWidget(cancelar)
        botoes.addWidget(ativar)
        lay.addSpacing(4)
        lay.addLayout(botoes)
        self._somar()
        self.setFixedHeight(lay.heightForWidth(self.width()) if lay.hasHeightForWidth() else self.sizeHint().height())

    def _alternar_item(self, item: QListWidgetItem) -> None:
        """Clique em qualquer parte da linha marca/desmarca (não só na caixinha)."""
        if self.lista.viewport().mapFromGlobal(self.cursor().pos()).x() > 28:
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _somar(self, *_):
        marcados = self.escolhidos()
        ram = sum(g.ram for g in marcados)
        self.total.setText(f"{len(marcados)} de {self.lista.count()} vão fechar"
                           + (f" · cerca de {_tamanho(ram)} de RAM" if ram else ""))

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        hwnd = int(self.winId())
        winapi._dwm_attr(hwnd, 20, 1)        # barra de título escura
        self.raise_()
        self.activateWindow()

    def escolhidos(self) -> list[modo_jogo.Grupo]:
        return [self.lista.item(i).data(Qt.UserRole) for i in range(self.lista.count())
                if self.lista.item(i).checkState() == Qt.Checked]

    def marcacoes(self) -> dict[str, bool]:
        return {self.lista.item(i).data(Qt.UserRole).chave: self.lista.item(i).checkState() == Qt.Checked
                for i in range(self.lista.count())}

    def direto(self) -> bool:
        return self._direto.isChecked()


class Controle(QObject):
    """Liga/desliga o Modo Jogo em segundo plano e mantém o botão do widget e a bandeja em dia."""

    _progresso = Signal(str)
    _planejado = Signal(object, bool)
    _fim = Signal(str, object)

    def __init__(self, cfg, janela, bandeja) -> None:
        super().__init__()
        self.cfg, self.janela, self.bandeja = cfg, janela, bandeja
        self.estado = modo_jogo.carregar_estado()
        self.ocupado = ""
        self._tentados: set[int] = set()
        self._progresso.connect(self._ao_progresso)
        self._planejado.connect(self._ao_planejar)
        self._fim.connect(self._ao_terminar)
        janela.ao_modo_jogo = self.alternar

    @property
    def ativo(self) -> bool:
        return bool(self.estado.get("ativo"))

    def iniciar(self) -> None:
        """Na abertura do widget: se o PC reiniciou com o Modo Jogo ligado, desliga sozinho."""
        if self.ativo and modo_jogo.restaurar_depois_de_reiniciar():
            self.estado = {}
            self._avisar("Modo Jogo desligado", "O PC reiniciou: o plano de energia voltou ao normal.")
        self._atualizar()

    def alternar(self) -> None:
        if self.ocupado:
            return
        if self.ativo:
            self._rodar("desativar", lambda: modo_jogo.desativar(self._progresso.emit))
            return
        self._ocupar("Vendo o que está aberto…")
        threading.Thread(target=self._planejar, daemon=True, name="modo-jogo").start()

    def tick(self, n: int) -> None:
        if self.ativo and not self.ocupado and n % 3 == 0:
            modo_jogo.impulsionar_jogo(self.estado, self._tentados)

    def resumo(self) -> str:
        e = self.estado
        partes = [f"{e.get('fechados', 0)} apps fechados"]
        if e.get("liberado", 0) > 64 * 1024 ** 2:
            partes.append(f"{cap(e['liberado'])} liberados")
        if e.get("servicos"):
            partes.append(f"{len(e['servicos'])} serviços pausados")
        elif not e.get("admin"):
            partes.append("serviços não pausados")
        return " · ".join(partes)

    # ---- trabalho em segundo plano

    def _planejar(self) -> None:
        try:
            self._planejado.emit(modo_jogo.planejar(), modo_jogo.precisa_permissao())
        except Exception as erro:
            self._registrar()
            self._fim.emit("erro", erro)

    def _ao_planejar(self, plano: modo_jogo.Plano, uac: bool) -> None:
        escolhas = dict(self.cfg.get("modo_jogo_escolhas") or {})
        if self.cfg["modo_jogo_confirmar"]:
            dlg = DialogoAtivar(plano, self.janela.paleta, escolhas, uac)
            if dlg.exec() != QDialog.Accepted:
                self.ocupado = ""
                self._atualizar()
                return
            escolhas.update(dlg.marcacoes())
            self.cfg["modo_jogo_escolhas"] = escolhas
            if dlg.direto():
                self.cfg["modo_jogo_confirmar"] = False
            self.cfg.salvar()
            escolhidos = dlg.escolhidos()
        else:
            escolhidos = [g for g in plano.grupos if escolhas.get(g.chave, g.sugestao())]
        salvo = self.cfg.get("modo_jogo_plano", "")
        self._rodar("ativar", lambda: modo_jogo.ativar(plano, escolhidos, salvo, self._progresso.emit))

    def _rodar(self, acao: str, funcao) -> None:
        self._ocupar("Ativando…" if acao == "ativar" else "Voltando ao normal…")

        def corpo() -> None:
            try:
                self._fim.emit(acao, funcao())
            except Exception as erro:
                self._registrar()
                self._fim.emit("erro", erro)

        threading.Thread(target=corpo, daemon=True, name="modo-jogo").start()

    def _ao_terminar(self, acao: str, r) -> None:
        self.ocupado = ""
        if acao == "ativar":
            self.estado = r
            self._tentados.clear()
            if r.get("plano_jogo") and r["plano_jogo"] != self.cfg.get("modo_jogo_plano"):
                self.cfg["modo_jogo_plano"] = r["plano_jogo"]
                self.cfg.salvar()
            texto = self.resumo()
            if r.get("teimosos"):
                texto += "\nContinuam abertos (pedindo para salvar): " + ", ".join(r["teimosos"])
            self._avisar("Modo Jogo ativo", texto)
        elif acao == "desativar":
            self.estado = {}
            texto = "Tudo de volta ao normal"
            if r.get("reabertos"):
                texto += f" · {r['reabertos']} apps reabertos"
            self._avisar("Modo Jogo desligado", texto)
        else:
            self.estado = modo_jogo.carregar_estado()
            self._avisar("Modo Jogo", f"Não deu certo: {r}. Detalhes em {config.LOG}")
        self._atualizar()

    # ---- aparência

    def _ocupar(self, msg: str) -> None:
        self.ocupado = msg
        self._atualizar()

    def _ao_progresso(self, msg: str) -> None:
        if self.ocupado:
            self.ocupado = msg
            self._atualizar()

    def _atualizar(self) -> None:
        self.janela.estado_jogo = {"ativo": self.ativo, "ocupado": self.ocupado,
                                   "linha": self.resumo() if self.ativo else ""}
        self.janela.pedir_completo()
        self.bandeja.setToolTip("CorePulse — Modo Jogo ativo" if self.ativo else "CorePulse")

    def _avisar(self, titulo: str, texto: str) -> None:
        self.bandeja.showMessage(titulo, texto, self.bandeja.icon(), 7000)

    @staticmethod
    def _registrar() -> None:
        try:
            os.makedirs(config.PASTA, exist_ok=True)
            with open(config.LOG, "a", encoding="utf-8") as f:
                f.write("[Modo Jogo] " + traceback.format_exc() + "\n")
        except OSError:
            pass
