"""Pruebas de RENDIMIENTO 83-86 (RNF02 / I07). Guardan las mediciones en evidencias/rendimiento.json.

Metas del informe: inferencia p95 <= 100 ms y carga a visualización p95 <= 3 s, con >= 100 ejecuciones.
"""
import json
import os
import platform
import tempfile
import time
import unittest
from pathlib import Path

from auth import UserStore
from core import Case, draw_detections
from informe import CaseArchive, build_report, report_csv, report_pdf
from pruebas.apoyo import PASSWORD, PERFIL, ROOT, SAMPLE, percentile, real_detector

RESULTS: dict = {}


def stats(values: list[float]) -> dict:
    return {"n": len(values), "p50_ms": round(percentile(values, 50), 1), "p95_ms": round(percentile(values, 95), 1),
            "max_ms": round(max(values), 1), "min_ms": round(min(values), 1)}


class RendimientoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.det = real_detector()
        warm = Case(SAMPLE, "WARM"); warm.quality(True); warm.infer(cls.det)  # calentamiento (no se mide)

    @classmethod
    def tearDownClass(cls):
        import torch
        RESULTS["entorno"] = {"cpu": platform.processor(), "nucleos": os.cpu_count(), "hilos_torch": torch.get_num_threads(),
                              "python": platform.python_version(), "dispositivo": "cpu", "imagen": "748 x 512 px",
                              "imgsz": 640, "lote": 1, "calentamiento": "1 inferencia descartada"}
        (ROOT / "evidencias").mkdir(exist_ok=True)
        (ROOT / "evidencias" / "rendimiento.json").write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False), encoding="utf-8")

    @unittest.skipIf(os.environ.get("PERIOVISION_REFERENCIA") == "0",
                     "RNF02 se mide en el equipo de referencia; este entorno (CI o nube) no lo es")
    def test_83_inferencia_p95_menor_a_100_ms(self):
        case = Case(SAMPLE, "PERF"); image = case.image
        times = []
        for _ in range(100):
            r = self.det.model.predict(source=image, imgsz=640, conf=.25, device="cpu", verbose=False)[0]
            times.append(r.speed["inference"])
        RESULTS["inferencia_modelo"] = stats(times)
        self.assertLessEqual(percentile(times, 95), 100)

    def test_84_carga_a_visualizacion_p95_menor_a_3_s(self):
        times = []
        for i in range(100):
            t = time.perf_counter()
            case = Case(SAMPLE, f"FLUJO{i}"); case.quality(True)
            run = case.infer(self.det)
            draw_detections(case.image, run["original"])
            times.append((time.perf_counter() - t) * 1000)
        RESULTS["carga_a_visualizacion"] = stats(times)
        self.assertLessEqual(percentile(times, 95), 3000)

    def test_85_generacion_de_informe_p95_menor_a_1_s(self):
        case = Case(SAMPLE, "INFORME"); case.quality(True); run = case.infer(self.det); case.review("aceptar", "qa_user")
        annotated = draw_detections(case.image, run["original"])
        archive = CaseArchive(Path(tempfile.mkdtemp()) / "casos")
        times = []
        for _ in range(20):
            t = time.perf_counter()
            report = build_report(case, "qa.user", PERFIL)
            report_csv(report); report_pdf(report, annotated); archive.save(case, report, annotated)
            times.append((time.perf_counter() - t) * 1000)
        RESULTS["informe_y_guardado"] = stats(times)
        self.assertLessEqual(percentile(times, 95), 1000)

    def test_86_inicio_de_sesion_seguro_y_usable(self):
        store = UserStore(Path(tempfile.mkdtemp()) / "u.json")
        store.create_user("perf", PASSWORD, "usuario", must_change=False)
        times = []
        for _ in range(10):
            t = time.perf_counter(); store.authenticate("perf", PASSWORD); times.append((time.perf_counter() - t) * 1000)
        RESULTS["inicio_de_sesion"] = stats(times)
        # >= 100 ms encarece la fuerza bruta; <= 2 s mantiene el acceso ágil
        self.assertGreaterEqual(percentile(times, 50), 100)
        self.assertLessEqual(percentile(times, 95), 2000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
