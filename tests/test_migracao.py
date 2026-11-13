"""Regressões da migração de dados para CorePulse, sempre em pastas temporárias."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from corepulse import config


class MigracaoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.nova = self.base / "CorePulse"
        self.destino = patch.object(config, "PASTA", str(self.nova))
        self.destino.start()
        self.addCleanup(self.destino.stop)

    def test_instalacao_nova_nao_cria_dados(self):
        config.migrar_dados()
        self.assertFalse(self.nova.exists())

    def test_preserva_configuracao_e_estado_do_modo_jogo(self):
        antiga = self.base / "MonitorPC"
        (antiga / "modo_jogo").mkdir(parents=True)
        preferencias = b'{"plano_mbps": 700, "fixado": false}'
        estado = b'{"ativo": true, "apps": ["exemplo.exe"]}'
        (antiga / "config.json").write_bytes(preferencias)
        (antiga / "modo_jogo" / "estado.json").write_bytes(estado)
        config.migrar_dados()
        config.migrar_dados()  # idempotente no próximo início
        self.assertEqual((self.nova / "config.json").read_bytes(), preferencias)
        self.assertEqual((self.nova / "modo_jogo" / "estado.json").read_bytes(), estado)
        self.assertFalse(antiga.exists())

    def test_tambem_reconhece_nome_anterior(self):
        antiga = self.base / "GlassPulse"
        antiga.mkdir()
        (antiga / "config.json").write_text('{}')
        config.migrar_dados()
        self.assertTrue((self.nova / "config.json").exists())

    def test_nao_sobrescreve_instalacao_existente(self):
        antiga = self.base / "MonitorPC"
        antiga.mkdir()
        (antiga / "config.json").write_text('anterior')
        self.nova.mkdir()
        (self.nova / "config.json").write_text('atual')
        config.migrar_dados()
        self.assertEqual((self.nova / "config.json").read_text(), 'atual')
        self.assertEqual((antiga / "config.json").read_text(), 'anterior')

    def test_falha_nao_apaga_dados_anteriores(self):
        antiga = self.base / "MonitorPC"
        antiga.mkdir()
        (antiga / "config.json").write_text('preservar')
        with patch.object(config.os, 'rename', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                config.migrar_dados()
        self.assertEqual((antiga / "config.json").read_text(), 'preservar')


if __name__ == '__main__':
    unittest.main()
