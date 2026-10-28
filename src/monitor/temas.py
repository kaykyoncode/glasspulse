# -*- coding: utf-8 -*-
"""Sistema de temas: cada tema é um JSON em `temas/` (do projeto) ou em %APPDATA%\\MonitorPC\\temas
(seus, têm prioridade). Qualquer campo ausente ou inválido herda do tema padrão."""
from __future__ import annotations

import copy
import glob
import json
import os
import re

from . import config

PASTA_PROJETO = os.path.join(config.RAIZ, "temas")
PASTA_USUARIO = os.path.join(config.PASTA, "temas")

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

PADRAO = {
    "nome": "Noite",
    "descricao": "Violeta e ciano sobre vidro azul-noite.",
    "cores": {"cpu": "#8E7CFF", "ram": "#27D3F0", "gpu": "#7BE27A", "download": "#58A6FF",
              "upload": "#FF7EB6", "disco": "#FFB84D", "neutro": "#9AA7C7"},
    "alerta": {"medio": "#FFB84D", "critico": "#FF5C70"},
    "vidro": {"tinta": "#0A0C14", "lavagem1": "#8E7CFF", "lavagem1_alpha": 52,
              "lavagem2": "#27D3F0", "lavagem2_alpha": 34, "cartao": "#FFFFFF", "borda": "#FFFFFF"},
    "texto": "#FFFFFF",
    "marca": ["#8E7CFF", "#27D3F0"],
    "icone": "",
}


class Tema:
    """Valores já validados e prontos para o desenho."""

    def __init__(self, id_: str, d: dict) -> None:
        self.id, self.nome, self.descricao = id_, str(d["nome"]), str(d.get("descricao", ""))
        c, a, v = d["cores"], d["alerta"], d["vidro"]
        self.cpu, self.ram, self.gpu = c["cpu"], c["ram"], c["gpu"]
        self.down, self.up, self.disco, self.neutro = c["download"], c["upload"], c["disco"], c["neutro"]
        self.medio, self.critico = a["medio"], a["critico"]
        self.tinta = v["tinta"]
        self.lavagem1, self.lavagem1_alpha = v["lavagem1"], int(v["lavagem1_alpha"])
        self.lavagem2, self.lavagem2_alpha = v["lavagem2"], int(v["lavagem2_alpha"])
        self.cartao, self.borda = v["cartao"], v["borda"]
        self.texto = d["texto"]
        self.marca = list(d["marca"])
        self.icone = d.get("icone", "")

    def caminho_icone(self) -> str:
        return os.path.join(config.RAIZ, self.icone) if self.icone else ""


def _cor_ok(v) -> bool:
    return isinstance(v, str) and bool(_HEX.match(v))


def _mesclar(base: dict, extra: dict) -> dict:
    """Mescla `extra` sobre `base` ignorando cores inválidas (o padrão cobre o buraco)."""
    saida = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if k not in saida:
            continue
        if isinstance(saida[k], dict) and isinstance(v, dict):
            saida[k] = _mesclar(saida[k], v)
        elif k == "marca":
            if isinstance(v, list) and len(v) == 2 and all(_cor_ok(x) for x in v):
                saida[k] = v
        elif isinstance(saida[k], str) and (saida[k].startswith("#") or k == "texto"):
            if _cor_ok(v):
                saida[k] = v
        elif isinstance(saida[k], int) and not isinstance(saida[k], bool):
            if isinstance(v, (int, float)):
                saida[k] = max(0, min(255, int(v)))
        elif isinstance(v, type(saida[k])):
            saida[k] = v
    return saida


def listar() -> dict[str, Tema]:
    """id -> Tema. O 'padrao' sempre existe, mesmo sem arquivos."""
    temas = {"padrao": Tema("padrao", PADRAO)}
    for pasta in (PASTA_PROJETO, PASTA_USUARIO):
        for arq in sorted(glob.glob(os.path.join(pasta, "*.json"))):
            try:
                with open(arq, encoding="utf-8") as f:
                    bruto = json.load(f)
                id_ = os.path.splitext(os.path.basename(arq))[0].lower()
                temas[id_] = Tema(id_, _mesclar(PADRAO, bruto))
            except (OSError, ValueError, KeyError, TypeError):
                continue                      # tema quebrado nunca derruba o widget
    return temas


def obter(id_: str | None) -> Tema:
    todos = listar()
    return todos.get(str(id_).lower(), todos["padrao"])
