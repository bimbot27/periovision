# PerioVision

Prototipo académico (Capstone UPN) de apoyo a la detección periodontal en radiografías periapicales con YOLO. **Apoyo experimental: no constituye un diagnóstico.**

- **App publicada:** https://periovision-upn.streamlit.app (solo datos de demostración)
- **Versión:** 1.2.0 · [cambios](https://github.com/bimbot27/periovision/commits/main)
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
