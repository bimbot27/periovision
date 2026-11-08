"""Pruebas UNITARIAS 45-56: funciones aisladas de core, auth, informe y metrics_csv."""
import json
import math
from pathlib import Path
import tempfile
import unittest

from PIL import Image

import auth
import core
import informe
from metrics_csv import summarize


class UnitariasTests(unittest.TestCase):
    def test_45_check_detections_acepta_valida_y_normaliza_tipos(self):
        out = core.check_detections([{"class": "Stage 1", "confidence": "0.5", "box": [1, 2, "30", 40]}], (100, 100))
        self.assertEqual(out, [{"class": "Stage 1", "confidence": 0.5, "box": [1.0, 2.0, 30.0, 40.0]}])

    def test_46_check_detections_rechaza_clase_caja_y_confianza(self):
        bad = [{"class": "Otra", "confidence": .5, "box": [0, 0, 10, 10]},
               {"class": "Normal", "confidence": 1.5, "box": [0, 0, 10, 10]},
               {"class": "Normal", "confidence": .5, "box": [10, 10, 5, 5]},
               {"class": "Normal", "confidence": .5, "box": [0, 0, 10]},
               {"class": "Normal", "box": [0, 0, 10, 10]}]
        for item in bad:
            with self.assertRaises(core.ProductError, msg=item):
                core.check_detections([item], (100, 100))

    def test_47_draw_detections_no_modifica_original(self):
        img = Image.new("RGB", (200, 200), "black")
        before = img.tobytes()
        out = core.draw_detections(img, [{"class": "Stage 3", "confidence": .9, "box": [10, 10, 100, 100]}])
        self.assertEqual(img.tobytes(), before)
        self.assertNotEqual(out.tobytes(), before)
        self.assertEqual(out.getpixel((10, 50)), (255, 59, 48))  # color de Stage 3

    def test_48_sha256_coincide_con_hashlib(self):
        import hashlib
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"periovision" * 1000)
        try:
            self.assertEqual(core.sha256(f.name), hashlib.sha256(b"periovision" * 1000).hexdigest())
        finally:
            Path(f.name).unlink()

    def test_49_ubicacion_aproximada_en_cuadricula(self):
        cases = {(0, 0, 10, 10): "zona superior izquierda", (45, 45, 55, 55): "zona central",
                 (90, 90, 100, 100): "zona inferior derecha", (40, 0, 60, 20): "zona superior central"}
        for box, expected in cases.items():
            self.assertEqual(informe.location(list(box), (100, 100)), expected)

    def test_50_validacion_nombre_usuario(self):
        self.assertEqual(auth.validate_username("  Ana.Quispe "), "ana.quispe")
        for bad in ("ab", "a" * 33, "ana quispe", "ana/../x", "ñandú"):
            with self.assertRaises(auth.AuthError, msg=bad):
                auth.validate_username(bad)

    def test_51_contrasena_generada_cumple_politica(self):
        for _ in range(50):
            pwd = auth.generate_password()
            self.assertEqual(auth.password_problems(pwd), [], pwd)
            self.assertEqual(len(pwd), 16)

    def test_52_hash_y_verificacion(self):
        rec = auth.hash_password("Clave-Segura-2026", iterations=1000)
        self.assertTrue(auth.verify_password("Clave-Segura-2026", rec))
        self.assertFalse(auth.verify_password("clave-segura-2026", rec))

    def test_53_nombre_visible(self):
        self.assertEqual(auth.display_name({"nombres": "Ana", "apellidos": "Quispe"}, "aq"), "Ana Quispe")
        self.assertEqual(auth.display_name({}, "aq"), "aq")
        self.assertEqual(auth.display_name(None, "aq"), "aq")

    def test_54_metricas_con_encabezados_con_espacios(self):
        p = Path(tempfile.mkdtemp()) / "r.csv"
        p.write_text("  epoch, metrics/precision(B), metrics/recall(B), metrics/mAP50(B), metrics/mAP50-95(B)\n"
                     "1, 0.5, 0.5, 0.4, 0.3\n2, 0.6, 0.6, 0.5, 0.35\n", encoding="utf-8")
        value = summarize(p)
        self.assertEqual(value["rows"], 2)
        self.assertAlmostEqual(value["last_epoch"]["harmonic_precision_recall"], 0.6)

    def test_55_descripciones_cubren_todas_las_clases(self):
        for label in core.LABELS:
            self.assertIn(label, informe.DESCRIPTIONS)
        self.assertEqual(informe.RESULTS["aceptar"], "Aprobada")
        self.assertEqual(informe.RESULTS["descartar"], "Rechazada")

    def test_56_informe_json_es_utf8_legible(self):
        data = informe.report_json({"profesional": {"nombre": "Lucía Ñahui"}, "confianza": "87.2 %"})
        self.assertIn("Lucía Ñahui".encode("utf-8"), data)
        self.assertEqual(json.loads(data)["confianza"], "87.2 %")


if __name__ == "__main__":
    unittest.main(verbosity=2)
