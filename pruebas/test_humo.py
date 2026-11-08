"""Pruebas de HUMO 79-82: comprobaciones rápidas de que el producto arranca y sus piezas responden."""
import importlib
import os
import socket
import subprocess
import sys
import time
import tomllib
import unittest
import urllib.request

from pruebas.apoyo import MODEL, ROOT


class HumoTests(unittest.TestCase):
    def test_79_modulos_y_dependencias_importan(self):
        for name in ("core", "auth", "informe", "metrics_csv", "streamlit", "ultralytics", "PIL", "torch"):
            self.assertIsNotNone(importlib.import_module(name), name)
        self.assertEqual(sys.version_info[:2], (3, 12))

    def test_80_modelo_presente_carga_y_predice(self):
        import core
        self.assertTrue(MODEL.exists())
        start = time.perf_counter()
        det = core.YoloDetector(MODEL, authorization=True)
        items, meta = det.predict(core.synthetic_image())
        self.assertIsInstance(items, list)
        self.assertEqual(meta["weights_sha256"], core.sha256(MODEL))
        self.assertLess(time.perf_counter() - start, 15)

    def test_81_configuracion_valida(self):
        cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
        self.assertIn("light", cfg["theme"]); self.assertIn("dark", cfg["theme"])
        for f in ("app.py", "ABRIR_DEMO.bat", "requirements.txt", "crear_usuarios.py", "LEEME.md"):
            self.assertTrue((ROOT / f).exists(), f)

    def test_82_servidor_arranca_y_responde(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
        env = {**os.environ, "PERIOVISION_DATA": os.environ.get("TEMP", str(ROOT)) + os.sep + "pv_humo"}
        proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
                                 "--server.headless", "true"], cwd=ROOT, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            health = None
            for _ in range(60):
                try:
                    health = urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2).read()
                    break
                except OSError:
                    time.sleep(0.5)
            self.assertEqual(health, b"ok")
            page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
            self.assertEqual(page.status, 200)
        finally:
            proc.terminate(); proc.wait(timeout=20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
