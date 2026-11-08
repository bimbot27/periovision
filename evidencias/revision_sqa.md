# Acta de revisión SQA · PerioVision 1.2.0

- **Fecha:** 08/11/2026
- **Alcance:** `app.py`, `core.py`, `auth.py`, `informe.py`, `evaluacion.py`, `datos.py`, `metrics_csv.py`, `crear_usuarios.py`, `ejecutar_pruebas_qa.py`
- **Herramientas:** ruff 0.17.4, radon 6.0.1, coverage 7.17.2, pip-audit 2.10.1 (ver `requirements-dev.txt`)
- **Dictamen:** APROBADA con deuda técnica registrada

## Lista de verificación

| N.º | Criterio | Método | Resultado inicial | Acción | Resultado final |
|---|---|---|---|---|---|
| 1 | Estándar de código y errores probables | `ruff check --select E,F,W,B,S` | 13 avisos (2 imports sin uso, 4 `zip` sin `strict`, 3 nombres ambiguos, 1 `raise` sin `from`, 1 import múltiple, 2 de seguridad) | Corregidos | 0 avisos |
| 2 | Seguridad estática (reglas Bandit S) | ruff S | S310: la descarga del modelo aceptaba cualquier esquema de URL (`file:`, `http:`); S603: `subprocess` | S310: solo `https://`. S603: argumentos fijos, justificado | 0 avisos |
| 3 | Complejidad ciclomática | `radon cc` | Promedio B (5,4); `analyze_page` E (38) | `analyze_page` dividida en 9 funciones | Promedio B; ninguna función E; `analyze_page` A |
| 4 | Mantenibilidad | `radon mi` | Módulos de lógica A (22–87); `app.py` C por tamaño | Registrada como deuda técnica DT-01 | Sin cambio |
| 5 | Cobertura de pruebas | `coverage` sobre la batería completa | — | — | Total 75 %: core 94 %, evaluacion 95 %, informe 95 %, auth 88 %, datos 87 %, metrics_csv 67 %, app 55 % |
| 6 | Vulnerabilidades en dependencias | `pip-audit` (OSV/PyPI) | — | — | 0 vulnerabilidades conocidas en 89 paquetes |
| 7 | Pruebas | `ejecutar_pruebas_qa.py` | 121/121 | — | 121/121, dictamen APTA |
| 8 | Gestión de configuración | Revisión de git y `.gitignore` | Sin control de versiones | Repositorio git con línea base `v1.0.0`, versión `v1.2.0`, dependencias fijadas | Datos, credenciales, secretos y pesos fuera del repositorio |
| 9 | Trazabilidad | Matriz requisito → prueba → evidencia | — | `evidencias/trazabilidad.md` | 10/10 RF y 10/10 RNF con prueba o pendiente explícito |
| 10 | Documentación | Revisión de `LEEME.md` y `DESPLIEGUE.md` | — | Guía de despliegue y de pruebas | Completa |

## Deuda técnica registrada

| ID | Descripción | Impacto | Acción propuesta |
|---|---|---|---|
| DT-01 | `app.py` concentra todas las vistas (~1 100 líneas); `users_page` D (30) y `data_page` D (22) | Mantenibilidad (RNF08) | Separar vistas de administrador y de usuario en módulos propios |
| DT-02 | `app.py` con 55 % de cobertura: la carga de archivos no se puede simular con AppTest | Riesgo de regresión en la interfaz | Automatizar la E2E con Playwright |
| DT-03 | `compute_metrics` D (29) | Mantenibilidad | Extraer la matriz de confusión a su propia función |

## Firmas

| Rol | Nombre | Fecha |
|---|---|---|
| QA (revisor) | Pendiente de firma | |
| Integración | Pendiente de firma | |
| Coordinación | Pendiente de firma | |
