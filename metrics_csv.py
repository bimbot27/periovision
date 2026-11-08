"""Lectura explícita de una serie de entrenamiento; no evalúa pesos ni test."""
from pathlib import Path
import csv
import hashlib
import json
import math

FIELDS = ['metrics/precision(B)', 'metrics/recall(B)', 'metrics/mAP50(B)', 'metrics/mAP50-95(B)']

def summarize(path):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not {'epoch', *FIELDS} <= {k.strip() for k in reader.fieldnames or []}:
            raise ValueError('Faltan columnas de época o métricas requeridas.')
        rows = []
        for raw in reader:
            normalized = {k.strip(): v.strip() for k, v in raw.items() if k is not None}
            try:
                epoch_value = float(normalized['epoch'])
                values = [float(normalized[k]) for k in FIELDS]
            except (ValueError, TypeError) as e:
                raise ValueError('Época o métrica no numérica.') from e
            if not math.isfinite(epoch_value) or not epoch_value.is_integer() or epoch_value < 1:
                raise ValueError('Época inválida.')
            if not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
                raise ValueError('Las métricas deben ser finitas y estar entre 0 y 1.')
            precision, recall, map50, map95 = values
            rows.append({'epoch': int(epoch_value), 'precision': precision, 'recall': recall,
                         'map50': map50, 'map50_95': map95,
                         'harmonic_precision_recall': 2 * precision * recall / (precision + recall) if precision + recall else None})
    if not rows:
        raise ValueError('Serie vacía.')
    if any(b['epoch'] <= a['epoch'] for a, b in zip(rows, rows[1:], strict=False)):
        raise ValueError('Las épocas deben estar ordenadas y no repetirse.')
    return {'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'rows': len(rows), 'last_epoch': rows[-1],
            'maximum_harmonic_row': max(rows, key=lambda r: r['harmonic_precision_recall'] if r['harmonic_precision_recall'] is not None else -1),
            'maximum_map50_95_row': max(rows, key=lambda r: r['map50_95']),
            'checkpoint_identified': False, 'test_evaluated': False,
            'aggregation': 'Media armónica de precisión y recall agregados del CSV. No presupone F1 micro o macro ni identifica best.pt.'}

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('csv_path')
    parser.add_argument('--out')
    args = parser.parse_args()
    value = summarize(args.csv_path)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
    print(text)
