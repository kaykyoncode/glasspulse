# -*- coding: utf-8 -*-
"""Chamadas diretas ao Windows: estilo da janela, vidro (acrílico), Z-order e mutex."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi")

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000

HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10

WM_WINDOWPOSCHANGING = 0x0046
WM_MOUSEACTIVATE = 0x0021
WM_APP = 0x8000
MSG_MOSTRAR = WM_APP + 1
MSG_SAIR = WM_APP + 2
MA_NOACTIVATE = 3

TITULO_JANELA = "Monitor do PC"
NOME_MUTEX = "Local\\GlassPulse-Widget"

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
user32.FindWindowW.restype = wt.HWND
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
psapi.EmptyWorkingSet.argtypes = [wt.HANDLE]
kernel32.GetCurrentProcess.restype = wt.HANDLE


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("hwndInsertAfter", wt.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wt.UINT)]


class _ACCENT(ctypes.Structure):
    _fields_ = [("estado", ctypes.c_int), ("flags", ctypes.c_int),
                ("cor", ctypes.c_uint), ("animacao", ctypes.c_int)]


class _WCAD(ctypes.Structure):
    _fields_ = [("atributo", ctypes.c_int), ("dados", ctypes.c_void_p),
                ("tamanho", ctypes.c_size_t)]


def _dwm_attr(hwnd: int, atributo: int, valor: int) -> None:
    v = ctypes.c_int(valor)
    dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), atributo, ctypes.byref(v), ctypes.sizeof(v))


def aplicar_estilo_widget(hwnd: int) -> None:
    """Fora da barra de tarefas e do Alt+Tab, sem roubar foco, no fundo do Z-order."""
    estilo = user32.GetWindowLongPtrW(wt.HWND(hwnd), GWL_EXSTYLE)
    estilo = (estilo | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
    user32.SetWindowLongPtrW(wt.HWND(hwnd), GWL_EXSTYLE, estilo)
    enviar_para_o_fundo(hwnd)


def enviar_para_o_fundo(hwnd: int) -> None:
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_BOTTOM), 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def trazer_ao_topo(hwnd: int) -> None:
    """Só para testes (--teste-topo): põe a janela acima das outras para capturar a tela."""
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-1), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def aplicar_vidro(hwnd: int, tinta_rgba: tuple[int, int, int, int]) -> None:
    """Acrílico do Windows 11 (desfoque do que está atrás) com cantos redondos do DWM."""
    _dwm_attr(hwnd, 20, 1)            # DWMWA_USE_IMMERSIVE_DARK_MODE
    _dwm_attr(hwnd, 33, 2)            # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
    _dwm_attr(hwnd, 34, 0xFFFFFFFE)   # DWMWA_BORDER_COLOR = sem borda (desenhamos a nossa)
    r, g, b, a = tinta_rgba
    acento = _ACCENT(4, 0, (a << 24) | (b << 16) | (g << 8) | r, 0)  # ACRYLICBLURBEHIND, ABGR
    dados = _WCAD(19, ctypes.cast(ctypes.pointer(acento), ctypes.c_void_p), ctypes.sizeof(acento))
    user32.SetWindowCompositionAttribute(wt.HWND(hwnd), ctypes.byref(dados))


def liberar_memoria() -> None:
    """Devolve ao Windows as páginas que o processo não está usando agora."""
    try:
        psapi.EmptyWorkingSet(kernel32.GetCurrentProcess())
    except Exception:
        pass


def criar_mutex() -> tuple[object, bool]:
    """Devolve (handle, ja_existia). Guarde o handle enquanto o programa viver."""
    h = kernel32.CreateMutexW(None, False, NOME_MUTEX)
    return h, ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def avisar_instancia(mensagem: int) -> bool:
    hwnd = user32.FindWindowW(None, TITULO_JANELA)
    if not hwnd:
        return False
    user32.PostMessageW(hwnd, mensagem, 0, 0)
    return True


def uptime_segundos() -> float:
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    return kernel32.GetTickCount64() / 1000.0


class _RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]


user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(_RECT)]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
_CLASSES_SHELL = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "XamlExplorerHostIslandWindow"}


def coberto_por_janela(hwnd: int) -> bool:
    """True se a janela em primeiro plano (ex.: jogo em tela cheia) esconde o widget por inteiro."""
    fg = user32.GetForegroundWindow()
    if not fg or fg == hwnd:
        return False
    nome = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(fg, nome, 64)
    if nome.value in _CLASSES_SHELL:
        return False
    a, b = _RECT(), _RECT()
    if not user32.GetWindowRect(fg, ctypes.byref(a)) or not user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(b)):
        return False
    return a.l <= b.l and a.t <= b.t and a.r >= b.r and a.b >= b.b


GWLP_HWNDPARENT = -8
user32.IsWindow.argtypes = [wt.HWND]


def fixar_ao_desktop(hwnd: int) -> bool:
    """Faz da área de trabalho (Progman) a DONA do widget. Janela dona-da fica sempre logo acima
    da dona e acompanha quando o Windows a levanta (Win+D / Mostrar área de trabalho)."""
    prog = user32.FindWindowW("Progman", None)
    if not prog:
        return False
    user32.SetWindowLongPtrW(wt.HWND(hwnd), GWLP_HWNDPARENT, prog)
    return True


def janela_viva(hwnd: int) -> bool:
    return bool(user32.IsWindow(wt.HWND(hwnd)))
