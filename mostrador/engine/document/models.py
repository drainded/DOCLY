"""
engine/document/models.py
=========================
Contrato de datos del motor de Mostrador.

Este módulo define los tipos que circulan por el pipeline de 7 pasos (§5).
Es la fuente de verdad compartida entre:
  - classification/gemini_classifier.py  (produce SemanticBlock[])
  - formatting/template_engine.py        (consume SemanticBlock[])
  - core/pipeline.py                     (orquesta el flujo completo)
  - webapp/api/routes.py                 (recibe ProcessingResult)

Regla §9.1: engine/ no debe importar nada de webapp/, FastAPI, Flask,
ni leer variables de entorno globales. La configuracion se inyecta
siempre como ProcessingConfig.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SemanticRole(str, Enum):
    """
    Roles semanticos que Gemini asigna a cada bloque de contenido (§5, Paso 3).

    La IA SOLO puede devolver uno de estos valores — nunca inventa roles nuevos.
    El codigo deterministico (Paso 4) solo actua sobre roles conocidos; cualquier
    valor fuera de este enum debe tratarse como UNKNOWN y preservarse sin modificar.
    """

    # Estructura de secciones
    HEADING1 = "heading1"
    HEADING2 = "heading2"
    HEADING3 = "heading3"
    HEADING4 = "heading4"          # nivel maximo soportado en v1

    # Contenido de cuerpo
    BODY = "body"                  # parrafo de texto normal
    LIST_ITEM = "list_item"        # item de lista (ordenada o no ordenada)
    BLOCKQUOTE = "blockquote"      # cita en bloque

    # Referencias bibliograficas
    REFERENCE = "reference"        # entrada de bibliografia / lista de referencias

    # Elementos flotantes
    CAPTION = "caption"            # pie de figura o tabla
    TABLE_HEADER = "table_header"  # fila de encabezado de tabla
    TABLE_CELL = "table_cell"      # celda de tabla (no encabezado)

    # Portada (campos que se colocan en la cover page del template §4)
    COVER_TITLE = "cover_title"
    COVER_AUTHOR = "cover_author"
    COVER_INSTITUTION = "cover_institution"
    COVER_DATE = "cover_date"
    COVER_COURSE = "cover_course"  # campo opcional de portada

    # Especiales — preservados sin tocar (§7)
    EQUATION = "equation"          # ecuacion OMML: se preserva sin modificar
    IMAGE = "image"                # imagen embebida: se conserva en posicion relativa

    # Fallback
    UNKNOWN = "unknown"            # rol no reconocido — se preserva tal cual


class FormatStyle(str, Enum):
    """
    Normas de citacion / formato soportadas en v1 (§1, §4).
    El valor string coincide con la clave usada en el TEMPLATES dict (§4).
    """
    APA = "apa"
    IEEE = "ieee"
    VANCOUVER = "vancouver"


class DocumentLanguage(str, Enum):
    """
    Idiomas soportados en v1 (§7 — soporte ES/EN confirmado en spec actualizado).
    Se usa para ajustar heuristicas del extractor y el prompt de Gemini.
    """
    SPANISH = "es"
    ENGLISH = "en"
    UNKNOWN = "unknown"   # cuando no se puede determinar; se procesa igual


# ---------------------------------------------------------------------------
# Bloque semantico — unidad que viaja del Paso 3 al Paso 4
# ---------------------------------------------------------------------------

@dataclass
class SemanticBlock:
    """
    Unidad atomica de contenido ya clasificada por Gemini (Paso 3).

    Cada bloque representa un parrafo, item de lista, celda, imagen, ecuacion,
    etc. del documento original. El conjunto de bloques de un documento constituye
    su estructura semantica completa, sobre la que opera el template_engine (Paso 4).

    Invariante del sistema (§5 — principio arquitectonico clave):
        Gemini SOLO asigna `role`. NUNCA modifica `text` ni decide estilo visual.
        El estilo visual (color, tipografia, espaciado) lo decide exclusivamente
        el TEMPLATES dict, operado por template_engine.py.
    """

    # --- Identidad ---
    block_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    index: int = 0

    # --- Contenido ---
    text: str = ""
    role: SemanticRole = SemanticRole.UNKNOWN

    # --- Jerarquia (solo relevante para headings) ---
    heading_level: int | None = None

    # --- Contexto de lista (solo para LIST_ITEM) ---
    list_ordered: bool | None = None
    list_depth: int = 0

    # --- Metadatos del elemento original ---
    original_style_name: str | None = None
    has_conflicting_style: bool = False

    # --- Estructura de tabla (solo para TABLE_HEADER / TABLE_CELL) ---
    # Sin estos campos, docx_builder.py (Paso 5) no puede saber cuantas
    # filas/columnas tiene la tabla original ni reconstruirla correctamente
    # cuando hay mas de una tabla en el documento (bug confirmado en revision
    # de extractor.py — ver notas de implementacion).
    table_id: str | None = None    # identifica a que <w:tbl> pertenece (una por documento)
    row_index: int | None = None   # fila dentro de la tabla (0-indexed)
    col_index: int | None = None   # columna dentro de la tabla (0-indexed)

    # --- Contenido binario / especial (preservado sin modificar, §7) ---
    raw_xml: str | None = None
    image_rId: str | None = None

    # --- Confianza de la clasificacion (informativo) ---
    classification_confidence: float | None = None

    def is_heading(self) -> bool:
        return self.role in (
            SemanticRole.HEADING1,
            SemanticRole.HEADING2,
            SemanticRole.HEADING3,
            SemanticRole.HEADING4,
        )

    def is_cover_field(self) -> bool:
        return self.role in (
            SemanticRole.COVER_TITLE,
            SemanticRole.COVER_AUTHOR,
            SemanticRole.COVER_INSTITUTION,
            SemanticRole.COVER_DATE,
            SemanticRole.COVER_COURSE,
        )

    def must_preserve_raw(self) -> bool:
        """True si el bloque debe reinsertarse desde raw_xml sin modificacion (§7)."""
        return self.role in (SemanticRole.EQUATION, SemanticRole.IMAGE)


# ---------------------------------------------------------------------------
# Metadatos del documento en entrada
# ---------------------------------------------------------------------------

# Fuente unica de verdad para el limite de tamano por defecto (§3: 50 MB).
# DocumentMeta.MAX_FILE_SIZE_BYTES y ProcessingConfig.max_file_size_bytes
# derivan ambos de esta constante para que no puedan divergir si alguien
# cambia el limite en un solo lugar (bug corregido: antes eran dos literales
# independientes que solo coincidian por casualidad).
DEFAULT_MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024


@dataclass
class DocumentMeta:
    """
    Metadatos del documento subido por el usuario (producidos en Paso 1 y Paso 2).
    """

    processing_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_filename: str = ""

    # Formato
    input_format: str = "docx"   # 'docx' o 'doc'; 'pdf' es rechazado (§3, §8)
    was_converted: bool = False  # True si era .doc y se convirtio via LibreOffice

    # Tamano
    file_size_bytes: int = 0
    MAX_FILE_SIZE_BYTES: int = field(default=DEFAULT_MAX_FILE_SIZE_BYTES, init=False, repr=False)

    # Estado de validacion
    is_valid: bool = False
    is_password_protected: bool = False
    is_corrupted: bool = False
    is_scanned: bool = False     # sin texto seleccionable → rechazado (§7, §8)
    is_empty: bool = False
    has_conflicting_styles: bool = False  # usuario decide si sobrescribir (§7)

    # Idioma (soporte ES/EN en v1, §7 actualizado)
    detected_language: DocumentLanguage = DocumentLanguage.UNKNOWN

    # Contenido
    block_count: int = 0
    heading_count: int = 0
    has_tables: bool = False
    has_images: bool = False
    has_equations: bool = False

    # Trazabilidad
    uploaded_at: datetime = field(default_factory=datetime.utcnow)
    validation_errors: list[str] = field(default_factory=list)

    def exceeds_size_limit(self, config: "ProcessingConfig | None" = None) -> bool:
        """
        Retorna True si el archivo supera el limite permitido.

        Regla §9.1: la fuente de verdad es siempre ProcessingConfig.
        Si se inyecta un config, se usa su max_file_size_bytes; de lo
        contrario se cae al valor por defecto de la clase (50 MB).
        """
        limit = config.max_file_size_bytes if config is not None else self.MAX_FILE_SIZE_BYTES
        return self.file_size_bytes > limit

    def rejection_reason(self, config: "ProcessingConfig | None" = None) -> str | None:
        """Motivo de rechazo mas prioritario, o None si el documento es valido.

        Pasa el config a exceeds_size_limit() para respetar el limite
        inyectado en lugar de la constante hardcodeada (§9.1).
        """
        if self.is_corrupted:
            return "El documento esta corrupto o no puede parsearse."
        if self.is_password_protected:
            return "El documento esta protegido con contrasena."
        if self.is_scanned:
            return "El documento es una imagen escaneada (sin texto seleccionable). No hay soporte OCR en v1."
        if self.exceeds_size_limit(config):
            limit_mb = (
                config.max_file_size_bytes / 1_048_576 if config is not None
                else self.MAX_FILE_SIZE_BYTES / 1_048_576
            )
            return (
                f"El documento supera el limite de {limit_mb:.0f} MB "
                f"({self.file_size_bytes / 1_048_576:.1f} MB)."
            )
        if self.is_empty:
            return "El documento esta vacio o solo contiene una portada sin contenido."
        return None


# ---------------------------------------------------------------------------
# Configuracion inyectada — nunca leida de env globales dentro de engine/
# ---------------------------------------------------------------------------

@dataclass
class ProcessingConfig:
    """
    Configuracion que el caller (webapp o integrador externo) inyecta al motor.

    Regla §9.1: engine/ NUNCA lee os.environ directamente. Toda credencial
    se recibe a traves de esta clase para que el motor sea agnostico del
    contexto de ejecucion (webapp, test, integracion en otro proyecto).

    Ejemplo de uso desde webapp:
        config = ProcessingConfig(
            gemini_api_key=os.environ["GEMINI_API_KEY"],
            style=FormatStyle.APA,
        )
        result = engine.process_document(doc_path, config)
    """

    # Credenciales (obligatorias)
    gemini_api_key: str = ""

    # Estilo de formato (obligatorio)
    style: FormatStyle = FormatStyle.APA

    # Modelo de Gemini — default Flash (costo  en free tier, §9)
    gemini_model: str = "gemini-1.5-flash"

    # Parametros operativos
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    output_dir: Path = field(default_factory=lambda: Path("output"))
    libreoffice_bin: str = "libreoffice"

    # Validar el .docx de salida contra los XSD de OpenXML (§6). Si falla,
    # el pipeline descarta el archivo y devuelve OUTPUT_SCHEMA_INVALID.
    validate_output_xsd: bool = True

    # Fallback Groq (v1.1, §9) — None = desactivado en v1
    groq_api_key: str | None = None
    groq_model: str = "llama3-70b-8192"


# ---------------------------------------------------------------------------
# Resultado del procesamiento
# ---------------------------------------------------------------------------

@dataclass
class ProcessingResult:
    """
    Resultado devuelto por engine.core.pipeline tras ejecutar los 7 pasos (§5).
    """

    processing_id: str = ""
    success: bool = False

    # Artefactos de salida
    output_docx_path: Path | None = None
    preview_path: Path | None = None   # None si el renderizado fallo (no invalida el .docx)

    # Error
    error_code: str | None = None      # ej. 'DOCUMENT_CORRUPTED', 'RATE_LIMIT_GEMINI'
    error_message: str | None = None   # mensaje humano-legible para el usuario

    # Trazabilidad
    doc_meta: DocumentMeta | None = None
    completed_at: datetime = field(default_factory=datetime.utcnow)

    # Estado del proveedor de IA
    gemini_rate_limited: bool = False  # si True → "error temporal, reintentar" (§9)
    fallback_used: bool = False        # True si se uso Groq en lugar de Gemini

    @property
    def user_message(self) -> str:
        """Mensaje listo para mostrar en el panel web."""
        if self.success:
            return "Tu documento ha sido procesado correctamente. Ya puedes descargarlo."
        if self.gemini_rate_limited:
            return (
                "El servicio de clasificacion alcanzo su limite temporal. "
                "Por favor, intentalo de nuevo en unos minutos."
            )
        return self.error_message or "Ocurrio un error inesperado. Intentalo de nuevo."
