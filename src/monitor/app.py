# -*- coding: utf-8 -*-
"""Aplicativo: bandeja, menu, ciclo de amostragem e instância única."""
from __future__ import annotations

import os
import sys
import traceback

from . import config, winapi


def _registrar_erros() -> None:
    def gancho(tipo, valor, tb):
        try:
            os.makedirs(config.PASTA, exist_ok=True)
            with open(config.LOG, "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(tipo, valor, tb)) + "\n")
        except OSError:
            pass

    sys.excepthook = gancho


def main() -> int:
    _registrar_erros()
    os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")

    if "--aguardar" in sys.argv:         # reinício automático: espera a instância antiga soltar o mutex
        import time
        time.sleep(2.5)
    mutex, ja_existe = winapi.criar_mutex()
    if "--sair" in sys.argv:
        winapi.avisar_instancia(winapi.MSG_SAIR)
        return 0
    if ja_existe:
        winapi.avisar_instancia(winapi.MSG_MOSTRAR)
        return 0

    import glob

    import psutil
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QAction, QActionGroup, QFontDatabase, QGuiApplication
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from . import coletores, icone, temas
    from .widget import MonitorWidget

    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # nunca disputa CPU com jogos
    except Exception:
        pass

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Monitor do PC")
    app.setWindowIcon(icone.icone(temas.obter(config.Config().get("tema"))))
    for arq in glob.glob(os.path.join(config.RAIZ, "fontes", "*.otf")):
        QFontDatabase.addApplicationFont(arq)

    cfg = config.Config()
    coletor = coletores.Coletor()
    processos = coletores.LeitorProcessos()
    processos.start()

    janela: MonitorWidget
    menu_ctx = QMenu()
    menu_bandeja = QMenu()

    CANTOS = [("sup-dir", "Superior direito"), ("sup-esq", "Superior esquerdo"),
              ("inf-dir", "Inferior direito"), ("inf-esq", "Inferior esquerdo"), ("centro", "Centro")]

    def alternar_visivel() -> None:
        if janela.isVisible():
            janela.hide()
        else:
            janela.show()
            winapi.enviar_para_o_fundo(janela._hwnd)

    def definir(chave: str, valor, reposicionar: bool = False, layout: bool = False,
                vidro: bool = False) -> None:
        cfg[chave] = valor
        cfg.salvar()
        if layout:
            janela.recalcular_layout()
        if reposicionar or layout:
            janela.posicionar()
        if vidro:
            janela.aplicar_vidro()
        janela.update()

    def escolher_tema(id_: str) -> None:
        cfg["tema"] = id_
        cfg.salvar()
        tema = temas.obter(id_)
        janela.definir_tema(tema)
        bandeja.setIcon(icone.icone(tema))
        app.setWindowIcon(icone.icone(tema))

    def escolher_monitor(nome: str) -> None:
        cfg["livre"] = False
        definir("monitor", nome, reposicionar=True)

    def escolher_canto(chave: str) -> None:
        cfg["livre"] = False
        definir("ancora", chave, reposicionar=True)

    def preencher(m: QMenu) -> None:
        m.clear()
        m.addAction("Ocultar widget" if janela.isVisible() else "Mostrar widget", alternar_visivel)
        m.addSeparator()

        sub = m.addMenu("Monitor")
        grupo = QActionGroup(sub)
        atual = janela.tela_configurada().name()
        principal = QGuiApplication.primaryScreen()
        for i, t in enumerate(QGuiApplication.screens(), 1):
            g = t.geometry()
            rot = f"Monitor {i} · {t.name()} ({g.width()}×{g.height()})"
            if t == principal:
                rot += " — principal"
            a = QAction(rot, sub, checkable=True, checked=(t.name() == atual))
            a.triggered.connect(lambda _=False, n=t.name(): escolher_monitor(n))
            grupo.addAction(a)
            sub.addAction(a)

        sub = m.addMenu("Canto")
        grupo = QActionGroup(sub)
        for chave, rot in CANTOS:
            a = QAction(rot, sub, checkable=True, checked=(not cfg["livre"] and cfg["ancora"] == chave))
            a.triggered.connect(lambda _=False, c=chave: escolher_canto(c))
            grupo.addAction(a)
            sub.addAction(a)

        a = m.addAction("Travar posição (não arrastar)")
        a.setCheckable(True)
        a.setChecked(cfg["travado"])
        a.triggered.connect(lambda v: definir("travado", bool(v)))

        m.addSeparator()
        sub = m.addMenu("Tema")
        grupo = QActionGroup(sub)
        for id_, tema in temas.listar().items():
            act = QAction(tema.nome, sub, checkable=True, checked=(janela.t.id == id_))
            act.setToolTip(tema.descricao)
            act.triggered.connect(lambda _=False, i=id_: escolher_tema(i))
            grupo.addAction(act)
            sub.addAction(act)

        sub = m.addMenu("Aparência")
        grupo = QActionGroup(sub)
        for chave, rot in (("leve", "Vidro leve"), ("medio", "Vidro médio"), ("fosco", "Vidro fosco")):
            a = QAction(rot, sub, checkable=True, checked=(cfg["vidro"] == chave))
            a.triggered.connect(lambda _=False, c=chave: definir("vidro", c, vidro=True))
            grupo.addAction(a)
            sub.addAction(a)
        sub.addSeparator()
        grupo = QActionGroup(sub)
        for chave, rot in (("coluna", "Layout em coluna"), ("painel", "Layout em painel largo")):
            a = QAction(rot, sub, checkable=True, checked=(cfg["layout"] == chave))
            a.triggered.connect(lambda _=False, c=chave: definir("layout", c, layout=True))
            grupo.addAction(a)
            sub.addAction(a)
        sub.addSeparator()
        for chave, rot in (("mostrar_nucleos", "Mostrar núcleos da CPU"),
                           ("mostrar_processos", "Mostrar maiores usos de RAM")):
            a = sub.addAction(rot)
            a.setCheckable(True)
            a.setChecked(cfg[chave])
            a.triggered.connect(lambda v, c=chave: definir(c, bool(v), layout=True))

        m.addSeparator()
        a = m.addAction("Iniciar com o Windows")
        a.setCheckable(True)
        a.setChecked(config.inicio_ativo())
        a.triggered.connect(lambda v: config.definir_inicio(bool(v)))
        m.addSeparator()
        m.addAction("Sair", app.quit)

    menu_ctx.aboutToShow.connect(lambda: preencher(menu_ctx))
    menu_bandeja.aboutToShow.connect(lambda: preencher(menu_bandeja))

    def criar_menu() -> QMenu:
        preencher(menu_ctx)
        return menu_ctx

    janela = MonitorWidget(cfg, coletor, processos, criar_menu)
    if "--teste-topo" in sys.argv:       # só para capturas de tela durante o desenvolvimento
        janela.setWindowFlag(Qt.WindowStaysOnBottomHint, False)
        janela.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        janela.teste_topo = True
    janela.winId()                      # cria o HWND antes de mostrar
    janela.posicionar()
    janela.show()
    janela.preparar_nativo()
    janela.posicionar()
    if janela.teste_topo:
        winapi.trazer_ao_topo(janela._hwnd)

    bandeja = QSystemTrayIcon(icone.icone(janela.t), app)
    bandeja.setToolTip("Monitor do PC")
    bandeja.setContextMenu(menu_bandeja)
    bandeja.activated.connect(
        lambda r: alternar_visivel() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    bandeja.show()

    app.screenAdded.connect(lambda *_: QTimer.singleShot(800, janela.posicionar))
    app.screenRemoved.connect(lambda *_: QTimer.singleShot(800, janela.posicionar))

    estado = {"coberto": False, "ticks": 0}

    def reiniciar_se_janela_morreu() -> bool:
        """Se o Explorer reiniciar, a área de trabalho (dona do widget) é destruída e leva a janela junto."""
        if janela._hwnd and not winapi.janela_viva(janela._hwnd):
            import subprocess
            bandeja.hide()
            subprocess.Popen([sys.executable, os.path.join(config.RAIZ, "monitor_pc.pyw"), "--aguardar"],
                             creationflags=0x08000008)
            app.quit()
            return True
        return False

    def tick() -> None:
        estado["ticks"] += 1
        if reiniciar_se_janela_morreu():
            return
        if (janela.d is not None and not janela.teste_topo and janela.isVisible()
                and winapi.coberto_por_janela(janela._hwnd)):
            if not estado["coberto"]:
                estado["coberto"] = True
                processos.ativo = False
            return                      # jogo/app em tela cheia por cima: não gasta nada
        if estado["coberto"]:
            estado["coberto"] = False
            processos.ativo = True
        if not janela.isVisible():
            return
        janela.aplicar(coletor.amostrar(), processos.resultado)
        if estado["ticks"] in (4, 12) or estado["ticks"] % 120 == 0:
            winapi.liberar_memoria()

    relogio = QTimer(app)
    relogio.setTimerType(Qt.PreciseTimer)
    relogio.timeout.connect(tick)
    QTimer.singleShot(500, tick)        # primeira leitura logo após o PDH aquecer
    QTimer.singleShot(1000, lambda: relogio.start(1000))

    codigo = app.exec()
    bandeja.hide()
    del mutex
    return codigo
