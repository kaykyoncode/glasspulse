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

HWND_TOP, HWND_BOTTOM = 0, 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
SWP_NOOWNERZORDER = 0x200

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
    """Atrás de todos os apps. O Explorer mantém a área de trabalho (Progman) no fundo, então o
    widget fica logo acima dela e continua visível onde não há janela por cima."""
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_BOTTOM), 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


def trazer_a_frente(hwnd: int) -> None:
    """Na frente dos apps (sem 'sempre por cima' e sem roubar o foco): aberto de propósito.
    HWND_TOP sozinho não passa da janela em primeiro plano quando o pedido vem de um processo em
    segundo plano; TOPMOST e logo NOTOPMOST deixa o widget no alto da pilha dos apps comuns."""
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-1), 0, 0, 0, 0, flags)
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-2), 0, 0, 0, 0, flags)


user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]


user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.AllowSetForegroundWindow.argtypes = [wt.DWORD]


def tomar_foco(hwnd: int) -> bool:
    """Põe o widget em primeiro plano. O Windows só deixa quando o pedido vem de uma ação do
    usuário (clique na bandeja, 2ª instância aberta por ele); devolve se conseguiu."""
    user32.SetForegroundWindow(wt.HWND(hwnd))
    return int(user32.GetForegroundWindow() or 0) == hwnd


def permitir_primeiro_plano() -> None:
    """2ª instância (aberta pelo usuário): deixa a instância que já roda pegar o foco."""
    user32.AllowSetForegroundWindow(0xFFFFFFFF)   # ASFW_ANY


def primeiro_plano() -> tuple[int, int]:
    """(hwnd, pid) da janela em primeiro plano agora (a que tem o foco)."""
    h = user32.GetForegroundWindow()
    if not h:
        return 0, 0
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return int(h), int(pid.value)


WS_EX_TOPMOST = 0x00000008
_SWP_SO_ORDEM = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER


def esta_no_topo(hwnd: int) -> bool:
    return bool(user32.GetWindowLongPtrW(wt.HWND(hwnd), GWL_EXSTYLE) & WS_EX_TOPMOST)


def trazer_ao_topo(hwnd: int) -> None:
    """Fixado: sempre por cima das outras janelas (HWND_TOPMOST), sem roubar o foco.
    SWP_NOOWNERZORDER: sem ele, depois de uma ativação o Windows às vezes ignora o TOPMOST."""
    for _ in range(2):
        user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-1), 0, 0, 0, 0, _SWP_SO_ORDEM)
        if esta_no_topo(hwnd):
            return


def tirar_do_topo(hwnd: int) -> None:
    """Desfaz o 'sempre por cima' (HWND_NOTOPMOST)."""
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-2), 0, 0, 0, 0, _SWP_SO_ORDEM)


def preparar_transparente(hwnd: int) -> None:
    """Janela transparente pura: sem cantos arredondados, borda, sombra ou animação do DWM.
    O formato (cards em pasta) é todo desenhado por nós; o que é transparente não pega clique."""
    _dwm_attr(hwnd, 20, 1)            # DWMWA_USE_IMMERSIVE_DARK_MODE
    _dwm_attr(hwnd, 33, 1)            # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_DONOTROUND
    _dwm_attr(hwnd, 34, 0xFFFFFFFE)   # DWMWA_BORDER_COLOR = DWMWA_COLOR_NONE
    _dwm_attr(hwnd, 3, 1)             # DWMWA_TRANSITIONS_FORCEDISABLED
    acento = _ACCENT(0, 0, 0, 0)      # ACCENT_DISABLED: desliga o acrílico da versão antiga
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


def soltar_do_desktop(hwnd: int) -> None:
    """Desfaz o fixar_ao_desktop (fixado por cima, o widget não tem dono)."""
    user32.SetWindowLongPtrW(wt.HWND(hwnd), GWLP_HWNDPARENT, 0)


def janela_viva(hwnd: int) -> bool:
    return bool(user32.IsWindow(wt.HWND(hwnd)))


# ---- Modo Jogo: janelas dos apps, tela cheia, sessão e elevação ------------------------

MSG_MODO_JOGO = WM_APP + 3
WM_CLOSE = 0x0010
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
GW_OWNER = 4
DWMWA_CLOAKED = 14

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindow.restype = wt.HWND
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.IsZoomed.argtypes = [wt.HWND]
user32.MonitorFromWindow.restype = wt.HANDLE
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.ProcessIdToSessionId.argtypes = [wt.DWORD, ctypes.POINTER(wt.DWORD)]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.GetApplicationUserModelId.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_uint32), wt.LPWSTR]
shell32 = ctypes.WinDLL("shell32")
version = ctypes.WinDLL("version")
version.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.DWORD)]
version.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
version.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(wt.UINT)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", wt.DWORD)]


user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(_MONITORINFO)]


def _pid_da_janela(hwnd) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _classe(hwnd) -> str:
    nome = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, nome, 64)
    return nome.value


def janelas_por_processo() -> dict[int, list[tuple[int, str, bool]]]:
    """pid -> [(hwnd, classe, principal)] das janelas de topo visíveis. 'principal' = janela de app
    de verdade (sem dona, com título, não é janela de ferramenta). As janelas da Microsoft Store
    contam para o processo do app, não para o ApplicationFrameHost que as emoldura."""
    saida: dict[int, list[tuple[int, str, bool]]] = {}

    def cada(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        oculta = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(oculta), ctypes.sizeof(oculta))
        if oculta.value:
            return True
        classe, pid = _classe(hwnd), _pid_da_janela(hwnd)
        if classe == "ApplicationFrameWindow":
            dentro = [0]

            def filho(h, _):
                if _classe(h) == "Windows.UI.Core.CoreWindow":
                    dentro[0] = _pid_da_janela(h)
                    return False
                return True

            user32.EnumChildWindows(hwnd, WNDENUMPROC(filho), 0)
            pid = dentro[0] or pid
        estilo = user32.GetWindowLongPtrW(wt.HWND(hwnd), GWL_EXSTYLE)
        principal = (not user32.GetWindow(hwnd, GW_OWNER) and not estilo & WS_EX_TOOLWINDOW
                     and (user32.GetWindowTextLengthW(hwnd) > 0 or classe == "ApplicationFrameWindow"))
        saida.setdefault(pid, []).append((hwnd, classe, bool(principal)))
        return True

    user32.EnumWindows(WNDENUMPROC(cada), 0)
    return saida


def fechar_janela(hwnd: int) -> None:
    """Pede para fechar como o X da janela (o app pode salvar ou perguntar)."""
    user32.PostMessageW(wt.HWND(hwnd), WM_CLOSE, 0, 0)


def _janela_tela_cheia() -> int:
    """HWND da janela em primeiro plano quando ela cobre o monitor inteiro sem moldura; 0 se não."""
    fg = user32.GetForegroundWindow()
    if not fg or _classe(fg) in _CLASSES_SHELL or user32.IsZoomed(fg):
        return 0
    if user32.GetWindowLongPtrW(fg, GWL_STYLE) & WS_CAPTION == WS_CAPTION:
        return 0
    r = _RECT()
    if not user32.GetWindowRect(fg, ctypes.byref(r)):
        return 0
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(mi)
    if not user32.GetMonitorInfoW(user32.MonitorFromWindow(fg, 2), ctypes.byref(mi)):
        return 0
    m = mi.rcMonitor
    if r.l <= m.l and r.t <= m.t and r.r >= m.r and r.b >= m.b:
        return fg
    return 0


def pid_tela_cheia() -> int:
    """PID da janela em primeiro plano quando ela cobre o monitor inteiro sem moldura (jogo em tela cheia
    ou sem bordas). Janela maximizada com barra de título não conta (com a barra de tarefas oculta,
    um navegador maximizado também cobre o monitor)."""
    fg = _janela_tela_cheia()
    return _pid_da_janela(fg) if fg else 0


def tela_cheia_no_monitor_de(hwnd: int) -> bool:
    """True se há um jogo/app em tela cheia em primeiro plano no mesmo monitor do widget."""
    fg = _janela_tela_cheia()
    if not fg or fg == hwnd:
        return False
    return user32.MonitorFromWindow(fg, 2) == user32.MonitorFromWindow(wt.HWND(hwnd), 2)


def sessao(pid: int) -> int:
    s = wt.DWORD()
    return s.value if kernel32.ProcessIdToSessionId(pid, ctypes.byref(s)) else -1


def aumid(pid: int) -> str:
    """Id do app da Microsoft Store/MSIX (para reabrir por shell:AppsFolder); vazio nos apps comuns."""
    h = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        n = ctypes.c_uint32(512)
        buf = ctypes.create_unicode_buffer(512)
        return buf.value if kernel32.GetApplicationUserModelId(h, ctypes.byref(n), buf) == 0 else ""
    finally:
        kernel32.CloseHandle(h)


def descricao_arquivo(caminho: str) -> str:
    """'Descrição do arquivo' do executável (o nome que o Gerenciador de Tarefas mostra)."""
    try:
        n = version.GetFileVersionInfoSizeW(caminho, None)
        if not n:
            return ""
        buf = ctypes.create_string_buffer(n)
        if not version.GetFileVersionInfoW(caminho, 0, n, buf):
            return ""
        p, tam = ctypes.c_void_p(), wt.UINT()
        idiomas = [(0x0409, 0x04B0), (0x0409, 0x04E4), (0x0416, 0x04E4), (0x0000, 0x04B0)]
        if version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(p), ctypes.byref(tam)) \
                and tam.value >= 4:
            par = ctypes.cast(p, ctypes.POINTER(ctypes.c_uint16))
            idiomas.insert(0, (par[0], par[1]))
        for idioma, pagina in idiomas:
            chave = f"\\StringFileInfo\\{idioma:04x}{pagina:04x}\\FileDescription"
            if version.VerQueryValueW(buf, chave, ctypes.byref(p), ctypes.byref(tam)) and tam.value > 1:
                return ctypes.wstring_at(p.value, tam.value - 1).strip()
    except OSError:
        pass
    return ""


def sou_admin() -> bool:
    return bool(shell32.IsUserAnAdmin())


class _SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wt.HWND),
                ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR),
                ("lpDirectory", wt.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY),
                ("dwHotKey", wt.DWORD), ("hIconOrMonitor", wt.HANDLE), ("hProcess", wt.HANDLE)]


shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFO)]


def executar_como_admin(exe: str, parametros: str, pasta: str) -> int | None:
    """Abre o processo elevado (o Windows mostra o UAC). Devolve o handle do processo, ou None se
    a pessoa recusou ou não deu para abrir."""
    info = _SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x400            # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb, info.lpFile, info.lpParameters, info.lpDirectory = "runas", exe, parametros, pasta
    info.nShow = 0
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        return None
    return info.hProcess


def processo_terminou(handle: int, espera_ms: int = 0) -> bool:
    return kernel32.WaitForSingleObject(handle, espera_ms) == 0


def fechar_handle(handle: int) -> None:
    kernel32.CloseHandle(handle)
