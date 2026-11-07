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
    if "--modo-jogo-admin" in sys.argv:  # parte elevada do Modo Jogo (tarefa agendada / UAC), sem interface
        from . import modo_jogo_admin
        return modo_jogo_admin.main(sys.argv)
    if "--modo-jogo-simular" in sys.argv:  # mostra o que o Modo Jogo faria, sem mexer em nada
        from . import modo_jogo
        return modo_jogo.simular()
    os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")

    if "--aguardar" in sys.argv:         # reinício automático: espera a instância antiga soltar o mutex
        import time
        time.sleep(2.5)
    mutex, ja_existe = winapi.criar_mutex()
    if "--sair" in sys.argv:
        winapi.avisar_instancia(winapi.MSG_SAIR)
        return 0
    if ja_existe:
        winapi.permitir_primeiro_plano()     # a instância que já roda pode aparecer na frente com foco
        winapi.avisar_instancia(winapi.MSG_MODO_JOGO if "--modo-jogo" in sys.argv else winapi.MSG_MOSTRAR)
        return 0

    import glob

    import psutil
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QAction, QActionGroup, QFontDatabase, QGuiApplication
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from . import coletores, icone, modo_jogo_ui, temas
    from .widget import MonitorWidget

    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # nunca disputa CPU com jogos
    except Exception:
        pass

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Monitor do PC")
    app.setWindowIcon(icone.icone(temas.obter(config.Config().get("tema"))))
    for arq in sorted(glob.glob(os.path.join(config.RAIZ, "fontes", "*.otf"))
                      + glob.glob(os.path.join(config.RAIZ, "fontes", "*.ttf"))):
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
            janela.mostrar_na_frente()      # aberto de propósito: na frente até o foco mudar
            janela.garantir_visivel()

    def clique_bandeja() -> None:
        # Solto, o widget pode estar escondido atrás dos apps: o 1º clique traz para a frente,
        # o seguinte oculta.
        if janela.isVisible() and not janela.esta_na_frente():
            janela.mostrar_na_frente()
            janela.garantir_visivel()
        else:
            alternar_visivel()

    def definir(chave: str, valor, reposicionar: bool = False, layout: bool = False) -> None:
        cfg[chave] = valor
        cfg.salvar()
        if layout:
            janela.recalcular_layout()
        if reposicionar or layout:
            janela.posicionar()
        janela.pedir_completo()

    def escolher_monitor(nome: str) -> None:
        cfg["livre"] = False
        definir("monitor", nome, reposicionar=True)

    def escolher_canto(chave: str) -> None:
        cfg["livre"] = False
        definir("ancora", chave, reposicionar=True)

    def preencher(m: QMenu) -> None:
        m.clear()
        if controle.ocupado:
            m.addAction(f"Modo Jogo: {controle.ocupado}").setEnabled(False)
        else:
            m.addAction("Desativar Modo Jogo" if controle.ativo else "Ativar Modo Jogo", controle.alternar)
        m.addAction("Ocultar widget" if janela.isVisible() else "Mostrar widget", alternar_visivel)
        a = m.addAction("Fixar sobre outras janelas")
        a.setCheckable(True)
        a.setChecked(bool(cfg["fixado"]))
        a.triggered.connect(lambda _=False: janela.alternar_fixado())
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
        sub = m.addMenu("Aparência")
        grupo = QActionGroup(sub)
        for chave, rot in (("coluna", "Layout em coluna"), ("painel", "Layout em painel largo")):
            a = QAction(rot, sub, checkable=True, checked=(cfg["layout"] == chave))
            a.triggered.connect(lambda _=False, c=chave: definir("layout", c, layout=True))
            grupo.addAction(a)
            sub.addAction(a)
        sub.addSeparator()
        for chave, rot in (("mostrar_nucleos", "Mostrar núcleos da CPU"),
                           ("mostrar_processos", "Mostrar maiores usos de RAM"),
                           ("mostrar_modo_jogo", "Mostrar botão Modo Jogo")):
            a = sub.addAction(rot)
            a.setCheckable(True)
            a.setChecked(cfg[chave])
            a.triggered.connect(lambda v, c=chave: definir(c, bool(v), layout=True))

        m.addSeparator()
        a = m.addAction("Modo Jogo: mostrar a lista antes de ativar")
        a.setCheckable(True)
        a.setChecked(cfg["modo_jogo_confirmar"])
        a.triggered.connect(lambda v: definir("modo_jogo_confirmar", bool(v)))
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
    if "--teste-topo" in sys.argv:       # só para testes: sempre por cima, sem mudar a configuração
        janela.teste_topo = True
    janela.winId()                      # cria o HWND antes de mostrar
    janela.posicionar()
    janela.show()
    janela.preparar_nativo()
    janela.posicionar()

    bandeja = QSystemTrayIcon(icone.icone(janela.t), app)
    bandeja.setToolTip("Monitor do PC")
    bandeja.setContextMenu(menu_bandeja)
    bandeja.activated.connect(
        lambda r: clique_bandeja() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    bandeja.show()

    controle = modo_jogo_ui.Controle(cfg, janela, bandeja)
    controle.iniciar()
    if "--modo-jogo" in sys.argv:
        QTimer.singleShot(1500, controle.alternar)

    # Monitor ligado/desligado (o vertical some quando dorme), resolução ou escala nova: o widget
    # volta para o monitor dele, ou para dentro de um monitor visível.
    reposicionar = QTimer(app)
    reposicionar.setSingleShot(True)
    reposicionar.setInterval(800)
    reposicionar.timeout.connect(janela.reposicionar)

    def vigiar_tela(t) -> None:
        for sinal in (t.geometryChanged, t.availableGeometryChanged, t.logicalDotsPerInchChanged):
            sinal.connect(lambda *_: reposicionar.start())

    for t in app.screens():
        vigiar_tela(t)
    app.screenAdded.connect(lambda t: (vigiar_tela(t), reposicionar.start()))
    app.screenRemoved.connect(lambda *_: reposicionar.start())
    app.primaryScreenChanged.connect(lambda *_: reposicionar.start())

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
        controle.tick(estado["ticks"])  # Modo Jogo: prioridade ao jogo em tela cheia
        if janela.isVisible():
            # Fixado por cima: um jogo em tela cheia no mesmo monitor tem prioridade (o widget sai
            # de cima dele e volta sozinho quando o jogo fecha ou sai da tela cheia).
            janela.suspender(janela.quer_topo() and winapi.tela_cheia_no_monitor_de(janela._hwnd))
            if estado["ticks"] % 3 == 0:
                janela.garantir_visivel()
        if (janela.d is not None and not janela.no_topo and janela.isVisible()
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
