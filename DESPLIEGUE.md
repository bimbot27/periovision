# Despliegue preliminar en Streamlit Community Cloud

PerioVision 1.2.0 queda listo para publicarse desde un repositorio de GitHub. La publicación la hace el responsable del proyecto con su propia cuenta.

> **Alcance del despliegue preliminar.** Es una demostración técnica con datos sintéticos o de ejemplo. No cargues radiografías de pacientes reales en la nube sin la autorización del cliente y el protocolo de datos (RNF10). El sistema de archivos de Streamlit Cloud se borra cuando la app se reinicia: usuarios, casos y auditoría se pierden. Antes de cada reinicio, descarga un respaldo desde **Respaldos**.

## 1. Subir el repositorio a GitHub

1. Crea un repositorio **privado** en GitHub (por ejemplo, `periovision`).
2. Desde la carpeta `proyecto`:

   ```bash
   git remote add origin https://github.com/<tu-usuario>/periovision.git
   git push -u origin main --tags
   ```

`.gitignore` deja fuera los datos de uso (`datos/`), las credenciales, los secretos y los pesos (`*.pt`).

## 2. Publicar los pesos del modelo

Elige una opción y regístrala en el control de cambios:

- **A. URL privada (recomendada, respeta la custodia separada de los pesos):** sube `best.pt` a un almacenamiento con enlace privado y ponlo en los secrets (paso 4) junto con su huella. La app descarga los pesos una vez y los descarta si la huella no coincide.
- **B. Repositorio privado:** `git add -f best.pt` y haz un commit. Es más simple, pero los pesos quedan dentro del repositorio técnico.

Huella SHA-256 de `best.pt` (versión actual):

```
0ddce02e5149067d01464c4ee611e2fb6beb87f2f4a9f23934822da76b355eaa
```

## 3. Crear la app

1. Entra a [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub.
2. **Create app** › repositorio `periovision`, rama `main`, archivo `app.py`.
3. **Advanced settings** › Python **3.12**.

Streamlit Cloud instala `packages.txt` (librerías del sistema para OpenCV) y `requirements.txt` (versiones fijadas; PyTorch solo CPU).

## 4. Configurar los secrets

En **Advanced settings › Secrets**, pega el contenido de `.streamlit/secrets.toml.example` con valores reales:

```toml
[periovision]
admin_user = "admin"
admin_password = "<clave inicial segura>"
model_url = "<enlace privado a best.pt>"          # solo opción A
model_sha256 = "0ddce02e5149067d01464c4ee611e2fb6beb87f2f4a9f23934822da76b355eaa"
```

El administrador inicial se crea solo si no hay usuarios y debe cambiar la clave al entrar.

## 5. Validar el despliegue

Después de publicar, sigue la lista de `evidencias/validacion_tecnica.md`:

1. La app abre y muestra el acceso con `periovision-1.2.0`.
2. El administrador entra, cambia la clave y ve **Estado del sistema** con el modelo Activo.
3. **Modelo y calibración › Verificar modelo** muestra las cuatro clases.
4. Crea un usuario con COP, entra con él, analiza `ejemplos/radiografia_ejemplo.jpg`, registra la revisión y descarga el PDF.
5. **Pruebas QA › Ejecutar pruebas** da APTA.
6. Descarga un respaldo desde **Respaldos**.

## Volver a la versión anterior

```bash
git checkout v1.0.0     # demo original
git checkout main       # versión vigente
```
