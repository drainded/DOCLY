"""
engine/document/validator.py
==============================
Paso 2c del pipeline: validacion semantica del documento ya extraido.

Expone una funcion publica (contrato firmado con pipeline.py):

    validate_document(meta, blocks, config) -> None
        Valida el documento contra los criterios del spec (secciones 3 y 7).
        Modifica meta.is_valid y meta.validation_errors in-place.
        Lanza excepciones de dominio si encuentra problemas bloqueantes.

Responsabilidades de este modulo
---------------------------------
* Doble comprobacion de vaciado (defensa en profundidad): aunque extractor.py
  ya lanza EmptyDocumentError, si por alguna razon llega un meta con
  block_count == 0, este modulo lo detecta y lanza de nuevo.
* Detectar conflictos de estilos Word con el template destino (seccion 7):
  si meta.has_conflicting_styles == True, lanza ConflictingStylesError
  (excepcion RECUPERABLE — pipeline la captura y espera confirmacion del
  usuario antes de continuar). No es un error fatal.
* Confirmar que el tamano del archivo no excede el limite del config
  (doble comprobacion: pipeline.py ya valida esto en el Paso 1, pero el
  archivo puede haber cambiado de tamano si fue convertido de .doc a .docx).
* Si pasa todas las comprobaciones, pone meta.is_valid = True.

Lo que este modulo NO hace
---------------------------
* NO abre ni parsea el .docx — eso ya lo hizo extractor.py.
* NO detecta corrupcion, contrasena ni escaneados — extractor.py ya lo hizo.
* NO decide estilo visual (eso es Paso 4, TEMPLATES dict).
* NO llama a Gemini (eso es Paso 3, classification/).

Orden de comprobaciones (prioridad decreciente)
-------------------------------------------------
1. Documento vacio (block_count == 0) -> EmptyDocumentError (fatal)
2. Tamano excede el limite del config -> FileSizeExceededError (fatal)
   [puede ocurrir post-conversion .doc -> .docx si el .docx es mas grande]
3. Sin bloques de texto util -> EmptyDocumentError (fatal)
4. Conflictos de estilos -> ConflictingStylesError (RECUPERABLE)
5. Advertencias no bloqueantes -> se agregan a meta.validation_errors

Si pasa 1-4 sin lanzar: meta.is_valid = True.
"""

from __future__ import annotations

import logging

from engine.document.models import (
    DocumentMeta,
    ProcessingConfig,
    SemanticBlock,
    SemanticRole,
)
from engine.core.exceptions import (
    ConflictingStylesError,
    EmptyDocumentError,
    FileSizeExceededError,
)

logger = logging.getLogger(__name__)

# Roles que aportan contenido de texto real (excluye IMAGE y EQUATION,
# que no tienen texto seleccionable)
_TEXT_ROLES: frozenset[SemanticRole] = frozenset(
    SemanticRole(r)
    for r in (
        "heading1", "heading2", "heading3", "heading4",
        "body", "list_item", "blockquote", "reference",
        "caption", "table_header", "table_cell",
        "cover_title", "cover_author", "cover_institution",
        "cover_date", "cover_course",
    )
)


# ===========================================================================
# API publica
# ===========================================================================

def validate_document(
    meta: DocumentMeta,
    blocks: list[SemanticBlock],
    config: ProcessingConfig,
) -> None:
    """
    Valida el documento ya extraido contra los criterios del spec (secciones 3 y 7).

    Modifica `meta` in-place:
      - Agrega mensajes a meta.validation_errors para cada problema detectado.
      - Pone meta.is_valid = True solo si supera todas las comprobaciones.

    Parameters
    ----------
    meta:
        Metadatos del documento, construidos por extractor.py.
        Se modifica in-place.
    blocks:
        Lista de SemanticBlock extraidos por extractor.py.
    config:
        Configuracion inyectada por el caller. Se usa para leer
        max_file_size_bytes (regla seccion 9.1).

    Raises
    ------
    EmptyDocumentError
        Si el documento no tiene bloques (block_count == 0) o no tiene
        ningun bloque con texto seleccionable.
    FileSizeExceededError
        Si el archivo excede el limite de tamano del config. Puede ocurrir
        post-conversion .doc -> .docx cuando el .docx resultante es mayor.
    ConflictingStylesError
        Si el documento tiene estilos que entran en conflicto con el
        template destino (RECUPERABLE — pipeline.py captura esta excepcion
        y espera confirmacion del usuario antes de continuar, seccion 7).
    """
    logger.debug(
        "Iniciando validacion. block_count=%d, has_conflicting_styles=%s",
        meta.block_count, meta.has_conflicting_styles,
    )

    # ------------------------------------------------------------------
    # Comprobacion 1: documento vacio (defensa en profundidad)
    # ------------------------------------------------------------------
    if not blocks or meta.block_count == 0:
        meta.is_empty = True
        meta.validation_errors.append("El documento no contiene bloques de contenido.")
        raise EmptyDocumentError(
            filename=meta.original_filename,
            block_count=meta.block_count,
        )

    # ------------------------------------------------------------------
    # Comprobacion 2: tamano del archivo post-conversion (seccion 3)
    # El Paso 1 ya valido el tamano del archivo original; aqui se
    # re-valida porque la conversion .doc -> .docx puede producir un
    # archivo mayor (LibreOffice puede expandir el contenido al convertir).
    # ------------------------------------------------------------------
    if meta.exceeds_size_limit(config):
        limit_mb = config.max_file_size_bytes / 1_048_576
        actual_mb = meta.file_size_bytes / 1_048_576
        msg = (
            f"El documento convertido ({actual_mb:.1f} MB) supera el limite "
            f"de {limit_mb:.0f} MB. Reduce el tamano del archivo original."
        )
        meta.validation_errors.append(msg)
        raise FileSizeExceededError(
            file_size_bytes=meta.file_size_bytes,
            max_size_bytes=config.max_file_size_bytes,
        )

    # ------------------------------------------------------------------
    # Comprobacion 3: al menos un bloque con texto seleccionable
    # Un documento con solo imagenes y ecuaciones no tiene contenido
    # textual que Gemini pueda clasificar ni el template pueda formatear.
    # ------------------------------------------------------------------
    text_blocks = [b for b in blocks if b.role in _TEXT_ROLES and b.text]
    if not text_blocks:
        meta.is_empty = True
        msg = (
            "El documento no contiene texto seleccionable. "
            "Solo se encontraron imagenes o ecuaciones."
        )
        meta.validation_errors.append(msg)
        raise EmptyDocumentError(
            filename=meta.original_filename,
            block_count=len(text_blocks),
        )

    # ------------------------------------------------------------------
    # Comprobacion 4: advertencias no bloqueantes
    # Se registran en meta.validation_errors pero NO bloquean el pipeline.
    # ------------------------------------------------------------------
    _check_warnings(meta, blocks)

    # ------------------------------------------------------------------
    # Comprobacion 5: conflictos de estilos (RECUPERABLE, seccion 7)
    # Se lanza al final, despues de todas las comprobaciones fatales,
    # para que el mensaje al usuario sea preciso y no oculte otros errores.
    # ------------------------------------------------------------------
    if meta.has_conflicting_styles:
        conflicting = _collect_conflicting_style_names(blocks)
        logger.info(
            "Conflicto de estilos detectado: %s",
            conflicting,
        )
        raise ConflictingStylesError(conflicting_styles=conflicting)

    # ------------------------------------------------------------------
    # Todas las comprobaciones superadas
    # ------------------------------------------------------------------
    meta.is_valid = True
    logger.debug("Validacion superada. is_valid=True")


# ===========================================================================
# Helpers internos
# ===========================================================================

def _check_warnings(
    meta: DocumentMeta,
    blocks: list[SemanticBlock],
) -> None:
    """
    Detecta condiciones no bloqueantes y las agrega a meta.validation_errors.

    Estas advertencias se propagan hasta el caller en ProcessingResult
    para que webapp pueda mostrarlas al usuario si lo considera relevante,
    pero NO interrumpen el pipeline.

    Advertencias actuales:
    - Sin headings: el documento no tiene estructura de secciones.
      El template podra aplicarse, pero el indice (TOC) quedara vacio.
    - Sin bloques de cuerpo (BODY): el documento tiene solo headings,
      listas o elementos especiales — puede ser una plantilla vacia.
    - Idioma no detectado: la heuristica de stopwords no pudo determinar
      el idioma. Gemini aun clasificara correctamente, pero el prompt
      no se ajustara al idioma del documento.
    """
    from engine.document.models import DocumentLanguage  # noqa: PLC0415

    heading_roles = {
        SemanticRole.HEADING1, SemanticRole.HEADING2,
        SemanticRole.HEADING3, SemanticRole.HEADING4,
    }
    has_headings = any(b.role in heading_roles for b in blocks)
    has_body     = any(b.role == SemanticRole.BODY for b in blocks)

    if not has_headings:
        meta.validation_errors.append(
            "Advertencia: el documento no tiene headings. "
            "El indice generado por el template quedara vacio."
        )
        logger.warning("[Validator] Sin headings detectados en el documento.")

    if not has_body:
        meta.validation_errors.append(
            "Advertencia: el documento no tiene parrafos de cuerpo de texto (BODY). "
            "Puede ser una plantilla incompleta."
        )
        logger.warning("[Validator] Sin bloques BODY detectados en el documento.")

    if meta.detected_language == DocumentLanguage.UNKNOWN:
        meta.validation_errors.append(
            "Advertencia: no se pudo determinar el idioma del documento. "
            "Se procesara sin ajuste de idioma."
        )
        logger.info("[Validator] Idioma no detectado — se usara prompt generico en Gemini.")


def _collect_conflicting_style_names(blocks: list[SemanticBlock]) -> list[str]:
    """
    Devuelve la lista deduplicada de nombres de estilo Word que fueron
    marcados como conflictivos por extractor.py.

    El orden es determinista (sorted) para que el mensaje al usuario
    sea reproducible entre ejecuciones.
    """
    seen: set[str] = set()
    result: list[str] = []
    for block in blocks:
        if (
            block.has_conflicting_style
            and block.original_style_name
            and block.original_style_name not in seen
        ):
            seen.add(block.original_style_name)
            result.append(block.original_style_name)
    return sorted(result)
