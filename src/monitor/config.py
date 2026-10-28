# -*- coding: utf-8 -*-
"""Configurações salvas em %APPDATA%\\MonitorPC\\config.json e atalho de inicialização."""
from __future__ import annotations

import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PASTA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MonitorPC")
ARQUIVO = os.path.join(PASTA, "config.json")
LOG = os.path.join(PASTA, "erro.log")

PADRAO = {
    "monitor": None,            # nome do monitor no Qt; None = principal
    "ancora": "sup-dir",        # sup-dir | sup-esq | inf-dir | inf-esq | centro
    "livre": False,             # True depois que o usuário arrasta o widget
    "x_rel": 0,                 # posição livre, relativa ao canto do monitor
    "y_rel": 0,
    "travado": False,
    "vidro": "medio",           # leve | medio | fosco
    "layout": "coluna",         # coluna | painel
    "mostrar_nucleos": True,
    "mostrar_processos": True,
    "plano_mbps": 0,            # velocidade contratada em Mb/s, para "% do plano" (0 = esconde)
}


class Config(dict):
    def __init__(self) -> None:
        super().__init__(PADRAO)
        try:
            with open(ARQUIVO, encoding="utf-8") as f:
                salvo = json.load(f)
            self.update({k: v for k, v in salvo.items() if k in PADRAO})
        except (OSError, ValueError):
            pass

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
    return os.path.join(_pasta_inicializar(), "Monitor do PC.lnk")


def inicio_ativo() -> bool:
    return os.path.exists(atalho_inicio())


def _pythonw() -> str:
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return exe


def criar_atalho(destino: str) -> None:
    script = os.path.join(RAIZ, "monitor_pc.pyw")
    ico = os.path.join(RAIZ, "assets", "icone.ico")
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        "$s.TargetPath='{exe}';$s.Arguments='\"{script}\"';$s.WorkingDirectory='{raiz}';"
        "$s.IconLocation='{ico}';$s.Description='Monitor do PC (widget de recursos)';"
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
