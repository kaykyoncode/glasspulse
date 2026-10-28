# -*- coding: utf-8 -*-
"""Coleta de métricas com custo mínimo: contadores do Windows (PDH, os mesmos do
Gerenciador de Tarefas), NVML da NVIDIA e Toolhelp para processos. Só ctypes + psutil."""
from __future__ import annotations

import ctypes
import re
import threading
import time
from ctypes import wintypes as wt

import psutil

from . import winapi

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_pdh = ctypes.WinDLL("pdh")

PDH_FMT_DOUBLE = 0x200
PDH_FMT_NOCAP100 = 0x8000
PDH_MORE_DATA = 0x800007D2
_FMT = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100

for _nome in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData",
              "PdhGetFormattedCounterValue", "PdhGetFormattedCounterArrayW", "PdhCloseQuery"):
    getattr(_pdh, _nome).restype = ctypes.c_uint32
_pdh.PdhOpenQueryW.argtypes = [wt.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wt.HANDLE)]
_pdh.PdhAddEnglishCounterW.argtypes = [wt.HANDLE, wt.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wt.HANDLE)]
_pdh.PdhCollectQueryData.argtypes = [wt.HANDLE]


class _Val(ctypes.Structure):
    _fields_ = [("status", ctypes.c_uint32), ("valor", ctypes.c_double)]


class _Item(ctypes.Structure):
    _fields_ = [("nome", ctypes.c_wchar_p), ("val", _Val)]


class Pdh:
    """Consulta única com vários contadores; valores de taxa precisam de 2 coletas."""

    def __init__(self) -> None:
        self.q = wt.HANDLE()
        if _pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.q)) != 0:
            raise OSError("PDH indisponível")
        self.c: dict[str, wt.HANDLE] = {}

    def add(self, chave: str, caminho: str) -> bool:
        h = wt.HANDLE()
        if _pdh.PdhAddEnglishCounterW(self.q, caminho, 0, ctypes.byref(h)) != 0:
            return False
        self.c[chave] = h
        return True

    def coletar(self) -> None:
        _pdh.PdhCollectQueryData(self.q)

    def valor(self, chave: str) -> float | None:
        h = self.c.get(chave)
        if h is None:
            return None
        v = _Val()
        r = _pdh.PdhGetFormattedCounterValue(h, _FMT, None, ctypes.byref(v))
        return v.valor if r == 0 and v.status in (0, 1) else None

    def matriz(self, chave: str) -> dict[str, float]:
        h = self.c.get(chave)
        if h is None:
            return {}
        tam, qtd = wt.DWORD(0), wt.DWORD(0)
        r = _pdh.PdhGetFormattedCounterArrayW(h, _FMT, ctypes.byref(tam), ctypes.byref(qtd), None)
        if r != PDH_MORE_DATA or tam.value == 0:
            return {}
        buf = (ctypes.c_byte * tam.value)()
        r = _pdh.PdhGetFormattedCounterArrayW(h, _FMT, ctypes.byref(tam), ctypes.byref(qtd), buf)
        if r != 0:
            return {}
        itens = ctypes.cast(buf, ctypes.POINTER(_Item))
        return {itens[i].nome: itens[i].val.valor
                for i in range(qtd.value) if itens[i].val.status in (0, 1)}


# --------------------------------------------------------------------------- NVIDIA

class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("mem", ctypes.c_uint)]


class _Mem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("livre", ctypes.c_ulonglong),
                ("usada", ctypes.c_ulonglong)]


class _Mem2(ctypes.Structure):
    """nvmlMemory_v2_t: igual ao que o nvidia-smi mostra (a v1 soma a memória reservada ao 'usado')."""
    _fields_ = [("versao", ctypes.c_uint), ("total", ctypes.c_ulonglong),
                ("reservada", ctypes.c_ulonglong), ("livre", ctypes.c_ulonglong),
                ("usada", ctypes.c_ulonglong)]


class Nvml:
    """Leitura direta da biblioteca da NVIDIA (sem chamar o nvidia-smi a cada segundo)."""

    @classmethod
    def abrir(cls) -> "Nvml | None":
        try:
            return cls()
        except Exception:
            return None

    def __init__(self) -> None:
        lib = None
        for caminho in ("nvml.dll", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll"):
            try:
                lib = ctypes.CDLL(caminho)
                break
            except OSError:
                continue
        if lib is None or lib.nvmlInit_v2() != 0:
            raise OSError("NVML indisponível")
        self.lib = lib
        self.h = ctypes.c_void_p()
        if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.h)) != 0:
            raise OSError("Sem GPU NVIDIA")
        buf = ctypes.create_string_buffer(96)
        lib.nvmlDeviceGetName(self.h, buf, 96)
        bruto = buf.value.decode(errors="ignore")
        self.nome = re.sub(r"^NVIDIA\s+(GeForce\s+)?", "", bruto).strip() or bruto

    def _uint(self, funcao, *args) -> int | None:
        v = ctypes.c_uint()
        return v.value if funcao(self.h, *args, ctypes.byref(v)) == 0 else None

    def ler(self) -> dict:
        l, h = self.lib, self.h
        util, mem = _Util(), _Mem()
        ok_u = l.nvmlDeviceGetUtilizationRates(h, ctypes.byref(util)) == 0
        m2 = _Mem2()
        m2.versao = ctypes.sizeof(_Mem2) | (2 << 24)
        if hasattr(l, "nvmlDeviceGetMemoryInfo_v2") and l.nvmlDeviceGetMemoryInfo_v2(h, ctypes.byref(m2)) == 0:
            mem.total, mem.usada, ok_m = m2.total, m2.usada, True
        else:
            ok_m = l.nvmlDeviceGetMemoryInfo(h, ctypes.byref(mem)) == 0
        potencia = self._uint(l.nvmlDeviceGetPowerUsage)
        return {
            "nome": self.nome,
            "uso": float(util.gpu) if ok_u else 0.0,
            "vram_usada": mem.usada if ok_m else 0,
            "vram_total": mem.total if ok_m else 0,
            "temp": self._uint(l.nvmlDeviceGetTemperature, 0),
            "watts": potencia / 1000.0 if potencia is not None else None,
            "clock_mhz": self._uint(l.nvmlDeviceGetClockInfo, 0),
            "ventoinha": self._uint(l.nvmlDeviceGetFanSpeed),
        }


# --------------------------------------------------------------------------- processos

class _PMC2(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("faltas", wt.DWORD),
                ("pico_ws", ctypes.c_size_t), ("ws", ctypes.c_size_t),
                ("pico_paginado", ctypes.c_size_t), ("paginado", ctypes.c_size_t),
                ("pico_nao_pag", ctypes.c_size_t), ("nao_pag", ctypes.c_size_t),
                ("pagefile", ctypes.c_size_t), ("pico_pagefile", ctypes.c_size_t),
                ("privado", ctypes.c_size_t), ("ws_privado", ctypes.c_size_t),
                ("commit_compartilhado", ctypes.c_ulonglong)]


class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("uso", wt.DWORD), ("pid", wt.DWORD),
                ("heap", ctypes.c_size_t), ("modulo", wt.DWORD), ("threads", wt.DWORD),
                ("pai", wt.DWORD), ("prioridade", ctypes.c_long), ("flags", wt.DWORD),
                ("exe", ctypes.c_wchar * 260)]


_k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
_k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PE32)]
_k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PE32)]
_k32.OpenProcess.restype = ctypes.c_void_p
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC2), wt.DWORD]

_INVALIDO = ctypes.c_void_p(-1).value

_APELIDOS = {
    "svchost": "Serviços do Windows", "chrome": "Google Chrome", "msedge": "Microsoft Edge",
    "msedgewebview2": "WebView2", "explorer": "Explorador de Arquivos", "dwm": "Janelas (DWM)",
    "vmmemwsl": "WSL (Linux)", "vmmem": "Máquina virtual", "msmpeng": "Windows Defender",
    "avp": "Kaspersky", "node": "Node.js", "code": "VS Code", "claude": "Claude",
    "python": "Python", "pythonw": "Python", "taskmgr": "Gerenciador de Tarefas",
    "firefox": "Firefox", "discord": "Discord", "steam": "Steam", "whatsapp": "WhatsApp",
    "adobe premiere pro": "Premiere Pro", "afterfx": "After Effects", "blender": "Blender",
    "docker desktop": "Docker Desktop", "com.docker.backend": "Docker", "codex": "Codex",
}


def nome_amigavel(exe: str) -> str:
    base = exe[:-4] if exe.lower().endswith(".exe") else exe
    apelido = _APELIDOS.get(base.lower())
    if apelido:
        return apelido
    base = base.replace("_", " ").replace("-", " ")
    return base[:1].upper() + base[1:]


def varrer_processos(limite: int = 5) -> list[tuple[str, int, int]]:
    """Maiores consumidores de RAM agrupados por programa: (nome, qtd, bytes).
    Usa o 'conjunto de trabalho privado', a mesma conta do Gerenciador de Tarefas."""
    grupos: dict[str, list[int]] = {}
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)
    if snap in (None, _INVALIDO):
        return []
    pe = _PE32()
    pe.dwSize = ctypes.sizeof(pe)
    pmc = _PMC2()
    pmc.cb = ctypes.sizeof(pmc)
    try:
        ok = _k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.pid > 4:
                h = _k32.OpenProcess(0x1000, False, pe.pid)  # QUERY_LIMITED_INFORMATION
                if h:
                    if _k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                        g = grupos.setdefault(pe.exe.lower(), [0, 0, pe.exe])
                        g[0] += 1
                        g[1] += pmc.ws_privado or pmc.ws
                    _k32.CloseHandle(h)
            ok = _k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        _k32.CloseHandle(snap)
    topo = sorted(grupos.values(), key=lambda g: g[1], reverse=True)[:limite]
    return [(nome_amigavel(g[2]), g[0], g[1]) for g in topo]


class LeitorProcessos(threading.Thread):
    """Varre os processos de tempos em tempos, fora da thread da interface."""

    def __init__(self, intervalo: float = 4.0, limite: int = 5) -> None:
        super().__init__(daemon=True, name="processos")
        self.intervalo, self.limite = intervalo, limite
        self.ativo = True
        self.resultado: list[tuple[str, int, int]] = []

    def run(self) -> None:
        while True:
            if self.ativo:
                try:
                    self.resultado = varrer_processos(self.limite)
                except Exception:
                    pass
            time.sleep(self.intervalo)


# --------------------------------------------------------------------------- coletor

_VIRTUAL = re.compile(
    r"virtual|vpn|hyper-v|vmware|vbox|loopback|bluetooth|tunnel|pseudo|teredo|isatap|"
    r"miniport|tap-|wireguard|tailscale|6to4|wi-fi direct", re.I)


def _rotulo_volume(raiz: str) -> str:
    buf = ctypes.create_unicode_buffer(261)
    ok = _k32.GetVolumeInformationW(raiz, buf, 261, None, None, None, None, 0)
    return buf.value if ok else ""


class Coletor:
    def __init__(self) -> None:
        self.pdh: Pdh | None = None
        try:
            p = Pdh()
            ok = all([
                p.add("cpu_nucleos", r"\Processor Information(*)\% Processor Utility"),
                p.add("cpu_perf", r"\Processor Information(_Total)\% Processor Performance"),
                p.add("cpu_freq", r"\Processor Information(_Total)\Processor Frequency"),
            ])
            p.add("rede_rx", r"\Network Interface(*)\Bytes Received/sec")
            p.add("rede_tx", r"\Network Interface(*)\Bytes Sent/sec")
            p.add("rede_bw", r"\Network Interface(*)\Current Bandwidth")
            p.add("disco_ocioso", r"\PhysicalDisk(*)\% Idle Time")
            p.add("disco_leitura", r"\PhysicalDisk(*)\Disk Read Bytes/sec")
            p.add("disco_escrita", r"\PhysicalDisk(*)\Disk Write Bytes/sec")
            p.coletar()
            self.pdh = p if ok else None
        except OSError:
            self.pdh = None
        self.nvml = Nvml.abrir()
        self._disco_ts = 0.0
        self._discos: list[dict] = []
        self._rede_anterior: tuple[float, int, int] | None = None
        psutil.cpu_percent(percpu=True)
        self.cpu_nome = self._nome_cpu()
        self.cpu_threads = psutil.cpu_count(logical=True) or 1
        self.gpu_nome = self.nvml.nome if self.nvml else None

    @staticmethod
    def _nome_cpu() -> str:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                bruto = winreg.QueryValueEx(k, "ProcessorNameString")[0]
        except OSError:
            return "CPU"
        limpo = re.sub(r"\((R|TM)\)|CPU|@.*$|\d+(st|nd|rd|th) Gen|Intel|AMD|Processor", "", bruto)
        limpo = re.sub(r"\s+", " ", limpo).strip()
        return limpo or "CPU"

    # ---- partes

    def _cpu(self) -> dict:
        nucleos: list[float] = []
        total = None
        ghz = None
        if self.pdh:
            dados = self.pdh.matriz("cpu_nucleos")
            ordem = []
            for nome, v in dados.items():
                if "_Total" in nome:
                    if nome == "_Total" or total is None:
                        total = v
                    continue
                grupo, _, idx = nome.partition(",")
                try:
                    ordem.append((int(grupo), int(idx), v))
                except ValueError:
                    pass
            ordem.sort()
            nucleos = [min(100.0, o[2]) for o in ordem]
            perf, freq = self.pdh.valor("cpu_perf"), self.pdh.valor("cpu_freq")
            if perf and freq:
                ghz = freq * perf / 100.0 / 1000.0
        if not nucleos or total is None:
            nucleos = psutil.cpu_percent(percpu=True)
            total = sum(nucleos) / max(1, len(nucleos))
        return {"total": min(100.0, total), "nucleos": nucleos, "ghz": ghz}

    def _ram(self) -> dict:
        m = psutil.virtual_memory()
        usada = m.total - m.available
        return {"total": m.total, "usada": usada, "livre": m.available, "pct": usada * 100.0 / m.total}

    def _rede(self) -> dict:
        rx = tx = 0.0
        bw = 0.0
        nome = ""
        if self.pdh and self.pdh.c.get("rede_rx"):
            d_rx, d_tx = self.pdh.matriz("rede_rx"), self.pdh.matriz("rede_tx")
            d_bw = self.pdh.matriz("rede_bw")
            melhor = -1.0
            for inst, v in d_rx.items():
                if _VIRTUAL.search(inst):
                    continue
                t = d_tx.get(inst, 0.0)
                rx += v
                tx += t
                if d_bw.get(inst, 0) > 0 and (v + t > melhor):
                    melhor, bw, nome = v + t, d_bw[inst], inst
        else:
            agora = time.monotonic()
            c = psutil.net_io_counters()
            if self._rede_anterior:
                dt = max(0.001, agora - self._rede_anterior[0])
                rx = (c.bytes_recv - self._rede_anterior[1]) / dt
                tx = (c.bytes_sent - self._rede_anterior[2]) / dt
            self._rede_anterior = (agora, c.bytes_recv, c.bytes_sent)
        tipo = "Wi-Fi" if re.search(r"wi-?fi|wireless|wlan|802\.11", nome, re.I) else "Ethernet"
        return {"down_bps": rx * 8.0, "up_bps": tx * 8.0, "link_bps": bw, "tipo": tipo}

    def _discos_lentos(self) -> list[dict]:
        agora = time.monotonic()
        if agora - self._disco_ts < 5.0 and self._discos:
            return self._discos
        self._disco_ts = agora
        lista = []
        for part in psutil.disk_partitions(all=False):
            if "fixed" not in part.opts.lower():
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            letra = part.mountpoint[:2].upper()
            lista.append({"letra": letra, "rotulo": _rotulo_volume(part.mountpoint),
                          "total": u.total, "usado": u.used, "livre": u.free, "pct": u.percent})
        self._discos = lista
        return lista

    def _atividade_discos(self) -> dict[str, tuple[float, float, float]]:
        """letra -> (% ativo, bytes lidos/s, bytes escritos/s)"""
        if not self.pdh:
            return {}
        ocioso = self.pdh.matriz("disco_ocioso")
        leitura = self.pdh.matriz("disco_leitura")
        escrita = self.pdh.matriz("disco_escrita")
        saida: dict[str, tuple[float, float, float]] = {}
        for inst, idle in ocioso.items():
            for letra in re.findall(r"[A-Z]:", inst):
                saida[letra] = (max(0.0, min(100.0, 100.0 - idle)),
                                leitura.get(inst, 0.0), escrita.get(inst, 0.0))
        return saida

    # ---- amostra completa

    def amostrar(self) -> dict:
        if self.pdh:
            self.pdh.coletar()
        discos = [dict(d) for d in self._discos_lentos()]
        ativ = self._atividade_discos()
        for d in discos:
            d["ativo"], d["leitura"], d["escrita"] = ativ.get(d["letra"], (0.0, 0.0, 0.0))
        return {
            "cpu": self._cpu(),
            "ram": self._ram(),
            "gpu": self.nvml.ler() if self.nvml else None,
            "rede": self._rede(),
            "discos": discos,
            "uptime": winapi.uptime_segundos(),
        }
