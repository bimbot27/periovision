"""Consolida los indicadores I01-I14 con su fuente, línea base, meta y estado.

Lee las evidencias que produce el producto (rendimiento, pruebas, auditoría de datos, evaluaciones)
y las fichas de `instrumentos/` cuando el equipo las llena. Escribe `evidencias/indicadores.json`.
Ningún valor se inventa: lo que no tiene datos queda como "Pendiente" con lo que falta.

Uso:  .venv\\Scripts\\python.exe calcular_indicadores.py
"""
from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime
from pathlib import Path

import datos
import evaluacion as ev

ROOT = Path(__file__).resolve().parent
EVID = ROOT / "evidencias"
INST = ROOT / "instrumentos"

# Validación del registro B del notebook (celda 33, época final; 60 imágenes, 99 regiones). No es la prueba congelada.
VALIDACION_NOTEBOOK = {"precision": 0.527, "recall": 0.584, "map50": 0.548, "map50_95": 0.379,
                       "stage1": {"soporte": 17, "recall": 0.412}}


def _latest(pattern: str) -> Path | None:
    files = sorted(EVID.glob(pattern), key=lambda f: f.stat().st_mtime)
    return files[-1] if files else None


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for k, v in r.items() if k not in ("participante", "tarea_n", "tarea"))]


def _state(value: float | None, goal: float, higher: bool = True) -> str:
    if value is None:
        return "Pendiente"
    return "Cumple" if (value >= goal if higher else value <= goal) else "No cumple"


def main() -> dict:
    v = VALIDACION_NOTEBOOK
    f1 = 2 * v["precision"] * v["recall"] / (v["precision"] + v["recall"])
    vp1 = round(v["stage1"]["recall"] * v["stage1"]["soporte"])
    ci = ev.wilson(vp1, v["stage1"]["soporte"])
    src_val = "Validación del notebook (registro B, 60 imágenes, 99 regiones); prueba congelada pendiente"
    evals = sorted((ROOT / "datos" / "evaluaciones").glob("*/metricas.json")) if (ROOT / "datos" / "evaluaciones").exists() else []
    evaluated = evals[-1] if evals else None
    out = []

    def add(code, name, base, value, goal, state, source, unit="%"):
        out.append({"id": code, "indicador": name, "linea_base": base, "valor_actual": value, "meta": goal,
                    "estado": state, "fuente": source, "unidad": unit})

    add("I01", "Precisión", "52,69 % histórica", round(v["precision"] * 100, 1), "≥ 65 %", _state(v["precision"], .65), src_val)
    add("I02", "Sensibilidad", "58,40 % histórica", round(v["recall"] * 100, 1), "≥ 70 %", _state(v["recall"], .70), src_val)
    add("I03", "Sensibilidad Stage 1", "No calculable", round(v["stage1"]["recall"] * 100, 1), "≥ 75 %",
        _state(v["stage1"]["recall"], .75), f"{src_val}; VP ≈ {vp1}, FN ≈ {v['stage1']['soporte'] - vp1}, "
        f"IC95 % Wilson {ci[0] * 100:.0f}–{ci[1] * 100:.0f} %")
    add("I04", "F1", "55,40 % histórica", round(f1 * 100, 1), "≥ 67 %", _state(f1, .67), src_val + "; media armónica de P y R agregadas")
    add("I05", "mAP@0.5", "54,83 % histórica", round(v["map50"] * 100, 1), "≥ 65 %", _state(v["map50"], .65), src_val)
    add("I06", "mAP@0.5:0.95", "38,00 % histórica", round(v["map50_95"] * 100, 1), "≥ 45 %", _state(v["map50_95"], .45), src_val)

    perf = json.loads((EVID / "rendimiento.json").read_text(encoding="utf-8")) if (EVID / "rendimiento.json").exists() else {}
    inf = perf.get("inferencia_modelo", {}).get("p95_ms")
    flow = perf.get("carga_a_visualizacion", {}).get("p95_ms")
    add("I07", "Latencia p95 (inferencia · carga a visualización)", "9,8 ms históricos, entorno no conciliado",
        f"{inf} ms · {flow} ms" if inf else None, "≤ 100 ms · ≤ 3 000 ms",
        "Cumple" if inf and inf <= 100 and flow <= 3000 else "Pendiente",
        "evidencias/rendimiento.json (100 ejecuciones, CPU)", unit="ms")

    t = _rows(INST / "ficha_tiempos_I08.csv")
    def secs(r):
        h1, m1, s1 = (int(x) for x in r["inicio_hhmmss"].split(":")); h2, m2, s2 = (int(x) for x in r["fin_hhmmss"].split(":"))
        return (h2 * 3600 + m2 * 60 + s2) - (h1 * 3600 + m1 * 60 + s1)
    man = [secs(r) for r in t if r["condicion"].strip().lower() == "manual"]
    asi = [secs(r) for r in t if r["condicion"].strip().lower() == "asistido"]
    i08 = (statistics.median(man) - statistics.median(asi)) / statistics.median(man) if man and asi else None
    add("I08", "Reducción del tiempo de revisión", "No medida", None if i08 is None else round(i08 * 100, 1), "≥ 20 %",
        _state(i08, .20), "instrumentos/ficha_tiempos_I08.csv" + ("" if t else " (sin registros: piloto pendiente)"))

    k = _rows(INST / "etiquetas_lectores_I09.csv")
    kappa = datos.weighted_kappa([(r["lector_1"].strip(), r["lector_2"].strip()) for r in k]) if k else None
    add("I09", "Kappa ponderado entre lectores", "No medido", None if kappa is None else round(kappa, 2), "≥ 0,70",
        _state(kappa, .70), "instrumentos/etiquetas_lectores_I09.csv" + ("" if k else " (sin registros: doble lectura pendiente)"), unit="")

    tasks = [r for r in _rows(INST / "ficha_tareas_I10.csv") if r.get("completada_sin_ayuda", "").strip()]
    i10 = sum(r["completada_sin_ayuda"].strip().lower() in ("si", "sí") for r in tasks) / len(tasks) if tasks else None
    add("I10", "Tareas completadas sin ayuda", "No medido", None if i10 is None else round(i10 * 100, 1), "≥ 90 % (3 usuarios × 5 tareas)",
        _state(i10, .90), "instrumentos/ficha_tareas_I10.csv" + ("" if tasks else " (sin registros: piloto pendiente)"))

    prot = datos.audit_data_protection(ROOT / "datos")
    add("I11", "Protección de datos", "No auditada", prot["indicador_I11"], "100 %", _state((prot["indicador_I11"] or 0) / 100, 1.0),
        f"Auditoría de {prot['revisados']} archivos de datos/ + pruebas 31–40, 87–94, 101, 122–123")

    trace = json.loads((EVID / "trazabilidad.json").read_text(encoding="utf-8")) if (EVID / "trazabilidad.json").exists() else None
    i12 = trace["con_prueba_y_evidencia"] / trace["total"] if trace else None
    add("I12", "Trazabilidad", "Catálogo definido; ejecución pendiente", None if i12 is None else round(i12 * 100, 1), "100 %",
        _state(i12, 1.0), "evidencias/trazabilidad.md")
    add("I13", "Avance EDT (paquetes aceptados)", "Pendiente de acta", None, "100 % al cierre", "Pendiente",
        "Requiere actas de aceptación del equipo; no se calcula con pruebas aprobadas")
    add("I14", "Desviación presupuestal", "S/ 23 408 línea base", None, "≤ 0 %", "Pendiente",
        "Requiere gastos ejecutados del coordinador")

    qa = json.loads(_latest("log_pruebas_QA_*.json").read_text(encoding="utf-8")) if _latest("log_pruebas_QA_*.json") else {}
    result = {"fecha": datetime.now().astimezone().isoformat(timespec="minutes"), "indicadores": out,
              "pruebas": {"total": qa.get("total"), "aprobadas": qa.get("aprobadas"), "dictamen": qa.get("dictamen")},
              "evaluacion_prueba_congelada": str(evaluated) if evaluated else "Pendiente: cargar el .zip de prueba en Evaluación del modelo"}
    (EVID / "indicadores.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for i in main()["indicadores"]:
        print(f"{i['id']:<4} {i['estado']:<10} {str(i['valor_actual']):<22} meta {i['meta']:<28} {i['indicador']}")
