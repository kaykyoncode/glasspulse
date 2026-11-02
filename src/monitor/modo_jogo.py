# -*- coding: utf-8 -*-
"""Modo Jogo: fecha o que não é essencial, pausa serviços em segundo plano e deixa o PC no máximo
para jogos; desligado, devolve tudo como estava (serviços, plano de energia, registro, apps).

Só mexe no que o usuário abriu na própria sessão. Processos do Windows, drivers, áudio, periféricos,
antivírus e antitrapaça ficam sempre. Apps abertos depois de ativar nunca são tocados.
A parte que exige administrador (serviços, memória em espera) fica em modo_jogo_admin.py."""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time
import uuid
import winreg
from dataclasses import dataclass, field

import psutil

from . import coletores, config, winapi

PASTA = os.path.join(config.PASTA, "modo_jogo")
ESTADO = os.path.join(PASTA, "estado.json")
PEDIDO = os.path.join(PASTA, "pedido.json")
TAREFA = "\\GlassPulse\\Modo Jogo"      # tarefa agendada elevada: depois da 1ª vez, sem UAC
SEM_JANELA = 0x08000000                 # CREATE_NO_WINDOW

WINDIR = os.environ.get("SystemRoot", r"C:\Windows").lower() + "\\"

# Programas da pasta do Windows ficam (são o sistema), menos estes, que são apps comuns.
FECHAVEIS_DO_WINDOWS = {
    "notepad.exe", "mspaint.exe", "mstsc.exe", "taskmgr.exe", "regedit.exe", "mmc.exe", "cmd.exe",
    "powershell.exe", "powershell_ise.exe", "wordpad.exe", "write.exe", "charmap.exe", "perfmon.exe",
    "resmon.exe", "msinfo32.exe", "control.exe", "systemsettings.exe", "wsl.exe", "wslhost.exe",
    "wslrelay.exe", "vmconnect.exe", "magnify.exe", "osk.exe",
}

# Hardware, drivers, áudio, periféricos, overlays de desempenho, antivírus e antitrapaça: nunca fecha.
MANTER = re.compile(r"(?<![a-z0-9])(" + "|".join([
    "nvidia", "nvcontainer", "nvdisplay", "nvsphelper", "nvbroadcast", "nvoverlay", "radeon", "amdrsserv",
    "igfx", "igcc", "intelgraphics", "driverstore",
    "lghub", "logioptionsplus", "logitech", "razer", "rzsynapse", "corsair", "icue", "steelseries",
    "hyperx", "ngenuity", "wooting", "roccat", "armoury", "asus", "lightingservice", "msi center",
    "msiafterburner", "msi afterburner", "rtss", "rivatuner", "evga", "alienware", "awcc",
    "thunder master", "thpanel", "nzxt", "signalrgb", "openrgb", "fancontrol", "hwinfo",
    "realtek", "rtkaud", "nahimic", "a-volute", "nhnotif", "waves", "maxxaudio", "dolby", "dts",
    "sonic studio", "voicemeeter", "vb-audio", "astro", "elgato", "streamdeck", "wacom", "synaptics",
    "kaspersky", "avp", "avpui", "ksde", "windows defender", "msmpeng",
    "vgtray", "vanguard", "easyanticheat", "battleye", "faceit", "anticheat", "anti-cheat", "nprotect",
    "xigncode", "gameinput", "xboxservice", "gamebar", "gamingservices",
    "translucenttb", "esconder",
]) + ")")

# Launchers de jogos: aparecem na lista desmarcados (dá para fechar, mas por padrão ficam).
LAUNCHERS = {
    "steam.exe", "steamwebhelper.exe", "steamservice.exe", "gameoverlayui.exe", "gameoverlayui64.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe", "epiconlineservicesuserhelper.exe",
    "epiconlineserviceshost.exe", "eosoverlayrenderer-win64-shipping.exe", "battle.net.exe",
    "riotclientservices.exe", "riotclientux.exe", "riotclientuxrender.exe", "riotclientcrashhandler.exe",
    "leagueclient.exe", "leagueclientux.exe", "leagueclientuxrender.exe", "eadesktop.exe",
    "eabackgroundservice.exe", "ealocalhostsvc.exe", "origin.exe", "upc.exe", "ubisoftconnect.exe",
    "uplaywebcore.exe", "galaxyclient.exe", "galaxyclient helper.exe", "playnite.desktopapp.exe",
    "playnite.fullscreenapp.exe", "hyp.exe", "hoyoplay.exe", "minecraftlauncher.exe", "xboxpcapp.exe",
    "xboxpcappft.exe", "xboxapp.exe", "rockstarlauncher.exe", "socialclubhelper.exe", "amazongames.exe",
    "itch.exe", "purple.exe", "proclient.exe",
}
# Jogo aberto (pela pasta onde está instalado): aparece desmarcado.
JOGO_CAMINHO = re.compile(
    r"\\(steamapps\\common|xboxgames|modifiablewindowsapps|riot games|gog galaxy\\games|gog games|"
    r"ubisoft game launcher\\games|ea games|origin games|hoyoplay\\games|games)\\|"
    r"\\epic games\\(?!launcher\\|epic online services\\)")
NAO_E_JOGO = re.compile(r"wallpaper_engine|wallpaper(32|64)\.exe")

# Pais que abrem apps do usuário: os filhos deles são avaliados por conta própria. Filho de qualquer
# outro processo que fica (ex.: o WebView2 da Pesquisa do Windows) fica junto com o pai.
PAIS_LANCADORES = {"explorer.exe", "svchost.exe", "sihost.exe", "userinit.exe", "taskhostw.exe",
                   "services.exe", "wininit.exe", "winlogon.exe", "runtimebroker.exe"}

# Interpretadores e ajudantes: fecham, mas não são reabertos sozinhos (poderiam repetir um script).
NUNCA_REABRIR = {
    "python.exe", "pythonw.exe", "py.exe", "node.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "bash.exe", "sh.exe", "wsl.exe", "wslhost.exe", "conhost.exe", "openconsole.exe", "java.exe",
    "ruby.exe", "deno.exe", "bun.exe", "uv.exe", "adb.exe", "git.exe", "ssh.exe", "msedgewebview2.exe",
    "crashpad_handler.exe", "werfault.exe",
}
SEMPRE_REABRIR = {"wallpaper64.exe", "wallpaper32.exe"}   # papel de parede animado volta sozinho

NOMES_GENERICOS = {"electron", "chromium", "node.js javascript runtime", "node.js", "java(tm) platform se binary"}

PLANO_MAXIMO = "e9a42b02-d5df-448d-aa00-03f14749eb61"   # "Desempenho Máximo" (Ultimate Performance)
PLANO_ALTO = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"     # "Alto desempenho"
_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Serviços que pausam junto com um app (só se esse app for fechado): nome do serviço -> app
SERVICOS_DE_APP = {"CoworkVMService": "claude", "CodexSandboxService.OpenAI.Codex": "chatgpt"}


@dataclass
class Grupo:
    nome: str
    categoria: str                     # fechar | launcher | jogo | wsl
    pids: list[int] = field(default_factory=list)
    reabrir: list[dict] = field(default_factory=list)
    criados: dict[int, float] = field(default_factory=dict)   # pid -> início (contra PID reaproveitado)
    ram: int = 0
    janela: bool = False

    @property
    def chave(self) -> str:
        return self.nome.lower()

    def sugestao(self) -> bool:
        return self.categoria in ("fechar", "wsl")


@dataclass
class Plano:
    grupos: list[Grupo]
    mantidos: list[str]                # apps do usuário que ficam (drivers, periféricos...)


# --------------------------------------------------------------------------- classificação

def classificar(nome: str, exe: str, tela_cheia: bool = False) -> str:
    """sistema | manter | jogo | launcher | fechar"""
    n, e = nome.lower(), (exe or "").lower()
    if not e:
        return "sistema"                # sem acesso ao caminho: na dúvida, fica
    if e.startswith(WINDIR) and n not in FECHAVEIS_DO_WINDOWS:
        return "sistema"
    if MANTER.search(e):
        return "manter"
    if n in LAUNCHERS:
        return "launcher"
    if NAO_E_JOGO.search(e):
        return "fechar"
    if tela_cheia or JOGO_CAMINHO.search(e):
        return "jogo"
    return "fechar"


_descricoes: dict[str, str] = {}


def nome_do_app(nome_exe: str, exe: str) -> str:
    base = nome_exe[:-4] if nome_exe.lower().endswith(".exe") else nome_exe
    if base.lower() in coletores._APELIDOS:
        return coletores.nome_amigavel(nome_exe)
    if exe not in _descricoes:
        _descricoes[exe] = winapi.descricao_arquivo(exe) if exe else ""
    d = _descricoes[exe]
    if d and len(d) <= 40 and d.lower() not in NOMES_GENERICOS and not d.lower().endswith(".exe"):
        return d
    return coletores.nome_amigavel(nome_exe)


def _exe_do_comando(cmd: str) -> str:
    cmd = cmd.strip()
    if cmd.startswith('"'):
        return cmd[1:].split('"', 1)[0]
    i = cmd.lower().find(".exe")
    return cmd[:i + 4] if i > 0 else ""


def _alvo_do_atalho(lnk: str) -> str:
    """Caminho do .exe dentro de um atalho .lnk (sem COM: procura o caminho no próprio arquivo)."""
    try:
        with open(lnk, "rb") as f:
            dados = f.read(16384)
    except OSError:
        return ""
    for texto in (dados.decode("utf-16-le", "ignore"), dados.decode("latin-1", "ignore")):
        m = re.search(r"[A-Za-z]:\\[^\x00-\x1f\"*?<>|]+?\.exe", texto, re.I)
        if m:
            return m.group(0)
    return ""


def _inicializacao() -> dict[str, str]:
    """exe (minúsculo) -> como o Windows o abre no logon: 'cmd:<comando do Run>' ou 'lnk:<atalho>'."""
    saida: dict[str, str] = {}
    run = r"Software\Microsoft\Windows\CurrentVersion\Run"
    for raiz, sub in ((winreg.HKEY_CURRENT_USER, run), (winreg.HKEY_LOCAL_MACHINE, run),
                      (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")):
        try:
            k = winreg.OpenKey(raiz, sub)
        except OSError:
            continue
        with k:
            i = 0
            while True:
                try:
                    _nome, valor, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                comando = os.path.expandvars(str(valor))
                exe = _exe_do_comando(comando)
                if exe:
                    saida.setdefault(exe.lower(), "cmd:" + comando)
    pastas = [os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
              os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                           r"Microsoft\Windows\Start Menu\Programs\StartUp")]
    for pasta in pastas:
        for lnk in glob.glob(os.path.join(pasta, "*.lnk")):
            alvo = _alvo_do_atalho(lnk)
            if alvo:
                saida.setdefault(alvo.lower(), "lnk:" + lnk)
    return saida


# --------------------------------------------------------------------------- planejamento

def planejar() -> Plano:
    """Lê o que está aberto e monta os grupos (um por app) que o Modo Jogo pode fechar."""
    eu = psutil.Process()
    usuario, minha_sessao = eu.username(), winapi.sessao(eu.pid)
    protegidos = {eu.pid} | {c.pid for c in eu.children(recursive=True)}
    janelas = winapi.janelas_por_processo()
    tela_cheia = winapi.pid_tela_cheia()

    mapa = coletores.mapa_processos()   # uma foto só: pedir o pai de cada um ao psutil leva segundos
    procs: dict[int, dict] = {}
    for p in psutil.process_iter(["username"]):
        if p.pid in (0, 4) or p.info["username"] != usuario or winapi.sessao(p.pid) != minha_sessao:
            continue
        try:
            exe, criado = p.exe(), p.create_time()
        except psutil.Error:
            exe, criado = "", 0.0
        ppid, nome = mapa.get(p.pid, (0, ""))
        procs[p.pid] = {"pid": p.pid, "ppid": ppid, "name": nome or os.path.basename(exe), "exe": exe,
                        "create_time": criado, "proc": p}

    def pai(pid: int) -> int:
        i = procs[pid]
        pp = procs.get(i["ppid"])
        # PID reaproveitado: um "pai" que nasceu depois do filho não é o pai
        if pp is None or (pp["create_time"] or 0) > (i["create_time"] or 0) + 1:
            return 0
        return i["ppid"]

    propria = {pid: ("sistema" if pid in protegidos else
                     classificar(i["name"] or "", i["exe"] or "", pid == tela_cheia))
               for pid, i in procs.items()}
    for pid, i in procs.items():        # Minecraft roda no javaw: só é jogo se a linha de comando disser
        if (i["name"] or "").lower() == "javaw.exe" and propria[pid] == "fechar":
            try:
                if "minecraft" in " ".join(i["proc"].cmdline()).lower():
                    propria[pid] = "jogo"
            except psutil.Error:
                pass

    efetiva: dict[int, str] = {}

    def categoria(pid: int, profundidade: int = 0) -> str:
        if pid in efetiva:
            return efetiva[pid]
        c = propria[pid]
        pp = pai(pid)
        if c not in ("sistema", "manter") and pp and profundidade < 64:
            cp = categoria(pp, profundidade + 1)
            if cp in ("sistema", "manter") and (procs[pp]["name"] or "").lower() not in PAIS_LANCADORES:
                c = cp                  # ajudante de algo que fica: fica junto
            elif procs[pp]["exe"] and procs[pp]["exe"] == procs[pid]["exe"]:
                c = cp                  # mesmo programa (abas e GPU de um navegador): mesmo destino
        efetiva[pid] = c
        return c

    for pid in procs:
        categoria(pid)
    candidatos = {pid for pid, c in efetiva.items() if c in ("fechar", "launcher", "jogo")}

    filhos: dict[int, list[int]] = {}
    for pid in procs:
        pp = pai(pid)
        if pp:
            filhos.setdefault(pp, []).append(pid)

    def arvore(raiz: int) -> list[int]:
        saida, pilha = [], [raiz]
        while pilha:
            pid = pilha.pop()
            saida.append(pid)
            pilha.extend(f for f in filhos.get(pid, []) if f in candidatos and efetiva[f] == efetiva[raiz])
        return saida

    inicio = _inicializacao()
    grupos: dict[tuple[str, str], Grupo] = {}
    for pid in sorted(candidatos):
        pp = pai(pid)
        if pp in candidatos and efetiva[pp] == efetiva[pid]:
            continue                    # não é raiz: entra no grupo do pai
        i = procs[pid]
        nome = nome_do_app(i["name"] or "", i["exe"] or "")
        cat = efetiva[pid]
        g = grupos.setdefault((nome.lower(), cat), Grupo(nome, cat))
        membros = arvore(pid)
        g.pids += membros
        g.criados.update({m: procs[m]["create_time"] or 0.0 for m in membros})
        g.ram += sum(coletores.ram_privada(m) for m in membros)
        com_janela = any(principal for m in membros for _h, _c, principal in janelas.get(m, []))
        g.janela |= com_janela
        g.reabrir.append(_como_reabrir(i, com_janela, inicio))

    lista = sorted(grupos.values(), key=lambda g: ({"jogo": 0, "fechar": 1, "launcher": 2}[g.categoria], -g.ram))
    if any(nome.lower() in ("vmmemwsl", "vmmem") for _pp, nome in mapa.values()) and _wsl_rodando():
        lista.append(Grupo("WSL / Docker (Linux)", "wsl"))

    mantidos = sorted({nome_do_app(procs[pid]["name"] or "", procs[pid]["exe"] or "")
                       for pid, c in efetiva.items() if c == "manter" and pid not in protegidos})
    return Plano(lista, mantidos)


def _wsl_rodando() -> bool:
    try:
        r = subprocess.run(["wsl.exe", "--list", "--running", "--quiet"], capture_output=True,
                           timeout=8, creationflags=SEM_JANELA)
        return r.returncode == 0 and bool(r.stdout.decode("utf-16-le", "ignore").strip(" \r\n\x00"))
    except (OSError, subprocess.SubprocessError):
        return False


def _como_reabrir(info: dict, janela: bool, inicio: dict[str, str]) -> dict:
    p: psutil.Process = info["proc"]
    exe = info["exe"] or ""
    try:
        cmd = p.cmdline()
    except psutil.Error:
        cmd = [exe]
    try:
        pasta = p.cwd()
    except psutil.Error:
        pasta = os.path.dirname(exe)
    return {"nome": info["name"] or "", "exe": exe, "cmd": cmd, "pasta": pasta,
            "aumid": winapi.aumid(info["pid"]), "janela": janela, "inicio": inicio.get(exe.lower(), "")}


# --------------------------------------------------------------------------- estado salvo

def carregar_estado() -> dict:
    try:
        with open(ESTADO, encoding="utf-8") as f:
            e = json.load(f)
        return e if isinstance(e, dict) else {}
    except (OSError, ValueError):
        return {}


def salvar_estado(e: dict) -> None:
    os.makedirs(PASTA, exist_ok=True)
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ESTADO)


def apagar_estado() -> None:
    for arq in (ESTADO, os.path.join(PASTA, "admin.json")):
        try:
            os.remove(arq)
        except OSError:
            pass


def ativo() -> bool:
    return bool(carregar_estado().get("ativo"))


# --------------------------------------------------------------------------- fechar e reabrir apps

def _janelas_principais(pids, janelas) -> list[int]:
    return [h for pid in pids for h, _c, principal in janelas.get(pid, []) if principal]


def _ainda_pede_algo(pids, janelas) -> bool:
    """Janela visível depois do pedido de fechar = o app está perguntando (ex.: salvar alterações)."""
    return any(principal or classe == "#32770" for pid in pids for _h, classe, principal in janelas.get(pid, []))


def _vivos(pids) -> list[int]:
    return [p for p in pids if psutil.pid_exists(p)]


def fechar_grupos(grupos: list[Grupo], progresso, espera: float = 8.0) -> tuple[list[Grupo], list[str], list[int]]:
    """Fecha como o X da janela; quem some para a bandeja ou não tem janela é encerrado. Quem continua
    com janela aberta (perguntando se quer salvar) fica, para não perder trabalho.
    Devolve (fechados, nomes que não fecharam, pids que precisam de administrador)."""
    janelas = winapi.janelas_por_processo()
    pendentes: dict[int, Grupo] = {}
    elevados: list[int] = []
    fechados: list[Grupo] = []

    def encerrar(g: Grupo) -> None:
        for pid in g.pids:
            try:
                p = psutil.Process(pid)
                if abs(p.create_time() - g.criados.get(pid, p.create_time())) > 1:
                    continue            # o processo original já saiu e o PID é de outro
                p.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                elevados.append(pid)
        fechados.append(g)

    for n, g in enumerate(grupos, 1):
        progresso(f"Fechando {g.nome} ({n}/{len(grupos)})…")
        hwnds = _janelas_principais(g.pids, janelas)
        if hwnds:
            for h in hwnds:
                winapi.fechar_janela(h)
            pendentes[id(g)] = g
        else:
            encerrar(g)

    limite = time.monotonic() + espera
    escondido_desde: dict[int, float] = {}
    while pendentes and time.monotonic() < limite:
        time.sleep(0.25)
        janelas = winapi.janelas_por_processo()
        agora = time.monotonic()
        for k, g in list(pendentes.items()):
            vivos = _vivos(g.pids)
            if not vivos:
                fechados.append(g)
                del pendentes[k]
            elif not _ainda_pede_algo(vivos, janelas):
                if agora - escondido_desde.setdefault(k, agora) >= 3.0:   # foi para a bandeja (ou terminando)
                    encerrar(g)
                    del pendentes[k]
            else:
                escondido_desde.pop(k, None)

    janelas = winapi.janelas_por_processo()
    teimosos = []
    for g in pendentes.values():
        vivos = _vivos(g.pids)
        if vivos and _ainda_pede_algo(vivos, janelas):
            teimosos.append(g.nome)
        else:
            encerrar(g)
    restantes = []
    for pid in sum((g.pids for g in fechados), []):
        if pid not in elevados:
            try:
                restantes.append(psutil.Process(pid))
            except psutil.NoSuchProcess:
                pass
    psutil.wait_procs(restantes, timeout=3)
    return fechados, teimosos, elevados


def _popen(cmd, pasta: str | None = None) -> bool:
    """Abre como um app normal: prioridade normal (o widget roda abaixo do normal) e sem herdar o
    ambiente do Qt."""
    ambiente = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}
    base = 0x20 | 0x200 | 0x08          # NORMAL_PRIORITY_CLASS | CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    pasta = pasta if pasta and os.path.isdir(pasta) else None
    for extra in (0x01000000, 0):       # CREATE_BREAKAWAY_FROM_JOB, se o job deixar
        try:
            subprocess.Popen(cmd, cwd=pasta, env=ambiente, creationflags=base | extra, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False


def reabrir(r: dict) -> bool:
    if r.get("aumid"):
        return _popen(["explorer.exe", "shell:AppsFolder\\" + r["aumid"]])
    inicio = r.get("inicio") or ""
    if inicio.startswith("lnk:"):
        return _popen(["explorer.exe", inicio[4:]])
    if inicio.startswith("cmd:"):
        return _popen(inicio[4:], os.path.dirname(r.get("exe", "")))
    if r.get("exe") and os.path.exists(r["exe"]):
        cmd = r.get("cmd") or [r["exe"]]
        if r["nome"].lower() not in SEMPRE_REABRIR and any(a.startswith("-") for a in cmd[1:]):
            cmd = [r["exe"]]            # flags internas (navegador, Electron): abre limpo; só arquivo passa
        return _popen(cmd, r.get("pasta"))
    return False


def para_reabrir(grupos: list[Grupo]) -> list[dict]:
    """Só o que dá para reabrir sem surpresa: apps com janela, os que abrem com o Windows e o papel
    de parede animado. Um por executável."""
    saida, vistos = [], set()
    for g in grupos:
        for r in g.reabrir:
            nome = r["nome"].lower()
            if nome in NUNCA_REABRIR and nome not in SEMPRE_REABRIR:
                continue
            if not (r["janela"] or r["inicio"] or nome in SEMPRE_REABRIR):
                continue
            chave = r["aumid"] or r["exe"].lower()
            if chave and chave not in vistos:
                vistos.add(chave)
                saida.append(r)
    return saida


# --------------------------------------------------------------------------- plano de energia e registro

def _powercfg(*args: str) -> str:
    try:
        r = subprocess.run(["powercfg", *args], capture_output=True, timeout=20, creationflags=SEM_JANELA)
        return r.stdout.decode("cp850", "ignore") if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def plano_ativo() -> str:
    m = _GUID.search(_powercfg("/getactivescheme"))
    return m.group(0).lower() if m else ""


def planos() -> dict[str, str]:
    saida = {}
    for linha in _powercfg("/list").splitlines():
        m = _GUID.search(linha)
        if m:
            nome = re.search(r"\((.*)\)", linha)
            saida[m.group(0).lower()] = nome.group(1) if nome else ""
    return saida


def plano_de_jogo(salvo: str) -> str:
    """'Desempenho Máximo' (cria na 1ª vez a partir do modelo do Windows); se não der, 'Alto desempenho'."""
    existentes = planos()
    if salvo and salvo.lower() in existentes:
        return salvo.lower()
    for guid, nome in existentes.items():
        if guid == PLANO_MAXIMO or re.search(r"desempenho m[aá]ximo|ultimate", nome, re.I):
            return guid
    m = _GUID.search(_powercfg("-duplicatescheme", PLANO_MAXIMO))
    if m:
        return m.group(0).lower()
    return PLANO_ALTO if PLANO_ALTO in existentes else ""


def definir_plano(guid: str) -> bool:
    return bool(guid) and subprocess.run(["powercfg", "/setactive", guid], capture_output=True,
                                         creationflags=SEM_JANELA).returncode == 0


_REG_JOGO = (r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
_REG_DX = (r"Software\Microsoft\DirectX\UserGpuPreferences", "DirectXUserGlobalSettings")


def _ler_reg(caminho: str, valor: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as k:
            return winreg.QueryValueEx(k, valor)[0]
    except OSError:
        return None


def _gravar_reg(caminho: str, valor: str, dado, tipo) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, caminho, 0, winreg.KEY_SET_VALUE) as k:
        if dado is None:
            try:
                winreg.DeleteValue(k, valor)
            except OSError:
                pass
        else:
            winreg.SetValueEx(k, valor, 0, tipo, dado)


def aplicar_registro() -> dict:
    """Modo de Jogo do Windows ligado + 'Otimizações para jogos em janela' (modelo flip, menos latência
    em jogos sem bordas). Devolve os valores de antes."""
    antes = {"jogo": _ler_reg(*_REG_JOGO), "dx": _ler_reg(*_REG_DX)}
    try:
        _gravar_reg(*_REG_JOGO, 1, winreg.REG_DWORD)
        pares = dict(p.split("=", 1) for p in str(antes["dx"] or "").split(";") if "=" in p)
        pares["SwapEffectUpgradeEnable"] = "1"
        _gravar_reg(*_REG_DX, "".join(f"{k}={v};" for k, v in pares.items()), winreg.REG_SZ)
    except OSError:
        pass
    return antes


def restaurar_registro(antes: dict) -> None:
    try:
        _gravar_reg(*_REG_JOGO, antes.get("jogo"), winreg.REG_DWORD)
        _gravar_reg(*_REG_DX, antes.get("dx"), winreg.REG_SZ)
    except OSError:
        pass


# --------------------------------------------------------------------------- parte de administrador

def _tarefa_existe() -> bool:
    try:
        return subprocess.run(["schtasks", "/Query", "/TN", TAREFA], capture_output=True, timeout=15,
                              creationflags=SEM_JANELA).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def precisa_permissao() -> bool:
    """True até a 1ª ativação criar a tarefa elevada (nessa vez o Windows mostra o UAC)."""
    return not _tarefa_existe()


def pedir_admin(acao: str, **dados) -> dict | None:
    """Manda o ajudante elevado fazer `acao`. Pela tarefa agendada não aparece UAC; sem ela (1ª vez),
    o Windows pede permissão e o próprio ajudante cria a tarefa. None = sem permissão."""
    os.makedirs(PASTA, exist_ok=True)
    id_ = uuid.uuid4().hex
    tmp = PEDIDO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"id": id_, "acao": acao, "criado": time.time(), **dados}, f)
    os.replace(tmp, PEDIDO)
    resposta = os.path.join(PASTA, f"resposta-{id_}.json")

    handle = None
    if _tarefa_existe() and subprocess.run(["schtasks", "/Run", "/TN", TAREFA], capture_output=True,
                                           creationflags=SEM_JANELA).returncode == 0:
        pass
    else:
        script = os.path.join(config.RAIZ, "monitor_pc.pyw")
        handle = winapi.executar_como_admin(config._pythonw(), f'"{script}" --modo-jogo-admin --instalar-tarefa',
                                            config.RAIZ)
        if handle is None:
            return None

    limite = time.monotonic() + 120
    try:
        while time.monotonic() < limite:
            if os.path.exists(resposta):
                time.sleep(0.1)
                try:
                    with open(resposta, encoding="utf-8") as f:
                        r = json.load(f)
                    os.remove(resposta)
                    return r
                except (OSError, ValueError):
                    pass
            if handle and winapi.processo_terminou(handle) and not os.path.exists(resposta):
                time.sleep(1.0)
                if not os.path.exists(resposta):
                    return None
            time.sleep(0.2)
        return None
    finally:
        if handle:
            winapi.fechar_handle(handle)


# --------------------------------------------------------------------------- ligar e desligar

def ativar(plano: Plano, escolhidos: list[Grupo], plano_salvo: str, progresso) -> dict:
    """Liga o Modo Jogo. O estado vai para o disco antes de fechar qualquer coisa: se algo cair no
    meio, o 'desligar' ainda sabe o que devolver."""
    livre_antes = psutil.virtual_memory().available
    apps = [g for g in escolhidos if g.categoria != "wsl"]
    e = {"ativo": True, "desde": time.time(), "boot": psutil.boot_time(),
         "plano_anterior": plano_ativo(), "registro": None, "reabrir": para_reabrir(apps),
         "prioridades": {}, "admin": False}
    salvar_estado(e)

    fechados, teimosos, elevados = fechar_grupos(apps, progresso)
    if any(g.categoria == "wsl" for g in escolhidos):
        progresso("Desligando o WSL / Docker…")
        try:
            subprocess.run(["wsl.exe", "--shutdown"], capture_output=True, timeout=60, creationflags=SEM_JANELA)
        except (OSError, subprocess.SubprocessError):
            pass

    progresso("Pausando serviços em segundo plano…")
    fechou = " ".join(g.nome.lower() for g in fechados)
    servicos_app = [s for s, app in SERVICOS_DE_APP.items() if app in fechou]
    adm = pedir_admin("ativar", pids=elevados, servicos_apps=servicos_app)
    e["admin"] = adm is not None

    progresso("Plano de energia no máximo…")
    guid = plano_de_jogo(plano_salvo)
    if guid and guid != e["plano_anterior"]:
        definir_plano(guid)
    e["registro"] = aplicar_registro()
    salvar_estado(e)

    time.sleep(1.5)                     # o Windows leva um instante para devolver a memória
    e.update({
        "fechados": len(fechados) + (1 if any(g.categoria == "wsl" for g in escolhidos) else 0),
        "teimosos": teimosos + [f"{n} (precisa de administrador)" for n in (adm or {}).get("nao_fechou", [])],
        "liberado": max(0, psutil.virtual_memory().available - livre_antes),
        "servicos": (adm or {}).get("parados", []),
        "plano_jogo": guid,
    })
    salvar_estado(e)
    return e


def desativar(progresso, reabrir_apps: bool = True) -> dict:
    """Desliga: serviços, plano de energia, registro e prioridade voltam; os apps fechados reabrem."""
    e = carregar_estado()
    resumo = {"retomados": [], "reabertos": 0}
    if e.get("admin"):
        progresso("Retomando serviços…")
        adm = pedir_admin("desativar")
        resumo["retomados"] = (adm or {}).get("retomados", [])
    progresso("Restaurando plano de energia…")
    if e.get("plano_anterior"):
        definir_plano(e["plano_anterior"])
    if e.get("registro") is not None:
        restaurar_registro(e["registro"])
    restaurar_prioridades(e)
    if reabrir_apps:
        lista = e.get("reabrir", [])
        for n, r in enumerate(lista, 1):
            progresso(f"Reabrindo {coletores.nome_amigavel(r['nome'])} ({n}/{len(lista)})…")
            if reabrir(r):
                resumo["reabertos"] += 1
            time.sleep(0.4)             # um de cada vez, sem pico de disco/CPU
    apagar_estado()
    return resumo


def restaurar_depois_de_reiniciar() -> bool:
    """O PC reiniciou com o Modo Jogo ligado: serviços já voltaram sozinhos e os apps de inicialização
    abrem com o Windows; falta só o plano de energia e o registro."""
    e = carregar_estado()
    if not e.get("ativo") or abs(e.get("boot", 0) - psutil.boot_time()) < 5:
        return False
    if e.get("plano_anterior"):
        definir_plano(e["plano_anterior"])
    if e.get("registro") is not None:
        restaurar_registro(e["registro"])
    apagar_estado()
    return True


# --------------------------------------------------------------------------- prioridade do jogo

def impulsionar_jogo(e: dict, tentados: set[int]) -> None:
    """Jogo em tela cheia aberto depois de ativar: prioridade 'acima do normal' (alta demais pode
    atrapalhar áudio e mouse). Volta ao normal quando o Modo Jogo desliga."""
    pid = winapi.pid_tela_cheia()
    if not pid or pid in tentados or pid == os.getpid():
        return
    tentados.add(pid)
    try:
        p = psutil.Process(pid)
        if p.name().lower() in ("explorer.exe",) or p.nice() != psutil.NORMAL_PRIORITY_CLASS:
            return
        p.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
        e.setdefault("prioridades", {})[str(pid)] = p.create_time()
        salvar_estado(e)
    except psutil.Error:
        pass


def restaurar_prioridades(e: dict) -> None:
    for pid, criado in (e.get("prioridades") or {}).items():
        try:
            p = psutil.Process(int(pid))
            if abs(p.create_time() - criado) < 1 and p.nice() == psutil.ABOVE_NORMAL_PRIORITY_CLASS:
                p.nice(psutil.NORMAL_PRIORITY_CLASS)
        except (psutil.Error, ValueError):
            pass


# --------------------------------------------------------------------------- simulação (teste)

def simular() -> int:
    """`python monitor_pc.pyw --modo-jogo-simular`: mostra o que o Modo Jogo faria, sem fazer nada."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    from . import modo_jogo_admin
    t0 = time.monotonic()
    plano = planejar()
    print(f"Análise em {time.monotonic() - t0:.1f} s\n")
    rotulo = {"fechar": "FECHA", "launcher": "fica (launcher)", "jogo": "fica (jogo aberto)", "wsl": "FECHA"}
    for g in plano.grupos:
        print(f"[{'x' if g.sugestao() else ' '}] {g.nome:34.34s} {g.ram / 2 ** 20:7.0f} MB  {len(g.pids):3d} proc  "
              f"{'janela' if g.janela else '      '}  {rotulo[g.categoria]}")
    print("\nReabre ao desligar:")
    for r in para_reabrir([g for g in plano.grupos if g.sugestao()]):
        como = "AppsFolder" if r["aumid"] else (r["inicio"][:4] or "exe")
        print(f"  - {r['nome']:32s} via {como}  {r['aumid'] or r['inicio'][4:] or ' '.join(r['cmd'])[:90]}")
    print("\nFicam sempre (drivers, periféricos, antivírus):", ", ".join(plano.mantidos) or "—")
    print("\nServiços que pausariam (se estiverem rodando):")
    for nome, desc, estado in modo_jogo_admin.situacao_servicos():
        print(f"  {'*' if estado == 'running' else ' '} {nome:34s} {estado:10s} {desc}")
    print(f"\nPlano de energia agora: {plano_ativo()}  ->  Desempenho Máximo")
    print(f"Tarefa elevada instalada: {'sim' if not precisa_permissao() else 'não (1ª ativação pede UAC)'}")
    return 0
