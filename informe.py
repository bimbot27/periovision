"""Informes legibles (JSON, CSV y PDF) e historial de casos validados de PerioVision.

core.export() conserva el registro técnico completo (pruebas 16-17). Este módulo arma
la versión para personas: textos en español, porcentajes, ubicación aproximada de cada
hallazgo y el profesional que analizó y validó el caso.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import core

DESCRIPTIONS = {
    "Normal": "Sin signos de pérdida ósea periodontal",
    "Stage 1": "Periodontitis estadio I (inicial)",
    "Stage 2": "Periodontitis estadio II (moderada)",
    "Stage 3": "Periodontitis estadio III (severa)",
    "DEMO": "Figura de demostración (sin valor clínico)",
}
RESULTS = {"aceptar": "Aprobada", "descartar": "Rechazada", "corregir": "Aprobada con correcciones"}
CODE_RE = re.compile(r"[A-Za-z0-9_-]{2,40}")


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")


def location(box: list[float], size: tuple[int, int]) -> str:
    """Ubicación aproximada del centro del cuadro en una cuadrícula de 3 × 3."""
    cx, cy = (box[0] + box[2]) / 2 / size[0], (box[1] + box[3]) / 2 / size[1]
    row = "superior" if cy < 1 / 3 else ("media" if cy < 2 / 3 else "inferior")
    col = "izquierda" if cx < 1 / 3 else ("central" if cx < 2 / 3 else "derecha")
    return "zona central" if (row, col) == ("media", "central") else f"zona {row} {col}"


def build_report(case: core.Case, username: str, profile: dict, observations: str = "") -> dict:
    snap = case.snapshot()
    if not snap["runs"] or not snap["reviews"]:
        raise core.ProductError("El caso necesita un análisis y una revisión registrada.")
    run, review = snap["runs"][-1], snap["reviews"][-1]
    if review["run_id"] != run["run_id"]:
        raise core.ProductError("La revisión no corresponde al último análisis.")
    size = tuple(snap["size"])
    corrected = review["action"] == "corregir"
    items = review["revised"] if corrected else run["original"]  # lo que el profesional confirmó
    findings = [{
        "n": n, "clase": i["class"], "descripcion": DESCRIPTIONS.get(i["class"], i["class"]),
        "confianza": f"{i['confidence'] * 100:.1f} %", "ubicacion": location(i["box"], size),
        "region_px": f"x {i['box'][0]:.0f}–{i['box'][2]:.0f} · y {i['box'][1]:.0f}–{i['box'][3]:.0f}",
    } for n, i in enumerate(items, 1)]
    counts: dict[str, int] = {}
    for i in items:
        counts[i["class"]] = counts.get(i["class"], 0) + 1
    if items:
        top = max(items, key=lambda i: i["confidence"])
        summary = (f"{len(items)} hallazgo(s): " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
                   + f". Mayor confianza: {top['class']} ({top['confidence']:.0%}).")
    else:
        summary = "El modelo no propuso hallazgos sobre el umbral configurado."
    if corrected:
        summary += f" Corregido por el profesional a partir de {len(run['original'])} propuesta(s) del modelo."
    name = f"{profile.get('nombres', '')} {profile.get('apellidos', '')}".strip() or username
    model = run["model"]
    return {
        "titulo": "Informe de análisis radiográfico periodontal",
        "codigo_caso": snap["case_code"],
        "resultado_validacion": RESULTS.get(review["action"], review["action"]),
        "fecha_analisis": _local(run["utc"]),
        "fecha_validacion": _local(review["utc"]),
        "profesional": {"nombre": name, "cop": profile.get("cop") or "—",
                        "especialidad": profile.get("especialidad") or "—", "usuario": username},
        "resumen": summary,
        "hallazgos": findings,
        "observaciones": observations.strip() or "Sin observaciones.",
        "imagen": {"dimensiones": f"{size[0]} × {size[1]} px", "huella_sha256": snap["input_sha256"]},
        "parametros": {"umbral_confianza": f"{model.get('confidence_threshold', 0) * 100:.0f} %",
                       "tamano_analisis": f"{model.get('imgsz', '—')} px",
                       "tiempo_analisis": f"{run['elapsed_adapter_ms'] / 1000:.2f} s",
                       "version_aplicacion": core.VERSION,
                       "huella_modelo": model.get("weights_sha256") or "demostración"},
        "aviso": core.NOTICE + " La validación registrada no reemplaza el diagnóstico clínico.",
    }


def build_unevaluable_report(case: core.Case, username: str, profile: dict, reason: str) -> dict:
    """Registro de una imagen marcada como no evaluable (RF05): sin inferencia."""
    if case.data["evaluable"] is not False:
        raise core.ProductError("Primero marca la imagen como no evaluable.")
    if not reason.strip():
        raise core.ProductError("Indica el motivo por el que la imagen no es evaluable.")
    snap = case.snapshot()
    now = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    name = f"{profile.get('nombres', '')} {profile.get('apellidos', '')}".strip() or username
    size = snap["size"]
    return {
        "titulo": "Registro de imagen no evaluable",
        "codigo_caso": snap["case_code"], "resultado_validacion": "No evaluable",
        "fecha_analisis": "Sin análisis", "fecha_validacion": now,
        "profesional": {"nombre": name, "cop": profile.get("cop") or "—",
                        "especialidad": profile.get("especialidad") or "—", "usuario": username},
        "resumen": "La imagen se registró como no evaluable y no se ejecutó el modelo.",
        "hallazgos": [], "observaciones": reason.strip(),
        "imagen": {"dimensiones": f"{size[0]} × {size[1]} px", "huella_sha256": snap["input_sha256"]},
        "parametros": {"umbral_confianza": "—", "tamano_analisis": "—", "tiempo_analisis": "—",
                       "version_aplicacion": core.VERSION, "huella_modelo": "—"},
        "aviso": core.NOTICE + " Se recomienda repetir la toma.",
    }


def report_json(report: dict) -> bytes:
    return json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")


class _SafeWriter:
    """Escritor CSV que neutraliza celdas que Excel interpretaría como fórmula (OWASP CSV injection)."""

    def __init__(self, out):
        self._w = csv.writer(out)

    @staticmethod
    def _cell(value) -> str:
        text = str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

    def writerow(self, row):
        self._w.writerow([self._cell(v) for v in row])


def report_csv(report: dict) -> bytes:
    """Bloque de datos del caso y, debajo, la tabla de hallazgos. Se abre directo en Excel."""
    out = io.StringIO()
    w = _SafeWriter(out)
    p = report["profesional"]
    w.writerow([report["titulo"]])
    for k, v in (("Código de caso", report["codigo_caso"]), ("Resultado de la validación", report["resultado_validacion"]),
                 ("Fecha de análisis", report["fecha_analisis"]), ("Fecha de validación", report["fecha_validacion"]),
                 ("Analizado y validado por", p["nombre"]), ("N.º COP", p["cop"]), ("Especialidad", p["especialidad"]),
                 ("Resumen", report["resumen"]), ("Observaciones", report["observaciones"]),
                 ("Umbral de confianza", report["parametros"]["umbral_confianza"]),
                 ("Versión", report["parametros"]["version_aplicacion"])):
        w.writerow([k, v])
    w.writerow([])
    w.writerow(["N.º", "Clase", "Descripción", "Confianza", "Ubicación aproximada", "Región (px)"])
    for f in report["hallazgos"]:
        w.writerow([f["n"], f["clase"], f["descripcion"], f["confianza"], f["ubicacion"], f["region_px"]])
    if not report["hallazgos"]:
        w.writerow(["—", "Sin hallazgos", report["resumen"], "", "", ""])
    w.writerow([])
    w.writerow(["Aviso", report["aviso"]])
    return out.getvalue().encode("utf-8-sig")


# ─────────────────────────────── PDF ───────────────────────────────
def _font(bold: bool, size: int):
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(str(fonts / name), size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=font) <= width:
            line = test
        else:
            lines.append(line); line = word
    return lines + [line] if line else lines


def report_pdf(report: dict, annotated: Image.Image) -> bytes:
    """Informe de una página A4 (150 ppp) generado con Pillow, sin dependencias extra."""
    W, H, M = 1240, 1754, 90
    page = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(page)
    ink, grey, blue, line = "#1D1D1F", "#6E6E73", "#0071E3", "#D2D2D7"
    f_title, f_h, f_b, f_s = _font(True, 40), _font(True, 24), _font(False, 22), _font(False, 18)
    y = M
    d.rounded_rectangle((M, y, M + 64, y + 64), 14, fill=blue)
    d.text((M + 32, y + 32), "PV", font=_font(True, 26), fill="white", anchor="mm")
    d.text((M + 84, y + 2), "PerioVision", font=f_h, fill=ink)
    d.text((M + 84, y + 34), report["titulo"], font=f_s, fill=grey)
    result = report["resultado_validacion"]
    color = "#1B7A34" if result.startswith("Aprobada") else ("#6E6E73" if result == "No evaluable" else "#D70015")
    tag = report["resultado_validacion"]
    tw = d.textlength(tag, font=f_h) + 40
    d.rounded_rectangle((W - M - tw, y + 12, W - M, y + 54), 21, fill=color)
    d.text((W - M - tw / 2, y + 33), tag, font=f_h, fill="white", anchor="mm")
    y += 100
    d.text((M, y), f"Caso {report['codigo_caso']}", font=f_title, fill=ink)
    y += 64
    p = report["profesional"]
    meta = [("Analizado y validado por", p["nombre"]), ("N.º COP", p["cop"]), ("Especialidad", p["especialidad"]),
            ("Fecha de análisis", report["fecha_analisis"]), ("Fecha de validación", report["fecha_validacion"]),
            ("Imagen", report["imagen"]["dimensiones"])]
    col = (W - 2 * M) // 3
    for i, (k, v) in enumerate(meta):
        x, yy = M + (i % 3) * col, y + (i // 3) * 64
        d.text((x, yy), k, font=f_s, fill=grey)
        d.text((x, yy + 24), str(v), font=f_b, fill=ink)
    y += 140
    d.line((M, y, W - M, y), fill=line, width=2); y += 24
    img = annotated.copy()
    img.thumbnail((W - 2 * M, 560))
    page.paste(img, ((W - img.width) // 2, y)); y += img.height + 30
    d.text((M, y), "Resumen", font=f_h, fill=ink); y += 36
    for line_ in _wrap(d, report["resumen"], f_b, W - 2 * M):
        d.text((M, y), line_, font=f_b, fill=ink); y += 30
    y += 16
    cols = [("N.º", 60), ("Clase", 130), ("Descripción", 400), ("Confianza", 130), ("Ubicación", 340)]
    d.rounded_rectangle((M, y, W - M, y + 40), 8, fill="#F2F2F7")
    x = M + 14
    for name, wdt in cols:
        d.text((x, y + 9), name, font=_font(True, 19), fill=grey); x += wdt
    y += 48
    rows = report["hallazgos"] or [{"n": "—", "clase": "—", "descripcion": "Sin hallazgos", "confianza": "", "ubicacion": ""}]
    for f in rows[:10]:
        x = M + 14
        for (key, wdt) in zip(("n", "clase", "descripcion", "confianza", "ubicacion"), [c[1] for c in cols], strict=True):
            d.text((x, y), str(f[key]), font=f_s, fill=ink); x += wdt
        y += 32
        d.line((M, y - 4, W - M, y - 4), fill=line)
    if len(rows) > 10:
        d.text((M, y), f"… y {len(rows) - 10} hallazgo(s) más en el CSV.", font=f_s, fill=grey); y += 30
    y += 18
    d.text((M, y), "Observaciones del profesional", font=f_h, fill=ink); y += 36
    for line_ in _wrap(d, report["observaciones"], f_b, W - 2 * M)[:6]:
        d.text((M, y), line_, font=f_b, fill=ink); y += 30
    # Pie: firma y aviso
    fy = H - M - 170
    d.line((M, fy, M + 420, fy), fill=ink, width=2)
    d.text((M, fy + 10), p["nombre"], font=f_b, fill=ink)
    d.text((M, fy + 40), f"COP {p['cop']}", font=f_s, fill=grey)
    par = report["parametros"]
    d.text((W - M, fy + 10), f"Umbral {par['umbral_confianza']} · {par['tamano_analisis']} · {par['version_aplicacion']}",
           font=f_s, fill=grey, anchor="ra")
    ay = fy + 90
    for line_ in _wrap(d, report["aviso"], f_s, W - 2 * M):
        d.text((M, ay), line_, font=f_s, fill=grey); ay += 24
    buf = io.BytesIO()
    page.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue()


# ─────────────────────────────── historial ───────────────────────────────
class CaseArchive:
    """Guarda cada caso validado en datos/casos/<código>/ para poder reconsultarlo."""

    FILES = {"pdf": ("informe.pdf", "application/pdf"), "json": ("informe.json", "application/json"),
             "csv": ("informe.csv", "text/csv")}

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def folder(self, code: str) -> Path:
        if not CODE_RE.fullmatch(code):
            raise core.ProductError("Código de caso inválido.")
        return self.root / code

    def save(self, case: core.Case, report: dict, annotated: Image.Image) -> Path:
        folder = self.folder(report["codigo_caso"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "informe.json").write_bytes(report_json(report))
        (folder / "informe.csv").write_bytes(report_csv(report))
        (folder / "informe.pdf").write_bytes(report_pdf(report, annotated))
        annotated.save(folder / "anotada.png")
        (folder / "registro_tecnico.json").write_text(
            json.dumps(case.snapshot(), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        return folder

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        items = []
        for f in self.root.glob("*/informe.json"):
            try:
                items.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        key = lambda r: datetime.strptime(r["fecha_validacion"], "%d/%m/%Y %H:%M")
        return sorted(items, key=key, reverse=True)

    def file(self, code: str, kind: str) -> tuple[bytes, str, str]:
        name, mime = self.FILES[kind]
        return (self.folder(code) / name).read_bytes(), f"{code}_{name}", mime

    def image(self, code: str) -> Path:
        return self.folder(code) / "anotada.png"

    def size_mb(self) -> float:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file()) / 1e6 if self.root.exists() else 0.0

    def delete(self, code: str) -> None:
        shutil.rmtree(self.folder(code), ignore_errors=True)
