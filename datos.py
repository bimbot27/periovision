"""Herramientas de datos del administrador: lote desidentificado (HU01/RF02), concordancia entre
lectores (I09) y respaldo/restauración con verificación de huellas (RNF07)."""
from __future__ import annotations

import csv
import re
import hashlib
import io
import json
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image

import core

ORDINAL = {label: i for i, label in enumerate(core.LABELS)}  # Normal < Stage 1 < Stage 2 < Stage 3


# ─────────────────────────────── lote desidentificado ───────────────────────────────
def deidentify_batch(files: list[tuple[str, bytes]], batch_code: str,
                     patient_map: dict[str, str] | None = None) -> tuple[bytes, list[dict], bytes]:
    """Re-codifica cada imagen sin metadatos (EXIF, texto PNG, ICC) y con nombre codificado.

    Devuelve (zip del lote, filas del manifiesto, CSV de correspondencia para el custodio).
    El texto impreso en los píxeles NO se puede quitar automáticamente: requiere revisión visual.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,20}", batch_code):
        raise core.ProductError("Código de lote: 2 a 20 letras, números, guion o guion bajo.")
    if not files:
        raise core.ProductError("Agrega al menos una imagen.")
    out, manifest, mapping = io.BytesIO(), [], io.StringIO()
    mw = csv.writer(mapping); mw.writerow(["nombre_original", "image_id", "patient_code"])
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, (name, data) in enumerate(files, 1):
            if len(data) > core.MAX_BYTES:
                raise core.ProductError(f"Imagen {n}: supera 20 MB.")
            try:
                with Image.open(io.BytesIO(data)) as src:
                    if src.format not in ("PNG", "JPEG") or src.width * src.height > core.MAX_PIXELS:
                        raise core.ProductError(f"Imagen {n}: formato o tamaño no admitido.")
                    mode = "L" if src.mode in ("L", "I;16", "I") else "RGB"
                    pixels = src.convert(mode)
                    clean = Image.frombytes(mode, pixels.size, pixels.tobytes())  # solo píxeles, sin metadatos
            except core.ProductError:
                raise
            except (OSError, ValueError) as e:
                raise core.ProductError(f"Imagen {n}: no se pudo leer.") from e
            buf = io.BytesIO(); clean.save(buf, format="PNG")
            image_id = f"{batch_code}_{n:04d}"
            zf.writestr(f"{image_id}.png", buf.getvalue())
            patient = (patient_map or {}).get(name, "")
            manifest.append({"image_id": image_id, "patient_code": patient,
                             "sha256": hashlib.sha256(buf.getvalue()).hexdigest(), "subset": ""})
            mw.writerow([name, image_id, patient])
        man = io.StringIO()
        w = csv.DictWriter(man, fieldnames=["image_id", "patient_code", "sha256", "subset"])
        w.writeheader(); w.writerows(manifest)
        zf.writestr("manifiesto.csv", man.getvalue())
        zf.writestr("LEEME.txt", "Lote desidentificado por PerioVision. Metadatos eliminados; nombres codificados.\n"
                                 "Pendiente: revisión visual de texto impreso en las imágenes y asignación de subset.\n"
                                 "La correspondencia con nombres originales se entrega aparte solo al custodio.\n")
    return out.getvalue(), manifest, mapping.getvalue().encode("utf-8")


def has_metadata(data: bytes) -> bool:
    with Image.open(io.BytesIO(data)) as im:
        return bool(im.info.get("exif") or im.getexif() or {k for k in im.info if k not in ("dpi",)})


# ─────────────────────────────── concordancia ───────────────────────────────
def weighted_kappa(pairs: list[tuple[str, str]], weights: str = "quadratic") -> float | None:
    """Kappa de Cohen ponderado para categorías ordinales (I09). None si no es calculable."""
    k = len(core.LABELS)
    if not pairs:
        return None
    obs = [[0] * k for _ in range(k)]
    for a, b in pairs:
        if a not in ORDINAL or b not in ORDINAL:
            raise core.ProductError(f"Categoría no válida: {a!r} / {b!r}.")
        obs[ORDINAL[a]][ORDINAL[b]] += 1
    n = len(pairs)
    rows = [sum(r) for r in obs]; cols = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = lambda i, j: ((i - j) ** 2 if weights == "quadratic" else abs(i - j)) / ((k - 1) ** 2 if weights == "quadratic" else (k - 1))
    observed = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    expected = sum(w(i, j) * rows[i] * cols[j] for i in range(k) for j in range(k)) / (n * n)
    return None if expected == 0 else 1 - observed / expected


def read_readers_csv(data: bytes) -> list[tuple[str, str]]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    if not {"lector_1", "lector_2"} <= set(reader.fieldnames or []):
        raise core.ProductError("El CSV necesita las columnas lector_1 y lector_2.")
    return [(r["lector_1"].strip(), r["lector_2"].strip()) for r in reader]


# ─────────────────────────────── respaldo y restauración ───────────────────────────────
EXCLUDE = {"respaldos", "respaldos_datos"}


def _data_files(data_dir: Path) -> list[Path]:
    return [p for p in sorted(data_dir.rglob("*")) if p.is_file()
            and p.relative_to(data_dir).parts[0] not in EXCLUDE and p.suffix != ".tmp"]


def create_backup(data_dir: str | Path) -> tuple[bytes, dict]:
    """Zip con usuarios, configuración, auditoría y casos + manifiesto de huellas SHA-256."""
    data_dir = Path(data_dir)
    files = _data_files(data_dir)
    manifest = {"version": core.VERSION, "creado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "archivos": {p.relative_to(data_dir).as_posix(): core.sha256(p) for p in files}}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, "datos/" + p.relative_to(data_dir).as_posix())
        zf.writestr("manifiesto_respaldo.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return out.getvalue(), manifest


def restore_backup(data: bytes, data_dir: str | Path) -> dict:
    """Verifica cada huella antes de tocar nada; luego reemplaza los datos. Devuelve el informe."""
    start = time.perf_counter()
    data_dir = Path(data_dir)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("manifiesto_respaldo.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise core.ProductError("El archivo no es un respaldo válido de PerioVision.") from e
    contents = {}
    for rel, digest in manifest["archivos"].items():
        path = PurePosixPath(rel)
        if ".." in path.parts or path.is_absolute() or path.parts[0] in EXCLUDE:
            raise core.ProductError("El respaldo contiene rutas no permitidas.")
        try:
            blob = zf.read("datos/" + rel)
        except KeyError as e:
            raise core.ProductError(f"Falta {rel} en el respaldo.") from e
        if hashlib.sha256(blob).hexdigest() != digest:
            raise core.ProductError(f"Huella distinta en {rel}: respaldo dañado o alterado.")
        contents[rel] = blob
    staging = data_dir.with_name(data_dir.name + "_restaurando")
    shutil.rmtree(staging, ignore_errors=True)
    for rel, blob in contents.items():
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    for p in data_dir.iterdir() if data_dir.exists() else []:  # conserva respaldos y modelos previos
        if p.name not in EXCLUDE:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    data_dir.mkdir(parents=True, exist_ok=True)
    for p in staging.iterdir():
        shutil.move(str(p), str(data_dir / p.name))
    shutil.rmtree(staging, ignore_errors=True)
    verified = all(core.sha256(data_dir / rel) == digest for rel, digest in manifest["archivos"].items())
    return {"archivos": len(contents), "verificado": verified, "creado_utc": manifest["creado_utc"],
            "segundos": round(time.perf_counter() - start, 3)}


def backup_path(folder: Path, suffix: str = "") -> Path:
    """Nombre único y ordenable por fecha (dos respaldos en el mismo segundo no se pisan)."""
    import uuid
    return Path(folder) / f"respaldo_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}{suffix}.zip"


def auto_backup(data_dir: str | Path, keep: int = 7, max_age_h: float = 24) -> Path | None:
    """Respaldo diario automático (RNF07): crea uno si el último tiene más de 24 h; conserva 7."""
    folder = Path(data_dir) / "respaldos_datos"
    folder.mkdir(parents=True, exist_ok=True)
    existing = sorted(folder.glob("respaldo_*.zip"))
    if existing and time.time() - existing[-1].stat().st_mtime < max_age_h * 3600:
        return None
    data, _ = create_backup(data_dir)
    path = backup_path(folder)
    path.write_bytes(data)
    for old in sorted(folder.glob("respaldo_*.zip"))[:-keep]:
        old.unlink()
    return path
