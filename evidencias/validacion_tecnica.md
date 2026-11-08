# Validación técnica del despliegue preliminar · v1.2.0

Fecha: 08/11/2026. Entorno: clon limpio de la etiqueta `v1.2.0` en una carpeta vacía (sin `.venv`, datos ni pesos), Windows 11, Python 3.12.10. Simula lo que hace Streamlit Community Cloud: clonar e instalar solo con `requirements.txt`.

| Comprobación | Resultado |
|---|---|
| Clonar la etiqueta v1.2.0 | Correcto; sin datos, credenciales, secretos ni pesos |
| Instalar con `requirements.txt` | Correcto en 198 s; `torch 2.15.0+cpu`, `torchvision 0.29.2+cpu` |
| Huella SHA-256 de `best.pt` | Coincide con `DESPLIEGUE.md` |
| Arranque del servidor | Salud `ok` y página 200 en 2,8 s |
| Administrador inicial desde secrets | Creado; exige cambiar la clave |
| Estado del sistema | Modelo Activo; 9 páginas de mantenimiento; respaldo diario creado |
| Verificar modelo | `detect`; clases Normal, Stage 1, Stage 2, Stage 3; 0,07 s |
| Batería completa en el clon | 123/123; APTA |
| Descarga verificada de pesos | Prueba 124 aprobada |
| Publicación en Streamlit Community Cloud | Publicada el 08/11/2026: https://periovision-upn.streamlit.app (repo `bimbot27/periovision`, `main`, Python 3.12); compilación sin errores, `torch 2.15.0+cpu` |
| Nube: acceso del administrador inicial | Correcto; clave inicial cambiada; modelo Activo |
| Nube: verificar modelo | `detect`; cuatro clases; 0,57 s |
| Nube: batería QA desde el panel | 123/124 (30/30 documentadas). Falla la 83: inferencia p95 > 100 ms en la CPU compartida (≈ 80 ms de media). **Observación O-02:** RNF02 se mide en el equipo de referencia (35 ms, cumple) |
| Nube: respaldos | Automático y manual creados |
| Nube: usuario con COP y análisis de prueba | Pendiente del responsable |

## Lista para repetir sobre la URL pública

1. La app abre y muestra el acceso con `periovision-1.2.0`.
2. El administrador inicial entra, cambia la clave y ve el modelo Activo.
3. **Modelo y calibración › Verificar modelo** muestra las cuatro clases.
4. Crear un usuario con COP, analizar `ejemplos/radiografia_ejemplo.jpg`, registrar la revisión y descargar el PDF.
5. **Pruebas QA › Ejecutar pruebas** da APTA.
6. **Respaldos › Crear respaldo ahora** y descargarlo.

Limitación: la plataforma ejecuta Linux; esta validación se hizo en Windows con las mismas versiones fijadas.
