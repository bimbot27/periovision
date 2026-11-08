@echo off
setlocal
cd /d "%~dp0"
set "YOLO_CONFIG_DIR=%~dp0.yolo"
if not exist ".venv\Scripts\python.exe" (
  echo No se encontro el entorno de la app. Contacta a quien preparo esta demo.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py --browser.gatherUsageStats false
