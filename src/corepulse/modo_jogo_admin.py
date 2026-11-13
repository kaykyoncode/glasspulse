# -*- coding: utf-8 -*-
"""Parte do Modo Jogo que precisa de administrador: pausar/retomar serviços, encerrar apps abertos
como administrador e esvaziar a memória em espera.

Roda como `pythonw corepulse.pyw --modo-jogo-admin`, pela tarefa agendada "\\CorePulse\\Modo Jogo"
(elevada, criada uma vez com `--instalar-tarefa`). Lê o pedido em %APPDATA%\\CorePulse\\modo_jogo e
responde no mesmo lugar. Só age sobre a lista fixa de serviços abaixo e revalida cada processo antes de
encerrar: o arquivo de pedido nunca escolhe o que pode ser feito."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes as wt

import psutil

from . import config, modo_jogo, winapi

ESTADO_ADMIN = os.path.join(modo_jogo.PASTA, "admin.json")

# Pausados enquanto o Modo Jogo está ligado (só se estiverem rodando) e retomados depois.
SERVICOS = [
    ("WSearch", "Indexação da Pesquisa do Windows"),
    ("SysMain", "SysMain (pré-carregamento de apps)"),
    ("DiagTrack", "Telemetria do Windows"),
    ("dmwappushservice", "Telemetria (WAP Push)"),
    ("wuauserv", "Windows Update"),
    ("UsoSvc", "Orquestrador de atualizações"),
    ("BITS", "Transferência inteligente em segundo plano"),
    ("DoSvc", "Otimização de Entrega"),
    ("InventorySvc", "Inventário de compatibilidade"),
    ("PcaSvc", "Assistente de compatibilidade de programas"),
    ("WerSvc", "Relatório de erros"),
    ("WSAIFabricSvc", "Componentes de IA do Windows"),
    ("MapsBroker", "Mapas offline"),
    ("Spooler", "Spooler de impressão"),
    ("StiSvc", "Aquisição de imagens (scanner)"),
    ("dptftcs", "Telemetria Intel DTT"),
    ("SupportAssistAgent", "Dell SupportAssist"),
    ("Killer Analytics Service", "Killer Analytics"),
    ("AdobeUpdateService", "Atualizador da Adobe"),
    ("Red Giant Service", "Red Giant"),
    ("ONLYOFFICE Update Service", "Atualizador do ONLYOFFICE"),
    ("ClickToRunSvc", "Office Clique para Executar"),
    ("edgeupdate", "Atualizador do Edge"),
    ("edgeupdatem", "Atualizador do Edge"),
    ("gupdate", "Atualizador do Google"),
    ("gupdatem", "Atualizador do Google"),
]
DESCRICOES = dict(SERVICOS) | {"CoworkVMService": "Máquina virtual do Claude",
                               "CodexSandboxService.OpenAI.Codex": "Sandbox do Codex"}

advapi = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")


class _STATUS(ctypes.Structure):
    _fields_ = [("tipo", wt.DWORD), ("estado", wt.DWORD), ("aceitos", wt.DWORD), ("saida", wt.DWORD),
                ("saida_servico", wt.DWORD), ("checkpoint", wt.DWORD), ("espera", wt.DWORD)]


advapi.OpenSCManagerW.restype = wt.HANDLE
advapi.OpenSCManagerW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
advapi.OpenServiceW.restype = wt.HANDLE
advapi.OpenServiceW.argtypes = [wt.HANDLE, wt.LPCWSTR, wt.DWORD]
advapi.ControlService.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(_STATUS)]
advapi.StartServiceW.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p]
advapi.QueryServiceStatus.argtypes = [wt.HANDLE, ctypes.POINTER(_STATUS)]
advapi.CloseServiceHandle.argtypes = [wt.HANDLE]

PARADO, RODANDO = 1, 4


def _servico(nome: str, operacao: str) -> int:
    """operacao: 'estado' | 'parar' | 'iniciar'. Devolve o estado (1 parado, 4 rodando) ou 0 se não existe."""
    scm = advapi.OpenSCManagerW(None, None, 0x1)                     # SC_MANAGER_CONNECT
    if not scm:
        return 0
    try:
        svc = advapi.OpenServiceW(scm, nome, 0x4 | 0x10 | 0x20)      # QUERY_STATUS | START | STOP
        if not svc:
            svc = advapi.OpenServiceW(scm, nome, 0x4)                # sem admin: só consulta
            if not svc:
                return 0
        try:
            st = _STATUS()
            if operacao == "parar":
                advapi.ControlService(svc, 1, ctypes.byref(st))      # SERVICE_CONTROL_STOP
            elif operacao == "iniciar":
                advapi.StartServiceW(svc, 0, None)
            advapi.QueryServiceStatus(svc, ctypes.byref(st))
            return st.estado
        finally:
            advapi.CloseServiceHandle(svc)
    finally:
        advapi.CloseServiceHandle(scm)


def situacao_servicos() -> list[tuple[str, str, str]]:
    nomes = {0: "não existe", PARADO: "parado", RODANDO: "running"}
    return [(n, d, nomes.get(_servico(n, "estado"), "mudando")) for n, d in SERVICOS]


def parar_servicos(nomes: list[str]) -> list[str]:
    pedidos = [n for n in nomes if _servico(n, "estado") == RODANDO and _servico(n, "parar")]
    limite = time.monotonic() + 15
    parados: list[str] = []
    while pedidos and time.monotonic() < limite:
        for n in list(pedidos):
            if _servico(n, "estado") == PARADO:
                parados.append(n)
                pedidos.remove(n)
        time.sleep(0.3)
    return parados


def retomar_servicos(nomes: list[str]) -> list[str]:
    return [n for n in reversed(nomes) if _servico(n, "iniciar") in (RODANDO, 2)]   # 2 = iniciando


# ---- memória em espera (o que o Windows guarda de cache e devolve se precisar)

class _LUID(ctypes.Structure):
    _fields_ = [("baixo", wt.DWORD), ("alto", wt.LONG)]


class _PRIV(ctypes.Structure):
    _fields_ = [("qtd", wt.DWORD), ("luid", _LUID), ("atributos", wt.DWORD)]


advapi.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
advapi.LookupPrivilegeValueW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.POINTER(_LUID)]
advapi.AdjustTokenPrivileges.argtypes = [wt.HANDLE, wt.BOOL, ctypes.POINTER(_PRIV), wt.DWORD,
                                         ctypes.c_void_p, ctypes.c_void_p]
kernel32.GetCurrentProcess.restype = wt.HANDLE


def _privilegio(nome: str) -> bool:
    token = wt.HANDLE()
    if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(token)):
        return False
    try:
        p = _PRIV(1, _LUID(), 2)                                     # SE_PRIVILEGE_ENABLED
        if not advapi.LookupPrivilegeValueW(None, nome, ctypes.byref(p.luid)):
            return False
        advapi.AdjustTokenPrivileges(token, False, ctypes.byref(p), 0, None, None)
        return ctypes.get_last_error() == 0
    finally:
        kernel32.CloseHandle(token)


def esvaziar_memoria_em_espera() -> bool:
    """Esvazia a lista em espera (cache de arquivos antigos): o jogo encontra RAM zerada na hora."""
    if not _privilegio("SeProfileSingleProcessPrivilege"):
        return False
    comando = ctypes.c_int(4)                                        # MemoryPurgeStandbyList
    return ntdll.NtSetSystemInformation(80, ctypes.byref(comando), ctypes.sizeof(comando)) == 0


# ---- apps abertos como administrador

def encerrar_validados(pids: list[int]) -> tuple[int, list[str]]:
    """Encerra só o que o próprio Modo Jogo classificaria como app do usuário (nunca sistema/driver)."""
    usuario = psutil.Process().username()
    mortos, falhas = 0, []
    for pid in pids:
        try:
            p = psutil.Process(int(pid))
            if p.username() != usuario or winapi.sessao(p.pid) != winapi.sessao(os.getpid()):
                continue
            if modo_jogo.classificar(p.name(), p.exe()) not in ("fechar", "launcher", "jogo"):
                continue
            p.kill()
            mortos += 1
        except psutil.NoSuchProcess:
            pass
        except (psutil.Error, ValueError):
            try:
                falhas.append(psutil.Process(int(pid)).name())
            except (psutil.Error, ValueError):
                pass
    return mortos, sorted(set(falhas))


# ---- estado e pedido

def _ler(caminho: str) -> dict:
    try:
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar(caminho: str, dados: dict) -> None:
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(tmp, caminho)


def executar(pedido: dict) -> dict:
    acao = pedido.get("acao")
    if acao == "ativar":
        mortos, falhas = encerrar_validados(pedido.get("pids") or [])
        extras = [s for s in pedido.get("servicos_apps") or [] if s in modo_jogo.SERVICOS_DE_APP]
        estado = _ler(ESTADO_ADMIN)
        ja = estado.get("parados", [])
        novos = parar_servicos([n for n, _d in SERVICOS] + extras)
        estado["parados"] = ja + [n for n in novos if n not in ja]
        _gravar(ESTADO_ADMIN, estado)
        return {"ok": True, "parados": [DESCRICOES.get(n, n) for n in novos], "encerrados": mortos,
                "nao_fechou": falhas, "memoria": esvaziar_memoria_em_espera()}
    if acao == "desativar":
        estado = _ler(ESTADO_ADMIN)
        permitidos = set(DESCRICOES)
        retomados = retomar_servicos([n for n in estado.get("parados", []) if n in permitidos])
        try:
            os.remove(ESTADO_ADMIN)
        except OSError:
            pass
        return {"ok": True, "retomados": [DESCRICOES.get(n, n) for n in retomados]}
    return {"ok": False, "erro": f"ação desconhecida: {acao}"}


def instalar_tarefa() -> bool:
    """Tarefa elevada que o widget dispara sem UAC (a pessoa autorizou uma vez)."""
    def q(s: str) -> str:                                           # texto entre aspas simples no PowerShell
        return s.replace("'", "''")

    script = os.path.join(config.RAIZ, "corepulse.pyw")
    ps = (
        "$ErrorActionPreference='Stop';"
        f"$a=New-ScheduledTaskAction -Execute '{q(config._pythonw())}' "
        f"-Argument '\"{q(script)}\" --modo-jogo-admin' -WorkingDirectory '{q(config.RAIZ)}';"
        f"$p=New-ScheduledTaskPrincipal -UserId '{q(psutil.Process().username())}' -LogonType Interactive "
        "-RunLevel Highest;"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances Queue;"
        "Register-ScheduledTask -TaskPath '\\CorePulse\\' -TaskName 'Modo Jogo' -Action $a -Principal $p "
        "-Settings $s -Description 'CorePulse: pausa e retoma servicos do Modo Jogo.' -Force | Out-Null"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=60, creationflags=modo_jogo.SEM_JANELA)
    if r.returncode != 0:
        return False
    # A tarefa nova já está registrada; a antiga deixa de apontar para a instalação anterior.
    subprocess.run(["schtasks", "/Delete", "/TN", "\\GlassPulse\\Modo Jogo", "/F"],
                   capture_output=True, timeout=30, creationflags=modo_jogo.SEM_JANELA)
    return True


def remover_tarefa() -> bool:
    r = subprocess.run(["schtasks", "/Delete", "/TN", modo_jogo.TAREFA, "/F"], capture_output=True,
                       creationflags=modo_jogo.SEM_JANELA)
    return r.returncode == 0


def main(argv: list[str]) -> int:
    if not winapi.sou_admin():
        return 2
    if "--remover-tarefa" in argv:
        return 0 if remover_tarefa() else 1
    if "--instalar-tarefa" in argv and not os.path.exists(modo_jogo.PEDIDO):
        return 0 if instalar_tarefa() else 1
    pedido = _ler(modo_jogo.PEDIDO)
    if pedido and time.time() - float(pedido.get("criado", 0)) < 300:
        try:
            os.remove(modo_jogo.PEDIDO)
        except OSError:
            pass
        try:
            resposta = executar(pedido)
        except Exception as erro:                                    # o widget precisa de uma resposta
            resposta = {"ok": False, "erro": repr(erro)}
        _gravar(os.path.join(modo_jogo.PASTA, f"resposta-{pedido.get('id', 'x')}.json"), resposta)
    if "--instalar-tarefa" in argv:
        return 0 if instalar_tarefa() else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
