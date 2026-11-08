"""Pruebas adicionales 41-44: perfil profesional, informes legibles e historial de casos."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from auth import AuthError, UserStore, validate_profile
from core import Case, DemoDetector, draw_detections, make_demo
from informe import CaseArchive, build_report, report_csv, report_pdf

PERFIL = {"nombres": "ana maría", "apellidos": "quispe rojas", "correo": "Ana.Quispe@Ejemplo.pe",
          "cop": "012345", "especialidad": "Periodoncia", "fecha_nacimiento": "1990-05-17"}


class InformesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        demo = self.root / "DEMO01.png"; make_demo(demo)
        self.case = Case(demo, "DEMO01"); self.case.quality(True); self.case.infer(DemoDetector())

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, action="aceptar", user="ana.quispe", obs="Control en 6 meses."):
        self.case.review(action, user.replace(".", "_"))
        return build_report(self.case, user, validate_profile(PERFIL, "usuario"), obs)

    def test_41_perfil_valida_y_exige_cop_al_usuario(self):
        clean = validate_profile(PERFIL, "usuario")
        self.assertEqual((clean["nombres"], clean["correo"], clean["cop"]), ("Ana María", "ana.quispe@ejemplo.pe", "12345"))
        for bad in ({"correo": "sin-arroba"}, {"cop": "ABC"}, {"cop": ""}, {"fecha_nacimiento": "2020-01-01"},
                    {"nombres": "<script>"}):
            with self.assertRaises(AuthError, msg=bad):
                validate_profile({**PERFIL, **bad}, "usuario")
        self.assertEqual(validate_profile({**PERFIL, "cop": ""}, "administrador")["cop"], "")
        store = UserStore(self.root / "u.json")
        store.create_user("ana.quispe", "Clave-Segura-2026", "usuario", profile=PERFIL)
        store.update_profile("ana.quispe", {**PERFIL, "cop": "99999"}, "ana.quispe")  # sin permiso: COP se conserva
        self.assertEqual(store.get_profile("ana.quispe")["cop"], "12345")

    def test_42_csv_es_un_informe_legible(self):
        rows = list(csv.reader(io.StringIO(report_csv(self.report()).decode("utf-8-sig"))))
        fields = {r[0]: r[1] for r in rows if len(r) == 2}
        self.assertEqual(fields["Analizado y validado por"], "Ana María Quispe Rojas")
        self.assertEqual(fields["N.º COP"], "12345")
        self.assertEqual(fields["Resultado de la validación"], "Aprobada")
        header = next(r for r in rows if r and r[0] == "N.º")
        self.assertIn("Ubicación aproximada", header)
        text = report_csv(self.report()).decode("utf-8-sig")
        self.assertIn("80.0 %", text); self.assertNotIn("run_id", text); self.assertNotIn("sha256", text)

    def test_43_pdf_generado_con_profesional(self):
        report = self.report("descartar")
        self.assertEqual(report["resultado_validacion"], "Rechazada")
        pdf = report_pdf(report, draw_detections(self.case.image, self.case.data["runs"][-1]["original"]))
        self.assertTrue(pdf.startswith(b"%PDF")); self.assertGreater(len(pdf), 10_000)

    def test_44_historial_guarda_y_lista_quien_valido(self):
        archive = CaseArchive(self.root / "casos")
        report = self.report()
        archive.save(self.case, report, draw_detections(self.case.image, []))
        listed = archive.list()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["profesional"]["nombre"], "Ana María Quispe Rojas")
        self.assertEqual(listed[0]["resultado_validacion"], "Aprobada")
        for kind in ("pdf", "csv", "json"):
            data, name, _ = archive.file("DEMO01", kind)
            self.assertTrue(data and name.startswith("DEMO01_"))
        self.assertTrue(json.loads((archive.folder("DEMO01") / "registro_tecnico.json").read_text(encoding="utf-8"))["runs"])
        with self.assertRaises(Exception):
            archive.folder("../fuera")


if __name__ == "__main__":
    unittest.main(verbosity=2)
