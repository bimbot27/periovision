"""Ejecuta las pruebas QA del Sprint 2 (01-30) y las pruebas de seguridad (31+).

Genera un log por prueba en evidencias/:
  log_pruebas_QA_<etiqueta>_<fecha>.txt   (legible)
  log_pruebas_QA_<etiqueta>_<fecha>.json  (estructurado, con SHA-256 de los módulos)

Uso:  .venv\\Scripts\\python.exe ejecutar_pruebas_qa.py [etiqueta]
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
import time
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "pruebas"
EVIDENCE = ROOT / "evidencias"
sys.path.insert(0, str(ROOT))

GROUPS = [
    (1, 6, "Carga y calidad"),
    (7, 11, "DEMO y bloqueos"),
    (12, 15, "Revisión"),
    (16, 19, "Exportación y datos de entrada"),
    (20, 23, "Partición estructural"),
    (24, 24, "Sin detecciones"),
    (25, 30, "Lectura de métricas"),
    (31, 40, "Seguridad e inicio de sesión (adicional)"),
    (41, 44, "Perfil, informes e historial (adicional)"),
    (45, 56, "Unitarias"),
    (57, 62, "Integración"),
    (63, 70, "Sistema"),
    (71, 78, "Aceptación"),
    (79, 82, "Humo"),
    (83, 86, "Rendimiento"),
    (87, 94, "Seguridad de la aplicación"),
    (95, 100, "Usabilidad y accesibilidad"),
    (101, 101, "Seguridad de la aplicación"),
    (102, 113, "Funciones que completan el MVP"),
    (114, 199, "Sistema (funciones del MVP)"),
]

# Tipo de prueba por archivo (las documentadas 01-30 forman la batería de regresión).
TYPES = {
    "test_producto": "Regresión", "test_metrics": "Regresión",
    "test_seguridad": "Seguridad", "test_informes": "Funcional (perfil e informes)",
    "test_unitarias": "Unitaria", "test_integracion": "Integración", "test_sistema": "Sistema",
    "test_aceptacion": "Aceptación", "test_humo": "Humo", "test_rendimiento": "Rendimiento",
    "test_seguridad_app": "Seguridad", "test_usabilidad": "Usabilidad",
    "test_sprint3": "Funcional (MVP completo)", "test_sistema_mvp": "Sistema",
}


def group_of(number: int) -> str:
    return next((name for lo, hi, name in GROUPS if lo <= number <= hi), "Otro")


def version(pkg: str) -> str | None:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return None


class LoggingResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.records: list[dict] = []
        self._start = 0.0

    def startTest(self, test):
        super().startTest(test)
        self._start = time.perf_counter()

    def _add(self, test, status, detail=""):
        parts = test.id().split(".")
        name, module = parts[-1], (parts[1] if len(parts) > 2 else "")
        try:
            number = int(name.split("_")[1])
        except (IndexError, ValueError):
            number = 0
        self.records.append({
            "id": f"{number:02d}", "prueba": name, "grupo": group_of(number), "tipo": TYPES.get(module, "Otro"),
            "estado": status, "duracion_ms": round((time.perf_counter() - self._start) * 1000, 1),
            "detalle": detail.strip().splitlines()[-1] if detail else "",
            "traza": detail.strip() if status != "APROBADA" else "",
        })

    def addSuccess(self, test):
        super().addSuccess(test); self._add(test, "APROBADA")

    def addFailure(self, test, err):
        super().addFailure(test, err); self._add(test, "FALLIDA", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err); self._add(test, "ERROR", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason); self._add(test, "OMITIDA", reason)


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "ejecucion"
    EVIDENCE.mkdir(exist_ok=True)
    stamp = datetime.now(timezone(timedelta(hours=-5)))

    loader = unittest.TestLoader()
    result = LoggingResult()
    for path in sorted(TESTS.glob("test_*.py")):
        module = f"pruebas.{path.stem}"
        try:
            import importlib
            suite = loader.loadTestsFromModule(importlib.import_module(module))
            suite.run(result)
        except Exception:
            # El módulo no se pudo importar: cada prueba declarada se registra como ERROR.
            err = traceback.format_exc()
            source = path.read_text(encoding="utf-8")
            import re
            for name in re.findall(r"def (test_\d+_\w+)", source):
                number = int(name.split("_")[1])
                result.records.append({
                    "id": f"{number:02d}", "prueba": name, "grupo": group_of(number),
                    "tipo": TYPES.get(path.stem, "Otro"), "estado": "ERROR", "duracion_ms": 0.0,
                    "detalle": err.strip().splitlines()[-1], "traza": err.strip()})

    records = sorted(result.records, key=lambda r: int(r["id"]))
    by_type: dict[str, list[int]] = {}
    for r in records:
        ok_total = by_type.setdefault(r["tipo"], [0, 0])
        ok_total[0] += r["estado"] == "APROBADA"; ok_total[1] += 1
    passed = sum(r["estado"] == "APROBADA" for r in records)
    documented = [r for r in records if int(r["id"]) <= 30]
    doc_passed = sum(r["estado"] == "APROBADA" for r in documented)
    apt = doc_passed == 30 and passed == len(records)

    lines = [
        "=" * 96,
        f"PERIOVISION · LOG DE PRUEBAS QA · {label.upper()}",
        f"Fecha: {stamp:%d/%m/%Y %H:%M:%S} (UTC-05)   Python {platform.python_version()}   "
        f"Pillow {version('Pillow')}   Streamlit {version('streamlit')}   Ultralytics {version('ultralytics')}",
        "=" * 96,
        f"{'ID':<5}{'ESTADO':<10}{'MS':>8}  {"GRUPO":<42}PRUEBA",
        "-" * 96,
    ]
    for r in records:
        lines.append(f"{r['id']:<5}{r['estado']:<10}{r['duracion_ms']:>8}  {r["grupo"]:<42}{r['prueba']}")
        if r["estado"] != "APROBADA":
            lines.append(f"{'':<24}↳ {r['detalle'][:150]}")
    lines += [
        "-" * 96,
        f"Pruebas documentadas (01-30): {doc_passed}/30 aprobadas",
        f"Total ejecutadas: {len(records)} · aprobadas {passed} · fallidas "
        f"{sum(r['estado'] == 'FALLIDA' for r in records)} · errores {sum(r['estado'] == 'ERROR' for r in records)}",
        "Por tipo: " + " · ".join(f"{t} {a}/{n}" for t, (a, n) in by_type.items()),
        f"DICTAMEN QA: {'APTA' if apt else 'NO APTA'}",
        "=" * 96,
    ]
    text = "\n".join(lines)
    base = EVIDENCE / f"log_pruebas_QA_{label}_{stamp:%Y%m%d_%H%M%S}"
    (base.parent / (base.name + ".txt")).write_text(text + "\n\nTRAZAS\n" + "\n\n".join(
        f"[{r['id']}] {r['prueba']}\n{r['traza']}" for r in records if r["traza"]), encoding="utf-8")
    (base.parent / (base.name + ".json")).write_text(json.dumps({
        "etiqueta": label, "fecha_local": stamp.isoformat(), "python": platform.python_version(),
        "dependencias": {p: version(p) for p in ("Pillow", "streamlit", "ultralytics")},
        "documentadas_aprobadas": doc_passed, "total": len(records), "aprobadas": passed,
        "dictamen": "APTA" if apt else "NO APTA", "por_tipo": {t: {"aprobadas": a, "total": n} for t, (a, n) in by_type.items()},
        "resultados": records,
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob("*.py"))},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(text)
    print(f"\nLog: {base.parent / (base.name + ".txt")}")
    return 0 if apt else 1


if __name__ == "__main__":
    raise SystemExit(main())
