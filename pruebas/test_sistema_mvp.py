"""Pruebas de SISTEMA 114-121 de las funciones que completan el MVP, ejecutando app.py con AppTest."""
import json
import unittest
from pathlib import Path

from core import Case
from informe import CaseArchive, build_report, build_unevaluable_report, report_pdf
from pruebas.apoyo import PERFIL, ROOT, SAMPLE, TempData, app_test, goto, logged_app, real_detector, title


def app_namespace() -> dict:
    """Funciones de app.py sin ejecutar main() (para probar ayudantes de la interfaz)."""
    src = (ROOT / "app.py").read_text(encoding="utf-8").rsplit("\nmain()", 1)[0]
    ns = {"__file__": str(ROOT / "app.py"), "__name__": "pv_app"}
    exec(compile(src, "app.py", "exec"), ns)
    return ns


class SistemaMvpTests(unittest.TestCase):
    def setUp(self):
        self.data = TempData()

    def tearDown(self):
        self.data.close()

    def test_114_paginas_nuevas_del_administrador_cargan(self):
        admin = logged_app("qa.admin", "administrador").run()
        expected = {"evaluacion": "Evaluación del modelo", "datos": "Datos", "respaldos": "Respaldos"}
        for url, name in expected.items():
            at = goto(admin, url)
            self.assertFalse(at.exception, url)
            self.assertEqual(title(at), name)
            self.assertGreaterEqual(len(at.get("file_uploader")), 1, url)

    def test_115_respaldo_diario_automatico_al_abrir_estado(self):
        at = logged_app("qa.admin", "administrador").run()
        self.assertEqual(title(at), "Estado del sistema")
        backups = list((self.data.path / "respaldos_datos").glob("respaldo_*.zip"))
        self.assertEqual(len(backups), 1)
        self.assertIn("respaldo_automatico", (self.data.path / "auditoria.jsonl").read_text(encoding="utf-8"))

    def test_116_crear_respaldo_desde_la_pagina(self):
        at = goto(logged_app("qa.admin", "administrador").run(), "respaldos")
        before = len(list((self.data.path / "respaldos_datos").glob("*.zip")))
        next(b for b in at.button if b.label == "Crear respaldo ahora").click().run()
        self.assertEqual(len(list((self.data.path / "respaldos_datos").glob("*.zip"))), before + 1)
        self.assertTrue(any("Respaldo creado" in s.value for s in at.success))

    def test_117_historial_muestra_no_evaluables(self):
        case = Case(SAMPLE, "NOEVAL01"); case.quality(False)
        report = build_unevaluable_report(case, "qa.user", PERFIL, "Imagen borrosa o movida")
        CaseArchive(self.data.path / "casos").save(case, report, case.image)
        at = goto(logged_app("qa.user", "usuario", PERFIL).run(), "historial")
        html = " ".join(m.value for m in at.markdown)
        self.assertIn("No evaluable", html)
        self.assertIn("No evaluables", " ".join(m.value for m in at.markdown))

    def test_118_arranque_en_la_nube_crea_administrador_desde_secrets(self):
        (self.data.path / "usuarios.json").unlink()
        at = app_test()
        at.secrets["periovision"] = {"admin_user": "cloud.admin", "admin_password": "Nube-Inicial-2026!"}
        at.run()
        self.assertFalse(at.exception)
        users = json.loads((self.data.path / "usuarios.json").read_text(encoding="utf-8"))
        self.assertEqual(users["cloud.admin"]["role"], "administrador")
        self.assertTrue(users["cloud.admin"]["must_change"])
        self.assertNotIn("Nube-Inicial-2026!", json.dumps(users))

    def test_124_descarga_del_modelo_verificada_por_huella(self):
        import hashlib
        import io
        import tempfile
        import urllib.request
        from unittest import mock
        ns = app_namespace()
        payload = b"pesos-de-prueba"
        good = hashlib.sha256(payload).hexdigest()
        model = Path(tempfile.mkdtemp()) / "best.pt"
        ns["MODEL_PATH"] = model
        ns["store"] = self.data.store  # ya hay usuarios: no crea administrador
        fake = lambda url, timeout: io.BytesIO(payload)  # noqa: E731
        cases = [({"model_url": "http://inseguro/best.pt", "model_sha256": good}, "https://"),
                 ({"model_url": "file:///C:/best.pt", "model_sha256": good}, "https://"),
                 ({"model_url": "https://ok/best.pt"}, "model_sha256"),
                 ({"model_url": "https://ok/best.pt", "model_sha256": "0" * 64}, "no coincide")]
        with mock.patch.object(urllib.request, "urlopen", fake):
            for secrets, message in cases:
                ns["st"].secrets = {"periovision": secrets}
                with self.assertRaisesRegex(ns["ProductError"], message):
                    ns["cloud_bootstrap"]()
                self.assertFalse(model.exists())
            ns["st"].secrets = {"periovision": {"model_url": "https://ok/best.pt", "model_sha256": good}}
            self.assertEqual(ns["cloud_bootstrap"](), "modelo verificado")
        self.assertEqual(model.read_bytes(), payload)

    def test_119_correccion_desde_el_editor(self):
        ns = app_namespace()
        original = [{"class": "Stage 2", "confidence": 0.87, "box": [1, 2, 3, 4]}]
        rows = [{"Clase": "Stage 3", "x1": 10, "y1": 10, "x2": 50, "y2": 60},
                {"Clase": "Stage 1", "x1": 100, "y1": 100, "x2": 150, "y2": 160},
                {"Clase": None, "x1": None, "y1": None, "x2": None, "y2": None}]
        out = ns["corrected_items"](rows, original)
        self.assertEqual([o["class"] for o in out], ["Stage 3", "Stage 1"])
        self.assertEqual([o["confidence"] for o in out], [0.87, 1.0])  # hallazgo agregado por el profesional
        with self.assertRaises(ns["ProductError"]):
            ns["corrected_items"]([{"Clase": "Stage 1", "x1": 1, "y1": None, "x2": 3, "y2": 4}], original)

    def test_120_registro_no_evaluable_sin_inferencia(self):
        case = Case(SAMPLE, "NOEVAL02")
        with self.assertRaises(Exception):
            build_unevaluable_report(case, "qa.user", PERFIL, "x")  # aún no marcada como no evaluable
        case.quality(False)
        report = build_unevaluable_report(case, "qa.user", PERFIL, "Zona de interés incompleta")
        self.assertEqual(report["resultado_validacion"], "No evaluable")
        self.assertEqual(case.data["runs"], [])
        self.assertTrue(report_pdf(report, case.image).startswith(b"%PDF"))

    def test_121_informe_de_caso_corregido(self):
        case = Case(SAMPLE, "CORR02"); case.quality(True); run = case.infer(real_detector())
        revised = [{"class": "Stage 1", "confidence": 1.0, "box": [10.0, 10.0, 120.0, 200.0]}]
        case.review("corregir", "qa_user", revised)
        report = build_report(case, "qa.user", PERFIL)
        self.assertEqual(report["resultado_validacion"], "Aprobada con correcciones")
        self.assertEqual([h["clase"] for h in report["hallazgos"]], ["Stage 1"])
        self.assertIn(f"{len(run['original'])} propuesta(s) del modelo", report["resumen"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
