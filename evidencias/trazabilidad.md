# Matriz de trazabilidad · PerioVision 1.2.0

Fecha: 08/11/2026. Un requisito cuenta para I12 si tiene al menos una prueba ejecutada y su evidencia en el repositorio. La aceptación externa se registra aparte.

**I12 = 20/20 = 100 %**

| Requisito | Historia | Pruebas (ID) | Evidencia | Estado | Nota |
|---|---|---|---|---|---|
| RF01 | HU01 | 33, 37, 65, 75, 87 | log QA; auditoria.jsonl | Verificado | Roles reducidos a administrador y usuario por pedido del cliente (cambio de alcance a registrar) |
| RF02 | HU01 | 107, 108 | log QA; página Datos | Verificado | Texto impreso en píxeles requiere revisión visual |
| RF03 | HU02 | 20–23, 108 | log QA; página Datos | Verificado | Inventario real pendiente |
| RF04 | HU02 | 109 | log QA; instrumentos/etiquetas_lectores_I09.csv | Parcial | Herramienta de kappa probada; acta de consenso clínico pendiente |
| RF05 | HU03 | 01–06, 71, 117, 120 | log QA; E2E pasos 3–4 | Verificado |  |
| RF06 | HU04 | 57, 58, 61, 72 | log QA; E2E paso 4 | Verificado |  |
| RF07 | HU05 | 12–15, 73, 113, 119, 121 | log QA; E2E paso 6 | Verificado |  |
| RF08 | HU06 | 16–17, 42–44, 74, 93 | log QA; E2E pasos 6–7 | Verificado |  |
| RF09 | HU07 | 25–30, 102–106 | log QA; página Evaluación del modelo | Verificado | Ejecución sobre la prueba congelada pendiente de datos |
| RF10 | HU08 | Ejecutor QA (121+ pruebas) | evidencias/trazabilidad.md; indicadores.json; git | Verificado | Costos y actas EDT a cargo de coordinación |
| RNF01 | — | 102–105 (herramienta) | indicadores.json | Medido, no cumple | Validación: I01–I06 bajo la meta; prueba congelada pendiente |
| RNF02 | — | 83–86 | rendimiento.json; E2E paso 4 | Verificado |  |
| RNF03 | — | 95–100 | log QA; instrumentos/ficha_tareas_I10.csv | Parcial | Piloto con 3 usuarios pendiente |
| RNF04 | — | 31–40, 87–94, 101, 122, 123 | log QA; auditoria_dependencias.json | Verificado | Clave de Roboflow expuesta en el notebook: revocar |
| RNF05 | — | 24, 76 | log QA | Verificado |  |
| RNF06 | — | 105 | requirements.txt fijado; git v1.2.0; huella de best.pt | Verificado | Semilla y data.yaml del entrenamiento pendientes |
| RNF07 | — | 110–112, 115, 116 | log QA; página Respaldos | Verificado |  |
| RNF08 | — | SQA (ruff, radon) | revision_sqa.md; validacion_tecnica.md | Verificado | Deuda técnica DT-01 registrada |
| RNF09 | — | 03, 10, 11, 101 | log QA | Verificado |  |
| RNF10 | — | 82, 90, 118 | DESPLIEGUE.md; validacion_tecnica.md | Verificado | Uso en nube solo con datos de demostración |
