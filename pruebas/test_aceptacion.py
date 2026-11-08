"""Pruebas de ACEPTACIÓN 71-78: criterios CA y RNF del informe del proyecto y pedidos del cliente."""
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

import core
from auth import UserStore
from core import Case, ProductError, draw_detections
from informe import CaseArchive, build_report, report_pdf
from pruebas.apoyo import PASSWORD, PERFIL, SAMPLE, TempData, goto, logged_app, pages, real_detector, title


class AceptacionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.det = real_detector()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def analyzed(self):
        case = Case(SAMPLE, "ACEP01"); case.quality(True); case.infer(self.det)
        return case

    def test_71_CA05_carga_valida_e_invalidas_rechazadas_con_causa(self):
        self.assertEqual(Case(SAMPLE, "OK01").image.size, (748, 512))
        (self.root / "a.webp").write_bytes(b"x")
        Image.new("RGB", (20, 20)).save(self.root / "b.png", format="BMP")
        (self.root / "c.jpg").write_bytes(b"")
        causes = []
        for name in ("a.webp", "b.png", "c.jpg"):
            with self.assertRaises(ProductError) as err:
                core.load_image(self.root / name)
            causes.append(str(err.exception))
        self.assertTrue(all(len(c) > 15 for c in causes), causes)  # cada rechazo explica la causa

    def test_72_CA06_detecciones_mostradas_igual_a_salida_almacenada(self):
        case = self.analyzed(); run = case.data["runs"][-1]
        case.review("aceptar", "qa_user")
        report = build_report(case, "qa.user", PERFIL)
        self.assertEqual([(h["clase"], h["confianza"]) for h in report["hallazgos"]],
                         [(i["class"], f"{i['confidence'] * 100:.1f} %") for i in run["original"]])
        self.assertEqual(case.data["version"], core.VERSION)

    def test_73_CA07_pendiente_hasta_validar_y_registro_sin_sobrescribir(self):
        case = self.analyzed()
        self.assertEqual(case.snapshot()["status"], "provisional")
        original = json.dumps(case.data["runs"][-1]["original"])
        review = case.review("aceptar", "qa_user")
        self.assertEqual((review["reviewer_code"], review["action"]), ("qa_user", "aceptar"))
        self.assertTrue(review["utc"])
        self.assertEqual(json.dumps(case.data["runs"][-1]["original"]), original)
        self.assertEqual(case.snapshot()["status"], "revision_registrada_sin_validacion_clinica")

    def test_74_CA08_informe_coincide_con_revision_y_sin_datos_identificables(self):
        case = self.analyzed(); case.review("descartar", "qa_user")
        report = build_report(case, "qa.user", PERFIL)
        self.assertEqual(report["resultado_validacion"], "Rechazada")
        text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("radiografia_ejemplo", text)
        self.assertNotIn(str(SAMPLE.parent), text)

    def test_75_RNF04_cien_por_ciento_de_pruebas_de_roles(self):
        data = TempData()
        try:
            checks = []
            admin = logged_app("qa.admin", "administrador").run()
            user = logged_app("qa.user", "usuario", PERFIL).run()
            checks += ["usuarios" in pages(admin), "modelo" in pages(admin), "pruebas" in pages(admin)]
            checks += ["usuarios" not in pages(user), "modelo" not in pages(user), "pruebas" not in pages(user)]
            checks += ["historial" in pages(user), "historial" not in pages(admin)]
            checks += [title(admin) == "Estado del sistema", title(user) == "Analizar radiografía"]
            self.assertEqual(sum(checks), len(checks))  # 100 % aprobadas
        finally:
            data.close()

    def test_76_RNF05_pantallas_e_informes_indican_apoyo_experimental(self):
        data = TempData()
        try:
            at = logged_app("qa.user", "usuario", PERFIL).run()
            self.assertTrue(any(core.NOTICE in m.value for m in at.markdown))
        finally:
            data.close()
        case = self.analyzed(); case.review("aceptar", "qa_user")
        report = build_report(case, "qa.user", PERFIL)
        self.assertIn("Requiere revisión profesional", report["aviso"])
        self.assertIn("no reemplaza el diagnóstico", report["aviso"])
        self.assertTrue(report_pdf(report, case.image).startswith(b"%PDF"))

    def test_77_cliente_informe_identifica_profesional_e_historial_por_estado(self):
        archive = CaseArchive(self.root / "casos")
        for code, action in (("ACEP_A", "aceptar"), ("ACEP_R", "descartar")):
            case = Case(SAMPLE, code); case.quality(True); case.infer(self.det); case.review(action, "qa_user")
            archive.save(case, build_report(case, "qa.user", PERFIL), draw_detections(case.image, []))
        listed = {r["codigo_caso"]: r for r in archive.list()}
        self.assertEqual(listed["ACEP_A"]["resultado_validacion"], "Aprobada")
        self.assertEqual(listed["ACEP_R"]["resultado_validacion"], "Rechazada")
        for r in listed.values():
            self.assertEqual((r["profesional"]["nombre"], r["profesional"]["cop"]), ("Lucía Prueba Ramos", "54321"))

    def test_78_cliente_usuario_no_cambia_calibracion_ni_cop(self):
        data = TempData()
        try:
            user = logged_app("qa.user", "usuario", PERFIL).run()
            self.assertEqual(len(user.slider) + len(user.select_slider), 0)
            account = goto(user, "cuenta")
            cop = next(t for t in account.text_input if t.label.startswith("N.º de COP"))
            self.assertTrue(cop.disabled)
            store: UserStore = data.store
            store.update_profile("qa.user", {**PERFIL, "cop": "11111"}, "qa.user")
            self.assertEqual(store.get_profile("qa.user")["cop"], "54321")
            store.update_profile("qa.user", {**PERFIL, "cop": "11111"}, "qa.admin", allow_cop=True)
            self.assertEqual(store.get_profile("qa.user")["cop"], "11111")
        finally:
            data.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
