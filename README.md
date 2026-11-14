# PerioVision

Prototipo académico (Capstone UPN) de apoyo a la detección periodontal en radiografías periapicales con YOLO. **Apoyo experimental: no constituye un diagnóstico.**

- **App publicada:** https://periovision-upn.streamlit.app (solo datos de demostración)
- **Versión:** 1.2.1 · [cambios](https://github.com/bimbot27/periovision/commits/main)
- **Pruebas:** 124 automatizadas; se ejecutan en cada `push` con GitHub Actions (`.github/workflows/pruebas.yml`)

## Uso local

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.\ABRIR_DEMO.bat
```

## Documentación

| Tema | Archivo |
|---|---|
| Guía de uso y roles | `LEEME.md` |
| Despliegue en Streamlit Community Cloud | `DESPLIEGUE.md` |
| Revisión SQA | `evidencias/revision_sqa.md` |
| Trazabilidad | `evidencias/trazabilidad.md` |
| Validación técnica y evidencia del despliegue | `evidencias/validacion_tecnica.md`, `evidencias/despliegue/` |
| Indicadores | `calcular_indicadores.py` → `evidencias/indicadores.json` |

## Licencias de terceros

| Componente | Licencia | Obligación principal |
|---|---|---|
| Ultralytics YOLO 8.4.207 | AGPL-3.0 | Quien use la app por red puede pedir el código fuente correspondiente; para uso cerrado o comercial se requiere la licencia empresarial de Ultralytics |
| Streamlit 1.67.0, PyTorch 2.15.0, OpenCV | Apache-2.0 | Conservar avisos de copyright y licencia |
| torchvision, NumPy, pi-heif | BSD | Conservar avisos de copyright y licencia |
| Pillow | MIT-CMU | Conservar avisos de copyright y licencia |
| Dataset de entrenamiento de `best.pt` (Roboflow, `joaquins-workspace-mtivu`) | Por confirmar con su autor | Verificar antes de redistribuir los pesos |

El aviso de AGPL-3.0 se muestra en la pantalla de acceso de la app.
