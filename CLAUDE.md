# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Fuente de verdad

`SPEC.md` es el spec oficial. Consúltalo antes de decidir cualquier cosa de implementación; el código y los docstrings citan sus secciones (`seccion 9.1`, etc.). Si tomas una decisión que el spec no cubre, añádela al spec. `estructuras_proyecto.md` es un documento de decisión ya superado (se eligió la Opción B, Domain-First).

Mostrador reformatea un `.docx`/`.doc` a APA, IEEE o Vancouver. Documentación y comentarios están en español (sin tildes en el código).

## Comandos

Usa el venv del repo (`.venv`, Python 3.11) y trabaja desde `mostrador/`: ahí viven `conftest.py` y los paquetes `engine`, `webapp`.

```bash
# instalar dependencias (desde la raíz)
.venv/Scripts/python.exe -m pip install -r requirements.txt

# tests completos / un archivo / un test (desde mostrador/)
cd mostrador
../.venv/Scripts/python.exe -m pytest -q
../.venv/Scripts/python.exe -m pytest tests/formatting/test_docx_builder.py -q
../.venv/Scripts/python.exe -m pytest tests/classification/test_fallback.py -k "rate_limit" -q

# corrida manual con documentos reales (desde mostrador/). HACE LLAMADAS REALES a Gemini:
# el contenido de los documentos sale hacia ese servicio. Informe en ../real_runs/<fecha>/report.md
../.venv/Scripts/python.exe tools/run_real.py "../documentos prueba" --styles apa

# servidor web (desde la raíz; es lo que usa .claude/launch.json)
.venv/Scripts/python.exe -m uvicorn --app-dir mostrador webapp.main:app --port 8000
```

No hay linter ni formateador configurados. Hay tests unitarios por módulo y `tests/test_pipeline_e2e.py` (pipeline completo con `.docx` generados por `tests/fixtures/docx_factory.py`); no existen tests de la webapp.

## Configuración y entorno

- Copia `.env.example` a `.env` en la raíz del repo (no en `mostrador/`). `GEMINI_API_KEY` es obligatoria; `GROQ_API_KEY` activa el fallback. Nunca leas ni imprimas `.env`.
- `LIBREOFFICE_BIN` debe apuntar al binario `soffice` si no está en PATH (el preview y la conversión `.doc` lo necesitan; en la máquina de desarrollo está en `C:\Program Files\LibreOffice\program\soffice.exe` pero no en PATH). El preview es no fatal: si falla, el `.docx` se entrega igual.
- Los documentos procesados se guardan en `storage/` (raíz del repo, relativo al cwd del servidor; se cambia con `MOSTRADOR_STORAGE_DIR`). Esa carpeta contiene datos de usuario/pruebas: no la borres ni la comitees.
- `.gitignore` excluye `.env`, `.venv/`, `storage/` y `output/`.

## Arquitectura

Dos paquetes bajo `mostrador/`, con una regla dura (spec §9.1): **`engine/` nunca importa FastAPI ni lee `os.environ`**. Toda configuración llega como un `ProcessingConfig` (en `engine/document/models.py`) construido por `webapp/config.py`, que es el único lugar que lee variables de entorno y `.env`. `webapp/api/routes.py` fuerza `config.output_dir` al directorio de storage para que el pipeline escriba directamente en su destino final.

**Punto de entrada del motor:** `engine.core.pipeline.run(doc_path, config, *, overwrite_styles=False) -> ProcessingResult`. Nunca lanza: toda `MostradorError` (definidas en `engine/core/exceptions.py`) se convierte en `ProcessingResult(success=False, error_code=..., user_message=...)`. Ejecuta los 7 pasos del spec sobre un `PipelineContext` mutable (`_step1_upload` … `_step7_deliver`) y limpia su directorio temporal en éxito y error.

**Contrato IA ↔ código:** `SemanticBlock` (en `models.py`) es lo que cruza la frontera.
- `engine/document/` (extractor, validator, store, models): pasos 1–2, lectura con `python-docx` + `lxml`, rechazo de corruptos/protegidos/vacíos/escaneados. `validator.py` solo hace validación semántica; la corrupción y las contraseñas ya las detecta `extractor.py`.
- `engine/classification/`: paso 3. Gemini solo asigna roles semánticos (JSON); nunca decide estilo visual. `_shared.py` tiene `build_prompt` y `parse_and_apply` compartidos entre `gemini_classifier.py` y `fallback.py` (Groq vía SDK de OpenAI, solo ante rate limit de Gemini).
- `engine/formatting/`: pasos 4–6, 100 % determinístico. Todo el estilo (paleta, portada, separadores, índice) sale de `TEMPLATES[style]` en `templates.py`; `template_engine.py` lo aplica a los roles, `docx_builder.py` genera el `.docx` (y `pipeline._step5_validate_output_schema` lo valida contra los XSD ECMA-376 de `engine/document/schemas/ooxml/` vía `xsd_validator.py`; si falla borra la salida y devuelve `OUTPUT_SCHEMA_INVALID`; se desactiva con `ProcessingConfig.validate_output_xsd=False`), `preview_renderer.py` produce un PNG de la primera página con `soffice --convert-to png` (ya no se usa `pdftoppm`, aunque el spec aún lo menciona).

**Reglas de negocio que atraviesan varios archivos:**
- Una sola llamada a Gemini por documento, sin chunking (spec §9).
- Conflicto de estilos (spec §7): la primera pasada devuelve `error_code="CONFLICTING_STYLES"`; `routes.py` guarda el archivo subido en memoria (`_PENDING_OVERWRITES`) bajo un `pending_id`, el frontend pide confirmación y `confirm-overwrite` reejecuta `run(..., overwrite_styles=True)`, que genera un `processing_id` nuevo.
- Concurrencia 1: `_PROCESSING_LOCK` (asyncio.Lock) en `routes.py` serializa `pipeline.run`, que corre en `asyncio.to_thread`.

**Frontend:** `webapp/static/` (HTML/JS/CSS plano, sin build), servido por `webapp/main.py`; la API cuelga de `/api`.

## Tests

`mostrador/conftest.py` añade `mostrador/`, `mostrador/engine/` y `mostrador/engine/document/` a `sys.path`, así que los tests pueden importar tanto `engine.document.models` como `models` a secas. Respeta el estilo de import del test que edites: mezclar ambos puede crear dos copias del mismo módulo (y clases/excepciones distintas). Los tests de clasificación usan dobles, no llaman a Gemini/Groq reales; el e2e parchea `engine.classification.gemini_classifier.classify` (el pipeline lo importa de forma perezosa) y solo ejecuta el test de preview real si encuentra `soffice`.
