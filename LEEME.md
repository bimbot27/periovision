# PerioVision · demo

Aplicación de presentación del detector YOLO del notebook. Carga una radiografía y muestra al lado la imagen con detecciones, las clases y las confianzas del modelo.

## Abrir la demo

Haz doble clic en `ABRIR_DEMO.bat`. Se abrirá la app en el navegador. Deja abierta la ventana de consola mientras la uses; para cerrar la app, cierra esa ventana.

El archivo `best.pt` está junto a la app y se carga automáticamente. Si reemplazas el modelo, conserva ese nombre.

## Si necesitas reinstalar las dependencias

El entorno local ya está preparado. En PowerShell, desde esta carpeta, puedes reinstalar con:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> Es una demo académica para apoyo visual; no constituye un diagnóstico.
