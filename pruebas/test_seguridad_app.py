"""Pruebas de SEGURIDAD de la aplicación 87-94 (complementan las 31-40 de autenticación)."""
import csv
import io
import json
import statistics
import time
import tomllib
import unittest
from pathlib import Path
import tempfile

from PIL import Image

import core
from auth import UserStore
from core import Case, DemoDetector, ProductError, draw_detections, make_demo
from informe import CaseArchive, build_report, report_csv
from pruebas.apoyo import PASSWORD, PERFIL, ROOT, TempData, goto, logged_app, pages


class SeguridadAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        demo = self.root / "DEMO01.png"; make_demo(demo)
        self.case = Case(demo, "DEMO01"); self.case.quality(True); self.case.infer(DemoDetector())

    def tearDown(self):
        self.tmp.cleanup()

    def test_87_usuario_no_accede_a_paginas_de_administrador(self):
        data = TempData()
        try:
            admin = logged_app("qa.admin", "administrador").run()
            admin_hash = next(h for h, i in admin._registered_pages.items() if i.get("url_pathname") == "usuarios")
            user = logged_app("qa.user", "usuario", PERFIL).run()
            self.assertNotIn("usuarios", pages(user))
            goto(user, "", page_hash=admin_hash)  # intenta abrir Usuarios con sesión de usuario
            texts = " ".join(m.value for m in user.markdown)
            self.assertNotIn("Crear usuario", texts)
            self.assertFalse(any(b.label == "Crear usuario" for b in user.button))
        finally:
            data.close()

    def test_88_xss_en_historial_se_escapa(self):
        data = TempData()
        try:
            self.case.review("aceptar", "qa_user")
            report = build_report(self.case, "qa.user", PERFIL, "<script>alert('x')</script>")
            CaseArchive(data.path / "casos").save(self.case, report, draw_detections(self.case.image, []))
            at = goto(logged_app("qa.user", "usuario", PERFIL).run(), "historial")
            html = " ".join(m.value for m in at.markdown)
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;", html)
        finally:
            data.close()

    def test_89_recorrido_de_rutas_bloqueado(self):
        archive = CaseArchive(self.root / "casos")
        for code in ("../fuera", "..\\fuera", "a/b", "C:x", ""):
            with self.assertRaises(ProductError, msg=code):
                archive.folder(code)
        for code in ("../x", "=1+1", "con espacios"):
            with self.assertRaises(ProductError):
                Case(self.root / "DEMO01.png", code)

    def test_90_configuracion_endurecida_del_servidor(self):
        cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
        self.assertTrue(cfg["server"]["enableXsrfProtection"])
        self.assertLessEqual(cfg["server"]["maxUploadSize"], 200)       # zips del administrador
        self.assertEqual(core.MAX_BYTES, 20 * 1024 * 1024)               # cada radiografía: 20 MB
        self.assertEqual(cfg["client"]["showErrorDetails"], "none")
        self.assertFalse(cfg["browser"]["gatherUsageStats"])

    def test_91_bomba_de_descompresion_rechazada(self):
        p = self.root / "enorme.png"
        Image.new("L", (5000, 4200)).save(p)  # 21 millones de píxeles, pocos KB en disco
        self.assertLess(p.stat().st_size, core.MAX_BYTES)
        with self.assertRaisesRegex(ProductError, "millones de píxeles"):
            core.load_image(p)

    def test_92_tiempo_no_revela_si_el_usuario_existe(self):
        store = UserStore(self.root / "u.json")
        store.create_user("real", PASSWORD, "usuario", must_change=False)
        def timed(user):
            t = time.perf_counter()
            try:
                store.authenticate(user, "Incorrecta-2026!")
            except Exception:
                pass
            return time.perf_counter() - t
        real = statistics.median(timed("real") for _ in range(3))
        ghost = statistics.median(timed("fantasma") for _ in range(3))
        self.assertLess(max(real, ghost) / min(real, ghost), 1.5)

    def test_93_csv_neutraliza_inyeccion_de_formulas(self):
        self.case.review("aceptar", "qa_user")
        report = build_report(self.case, "qa.user", PERFIL, '=HYPERLINK("http://malicioso","clic")')
        rows = list(csv.reader(io.StringIO(report_csv(report).decode("utf-8-sig"))))
        for row in rows:
            for cell in row:
                self.assertFalse(cell[:1] in ("=", "+", "-", "@"), f"celda peligrosa: {cell!r}")

    def test_94_registros_sin_secretos_ni_rutas_locales(self):
        data = TempData()
        try:
            raw = data.store.path.read_text(encoding="utf-8")
            self.assertNotIn(PASSWORD, raw)
            self.assertTrue(all(u["password"]["algorithm"] == "pbkdf2_sha256" for u in json.loads(raw).values()))
            self.case.review("aceptar", "qa_user")
            folder = CaseArchive(data.path / "casos").save(
                self.case, build_report(self.case, "qa.user", PERFIL), draw_detections(self.case.image, []))
            for f in folder.glob("*.json"):
                text = f.read_text(encoding="utf-8")
                self.assertNotIn(str(self.root), text)
                self.assertNotIn("DEMO01.png", text)
        finally:
            data.close()

    def test_101_sin_instalaciones_automaticas_en_ejecucion(self):
        import ultralytics.utils as uu
        self.assertFalse(uu.AUTOINSTALL)  # core fija YOLO_AUTOINSTALL=false antes de importar Ultralytics
        p = self.root / "corrupto.jpg"; p.write_bytes(b"\xff\xd8 no es una imagen")
        with self.assertRaises(ProductError):
            core.load_image(p)  # rechaza con causa, sin intentar descargar paquetes


if __name__ == "__main__":
    unittest.main(verbosity=2)
