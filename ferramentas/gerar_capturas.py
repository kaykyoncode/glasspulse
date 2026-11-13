"""Gera as capturas da documentação com dados fictícios, sem ler recursos do PC."""
from pathlib import Path
from types import SimpleNamespace
import math
import os
import sys
import time

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / '.libs'), str(RAIZ / 'src')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import QRect
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from corepulse.config import PADRAO
from corepulse.widget import CorePulseWidget


class CapturaWidget(CorePulseWidget):
    def _tela_atual(self):
        # O monitor virtual offscreen mede 800x800; reserve espaço para os dois layouts.
        return SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 3840, 2160))


def main():
    app = QApplication([])
    for fonte in (RAIZ / 'fontes').iterdir():
        if fonte.suffix in {'.ttf', '.otf'}:
            QFontDatabase.addApplicationFont(str(fonte))
    gb = 1024 ** 3
    coletor = SimpleNamespace(nvml=True, cpu_nome='Core i9-13900K', cpu_threads=32)
    dados = {
        'cpu': {'total': 12, 'nucleos': [6 + (i * 7 % 25) for i in range(32)], 'ghz': 4.77},
        'ram': {'total': 32 * gb, 'usada': 18 * gb, 'livre': 14 * gb, 'pct': 56.25},
        'gpu': {'nome': 'NVIDIA GeForce RTX 5070 Ti', 'uso': 4, 'vram_usada': 2.7 * gb,
                'vram_total': 16 * gb, 'temp': 59, 'watts': 65, 'clock_mhz': 2540, 'ventoinha': 0},
        'rede': {'down_bps': 15e6, 'up_bps': 3e6, 'link_bps': 2.5e9, 'tipo': 'Ethernet'},
        'discos': [
            {'letra': 'C:', 'rotulo': '', 'total': 952 * gb, 'usado': 542 * gb,
             'livre': 410 * gb, 'pct': 57, 'ativo': 2, 'leitura': 96e3, 'escrita': 140e3},
            {'letra': 'D:', 'rotulo': '', 'total': 1863 * gb, 'usado': 815 * gb,
             'livre': 1048 * gb, 'pct': 44, 'ativo': 0, 'leitura': 0, 'escrita': 0},
        ],
        'uptime': 7680,
    }
    processos = [('Navegador', 12, 2.6 * gb), ('Editor', 5, 2.3 * gb),
                 ('Player', 2, 1.6 * gb), ('Terminal', 3, 1.5 * gb), ('Arquivos', 2, gb)]
    for layout in ('coluna', 'painel'):
        cfg = dict(PADRAO, layout=layout, plano_mbps=700)
        janela = CapturaWidget(cfg, coletor, None, lambda: None)
        for i in range(62):
            dados['cpu']['total'] = 12 + 7 * abs(math.sin(i * 0.31))
            dados['gpu']['uso'] = 4 + 4 * abs(math.sin(i * 0.21))
            dados['rede']['down_bps'] = 15e6 + 5e6 * abs(math.sin(i * 0.38))
            janela.aplicar(dados, processos)
        dados['cpu']['total'] = 12
        dados['gpu']['uso'] = 4
        dados['rede']['down_bps'] = 15e6
        janela.aplicar(dados, processos)
        janela.t0 = time.monotonic() - 2
        janela.anim.stop()
        for tween in janela.tw.values():
            tween.passo(1)
        imagem = janela.grab()
        destino = RAIZ / 'docs' / f'{layout}.png'
        if not imagem.save(str(destino)):
            raise RuntimeError(f'Falha ao salvar {destino}')
        print(f'{destino}: {imagem.width()} x {imagem.height()}')
        janela.close()
    app.quit()


if __name__ == '__main__':
    main()
