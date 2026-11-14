# PerioVision · v1.2.1

Prototipo académico que carga una radiografía periapical, ejecuta el detector YOLO (`best.pt`) y permite revisar y exportar el resultado. **No constituye un diagnóstico.**

## Abrir la app

Haz doble clic en `ABRIR_DEMO.bat` y entra a http://localhost:8501/. No cierres la ventana de consola mientras uses la app.

## Inicio de sesión y roles

| Rol | Qué puede hacer |
|---|---|
| **Administrador** | Solo mantenimiento: estado del sistema, verificar/autorizar/reemplazar el modelo, **calibración** (confianza y tamaño de análisis), usuarios y sus datos profesionales, pruebas QA, auditoría y limpieza de temporales. |
| **Usuario** | Uso de la web: cargar la radiografía, analizar con la calibración vigente, **aprobar o rechazar** con observaciones, descargar el informe (PDF, CSV, JSON) y consultar el **Historial**. |

### Datos profesionales e informes
- Cada cuenta tiene nombres, apellidos, correo, N.º de COP (obligatorio para el rol usuario), especialidad y fecha de nacimiento. En el primer acceso se pide completar el perfil; el COP solo lo modifica el administrador.
- Al registrar la revisión se genera un informe legible con el profesional que analizó y validó, los hallazgos (clase, descripción del estadio, confianza y ubicación aproximada) y sus observaciones. Se guarda en `datos/casos/<código>/` junto con la imagen anotada y el registro técnico completo.
- **Historial**: listado de radiografías aprobadas y rechazadas con filtros por estado, búsqueda por código, profesional o COP, y "solo mis análisis". Desde ahí se vuelven a descargar los informes.

- Las credenciales iniciales (`admin` y `usuario`) están en `CREDENCIALES_INICIALES.txt`. Ambas cuentas deben cambiar la contraseña en el primer acceso. **Borra ese archivo después de entregarlas.**
- Las contraseñas se guardan cifradas con PBKDF2-HMAC-SHA256 (sal aleatoria, 600 000 iteraciones) en `datos/usuarios.json`. Nunca se guardan en claro.
- Política: mínimo 10 caracteres, con mayúscula, minúscula, número y símbolo. Después de 5 intentos fallidos la cuenta se bloquea 5 minutos (el administrador puede desbloquearla).
- La sesión se cierra tras 30 minutos de inactividad (configurable). Recargar la página también cierra la sesión.
- Cada acceso y acción queda en `datos/auditoria.jsonl` (sin contraseñas).

## Apariencia y accesibilidad

El diseño sigue las Human Interface Guidelines de Apple: tipografía del sistema, colores semánticos, esquinas continuas y controles de 44 px. La app sigue el modo claro u oscuro del sistema. Para fijar uno: menú **⋮** › **Settings** › **Choose app theme**. Además tiene foco visible para teclado, etiquetas en todos los campos, tablas con encabezados, contraste AA y respeta "reducir movimiento".

## Pruebas QA

```powershell
.venv\Scripts\python.exe ejecutar_pruebas_qa.py final
```

Ejecuta 101 pruebas en `pruebas/`: regresión (las 30 documentadas del Sprint 2), unitarias, integración, sistema (AppTest), aceptación, humo, rendimiento, seguridad y usabilidad/accesibilidad. El log por prueba se guarda en `evidencias/`, las mediciones de rendimiento en `evidencias/rendimiento.json` y la prueba E2E en `evidencias/e2e_navegador.json`. El administrador también puede ejecutarlas desde **Pruebas QA**.

## Archivos

- `app.py`: interfaz (inicio de sesión, vistas por rol).
- `core.py`: validación de imágenes, adaptador YOLO, casos, revisión, exportación y auditoría de manifiestos.
- `metrics_csv.py`: lectura verificada de la serie de entrenamiento.
- `auth.py` / `crear_usuarios.py`: usuarios, roles, perfiles y cifrado.
- `informe.py`: informes PDF/CSV/JSON e historial de casos.
- `respaldo_original/`: versión anterior de la app, sin cambios.
