"""
engine/core/exceptions.py
==========================
Jerarquia de excepciones de dominio del motor de Mostrador.

Todos los errores que puede lanzar el pipeline (§5) se representan aqui.
Reglas de uso:
  - El pipeline (core/pipeline.py) captura estas excepciones y las convierte
    en ProcessingResult(success=False, error_code=...) antes de devolverlas
    al caller. Nunca deja que suban como excepciones Python no capturadas.
  - webapp/api/routes.py NUNCA debe importar ni capturar estas clases
    directamente: solo interactua con ProcessingResult.
  - Cada excepcion incluye un error_code string constante que coincide
    con el campo ProcessingResult.error_code (facilita logging y trazabilidad).
  - Las excepciones de IA (rate limit, fallo de Gemini) heredan de
    ClassificationError para que el pipeline pueda manejarlas con un solo
    except cuando sea apropiado.

Mapa excepcion -> paso del pipeline que la lanza (§5):
    Paso 1 (upload)         : FileSizeExceededError, UnsupportedFormatError
    Paso 2 (extraccion)     : DocumentCorruptError, PasswordProtectedError,
                              ScannedDocumentError, EmptyDocumentError,
                              ConversionError
    Paso 2b (validacion)    : ConflictingStylesError
    Paso 3 (clasificacion)  : GeminiRateLimitError, GeminiAPIError,
                              ClassificationError
    Paso 4 (template)       : TemplateNotFoundError, TemplateApplicationError
    Paso 5 (generacion)     : DocxBuildError
    Paso 6 (preview)        : PreviewRenderError
    Transversal             : MostradorError (base), PipelineError
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class MostradorError(Exception):
    """
    Clase base de todas las excepciones del motor.

    Atributos:
        message   : Mensaje humano-legible para el usuario final (panel web).
        error_code: Identificador maquina-legible que se propaga hasta
                    ProcessingResult.error_code. En mayusculas con guiones
                    bajos, ej. 'DOCUMENT_CORRUPTED'.
        details   : Informacion adicional para logs/debugging (no se muestra
                    al usuario). Puede ser None.
    """

    error_code: str = "MOSTRADOR_ERROR"

    def __init__(
        self,
        message: str,
        details: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"error_code={self.error_code!r}, "
            f"message={self.message!r}, "
            f"details={self.details!r})"
        )


# ---------------------------------------------------------------------------
# Errores de validacion de entrada (Pasos 1 y 2)
# Lanzados por: document/validator.py
# ---------------------------------------------------------------------------

class DocumentValidationError(MostradorError):
    """Base para todos los errores de validacion del documento de entrada."""
    error_code = "DOCUMENT_VALIDATION_ERROR"


class FileSizeExceededError(DocumentValidationError):
    """
    El archivo supera el limite de tamano permitido (§3: 50 MB en v1).

    Lanzado en: Paso 1 (upload), antes de cualquier parseo.

    Args:
        file_size_bytes : Tamano real del archivo subido.
        max_size_bytes  : Limite configurado en ProcessingConfig.max_file_size_bytes.
    """
    error_code = "FILE_SIZE_EXCEEDED"

    def __init__(self, file_size_bytes: int, max_size_bytes: int) -> None:
        size_mb = file_size_bytes / 1_048_576
        limit_mb = max_size_bytes / 1_048_576
        super().__init__(
            message=(
                f"El archivo pesa {size_mb:.1f} MB y supera el limite "
                f"permitido de {limit_mb:.0f} MB."
            ),
            details=f"file_size_bytes={file_size_bytes}, max_size_bytes={max_size_bytes}",
        )
        self.file_size_bytes = file_size_bytes
        self.max_size_bytes = max_size_bytes


class UnsupportedFormatError(DocumentValidationError):
    """
    El archivo no tiene un formato aceptado por el motor (§3).
    Formatos aceptados en v1: .docx, .doc
    Rechazados explicitamente: .pdf y cualquier otro (§8).

    Args:
        filename       : Nombre original del archivo subido.
        detected_format: Extension o MIME type detectado.
    """
    error_code = "UNSUPPORTED_FORMAT"

    def __init__(self, filename: str, detected_format: str) -> None:
        super().__init__(
            message=(
                f"El formato '{detected_format}' no esta soportado en v1. "
                f"Solo se aceptan archivos .docx y .doc."
            ),
            details=f"filename={filename!r}, detected_format={detected_format!r}",
        )
        self.filename = filename
        self.detected_format = detected_format


class DocumentCorruptError(DocumentValidationError):
    """
    El documento no puede parsearse (archivo ZIP invalido, XML malformado,
    estructura OpenXML incompleta, etc.) (§3, §7).

    Lanzado antes de entrar al pipeline para evitar errores en cascada (§3).

    Args:
        filename: Nombre original del archivo.
        cause   : Excepcion original de python-docx / lxml (opcional).
    """
    error_code = "DOCUMENT_CORRUPTED"

    def __init__(self, filename: str, cause: Exception | None = None) -> None:
        super().__init__(
            message=(
                "El documento esta corrupto o no puede leerse. "
                "Asegurate de que el archivo no esta danado y vuelve a intentarlo."
            ),
            details=f"filename={filename!r}, cause={cause!r}",
        )
        self.filename = filename
        self.cause = cause


class PasswordProtectedError(DocumentValidationError):
    """
    El documento esta protegido con contrasena (§3).

    Lanzado en: Paso 2 (extraccion), al intentar abrir el archivo.
    """
    error_code = "PASSWORD_PROTECTED"

    def __init__(self, filename: str) -> None:
        super().__init__(
            message=(
                "El documento esta protegido con contrasena. "
                "Elimina la proteccion y vuelve a subirlo."
            ),
            details=f"filename={filename!r}",
        )
        self.filename = filename


class ScannedDocumentError(DocumentValidationError):
    """
    El documento es una imagen escaneada sin texto seleccionable (§7, §8).
    No hay OCR en v1 — se rechaza explicitamente.

    Heuristica de deteccion: documento con 0 parrafos de texto pero con
    imagenes embebidas, o con texto extraido vacio / solo espacios en blanco.
    """
    error_code = "SCANNED_DOCUMENT"

    def __init__(self, filename: str) -> None:
        super().__init__(
            message=(
                "El documento parece ser una imagen escaneada sin texto "
                "seleccionable. El procesamiento OCR no esta disponible en v1."
            ),
            details=f"filename={filename!r}",
        )
        self.filename = filename


class EmptyDocumentError(DocumentValidationError):
    """
    El documento esta vacio o solo contiene una portada sin contenido (§7).

    Lanzado en: Paso 2, despues de la extraccion, si block_count == 0.
    """
    error_code = "EMPTY_DOCUMENT"

    def __init__(self, filename: str, block_count: int = 0) -> None:
        super().__init__(
            message=(
                "El documento esta vacio o no contiene contenido procesable. "
                "Asegurate de que el archivo tiene texto y vuelve a intentarlo."
            ),
            details=f"filename={filename!r}, block_count={block_count}",
        )
        self.filename = filename
        self.block_count = block_count


class ConversionError(DocumentValidationError):
    """
    LibreOffice headless no pudo convertir el archivo .doc a .docx (§3).

    Lanzado en: Paso 2, antes de la extraccion, cuando input_format == 'doc'.

    Args:
        filename   : Nombre original del .doc.
        returncode : Codigo de salida del proceso LibreOffice.
        stderr     : Salida de error del proceso (para diagnostico).
    """
    error_code = "CONVERSION_FAILED"

    def __init__(
        self,
        filename: str,
        returncode: int | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(
            message=(
                "No se pudo convertir el archivo .doc a .docx. "
                "Intenta guardar el documento en formato .docx directamente desde Word."
            ),
            details=(
                f"filename={filename!r}, "
                f"libreoffice_returncode={returncode}, "
                f"stderr={stderr!r}"
            ),
        )
        self.filename = filename
        self.returncode = returncode
        self.stderr = stderr


class ConflictingStylesError(DocumentValidationError):
    """
    El documento tiene estilos propios que entran en conflicto con el
    template destino (§7).

    Este error es RECUPERABLE: el pipeline pausa y espera que el usuario
    decida si sobrescribir los estilos existentes o cancelar el procesamiento.
    NO se lanza como error fatal; se captura en pipeline.py y se devuelve
    al caller con DocumentMeta.has_conflicting_styles = True para que
    webapp muestre un dialogo de confirmacion al usuario.

    Args:
        conflicting_styles: Lista de nombres de estilos Word en conflicto.
    """
    error_code = "CONFLICTING_STYLES"

    def __init__(self, conflicting_styles: list[str]) -> None:
        styles_str = ", ".join(conflicting_styles[:5])  # mostrar max 5 en el mensaje
        extra = f" (y {len(conflicting_styles) - 5} mas)" if len(conflicting_styles) > 5 else ""
        super().__init__(
            message=(
                f"El documento tiene estilos que pueden entrar en conflicto con "
                f"el template seleccionado: {styles_str}{extra}. "
                f"Podemos sobrescribirlos automaticamente. Deseas continuar?"
            ),
            details=f"conflicting_styles={conflicting_styles!r}",
        )
        self.conflicting_styles = conflicting_styles


# ---------------------------------------------------------------------------
# Errores de clasificacion semantica (Paso 3)
# Lanzados por: classification/gemini_classifier.py y classification/fallback.py
# ---------------------------------------------------------------------------

class ClassificationError(MostradorError):
    """
    Base para todos los errores del paso de clasificacion semantica (Paso 3).

    El pipeline captura esta clase base cuando quiere manejar cualquier
    fallo de clasificacion de forma uniforme (ej. para intentar el fallback
    a Groq antes de marcar el documento como error).
    """
    error_code = "CLASSIFICATION_ERROR"


class GeminiRateLimitError(ClassificationError):
    """
    La API de Gemini devolvio un error de rate limit (§9).

    Comportamiento en pipeline.py:
      1. Si ProcessingConfig.groq_api_key is not None → intenta fallback a Groq.
      2. Si no hay fallback → devuelve ProcessingResult con
         success=False, gemini_rate_limited=True.
         El usuario ve el mensaje de "reintentar mas tarde" (§9).

    NO hay reintento automatico en v1 (§9: 'el usuario reintenta manualmente').
    """
    error_code = "RATE_LIMIT_GEMINI"

    def __init__(self, retry_after_seconds: int | None = None) -> None:
        hint = (
            f" Intenta de nuevo en {retry_after_seconds} segundos."
            if retry_after_seconds
            else " Intenta de nuevo en unos minutos."
        )
        super().__init__(
            message=(
                "El servicio de clasificacion alcanzo su limite de solicitudes temporalmente."
                + hint
            ),
            details=f"retry_after_seconds={retry_after_seconds}",
        )
        self.retry_after_seconds = retry_after_seconds


class GeminiAPIError(ClassificationError):
    """
    Error no relacionado con rate limit en la API de Gemini (ej. credencial
    invalida, error de red, respuesta malformada).

    A diferencia de GeminiRateLimitError, este error puede ser persistente
    (ej. API key incorrecta) y requiere intervencion del administrador.

    Args:
        status_code: Codigo HTTP de la respuesta de Gemini (si disponible).
        raw_response: Fragmento de la respuesta cruda para diagnostico.
    """
    error_code = "GEMINI_API_ERROR"

    def __init__(
        self,
        status_code: int | None = None,
        raw_response: str | None = None,
    ) -> None:
        super().__init__(
            message=(
                "El servicio de clasificacion no esta disponible en este momento. "
                "Por favor, intenta de nuevo mas tarde."
            ),
            details=f"status_code={status_code}, raw_response={raw_response!r}",
        )
        self.status_code = status_code
        self.raw_response = raw_response


class GroqAPIError(ClassificationError):
    """
    Error en la API de Groq durante el fallback (§9, v1.1).

    Si tanto Gemini como Groq fallan, el pipeline devuelve ProcessingResult
    con success=False y error_code='CLASSIFICATION_ERROR', indicando que
    ningun proveedor esta disponible.
    """
    error_code = "GROQ_API_ERROR"

    def __init__(
        self,
        status_code: int | None = None,
        raw_response: str | None = None,
    ) -> None:
        super().__init__(
            message=(
                "El servicio de clasificacion alternativo tampoco esta disponible. "
                "Por favor, intenta de nuevo mas tarde."
            ),
            details=f"status_code={status_code}, raw_response={raw_response!r}",
        )
        self.status_code = status_code
        self.raw_response = raw_response


class InvalidClassificationResponseError(ClassificationError):
    """
    Gemini (o Groq) devolvio una respuesta que no puede parsearse como
    la estructura JSON esperada de SemanticBlock[].

    Puede indicar alucinacion del modelo o cambio en el formato de respuesta.
    El pipeline lo trata como error fatal del Paso 3 (no hay reintentos en v1).

    Args:
        raw_response: Respuesta cruda del modelo para diagnostico.
    """
    error_code = "INVALID_CLASSIFICATION_RESPONSE"

    def __init__(self, raw_response: str | None = None) -> None:
        super().__init__(
            message=(
                "El servicio de clasificacion devolvio una respuesta inesperada. "
                "Por favor, intenta de nuevo."
            ),
            details=f"raw_response={raw_response!r}",
        )
        self.raw_response = raw_response


# ---------------------------------------------------------------------------
# Errores de aplicacion de template (Paso 4)
# Lanzados por: formatting/template_engine.py
# ---------------------------------------------------------------------------

class TemplateError(MostradorError):
    """Base para errores del modulo de formateo (Pasos 4 y 5)."""
    error_code = "TEMPLATE_ERROR"


class TemplateNotFoundError(TemplateError):
    """
    El estilo solicitado no existe en el TEMPLATES dict (§4).

    En v1 esto no deberia ocurrir si el frontend valida la seleccion del
    usuario contra los valores de FormatStyle. Si ocurre, indica un bug
    en la capa de integracion webapp ↔ engine.

    Args:
        style: Valor de FormatStyle que no se encontro en TEMPLATES.
    """
    error_code = "TEMPLATE_NOT_FOUND"

    def __init__(self, style: str) -> None:
        super().__init__(
            message=(
                f"El formato '{style}' no esta disponible. "
                f"Selecciona APA, IEEE o Vancouver."
            ),
            details=f"style={style!r}",
        )
        self.style = style


class TemplateApplicationError(TemplateError):
    """
    Error al aplicar el template sobre los SemanticBlocks (Paso 4).

    Puede ocurrir si un bloque tiene datos inconsistentes (ej. heading_level
    fuera de rango) o si hay un bug en template_engine.py.

    Args:
        block_index: Indice del SemanticBlock que causo el error.
        block_role : Rol del bloque problematico.
        cause      : Excepcion original.
    """
    error_code = "TEMPLATE_APPLICATION_ERROR"

    def __init__(
        self,
        block_index: int,
        block_role: str,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            message=(
                "Ocurrio un error al aplicar el formato al documento. "
                "Por favor, intenta de nuevo."
            ),
            details=(
                f"block_index={block_index}, "
                f"block_role={block_role!r}, "
                f"cause={cause!r}"
            ),
        )
        self.block_index = block_index
        self.block_role = block_role
        self.cause = cause


# ---------------------------------------------------------------------------
# Errores de generacion del .docx final (Paso 5)
# Lanzados por: formatting/docx_builder.py
# ---------------------------------------------------------------------------

class DocxBuildError(MostradorError):
    """
    python-docx no pudo construir el .docx de salida (Paso 5).

    Args:
        cause: Excepcion original de python-docx.
    """
    error_code = "DOCX_BUILD_ERROR"

    def __init__(self, cause: Exception | None = None) -> None:
        super().__init__(
            message=(
                "No se pudo generar el documento de salida. "
                "Por favor, intenta de nuevo."
            ),
            details=f"cause={cause!r}",
        )
        self.cause = cause


# ---------------------------------------------------------------------------
# Errores de validacion XSD del .docx de salida (Paso 5, seccion 6)
# Lanzados por: pipeline.py a partir de document/xsd_validator.py
# ---------------------------------------------------------------------------

class OutputSchemaValidationError(MostradorError):
    """
    El .docx generado en el Paso 5 no cumple el esquema XSD de OpenXML
    (criterio de aceptacion, seccion 6). Es un defecto del motor, no del
    documento del usuario: el archivo de salida se descarta.

    Args:
        errors: Mensajes de validacion (parte del paquete + linea + motivo).
    """
    error_code = "OUTPUT_SCHEMA_INVALID"

    def __init__(self, errors: list[str]) -> None:
        super().__init__(
            message=(
                "No se pudo generar un documento valido. "
                "Por favor, intenta de nuevo o contacta al administrador."
            ),
            details=f"{len(errors)} error(es) XSD: " + " | ".join(errors[:10]),
        )
        self.errors = errors


# ---------------------------------------------------------------------------
# Errores de renderizado de preview (Paso 6)
# Lanzados por: formatting/preview_renderer.py
# NOTA: Este error es NO fatal — la preview es opcional (§3).
#       El pipeline devuelve ProcessingResult con output_docx_path valido
#       pero preview_path=None cuando ocurre este error.
# ---------------------------------------------------------------------------

class PreviewRenderError(MostradorError):
    """
    LibreOffice headless o pdftoppm no pudo generar la imagen de preview (Paso 6).

    Este error es NO FATAL (§3): el .docx de salida sigue siendo valido y
    descargable. El pipeline lo registra en logs y devuelve preview_path=None.

    Args:
        returncode: Codigo de salida del proceso fallido.
        stderr    : Salida de error del proceso.
    """
    error_code = "PREVIEW_RENDER_ERROR"

    def __init__(
        self,
        returncode: int | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(
            message=(
                "No se pudo generar la vista previa del documento, "
                "pero puedes descargarlo igualmente."
            ),
            details=f"returncode={returncode}, stderr={stderr!r}",
        )
        self.returncode = returncode
        self.stderr = stderr


# ---------------------------------------------------------------------------
# Error transversal del pipeline
# ---------------------------------------------------------------------------

class PipelineError(MostradorError):
    """
    Error inesperado durante la orquestacion del pipeline (core/pipeline.py).

    Actua como captura de ultimo recurso para excepciones no cubiertas por
    las clases anteriores. pipeline.py lo lanza al envolver cualquier
    Exception no reconocida, asegurando que el caller siempre recibe un
    ProcessingResult y nunca una excepcion no capturada.

    Args:
        step   : Numero del paso del pipeline donde ocurrio el error (1-7).
        cause  : Excepcion original.
    """
    error_code = "PIPELINE_ERROR"

    def __init__(self, step: int, cause: Exception) -> None:
        super().__init__(
            message=(
                "Ocurrio un error inesperado durante el procesamiento. "
                "Por favor, intenta de nuevo."
            ),
            details=f"step={step}, cause={cause!r}",
        )
        self.step = step
        self.cause = cause
