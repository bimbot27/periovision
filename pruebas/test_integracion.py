"""Pruebas de INTEGRACIÓN 57-62: módulos trabajando juntos, con el modelo YOLO real (best.pt)."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from auth import UserStore, validate_profile
from core import Case, ProductError, YoloDetector, draw_detections
from informe import CaseArchive, build_report, report_csv
from pruebas.apoyo import MODEL, PASSWORD, PERFIL, SAMPLE, real_detector


class IntegracionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.det = real_detector()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def new_case(self):
        case = Case(SAMPLE, "INT01"); case.quality(True)
        return case

    def test_57_carga_real_mas_yolo_real(self):
        run = self.new_case().infer(self.det)
        self.assertEqual(run["mode"], "REAL")
        self.assertTrue(run["model"]["clinical_inference"])
        self.assertEqual(len(run["model"]["weights_sha256"]), 64)
        self.assertGreaterEqual(len(run["original"]), 1)
        for item in run["original"]:
            self.assertIn(item["class"], ("Normal", "Stage 1", "Stage 2", "Stage 3"))

    def test_58_clases_del_modelo_coinciden_con_protocolo(self):
        self.assertEqual(set(self.det.names.values()), {"Normal", "Stage 1", "Stage 2", "Stage 3"})
        self.assertEqual(self.det.model.task, "detect")

    def test_59_calibracion_del_admin_se_aplica_al_detector(self):
        import copy
        strict = copy.copy(self.det); strict.conf = 0.80
        loose = copy.copy(self.det); loose.conf = 0.10
        n_strict = len(self.new_case().infer(strict)["original"])
        n_loose = len(self.new_case().infer(loose)["original"])
        self.assertLessEqual(n_strict, n_loose)
        self.assertEqual(self.new_case().infer(strict)["model"]["confidence_threshold"], 0.80)
        with self.assertRaises(ProductError):
            YoloDetector(MODEL, True, conf=1.5)

    def test_60_flujo_completo_hasta_historial(self):
        store = UserStore(self.root / "u.json")
        store.create_user("lucia", PASSWORD, "usuario", must_change=False, profile=PERFIL)
        user = store.authenticate("lucia", PASSWORD)
        case = self.new_case(); run = case.infer(self.det)
        case.review("aceptar", "lucia")
        report = build_report(case, user["usuario"], user["perfil"], "Control en 6 meses.")
        archive = CaseArchive(self.root / "casos")
        archive.save(case, report, draw_detections(case.image, run["original"]))
        saved = archive.list()[0]
        self.assertEqual(saved["profesional"]["cop"], "54321")
        self.assertEqual(len(saved["hallazgos"]), len(run["original"]))

    def test_61_csv_del_informe_coincide_con_salida_del_modelo(self):
        case = self.new_case(); run = case.infer(self.det); case.review("aceptar", "lucia")
        report = build_report(case, "lucia", validate_profile(PERFIL, "usuario"))
        rows = list(csv.reader(io.StringIO(report_csv(report).decode("utf-8-sig"))))
        start = next(i for i, r in enumerate(rows) if r and r[0] == "N.º") + 1
        table = [r for r in rows[start:] if r and r[0].isdigit()]
        self.assertEqual(len(table), len(run["original"]))
        for row, item in zip(table, run["original"]):
            self.assertEqual(row[1], item["class"])
            self.assertEqual(row[3], f"{item['confidence'] * 100:.1f} %")

    def test_62_registro_tecnico_y_exportacion_core_con_modelo_real(self):
        case = self.new_case(); case.infer(self.det); case.review("descartar", "lucia")
        json_path, csv_path = case.export(self.root / "salida")
        value = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertFalse(value["demo"])
        self.assertEqual(value["reviews"][0]["revised"], [])
        self.assertGreaterEqual(len(value["runs"][0]["original"]), 1)  # el descarte no borra la propuesta
        self.assertNotIn("radiografia_ejemplo", json_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
