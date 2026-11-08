"""Pruebas FUNCIONALES 102-113 de las funciones que completan el MVP: evaluación congelada (RF09),
lote desidentificado (RF02), concordancia (I09), respaldo/restauración (RNF07) y corrección (RF07)."""
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from PIL import Image, PngImagePlugin

import core
import datos
import evaluacion as ev
from auth import UserStore
from core import Case, ProductError
from pruebas.apoyo import PASSWORD, SAMPLE, real_detector

CLASSES = list(core.LABELS)


def B(img, cls, x1, y1, x2, y2, conf=1.0):
    return ev.Box(img, cls, x1, y1, x2, y2, conf)


class Sprint3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # ── RF09 evaluación ──
    def test_102_metricas_con_resultado_conocido(self):
        gts = [B("a", "Stage 1", 0, 0, 10, 10), B("a", "Stage 2", 20, 20, 30, 30), B("b", "Stage 1", 0, 0, 10, 10)]
        preds = [B("a", "Stage 1", 0, 0, 10, 10, .9),     # VP Stage 1
                 B("a", "Stage 2", 50, 50, 60, 60, .8),   # FP Stage 2 (no se superpone)
                 B("b", "Stage 2", 0, 0, 10, 10, .7)]     # clase equivocada: FP Stage 2 y FN Stage 1
        m = ev.compute_metrics(preds, gts, CLASSES, .25)
        s1, s2 = m["por_clase"]["Stage 1"], m["por_clase"]["Stage 2"]
        self.assertEqual((s1["VP"], s1["FP"], s1["FN"]), (1, 0, 1))
        self.assertEqual((s2["VP"], s2["FP"], s2["FN"]), (0, 2, 1))
        self.assertAlmostEqual(m["global"]["precision_micro"], 1 / 3)
        self.assertAlmostEqual(m["global"]["sensibilidad_micro"], 1 / 3)
        self.assertEqual(m["matriz_confusion"]["Stage 1"]["Stage 2"], 1)  # confusión registrada
        self.assertEqual(m["matriz_confusion"]["Fondo"]["Stage 2"], 1)
        self.assertEqual(m["stage1"]["VP"], 1); self.assertEqual(m["stage1"]["FN"], 1)

    def test_103_ap_y_map_perfectos_y_denominador_cero(self):
        gts = [B("a", "Stage 3", 0, 0, 10, 10)]
        m = ev.compute_metrics([B("a", "Stage 3", 0, 0, 10, 10, .9)], gts, CLASSES, .25)
        self.assertAlmostEqual(m["por_clase"]["Stage 3"]["ap50"], 1.0)
        self.assertAlmostEqual(m["global"]["map50_95"], 1.0)
        self.assertIsNone(m["por_clase"]["Normal"]["sensibilidad"])  # sin soporte: no calculable
        self.assertIsNone(m["por_clase"]["Normal"]["ap50"])

    def test_104_iou_y_etiquetas_yolo(self):
        self.assertAlmostEqual(ev.iou(B("a", "x", 0, 0, 10, 10), B("a", "x", 5, 0, 15, 10)), 1 / 3)
        boxes = ev.yolo_labels("1 0.5 0.5 0.2 0.4\n", (100, 50), "img", CLASSES)
        self.assertEqual((boxes[0].cls, boxes[0].x1, boxes[0].y1, boxes[0].x2, boxes[0].y2), ("Stage 1", 40, 15, 60, 35))
        for bad in ("9 0.5 0.5 0.1 0.1", "1 1.5 0.5 0.1 0.1", "1 0.5 0.5"):
            with self.assertRaises(ProductError):
                ev.yolo_labels(bad, (100, 100), "img", CLASSES)

    def test_105_CA09_recalculo_desde_predicciones_guardadas(self):
        det = real_detector()
        img = Image.open(SAMPLE).convert("RGB")
        found, _ = det.predict(img)
        lines = []
        for d in found:  # referencia sintética: las mismas cajas, para un lote reproducible
            x1, y1, x2, y2 = d["box"]; w, h = img.size
            lines.append(f"{CLASSES.index(d['class'])} {(x1 + x2) / 2 / w} {(y1 + y2) / 2 / h} {(x2 - x1) / w} {(y2 - y1) / h}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.write(SAMPLE, "test/images/r1.jpg"); zf.writestr("test/labels/r1.txt", "\n".join(lines))
        items = ev.read_test_zip(buf.getvalue(), CLASSES)
        preds = ev.predict_items(det, items)
        gts = [g for _, _, gs in items for g in gs]
        first = ev.compute_metrics(preds, gts, CLASSES, det.conf)
        saved_preds, saved_gts = ev.read_predictions_csv(ev.predictions_csv(preds, gts))
        again = ev.compute_metrics(saved_preds, saved_gts, CLASSES, det.conf)
        for key in ("precision_micro", "sensibilidad_micro", "map50", "map50_95"):
            self.assertLessEqual(abs(first["global"][key] - again["global"][key]) * 100, 0.1)  # <= 0.1 pp
        self.assertAlmostEqual(first["global"]["sensibilidad_micro"], 1.0)

    def test_106_zip_de_prueba_inseguro_rechazado(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../fuera.png", b"x")
        with self.assertRaises(ProductError):
            ev.read_test_zip(buf.getvalue(), CLASSES)
        with self.assertRaises(ProductError):
            ev.read_test_zip(b"no es zip", CLASSES)

    # ── RF02 lote desidentificado ──
    def test_107_lote_sin_metadatos_y_con_nombres_codificados(self):
        meta = PngImagePlugin.PngInfo(); meta.add_text("Paciente", "Juan Perez")
        a = io.BytesIO(); Image.new("RGB", (40, 30), "gray").save(a, format="PNG", pnginfo=meta)
        b = io.BytesIO(); exif = Image.Exif(); exif[0x010E] = "Juan Perez DNI 12345678"
        Image.new("RGB", (40, 30)).save(b, format="JPEG", exif=exif)
        self.assertTrue(datos.has_metadata(a.getvalue())); self.assertTrue(datos.has_metadata(b.getvalue()))
        zip_bytes, manifest, mapping = datos.deidentify_batch(
            [("juan_perez.png", a.getvalue()), ("juan_perez_2.jpg", b.getvalue())], "LOTE01", {"juan_perez.png": "P001"})
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        self.assertEqual(sorted(zf.namelist()), ["LEEME.txt", "LOTE01_0001.png", "LOTE01_0002.png", "manifiesto.csv"])
        for name in ("LOTE01_0001.png", "LOTE01_0002.png"):
            self.assertFalse(datos.has_metadata(zf.read(name)), name)
        self.assertNotIn(b"Juan", zf.read("manifiesto.csv"))
        self.assertEqual(manifest[0]["patient_code"], "P001")
        self.assertIn(b"juan_perez.png", mapping)  # la correspondencia va aparte, solo al custodio

    def test_108_manifiesto_del_lote_pasa_la_auditoria(self):
        img = io.BytesIO(); Image.new("L", (20, 20)).save(img, format="PNG")
        img2 = io.BytesIO(); Image.new("L", (20, 20), 255).save(img2, format="PNG")
        _, manifest, _ = datos.deidentify_batch([("a.png", img.getvalue()), ("b.png", img2.getvalue())], "L2")
        path = self.root / "m.csv"
        import csv
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(manifest[0])); w.writeheader()
            for row, (pat, sub) in zip(manifest, (("P1", "train"), ("P2", "test"))):
                w.writerow({**row, "patient_code": pat, "subset": sub})
        self.assertTrue(core.audit_manifest(path)["structural_check_passed"])

    # ── I09 concordancia ──
    def test_109_kappa_ponderado(self):
        perfect = [("Normal", "Normal"), ("Stage 1", "Stage 1"), ("Stage 2", "Stage 2"), ("Stage 3", "Stage 3")]
        self.assertAlmostEqual(datos.weighted_kappa(perfect), 1.0)
        near = [("Stage 1", "Stage 2"), ("Stage 2", "Stage 2"), ("Normal", "Normal"), ("Stage 3", "Stage 3")]
        far = [("Normal", "Stage 3"), ("Stage 2", "Stage 2"), ("Normal", "Normal"), ("Stage 3", "Stage 3")]
        self.assertGreater(datos.weighted_kappa(near), datos.weighted_kappa(far))  # castiga más el desacuerdo lejano
        self.assertIsNone(datos.weighted_kappa([]))
        with self.assertRaises(ProductError):
            datos.weighted_kappa([("Normal", "Grave")])

    # ── RNF07 respaldo ──
    def test_110_respaldo_y_restauracion_con_huellas(self):
        data_dir = self.root / "datos"
        store = UserStore(data_dir / "usuarios.json")
        store.create_user("ana", PASSWORD, "usuario", must_change=False)
        (data_dir / "casos" / "C1").mkdir(parents=True); (data_dir / "casos" / "C1" / "informe.json").write_text('{"x":1}')
        backup, manifest = datos.create_backup(data_dir)
        self.assertEqual(set(manifest["archivos"]), {"usuarios.json", "auditoria.jsonl", "casos/C1/informe.json"})
        (data_dir / "usuarios.json").write_text("{}")  # pérdida simulada
        (data_dir / "casos" / "C1" / "informe.json").unlink()
        report = datos.restore_backup(backup, data_dir)
        self.assertTrue(report["verificado"]); self.assertEqual(report["archivos"], 3)
        self.assertLess(report["segundos"], 4 * 3600)  # RNF07: restauración <= 4 h
        self.assertEqual(store.authenticate("ana", PASSWORD)["usuario"], "ana")

    def test_111_respaldo_alterado_se_rechaza_sin_tocar_datos(self):
        data_dir = self.root / "datos"; data_dir.mkdir()
        (data_dir / "config.json").write_text('{"conf": 0.25}')
        backup, _ = datos.create_backup(data_dir)
        zin = zipfile.ZipFile(io.BytesIO(backup)); out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for name in zin.namelist():
                zf.writestr(name, b'{"conf": 0.99}' if name.endswith("config.json") else zin.read(name))
        (data_dir / "config.json").write_text('{"conf": 0.30}')
        with self.assertRaisesRegex(ProductError, "Huella distinta"):
            datos.restore_backup(out.getvalue(), data_dir)
        self.assertEqual(json.loads((data_dir / "config.json").read_text())["conf"], 0.30)

    def test_112_respaldo_diario_automatico_conserva_siete(self):
        data_dir = self.root / "datos"; data_dir.mkdir(); (data_dir / "config.json").write_text("{}")
        self.assertIsNotNone(datos.auto_backup(data_dir))
        self.assertIsNone(datos.auto_backup(data_dir))  # ya hay uno de hoy
        folder = data_dir / "respaldos_datos"
        for i in range(9):
            (folder / f"respaldo_2026010{i}_000000.zip").write_bytes(b"x")
        old = time.time() - 2 * 86400
        import os
        for p in folder.iterdir():
            os.utime(p, (old, old))
        datos.auto_backup(data_dir)
        self.assertEqual(len(list(folder.glob("respaldo_*.zip"))), 7)

    # ── RF07 corrección ──
    def test_113_correccion_conserva_original_y_valida_cajas(self):
        case = Case(SAMPLE, "CORR01"); case.quality(True); run = case.infer(real_detector())
        original = json.dumps(run["original"])
        fixed = [{**run["original"][0], "class": "Stage 3", "box": [10.0, 10.0, 200.0, 200.0]}]
        review = case.review("corregir", "qa_user", fixed)
        self.assertEqual(review["revised"][0]["class"], "Stage 3")
        self.assertEqual(json.dumps(case.data["runs"][-1]["original"]), original)  # la propuesta no cambia
        with self.assertRaises(ProductError):
            case.review("corregir", "qa_user", [{**fixed[0], "box": [10, 10, 5000, 200]}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
