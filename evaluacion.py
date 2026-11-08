"""Evaluación del detector sobre una prueba congelada (HU07 / RF09 / RNF06).

Protocolo del informe (3.7): unidad = región anotada, emparejamiento uno a uno por clase con
IoU >= 0.5; predicciones sobrantes = FP, referencias sin pareja = FN. Se informan P, R, F1 por
clase y globales (micro y macro), AP@0.5 y mAP@0.5:0.95 (interpolación de todos los puntos),
matriz de confusión, soporte y el intervalo de Wilson para la sensibilidad de Stage 1 (I03).
Las métricas se recalculan desde predicciones guardadas (CA09: diferencia <= 0.1 pp).
"""
from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import core

IMAGE_EXT = (".png", ".jpg", ".jpeg")
IOU_THRESHOLDS = [round(0.5 + 0.05 * i, 2) for i in range(10)]
BACKGROUND = "Fondo"


@dataclass(frozen=True)
class Box:
    image: str
    cls: str
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float = 1.0


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0 else 0.0


def yolo_labels(text: str, size: tuple[int, int], image: str, names: list[str]) -> list[Box]:
    """Lee etiquetas YOLO (clase cx cy w h normalizados) y las pasa a píxeles."""
    w, h = size
    boxes = []
    for n, line in enumerate(text.splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 5:
            raise core.ProductError(f"{image}: línea {n} de etiquetas inválida.")
        k, cx, cy, bw, bh = int(float(parts[0])), *(float(v) for v in parts[1:])
        if not 0 <= k < len(names) or not all(0 <= v <= 1 for v in (cx, cy, bw, bh)):
            raise core.ProductError(f"{image}: línea {n} fuera de rango o con clase desconocida.")
        boxes.append(Box(image, names[k], (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
    return boxes


def _match(preds: list[Box], gts: list[Box], threshold: float, same_class: bool = True):
    """Empareja por confianza descendente con la referencia libre de mayor IoU."""
    used: set[int] = set()
    pairs, unmatched = [], []
    for p in sorted(preds, key=lambda b: -b.conf):
        best, best_iou = None, threshold
        for i, g in enumerate(gts):
            if i in used or g.image != p.image or (same_class and g.cls != p.cls):
                continue
            v = iou(p, g)
            if v >= best_iou:
                best, best_iou = i, v
        if best is None:
            unmatched.append(p)
        else:
            used.add(best); pairs.append((p, gts[best]))
    missed = [g for i, g in enumerate(gts) if i not in used]
    return pairs, unmatched, missed


def average_precision(preds: list[Box], gts: list[Box], threshold: float) -> float | None:
    """AP con interpolación de todos los puntos para UNA clase; None si no hay soporte."""
    if not gts:
        return None
    ordered = sorted(preds, key=lambda b: -b.conf)
    used: set[int] = set()
    tp = []
    for p in ordered:
        best, best_iou = None, threshold
        for i, g in enumerate(gts):
            if i not in used and g.image == p.image:
                v = iou(p, g)
                if v >= best_iou:
                    best, best_iou = i, v
        tp.append(best is not None)
        if best is not None:
            used.add(best)
    recalls, precisions, hits = [0.0], [1.0], 0
    for k, hit in enumerate(tp, 1):
        hits += hit
        recalls.append(hits / len(gts)); precisions.append(hits / k)
    for i in range(len(precisions) - 2, -1, -1):  # envolvente monótona
        precisions[i] = max(precisions[i], precisions[i + 1])
    return sum((recalls[i] - recalls[i - 1]) * precisions[i] for i in range(1, len(recalls)))


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    if total == 0:
        return None
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centre - half), min(1.0, centre + half)


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def compute_metrics(preds: list[Box], gts: list[Box], classes: list[str], conf_threshold: float) -> dict:
    """Métricas del protocolo. `preds` ya filtradas por el umbral congelado."""
    per_class, aps50, tp_all, fp_all, fn_all = {}, {}, 0, 0, 0
    for c in classes:
        pc = [p for p in preds if p.cls == c]
        gc = [g for g in gts if g.cls == c]
        pairs, fps, fns = _match(pc, gc, 0.5)
        tp, fp, fn = len(pairs), len(fps), len(fns)
        tp_all += tp; fp_all += fp; fn_all += fn
        p, r = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        f1 = 2 * p * r / (p + r) if p is not None and r is not None and p + r else (0.0 if p is not None and r is not None else None)
        ap_t = [average_precision(pc, gc, t) for t in IOU_THRESHOLDS]
        aps50[c] = ap_t[0]
        per_class[c] = {"soporte": len(gc), "predicciones": len(pc), "VP": tp, "FP": fp, "FN": fn,
                        "precision": p, "sensibilidad": r, "f1": f1, "ap50": ap_t[0],
                        "ap50_95": None if ap_t[0] is None else sum(ap_t) / len(ap_t)}
    supported = [c for c in classes if per_class[c]["soporte"]]
    micro_p, micro_r = _ratio(tp_all, tp_all + fp_all), _ratio(tp_all, tp_all + fn_all)
    mean = lambda key: (sum(per_class[c][key] or 0 for c in supported) / len(supported)) if supported else None
    s1 = per_class.get("Stage 1", {})
    # Matriz de confusión: emparejamiento por IoU >= 0.5 sin mirar la clase.
    labels = classes + [BACKGROUND]
    matrix = {g: {p: 0 for p in labels} for g in labels}
    pairs, fps, fns = _match(preds, gts, 0.5, same_class=False)
    for p, g in pairs:
        matrix[g.cls][p.cls] += 1
    for p in fps:
        matrix[BACKGROUND][p.cls] += 1
    for g in fns:
        matrix[g.cls][BACKGROUND] += 1
    return {
        "unidad": "región anotada; emparejamiento uno a uno por clase con IoU >= 0.5",
        "umbral_confianza": conf_threshold, "imagenes": len({b.image for b in gts} | {b.image for b in preds}),
        "regiones_referencia": len(gts), "predicciones": len(preds),
        "por_clase": per_class,
        "global": {"precision_micro": micro_p, "sensibilidad_micro": micro_r,
                   "f1_micro": (2 * micro_p * micro_r / (micro_p + micro_r)) if micro_p and micro_r else 0.0 if micro_p is not None and micro_r is not None else None,
                   "precision_macro": mean("precision"), "sensibilidad_macro": mean("sensibilidad"),
                   "map50": mean("ap50"), "map50_95": mean("ap50_95")},
        "stage1": {"VP": s1.get("VP", 0), "FN": s1.get("FN", 0), "sensibilidad": s1.get("sensibilidad"),
                   "ic95_wilson": wilson(s1.get("VP", 0), s1.get("VP", 0) + s1.get("FN", 0))},
        "matriz_confusion": matrix,
        "nota": "AP con interpolación de todos los puntos (puede diferir levemente de Ultralytics, que usa 101 puntos).",
    }


# ─────────────────────────────── lectura del lote ───────────────────────────────
def read_test_zip(data: bytes, names: list[str]) -> list[tuple[str, "core.Image.Image", list[Box]]]:
    """Abre un .zip con imágenes y etiquetas YOLO (images/ y labels/, en cualquier subcarpeta)."""
    from PIL import Image
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise core.ProductError("El archivo no es un .zip válido.") from e
    files = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if ".." in path.parts or path.is_absolute():
            raise core.ProductError("El .zip contiene rutas no permitidas.")
        if info.file_size > core.MAX_BYTES:
            raise core.ProductError(f"{path.name} supera 20 MB.")
        files[path] = info
    images = {p.stem: p for p in files if p.suffix.lower() in IMAGE_EXT}
    labels = {p.stem: p for p in files if p.suffix.lower() == ".txt"}
    if not images:
        raise core.ProductError("El .zip no contiene imágenes PNG/JPEG.")
    items = []
    for stem in sorted(images):
        with zf.open(files[images[stem]]) as f:
            img = Image.open(io.BytesIO(f.read()))
            if img.width * img.height > core.MAX_PIXELS:
                raise core.ProductError(f"{stem}: supera el límite de píxeles.")
            img = img.convert("RGB")
        text = zf.read(files[labels[stem]]).decode("utf-8") if stem in labels else ""
        items.append((stem, img, yolo_labels(text, img.size, stem, names)))
    return items


def predict_items(det, items) -> list[Box]:
    preds = []
    for stem, img, _ in items:
        found, _ = det.predict(img)
        for d in core.check_detections(found, img.size):
            preds.append(Box(stem, d["class"], *d["box"], conf=d["confidence"]))
    return preds


def predictions_csv(preds: list[Box], gts: list[Box]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["tipo", "imagen", "clase", "confianza", "x1", "y1", "x2", "y2"])
    for kind, rows in (("prediccion", preds), ("referencia", gts)):
        for b in rows:
            w.writerow([kind, b.image, b.cls, f"{b.conf:.6f}", f"{b.x1:.3f}", f"{b.y1:.3f}", f"{b.x2:.3f}", f"{b.y2:.3f}"])
    return out.getvalue().encode("utf-8")


def read_predictions_csv(data: bytes) -> tuple[list[Box], list[Box]]:
    preds, gts = [], []
    try:
        for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
            box = Box(row["imagen"], row["clase"], float(row["x1"]), float(row["y1"]), float(row["x2"]),
                      float(row["y2"]), float(row["confianza"]))
            (preds if row["tipo"] == "prediccion" else gts).append(box)
    except (KeyError, ValueError) as e:
        raise core.ProductError("CSV de predicciones inválido: faltan columnas o hay números no válidos.") from e
    return preds, gts


def metrics_json(metrics: dict) -> bytes:
    return json.dumps(metrics, ensure_ascii=False, indent=2).encode("utf-8")
