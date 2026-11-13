# -*- coding: utf-8 -*-
"""Configurações salvas em %APPDATA%\\CorePulse\\config.json e atalho de inicialização."""
from __future__ import annotations

import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PASTA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "CorePulse")
ARQUIVO = os.path.join(PASTA, "config.json")
LOG = os.path.join(PASTA, "erro.log")

VERSAO = 2                      # sobe quando um padrão muda e as configurações salvas precisam migrar

PADRAO = {
    "versao": VERSAO,
    "monitor": None,            # nome do monitor no Qt; None = principal
    "ancora": "sup-dir",        # sup-dir | sup-esq | inf-dir | inf-esq | centro
    "livre": False,             # True depois que o usuário arrasta o widget
    "x_rel": 0,                 # posição livre, relativa ao canto do monitor
    "y_rel": 0,
    "travado": False,
    "fixado": False,            # alfinete: True = sempre por cima das janelas; False = atrás dos apps
    "tema": "padrao",           # só escolhe a arte do ícone da bandeja (temas/ ou %APPDATA%\\CorePulse\\temas)
    "layout": "coluna",         # coluna | painel (se não couber no monitor, usa o outro sozinho)
    "mostrar_nucleos": True,
    "mostrar_processos": True,
    "plano_mbps": 0,            # velocidade contratada em Mb/s, para "% do plano" (0 = esconde)
    "mostrar_modo_jogo": True,  # botão Modo Jogo abaixo do cabeçalho
    "modo_jogo_confirmar": True,  # mostra a lista do que vai fechar antes de ativar
    "modo_jogo_escolhas": {},   # app (minúsculo) -> fechar? — lembra o que foi marcado na lista
    "modo_jogo_plano": "",      # GUID do plano "Desempenho Máximo" criado na primeira ativação
}


def migrar_dados() -> None:
    """Preserva as preferências e o estado do Modo Jogo de instalações anteriores.

    Só move a pasta quando ainda não existe uma instalação CorePulse. Nunca
    sobrescreve configurações novas nem apaga a origem se a migração falhar.
    """
    if os.path.exists(PASTA):
        return
    base = os.path.dirname(PASTA)
    for nome in ("MonitorPC", "GlassPulse"):
        anterior = os.path.join(base, nome)
        if os.path.isdir(anterior):
            os.rename(anterior, PASTA)
            return


class Config(dict):
    def __init__(self) -> None:
        super().__init__(PADRAO)
        try:
            with open(ARQUIVO, encoding="utf-8") as f:
                salvo = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(salvo, dict):
            return
        self.update({k: v for k, v in salvo.items() if k in PADRAO})
        versao = salvo.get("versao", 1)
        if not isinstance(versao, int) or versao < VERSAO:
            self._migrar(versao if isinstance(versao, int) else 1)

    def _migrar(self, de: int) -> None:
        """Roda uma vez por versão, para quem já tinha configurações salvas."""
        if de < 2:
            # Até a versão 1 o alfinete vinha ligado por padrão (widget por cima dos apps) sem o
            # usuário escolher. Volta para trás dos apps; quem quiser, liga de novo pelo alfinete.
            self["fixado"] = False
        self["versao"] = VERSAO
        self.salvar()

    def salvar(self) -> None:
        try:
            os.makedirs(PASTA, exist_ok=True)
            tmp = ARQUIVO + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self, f, ensure_ascii=False, indent=2)
            os.replace(tmp, ARQUIVO)
        except OSError:
            pass


# ---- iniciar com o Windows (atalho na pasta shell:startup) ---------------------------

def _pasta_inicializar() -> str:
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup")


def atalho_inicio() -> str:
    return os.path.join(_pasta_inicializar(), "CorePulse.lnk")


def inicio_ativo() -> bool:
    return os.path.exists(atalho_inicio())


def _pythonw() -> str:
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return exe


def criar_atalho(destino: str) -> None:
    script = os.path.join(RAIZ, "corepulse.pyw")
    tema = str(Config().get("tema", "padrao"))
    ico = os.path.join(RAIZ, "assets", f"icone-{tema}.ico")
    if not os.path.exists(ico):
        ico = os.path.join(RAIZ, "assets", "icone.ico")
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        "$s.TargetPath='{exe}';$s.Arguments='\"{script}\"';$s.WorkingDirectory='{raiz}';"
        "$s.IconLocation='{ico}';$s.Description='CorePulse (widget de recursos)';"
        "$s.WindowStyle=7;$s.Save()"
    ).format(lnk=destino, exe=_pythonw(), script=script, raiz=RAIZ, ico=ico)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=0x08000000, check=False, timeout=30)


def definir_inicio(ativo: bool) -> None:
    lnk = atalho_inicio()
    if ativo:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        criar_atalho(lnk)
    elif os.path.exists(lnk):
        os.remove(lnk)
