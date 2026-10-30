# Propuestas de Estructura — Mostrador

Basado en el análisis del `SPEC-DRIVEN_DEVELOPMENT.md`.

---

## Opción A — Monolito por Capas (Layer-First)

```
mostrador/
├── main.py                    # Entrada: servidor web (FastAPI/Flask)
├── config.py                  # TEMPLATES dict (APA, IEEE, Vancouver)
├── templates/
│   ├── styles.xml
│   └── numbering.xml
│
├── api/
│   └── routes.py              # Endpoints: /upload, /download, /delete
│
├── pipeline/
│   ├── __init__.py
│   ├── step1_upload.py        # Validación y recepción del archivo
│   ├── step2_extract.py       # python-docx + lxml → estructura semántica
│   ├── step3_classify.py      # Llamada a Gemini → roles semánticos (JSON)
│   ├── step4_apply_template.py # Determinístico: TEMPLATES[style] → roles
│   ├── step5_generate_docx.py  # Construcción del .docx final
│   ├── step6_preview.py       # LibreOffice headless + pdftoppm
│   └── step7_deliver.py       # Respuesta al usuario (URL de descarga)
│
├── services/
│   ├── gemini_client.py       # Wrapper de la API de Gemini
│   └── libreoffice.py         # Wrapper de LibreOffice headless
│
├── storage/
│   └── document_store.py      # Almacenamiento + botón de eliminación (§9)
│
├── validators/
│   └── docx_validator.py      # Validación XSD + detección de corrupción
│
├── static/                    # Frontend (HTML/JS del panel web)
└── tests/
    ├── test_pipeline/
    └── fixtures/              # .docx de prueba validados
```

### ✅ Ventajas
- **Alineación directa con el spec**: cada step_N.py mapea 1:1 con los 7 pasos del pipeline (§5), facilitando auditar que el código sigue la especificación.
- **Separación IA / determinístico clara**: `step3_classify.py` vs `step4_apply_template.py` refuerza el principio arquitectónico clave del spec (§5).
- **Bajo overhead**: sin frameworks de orquestación pesados; ideal para la concurrencia de 1 documento a la vez (§9).
- **Fácil onboarding**: cualquier colaborador que lea el spec sabe exactamente en qué archivo buscar cada responsabilidad.
- **Tests por paso**: permite probar cada paso del pipeline de forma aislada con los `.docx` de prueba mencionados en §10.

### ❌ Inconvenientes
- **Escalabilidad limitada**: cuando se añada concurrencia real (v1.1+) o procesamiento asíncrono, habrá que refactorizar `pipeline/` significativamente.
- **Acoplamiento temporal entre pasos**: los pasos se llaman en secuencia directa; introducir un paso nuevo (ej. OCR en v2) implica modificar el flujo central.
- **`config.py` crece con el proyecto**: a medida que se añaden más templates, ese archivo se vuelve un punto de contención y fusión conflictiva en Git.

---

## Opción B — Modular por Dominio (Domain-First / Feature-First)

```
mostrador/
├── main.py                    # Entrada: servidor web
│
├── core/
│   ├── pipeline.py            # Orquestador: ensambla y ejecuta los pasos
│   └── exceptions.py          # Errores de dominio (DocumentCorrupt, etc.)
│
├── document/
│   ├── extractor.py           # python-docx + lxml (Paso 2)
│   ├── validator.py           # Validación XSD, corrupción, límites (§3, §7)
│   ├── store.py               # Almacenamiento + eliminación (§9)
│   └── models.py              # Dataclasses: SemanticBlock, DocumentMeta
│
├── classification/
│   ├── gemini_classifier.py   # Paso 3: llamada a Gemini → roles semánticos
│   └── fallback.py            # (Opcional v1.1) Groq como fallback (§9)
│
├── formatting/
│   ├── templates.py           # TEMPLATES dict: APA, IEEE, Vancouver (§4)
│   ├── template_engine.py     # Paso 4: aplica TEMPLATES[style] a roles
│   ├── docx_builder.py        # Paso 5: genera .docx + styles/numbering.xml
│   └── preview_renderer.py    # Paso 6: LibreOffice headless + pdftoppm
│
├── api/
│   └── routes.py              # /upload, /download, /delete
│
├── static/                    # Frontend (panel web)
│
└── tests/
    ├── document/
    ├── classification/
    ├── formatting/
    └── fixtures/
```

### ✅ Ventajas
- **Alta cohesión por dominio**: todo lo relativo a clasificación vive en `classification/`, todo lo de formato en `formatting/`. Añadir el fallback a Groq (§9) solo toca un módulo.
- **Extensible sin romper contratos**: añadir soporte PDF (v2, §8) o un nuevo template implica añadir archivos dentro del dominio correspondiente, no tocar el pipeline central.
- **`models.py` como contrato explícito**: los dataclasses (`SemanticBlock`, etc.) formalizan el contrato entre el paso 3 (IA) y el paso 4 (determinístico), reforzando la separación del spec.
- **Tests más enfocados**: se prueba `formatting/` sin necesidad de simular Gemini; se prueba `classification/` sin necesidad de un `.docx` real.
- **Mejor para trabajo en equipo**: dos personas pueden trabajar en `classification/` y `formatting/` en paralelo sin conflictos.

### ❌ Inconvenientes
- **El flujo del pipeline es menos obvio**: para entender los 7 pasos hay que leer `core/pipeline.py` y luego rastrear los módulos que invoca; no está en un solo lugar.
- **Más archivos desde el inicio**: para un proyecto que empieza como un solo desarrollador con concurrencia = 1 (§9), puede ser sobreingeniería inicial.
- **Riesgo de abstracción prematura**: si los dominios no están bien definidos desde el principio, los módulos terminan con responsabilidades solapadas (ej. ¿dónde va la conversión DOC→DOCX: en `document/` o en `formatting/`?).

---

## Comparativa rápida

| Criterio | Opción A (Layer-First) | Opción B (Domain-First) |
|---|---|---|
| Alineación con el spec §5 | ⭐⭐⭐ Directa (step_N) | ⭐⭐ Indirecta (via orquestador) |
| Extensibilidad v2+ | ⭐⭐ Requiere refactor | ⭐⭐⭐ Abierta a extensión |
| Legibilidad para 1 dev | ⭐⭐⭐ Muy directa | ⭐⭐ Más archivos |
| Trabajo en equipo | ⭐⭐ Conflictos posibles | ⭐⭐⭐ Módulos independientes |
| Separación IA/determinístico | ⭐⭐⭐ Explícita por archivo | ⭐⭐⭐ Explícita por módulo |
| Preparado para fallback Groq §9 | ⭐⭐ Modificar step3 | ⭐⭐⭐ Añadir fallback.py |

## Recomendación

Para **v1 con 1 desarrollador** → **Opción A** es suficiente y más fiel al spec.  
Para **preparar la base de v1.1+** (Groq fallback, concurrencia, PDF) → **Opción B**.

Una estrategia híbrida viable: comenzar con Opción A y extraer `classification/` y `formatting/` como dominios (Opción B) solo cuando se vayan a tocar esos módulos para añadir features de v1.1.
