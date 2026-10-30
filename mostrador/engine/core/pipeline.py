"""
engine/core/pipeline.py
========================
Orquestador del pipeline de 7 pasos de Mostrador (seccion 5 del spec).

Punto de entrada publico del motor::

    from engine.core.pipeline import run
    result = run(doc_path, config)  # devuelve siempre un ProcessingResult

Responsabilidades
-----------------
* Ejecuta los 7 pasos en orden via un PipelineContext mutable.
* Convierte TODA excepcion de dominio (MostradorError y subclases) en
  ProcessingResult(success=False) antes de devolverla al caller.
  Nunca lanza excepciones no capturadas hacia webapp (regla seccion 9.1).
* Implementa el fallback a Groq cuando Gemini devuelve rate limit y
  ProcessingConfig.groq_api_key no es None (seccion 9).
* Maneja ConflictingStylesError como pausa recuperable (seccion 7):
  - Primera llamada: devuelve error_code="CONFLICTING_STYLES".
  - Webapp muestra dialogo de confirmacion al usuario.
  - Segunda llamada con overwrite_styles=True: el pipeline continua.
* Garantiza limpieza del directorio temporal en exito y en error.

Regla seccion 9.1: NO importa nada de webapp/, FastAPI, Flask ni os.environ.
Toda configuracion llega via ProcessingConfig.

Mapa paso -> funcion interna
----------------------------
Paso 1  _step1_upload            validacion de tamano y formato
Paso 2a _step2a_convert_if_doc   .doc -> .docx via LibreOffice headless
Paso 2b _step2b_extract          extraccion de SemanticBlock[] con python-docx
Paso 2c _step2c_validate         validacion semantica del documento
Paso 3  _step3_classify          clasificacion con Gemini (+ fallback Groq)
Paso 4  _step4_apply_template    aplicacion deterministica del TEMPLATES[style]
Paso 5  _step5_build_docx        generacion del .docx final (+ validacion XSD, 5b)
Paso 6  _step6_render_preview    preview via LibreOffice headless + pdftoppm
Paso 7  _step7_deliver           empaquetado del ProcessingResult
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from engine.document.models import (
    DocumentLanguage,
    DocumentMeta,
    ProcessingConfig,
    ProcessingResult,
    SemanticBlock,
)
from engine.core.exceptions import (
    ClassificationError,
    ConflictingStylesError,
    FileSizeExceededError,
    GeminiRateLimitError,
    MostradorError,
    OutputSchemaValidationError,
    PipelineError,
    PreviewRenderError,
    UnsupportedFormatError,
)

logger = logging.getLogger(__name__)

# Extensiones aceptadas en v1 (seccion 3 del spec)
_ACCEPTED_EXTENSIONS: frozenset[str] = frozenset({".docx", ".doc"})


# ---------------------------------------------------------------------------
# Contexto mutable que viaja por todos los pasos
# ---------------------------------------------------------------------------

@dataclass
class PipelineContext:
    """
    Estado compartido entre los pasos del pipeline.

    Se construye al inicio de run() y cada paso lo modifica in-place.
    No es parte de la API publica del motor: solo pipeline.py lo usa.
    """

    # --- Entrada ---
    original_path: Path
    """Ruta al archivo subido por el usuario. Nunca se modifica."""

    config: ProcessingConfig
    """Configuracion inyectada por el caller (regla seccion 9.1)."""

    # --- Sesion ---
    processing_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    work_dir: Path | None = None
    """Directorio temporal creado en Paso 1 y eliminado en Paso 7."""

    working_docx: Path | None = None
    """Ruta al .docx activo (original o resultado de la conversion .doc)."""

    # --- Datos del documento ---
    meta: DocumentMeta | None = None
    blocks: list[SemanticBlock] = field(default_factory=list)

    # --- Artefactos de salida ---
    output_docx: Path | None = None
    preview_path: Path | None = None

    # --- Flags de flujo ---
    gemini_rate_limited: bool = False
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# Punto de entrada publico
# ---------------------------------------------------------------------------

def run(
    doc_path: Path,
    config: ProcessingConfig,
    *,
    overwrite_styles: bool = False,
) -> ProcessingResult:
    """
    Ejecuta el pipeline completo de 7 pasos sobre el documento dado.

    Es el unico punto de entrada publico del motor. El caller nunca llama
    a los pasos individuales directamente.

    Parameters
    ----------
    doc_path:
        Ruta al archivo subido por el usuario (.docx o .doc).
    config:
        Configuracion inyectada (API keys, estilo, limites, rutas).
    overwrite_styles:
        Si True, el pipeline ignora ConflictingStylesError y sobrescribe
        los estilos conflictivos sin pausar (seccion 7). Debe pasarse como
        True solo cuando el usuario confirmo la sobrescritura en el dialogo
        web.

    Returns
    -------
    ProcessingResult
        Siempre. Nunca lanza excepciones al caller (regla seccion 9.1).

    Flujo de ConflictingStylesError (seccion 7)
    --------------------------------------------
    1. Primera llamada sin overwrite_styles -> devuelve
       ProcessingResult(success=False, error_code="CONFLICTING_STYLES").
    2. Webapp muestra dialogo al usuario.
    3. Si el usuario confirma -> webapp llama run() con overwrite_styles=True
       y el pipeline continua normalmente.
    """
    ctx = PipelineContext(original_path=doc_path, config=config)

    try:
        # Paso 1: validacion de entrada
        _step1_upload(ctx)

        # Paso 2: extraccion y validacion del documento
        _step2a_convert_if_doc(ctx)
        _step2b_extract(ctx)
        try:
            _step2c_validate(ctx)
        except ConflictingStylesError as exc:
            if not overwrite_styles:
                logger.info(
                    "[Paso 2c] Conflicto de estilos — esperando confirmacion. "
                    "processing_id=%s", ctx.processing_id
                )
                return _make_error_result(ctx, exc)
            logger.info(
                "[Paso 2c] Conflicto de estilos aceptado por el usuario — continuando."
            )

        # Paso 3: clasificacion semantica (Gemini / fallback Groq)
        _step3_classify(ctx)

        # Paso 4: aplicacion deterministica del template
        _step4_apply_template(ctx)

        # Paso 5: generacion del .docx final
        _step5_build_docx(ctx)

        # Paso 6: preview (no fatal si falla)
        _step6_render_preview(ctx)

        # Paso 7: empaquetar y entregar
        return _step7_deliver(ctx)

    except GeminiRateLimitError as exc:
        # Rate limit sin fallback disponible (seccion 9)
        logger.warning(
            "[Pipeline] Rate limit Gemini sin fallback. processing_id=%s",
            ctx.processing_id,
        )
        result = _make_error_result(ctx, exc)
        result.gemini_rate_limited = True
        return result

    except ClassificationError as exc:
        logger.error(
            "[Pipeline] Error de clasificacion: %s | %s",
            exc.error_code, exc.details,
        )
        return _make_error_result(ctx, exc)

    except MostradorError as exc:
        logger.error(
            "[Pipeline] Error de dominio [%s]: %s | details: %s",
            exc.error_code, exc.message, exc.details,
        )
        return _make_error_result(ctx, exc)

    except Exception as exc:
        # Captura de ultimo recurso: envuelve en PipelineError para que
        # el caller siempre reciba un ProcessingResult (regla seccion 9.1)
        step = _infer_step_from_context(ctx)
        wrapped = PipelineError(step=step, cause=exc)
        logger.exception(
            "[Pipeline] Error inesperado en paso %d. processing_id=%s",
            step, ctx.processing_id,
        )
        return _make_error_result(ctx, wrapped)


# ---------------------------------------------------------------------------
# Implementaciones de los pasos (stubs con contratos completos)
# Cada modulo de dominio implementara la logica real cuando sea su turno.
# ---------------------------------------------------------------------------

def _step1_upload(ctx: PipelineContext) -> None:
    """
    Paso 1: Validar tamano y formato del archivo antes de tocarlo (seccion 3).

    Raises
    ------
    UnsupportedFormatError
        Si la extension no es .docx ni .doc.
    FileSizeExceededError
        Si el archivo supera config.max_file_size_bytes.
    """
    path = ctx.original_path
    ext = path.suffix.lower()

    if ext not in _ACCEPTED_EXTENSIONS:
        raise UnsupportedFormatError(filename=path.name, detected_format=ext)

    size = path.stat().st_size
    if size > ctx.config.max_file_size_bytes:
        raise FileSizeExceededError(
            file_size_bytes=size,
            max_size_bytes=ctx.config.max_file_size_bytes,
        )

    # Copiar al directorio temporal para no tocar jamas el original
    ctx.work_dir = Path(tempfile.mkdtemp(prefix=f"mostrador_{ctx.processing_id}_"))
    ctx.working_docx = ctx.work_dir / path.name
    shutil.copy2(path, ctx.working_docx)

    logger.info("[Paso 1] Archivo aceptado: %s (%d bytes)", path.name, size)


def _step2a_convert_if_doc(ctx: PipelineContext) -> None:
    """
    Paso 2a: Convertir .doc a .docx via LibreOffice headless si aplica (seccion 3).

    Si el archivo ya es .docx, este paso es un no-op.

    Raises
    ------
    ConversionError
        Si LibreOffice falla o no esta instalado.
    """
    if ctx.working_docx and ctx.working_docx.suffix.lower() == ".doc":
        from engine.document.extractor import convert_doc_to_docx  # noqa: PLC0415
        logger.info("[Paso 2a] Convirtiendo .doc -> .docx: %s", ctx.working_docx.name)
        ctx.working_docx = convert_doc_to_docx(
            doc_path=ctx.working_docx,
            work_dir=ctx.work_dir,
            libreoffice_bin=ctx.config.libreoffice_bin,
        )
        if ctx.meta:
            ctx.meta.was_converted = True
        logger.info("[Paso 2a] Conversion completada: %s", ctx.working_docx.name)


def _step2b_extract(ctx: PipelineContext) -> None:
    """
    Paso 2b: Extraer SemanticBlock[] del .docx via python-docx + lxml (seccion 5, Paso 2).

    Raises
    ------
    DocumentCorruptError
        Si el archivo no puede abrirse ni parsearse.
    PasswordProtectedError
        Si el documento esta protegido con contrasena.
    ScannedDocumentError
        Si no contiene texto seleccionable.
    EmptyDocumentError
        Si el bloque de contenido extraido esta vacio.
    """
    from engine.document.extractor import extract_blocks  # noqa: PLC0415
    logger.info("[Paso 2b] Extrayendo contenido de: %s", ctx.working_docx)
    ctx.blocks, ctx.meta = extract_blocks(
        docx_path=ctx.working_docx,
        processing_id=ctx.processing_id,
        original_filename=ctx.original_path.name,
    )
    logger.info("[Paso 2b] %d bloques extraidos.", len(ctx.blocks))


def _step2c_validate(ctx: PipelineContext) -> None:
    """
    Paso 2c: Validar el documento contra los criterios del spec (secciones 3 y 7).

    Raises
    ------
    EmptyDocumentError
        Si block_count == 0.
    ConflictingStylesError
        Si hay estilos conflictivos (recuperable — pipeline pausa, seccion 7).
    """
    from engine.document.validator import validate_document  # noqa: PLC0415
    logger.info("[Paso 2c] Validando documento.")
    validate_document(meta=ctx.meta, blocks=ctx.blocks, config=ctx.config)
    logger.info(
        "[Paso 2c] Validacion completada. is_valid=%s",
        ctx.meta.is_valid if ctx.meta else "?",
    )


def _step3_classify(ctx: PipelineContext) -> None:
    """
    Paso 3: Clasificacion semantica via Gemini (seccion 5, Paso 3).

    Invariante del sistema (seccion 5 — principio arquitectonico clave):
        Gemini SOLO asigna SemanticRole a cada bloque.
        NUNCA decide color, tipografia, estructura de portada ni espaciado.
        Esas decisiones son exclusivas del TEMPLATES dict (Paso 4).

    Si Gemini devuelve rate limit y config.groq_api_key no es None,
    intenta el fallback a Groq (seccion 9).

    Raises
    ------
    GeminiRateLimitError
        Si Gemini devuelve 429 y no hay fallback configurado.
    GeminiAPIError
        Si Gemini falla por otra razon (credencial invalida, red, etc.).
    GroqAPIError
        Si el fallback a Groq tambien falla.
    InvalidClassificationResponseError
        Si la respuesta JSON no puede parsearse como SemanticBlock[].
    """
    from engine.classification.gemini_classifier import classify  # noqa: PLC0415
    lang = ctx.meta.detected_language if ctx.meta else DocumentLanguage.UNKNOWN
    logger.info(
        "[Paso 3] Clasificando %d bloques con Gemini (%s).",
        len(ctx.blocks), ctx.config.gemini_model,
    )
    try:
        ctx.blocks = classify(
            blocks=ctx.blocks,
            api_key=ctx.config.gemini_api_key,
            model=ctx.config.gemini_model,
            language=lang,
        )
        logger.info("[Paso 3] Clasificacion completada.")
    except GeminiRateLimitError:
        ctx.gemini_rate_limited = True
        if ctx.config.groq_api_key:
            logger.warning("[Paso 3] Rate limit Gemini — activando fallback a Groq.")
            _step3_classify_fallback(ctx)
        else:
            logger.error("[Paso 3] Rate limit Gemini sin fallback configurado.")
            raise


def _step3_classify_fallback(ctx: PipelineContext) -> None:
    """
    Paso 3 (fallback): Clasificacion via Groq cuando Gemini esta en rate limit (seccion 9).

    Solo se invoca si config.groq_api_key no es None.
    Si Groq tambien falla, propaga GroqAPIError hacia run().
    """
    from engine.classification.fallback import classify_with_groq  # noqa: PLC0415
    lang = ctx.meta.detected_language if ctx.meta else DocumentLanguage.UNKNOWN
    ctx.blocks = classify_with_groq(
        blocks=ctx.blocks,
        api_key=ctx.config.groq_api_key,
        model=ctx.config.groq_model,
        language=lang,
    )
    ctx.fallback_used = True
    logger.info("[Paso 3 fallback] Clasificacion via Groq completada.")


def _step4_apply_template(ctx: PipelineContext) -> None:
    """
    Paso 4: Aplicacion deterministica del template (seccion 5, Paso 4).

    Toda decision de estilo (color, tipografia, espaciado, portada) proviene
    del TEMPLATES dict definido en formatting/templates.py (seccion 4).
    Ninguna decision de estilo se toma aqui ni en Paso 3.

    Raises
    ------
    TemplateNotFoundError
        Si config.style no existe en TEMPLATES.
    TemplateApplicationError
        Si un bloque no puede procesarse por datos inconsistentes.
    """
    from engine.formatting.template_engine import apply_template  # noqa: PLC0415
    logger.info("[Paso 4] Aplicando template '%s'.", ctx.config.style.value)
    ctx.blocks = apply_template(blocks=ctx.blocks, style=ctx.config.style)
    logger.info("[Paso 4] Template aplicado.")


def _step5_build_docx(ctx: PipelineContext) -> None:
    """
    Paso 5: Generar el .docx final via python-docx (seccion 5, Paso 5).

    El archivo de salida se escribe en:
        config.output_dir / {processing_id}.docx

    Se le pasa ctx.working_docx como `source_docx_path` para que
    docx_builder.py pueda copiar los bytes de las imagenes embebidas
    (seccion 7) desde el paquete OOXML original, y el idioma detectado
    para el titulo del indice y de la seccion de referencias (seccion 7).

    Raises
    ------
    DocxBuildError
        Si python-docx no puede construir el documento.
    """
    from engine.formatting.docx_builder import build_docx  # noqa: PLC0415
    out_path = ctx.config.output_dir / f"{ctx.processing_id}.docx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("[Paso 5] Generando .docx en: %s", out_path)
    lang = ctx.meta.detected_language if ctx.meta else DocumentLanguage.UNKNOWN
    build_docx(
        blocks=ctx.blocks,
        style=ctx.config.style,
        output_path=out_path,
        source_docx_path=ctx.working_docx,
        language=lang,
    )
    ctx.output_docx = out_path
    logger.info("[Paso 5] .docx generado correctamente.")

    if ctx.config.validate_output_xsd:
        _step5_validate_output_schema(ctx)


def _step5_validate_output_schema(ctx: PipelineContext) -> None:
    """
    Paso 5b: validar el .docx generado contra los XSD de OpenXML (seccion 6).

    Un fallo es un defecto del motor, no del documento del usuario: se borra
    el archivo de salida para no entregar un .docx potencialmente corrupto.

    Raises
    ------
    OutputSchemaValidationError
        Si el paquete no cumple el esquema.
    """
    from engine.document.xsd_validator import validate_docx_against_xsd  # noqa: PLC0415
    errors = validate_docx_against_xsd(ctx.output_docx)
    if errors:
        ctx.output_docx.unlink(missing_ok=True)
        ctx.output_docx = None
        raise OutputSchemaValidationError(errors)
    logger.info("[Paso 5b] El .docx de salida cumple el esquema XSD.")


def _step6_render_preview(ctx: PipelineContext) -> None:
    """
    Paso 6: Generar imagen de preview via LibreOffice headless + pdftoppm (seccion 5, Paso 6).

    Este paso es NO FATAL (seccion 3): si falla, ctx.preview_path queda en
    None y el pipeline continua. El .docx de salida sigue siendo valido y
    descargable.

    Nunca re-lanza PreviewRenderError. Lo registra en logs y continua.
    """
    from engine.formatting.preview_renderer import render_preview  # noqa: PLC0415
    preview_out = ctx.config.output_dir / f"{ctx.processing_id}_preview.png"
    logger.info("[Paso 6] Generando preview en: %s", preview_out)
    try:
        render_preview(
            docx_path=ctx.output_docx,
            output_path=preview_out,
            libreoffice_bin=ctx.config.libreoffice_bin,
        )
        ctx.preview_path = preview_out
        logger.info("[Paso 6] Preview generada correctamente.")
    except PreviewRenderError as exc:
        logger.warning(
            "[Paso 6] Fallo al generar preview (no fatal). details=%s", exc.details
        )


def _step7_deliver(ctx: PipelineContext) -> ProcessingResult:
    """
    Paso 7: Empaquetar el resultado para el caller (seccion 5, Paso 7).

    Convierte el PipelineContext en un ProcessingResult inmutable y limpia
    el directorio temporal de trabajo antes de devolver.
    """
    _cleanup_work_dir(ctx)
    logger.info(
        "[Paso 7] Entregando resultado. processing_id=%s output_docx=%s",
        ctx.processing_id, ctx.output_docx,
    )
    return ProcessingResult(
        processing_id=ctx.processing_id,
        success=True,
        output_docx_path=ctx.output_docx,
        preview_path=ctx.preview_path,
        doc_meta=ctx.meta,
        gemini_rate_limited=ctx.gemini_rate_limited,
        fallback_used=ctx.fallback_used,
    )


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _cleanup_work_dir(ctx: PipelineContext) -> None:
    """Elimina el directorio temporal de trabajo si existe."""
    if ctx.work_dir and ctx.work_dir.exists():
        try:
            shutil.rmtree(ctx.work_dir)
        except OSError as exc:
            logger.warning(
                "No se pudo eliminar el directorio temporal %s: %s",
                ctx.work_dir, exc,
            )


def _make_error_result(
    ctx: PipelineContext,
    exc: MostradorError,
) -> ProcessingResult:
    """
    Convierte una MostradorError en un ProcessingResult de fallo.
    Limpia el directorio temporal antes de devolver.
    """
    _cleanup_work_dir(ctx)
    return ProcessingResult(
        processing_id=ctx.processing_id,
        success=False,
        error_code=exc.error_code,
        error_message=exc.message,
        doc_meta=ctx.meta,
        gemini_rate_limited=ctx.gemini_rate_limited,
        fallback_used=ctx.fallback_used,
    )


def _infer_step_from_context(ctx: PipelineContext) -> int:
    """
    Infiere el paso del pipeline donde ocurrio un error inesperado,
    basandose en el estado del contexto. Usado solo por PipelineError.
    """
    if ctx.output_docx:
        return 6   # docx generado pero fallo en preview (paso 6)
    if ctx.blocks and any(b.role.value != "unknown" for b in ctx.blocks):
        return 5   # bloques clasificados pero sin docx -> fallo en build (paso 5)
    if ctx.blocks:
        return 3   # bloques extraidos sin clasificar -> fallo en clasificacion (paso 3)
    if ctx.meta:
        return 2   # meta creada sin bloques -> fallo en extraccion (paso 2)
    if ctx.work_dir:
        return 1   # directorio creado pero sin meta -> fallo en conversion (paso 2a)
    return 1       # sin contexto alguno -> fallo en upload (paso 1)
