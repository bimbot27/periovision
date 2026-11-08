"""Núcleo de PerioVision: validación, adaptadores, casos, revisión, exportación y auditoría.
No contiene datos clínicos ni pesos."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import importlib.metadata
import io
import json
import math
import os
import re
import uuid
from PIL import Image, ImageDraw

# Ultralytics instala paquetes desde internet si le falta alguno (p. ej. pi-heif al abrir un archivo
# corrupto). El producto no descarga ni instala nada en tiempo de ejecución (defecto D-04).
os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
os.environ.setdefault('YOLO_OFFLINE', 'true')

VERSION = 'periovision-1.0.0'
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 20_000_000
LABELS = ('Normal', 'Stage 1', 'Stage 2', 'Stage 3')
NOTICE = 'Apoyo experimental. Requiere revisión profesional. Sin detecciones no significa ausencia de enfermedad.'

class ProductError(ValueError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()

def synthetic_image():
    """Imagen geométrica de demostración; no imita una radiografía."""
    im = Image.new('RGB', (640, 640), '#eef2f6')
    draw = ImageDraw.Draw(im)
    draw.rectangle((100, 100, 220, 220), fill='#b6ccd9', outline='#425f72', width=3)
    draw.text((30, 25), 'SIMULACION TECNICA - SIN PACIENTES', fill='black')
    draw.text((30, 590), 'No contiene inferencia ni etiquetas clinicas.', fill='black')
    return im

def make_demo(path):
    synthetic_image().save(path, format='PNG')

def load_image(path):
    p = Path(path)
    if p.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        raise ProductError('Formato no admitido. Use PNG o JPEG.')
    if not p.is_file():
        raise ProductError('No se encontró el archivo.')
    if p.stat().st_size > MAX_BYTES:
        raise ProductError('La imagen supera 20 MB.')
    try:
        with Image.open(p) as original:
            if original.format not in ('PNG', 'JPEG'):
                raise ProductError('El contenido del archivo no es PNG/JPEG.')
            if original.width * original.height > MAX_PIXELS:
                raise ProductError('La imagen supera el límite de 20 millones de píxeles.')
            original.verify()
        with Image.open(p) as original:
            image = original.convert('RGB')
            image.load()
    except ProductError:
        raise
    except (OSError, ValueError, ImportError, Image.DecompressionBombError) as e:
        raise ProductError('No se pudo leer la imagen; puede estar vacía o corrupta.') from e
    # Ni nombres de archivo ni metadatos de paciente se copian al registro.
    return image, sha256(p)

def check_detections(items, size, demo=False):
    if not isinstance(items, list):
        raise ProductError('Las detecciones deben ser una lista.')
    result = []
    for item in items:
        try:
            label = item['class']
            confidence = float(item['confidence'])
            box = [float(v) for v in item['box']]
        except (KeyError, TypeError, ValueError) as e:
            raise ProductError('Detección incompleta o con números inválidos.') from e
        if label not in (('DEMO',) if demo else LABELS):
            raise ProductError('Clase no permitida en este modo.')
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ProductError('Confianza fuera de 0 a 1.')
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            raise ProductError('El cuadro requiere cuatro números finitos.')
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= size[0] and 0 <= y1 < y2 <= size[1]):
            raise ProductError('Cuadro fuera de la imagen o sin área.')
        result.append({'class': label, 'confidence': confidence, 'box': box})
    return result

class DemoDetector:
    mode = 'DEMO'
    def predict(self, image):
        if image.size != (640, 640) or image.tobytes() != synthetic_image().tobytes():
            raise ProductError('La simulación solo admite la imagen geométrica incluida.')
        return ([{'class': 'DEMO', 'confidence': .80, 'box': [100, 100, 220, 220]}],
                {'architecture': 'adaptador_prefijado_sin_IA', 'weights_sha256': None,
                 'demo': True, 'clinical_inference': False})

class YoloDetector:
    mode = 'REAL'
    def __init__(self, weights, authorization=False, conf=.25, imgsz=640, iou=.7):
        if not authorization:
            raise ProductError('Confirme autorización de datos, saneamiento y procedencia de pesos antes de integrar.')
        self.path = Path(weights)
        if self.path.suffix.lower() != '.pt' or not self.path.is_file():
            raise ProductError('Modelo no disponible. Seleccione pesos locales .pt autorizados.')
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ProductError('Ultralytics no está instalado. Use el entorno validado del equipo; no se descarga nada automáticamente.') from e
        self.model = YOLO(str(self.path))
        if self.model.task != 'detect':
            raise ProductError('El archivo de pesos no corresponde a detección de objetos.')
        self.names = self.model.names
        if set(self.names.values()) != set(LABELS):
            raise ProductError('Las clases de los pesos no coinciden con Normal, Stage 1, Stage 2 y Stage 3. Conciliar el protocolo; no se renombra silenciosamente.')
        self.digest = sha256(self.path)
        conf, iou, imgsz = float(conf), float(iou), int(imgsz)
        if not (0 < conf < 1 and 0 < iou < 1 and 160 <= imgsz <= 1280 and imgsz % 32 == 0):
            raise ProductError('Parámetros de inferencia fuera de rango.')
        self.conf, self.iou, self.imgsz = conf, iou, imgsz

    def predict(self, image):
        results = self.model.predict(source=image, imgsz=self.imgsz, conf=self.conf, iou=self.iou,
                                     device='cpu', save=False, verbose=False)
        detections = []
        w, h = image.size
        for box in results[0].boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            # Recorte a los límites de la imagen para cumplir check_detections.
            x1, y1 = max(0.0, x1), max(0.0, y1)
            x2, y2 = min(float(w), x2), min(float(h), y2)
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append({'class': self.names[int(box.cls.item())],
                               'confidence': float(box.conf.item()),
                               'box': [x1, y1, x2, y2]})
        return detections, {'architecture': f'Ultralytics {self.model.task}',
                            'weights_sha256': self.digest, 'ultralytics': importlib.metadata.version('ultralytics'),
                            'imgsz': self.imgsz, 'confidence_threshold': self.conf, 'nms_iou': self.iou,
                            'device': 'cpu', 'demo': False, 'clinical_inference': True}

class Case:
    def __init__(self, path, code):
        if not re.fullmatch(r'[A-Za-z0-9_-]{2,40}', code):
            raise ProductError('Use un código de caso de 2 a 40 letras, números, guion o guion bajo.')
        self.image, digest = load_image(path)
        self.data = {'schema': 1, 'version': VERSION, 'case_code': code,
                     'case_id': uuid.uuid4().hex, 'created_utc': now(),
                     'input_sha256': digest, 'size': list(self.image.size),
                     'notice': NOTICE, 'evaluable': None, 'runs': [], 'reviews': []}

    def quality(self, evaluable):
        if not isinstance(evaluable, bool):
            raise ProductError('Confirme si la imagen es evaluable.')
        self.data['evaluable'] = evaluable

    def infer(self, detector):
        if self.data['evaluable'] is not True:
            raise ProductError('La imagen no está confirmada como evaluable.')
        # El estado se modifica solamente al concluir una ejecución válida.
        try:
            import time
            start = time.perf_counter()
            items, meta = detector.predict(self.image.copy())
            elapsed = (time.perf_counter() - start) * 1000
            items = check_detections(items, self.image.size, demo=detector.mode == 'DEMO')
        except MemoryError as e:
            raise ProductError('Memoria insuficiente. Se conservan los registros anteriores.') from e
        run = {'run_id': uuid.uuid4().hex, 'utc': now(), 'mode': detector.mode,
               'original': deepcopy(items), 'model': deepcopy(meta),
               'elapsed_adapter_ms': round(elapsed, 3)}
        self.data['runs'].append(run)
        return deepcopy(run)

    def review(self, action, reviewer_code, revised=None, role='tecnico'):
        if not self.data['runs']:
            raise ProductError('Primero ejecute una inferencia o una demostración.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{2,40}', reviewer_code):
            raise ProductError('Use un código de revisor sin nombres personales.')
        if action not in ('aceptar', 'corregir', 'descartar') or role not in ('tecnico', 'especialista_declarado'):
            raise ProductError('Acción o rol inválido.')
        run = self.data['runs'][-1]
        boxes = deepcopy(run['original']) if action == 'aceptar' else []
        if action == 'corregir':
            boxes = check_detections(revised, self.image.size, demo=run['mode'] == 'DEMO')
        review = {'run_id': run['run_id'], 'utc': now(), 'reviewer_code': reviewer_code,
                  'role_declared': role, 'identity_verified': False, 'action': action,
                  'revised': boxes, 'clinical_validation': False}
        self.data['reviews'].append(review)
        return deepcopy(review)

    def snapshot(self):
        value = deepcopy(self.data)
        run = value['runs'][-1] if value['runs'] else None
        review = next((r for r in reversed(value['reviews']) if run and r['run_id'] == run['run_id']), None)
        value['status'] = 'revision_registrada_sin_validacion_clinica' if review else 'provisional'
        value['demo'] = bool(run and run['mode'] == 'DEMO')
        return value

    def export(self, folder):
        destination = Path(folder)
        destination.mkdir(parents=True, exist_ok=True)
        value = self.snapshot()
        # Una exportación genera una revisión nueva, nunca pisa un archivo anterior.
        stem = f"{value['case_code']}_{uuid.uuid4().hex[:12]}"
        json_path = destination / (stem + '.json')
        csv_path = destination / (stem + '.csv')
        with json_path.open('x', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        fields = ['case_code', 'status', 'demo', 'run_id', 'record_type', 'class',
                  'confidence', 'x1', 'y1', 'x2', 'y2']
        with csv_path.open('x', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
            runs = value['runs']
            records = []
            for run in runs:
                records.extend((run['run_id'], 'original', b) for b in run['original'])
            for review in value['reviews']:
                records.extend((review['run_id'], 'revision', b) for b in review['revised'])
            if not records:
                writer.writerow({'case_code': value['case_code'], 'status': value['status'], 'demo': value['demo'], 'record_type': 'sin_cajas'})
            for run_id, kind, b in records:
                writer.writerow(dict(case_code=value['case_code'], status=value['status'], demo=value['demo'],
                                     run_id=run_id, record_type=kind, **{'class': b['class']},
                                     confidence=b['confidence'], **dict(zip(('x1','y1','x2','y2'), b['box']))))
        return json_path, csv_path

COLORS = {'Normal': '#34C759', 'Stage 1': '#FFCC00', 'Stage 2': '#FF9500', 'Stage 3': '#FF3B30', 'DEMO': '#007AFF'}

def draw_detections(image, items):
    """Devuelve una copia con los cuadros dibujados; la imagen original no se modifica."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    width = max(2, round(min(out.size) / 200))
    for n, item in enumerate(items, 1):
        x1, y1, x2, y2 = item['box']
        color = COLORS.get(item['class'], '#007AFF')
        draw.rectangle((x1, y1, x2, y2), outline=color, width=width)
        label = f"{n} · {item['class']} {item['confidence']:.0%}"
        tw = draw.textlength(label) + 10
        draw.rectangle((x1, max(0, y1 - 18), x1 + tw, max(18, y1)), fill=color)
        draw.text((x1 + 5, max(0, y1 - 18) + 3), label, fill='black')
    return out

def audit_manifest(path):
    """Audita agrupación y duplicados; no certifica identidad, permiso o etiquetas clínicas."""
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not {'image_id','patient_code','sha256','subset'} <= set(reader.fieldnames or []):
            raise ProductError('Faltan columnas image_id, patient_code, sha256 o subset.')
        rows = list(reader)
    issues, patients, hashes, ids, counts = [], {}, {}, set(), {}
    if not rows: issues.append('Manifiesto vacío.')
    for number, row in enumerate(rows, 2):
        image, patient, digest, subset = (row[k].strip() for k in ('image_id','patient_code','sha256','subset'))
        if not image or not patient or not re.fullmatch(r'[a-f0-9]{64}', digest) or subset not in ('train','val','test'):
            issues.append(f'Fila {number}: campos inválidos.'); continue
        if image in ids: issues.append(f'Fila {number}: image_id duplicado.')
        ids.add(image)
        if patient in patients and patients[patient] != subset:
            issues.append(f'Fila {number}: paciente en varios subconjuntos.')
        patients[patient] = subset
        if digest in hashes: issues.append(f'Fila {number}: hash repetido.')
        hashes[digest] = subset
        counts[subset] = counts.get(subset,0)+1
    return {'rows': len(rows), 'counts': counts, 'issues': issues,
            'structural_check_passed': not issues,
            'clinical_validity': False, 'data_authorization_verified': False}
