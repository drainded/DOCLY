"""
engine/document/extractor.py
=============================
Paso 2 del pipeline: extraccion de contenido estructurado del documento.

Expone dos funciones publicas (contrato firmado con pipeline.py):

    convert_doc_to_docx(doc_path, work_dir, libreoffice_bin) -> Path
        Convierte un archivo .doc a .docx usando LibreOffice headless.
        Solo se llama cuando el archivo de entrada es .doc (Paso 2a).

    extract_blocks(docx_path, processing_id, original_filename)
        -> tuple[list[SemanticBlock], DocumentMeta]
        Abre el .docx con python-docx + lxml, recorre el body en orden
        de lectura y devuelve la lista de SemanticBlock mas los metadatos
        del documento (DocumentMeta). (Paso 2b)

Responsabilidades de este modulo
---------------------------------
* Abrir el .docx y detectar: corrupcion, proteccion con contrasena,
  documentos escaneados (sin texto) y documentos vacios (seccion 3, §7).
* Recorrer el body del documento en orden real (parrafos Y tablas
  intercalados) usando doc.element.body para respetar el flujo de lectura.
* Para cada parrafo:
  - Detectar si contiene una ecuacion OMML (w:oMath) -> SemanticRole.EQUATION
  - Detectar si contiene una imagen inline (a:graphic) -> SemanticRole.IMAGE
  - De lo contrario, mapear el nombre de estilo Word a un SemanticRole
    preliminar (heuristica). Gemini refinara esto en el Paso 3.
* Para cada tabla: iterar filas y celdas, distinguiendo la primera fila
  como TABLE_HEADER y el resto como TABLE_CELL.
* Capturar el XML crudo (raw_xml) de ecuaciones e imagenes para que
  docx_builder.py pueda reinsertarlos sin modificacion (§7).
* Detectar el idioma del documento (ES/EN) mediante heuristica de
  palabras de parada (stopwords) para rellenar DocumentMeta.detected_language.
* Rellenar todos los campos de DocumentMeta: block_count, heading_count,
  has_tables, has_images, has_equations, detected_language, is_valid, etc.

Lo que este modulo NO hace
---------------------------
* NO decide estilo visual (eso es Paso 4, TEMPLATES dict).
* NO llama a Gemini (eso es Paso 3, classification/).
* NO valida conflictos de estilos (eso es Paso 2c, validator.py).
* NO lanza ConflictingStylesError (validator.py lo hace).

Dependencias en tiempo de ejecucion
-------------------------------------
    python-docx >= 1.1
    lxml >= 5.0
    (LibreOffice en PATH o en config.libreoffice_bin para conversion .doc)
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path
from typing import Iterator

from lxml import etree

import docx
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn

from engine.document.models import (
    DocumentLanguage,
    DocumentMeta,
    SemanticBlock,
    SemanticRole,
)
from engine.core.exceptions import (
    ConversionError,
    DocumentCorruptError,
    EmptyDocumentError,
    PasswordProtectedError,
    ScannedDocumentError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Namespaces XML de OpenXML que se usan en la extraccion
# ---------------------------------------------------------------------------
_NS = {
    "w":   "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m":   "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "a":   "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp":  "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "r":   "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}

# Etiquetas XML de los dos tipos de elementos de primer nivel en el body
_TAG_PARAGRAPH = qn("w:p")
_TAG_TABLE     = qn("w:tbl")
_TAG_OMATH     = qn("m:oMath")          # ecuacion OMML
_TAG_OMATH_R   = qn("m:oMathPara")      # parrafo de ecuacion
_TAG_DRAWING   = qn("w:drawing")        # contenedor de imagen inline
_TAG_PICT      = qn("w:pict")           # imagen en formato legado (VML)
_TAG_OBJECT    = qn("w:object")         # objeto OLE embebido
_TAG_ALTERNATE = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"
_TAG_FALLBACK  = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_TAG_TXBX      = qn("w:txbxContent")    # contenido de un cuadro de texto

# Subarboles cuyo texto NO es texto propio del parrafo (imagenes, cuadros de texto)
_EMBEDDED_TAGS = frozenset({_TAG_DRAWING, _TAG_PICT, _TAG_OBJECT, _TAG_ALTERNATE})

# Firma de los primeros 8 bytes de un contenedor OLE/CFB (Compound File
# Binary). Un .docx cifrado con contrasena ("Encrypt with Password" de
# Word) se guarda en este contenedor en vez de como ZIP OOXML normal.
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# ---------------------------------------------------------------------------
# Mapeo de nombres de estilo Word -> SemanticRole preliminar
# (Gemini refinara esto en el Paso 3)
# ---------------------------------------------------------------------------
_STYLE_TO_ROLE: dict[str, SemanticRole] = {
    # Headings en ingles (estilos integrados de Word)
    "heading 1": SemanticRole.HEADING1,
    "heading 2": SemanticRole.HEADING2,
    "heading 3": SemanticRole.HEADING3,
    "heading 4": SemanticRole.HEADING4,
    # Headings en espanol (Word en espanol)
    "titulo 1":  SemanticRole.HEADING1,
    "titulo 2":  SemanticRole.HEADING2,
    "titulo 3":  SemanticRole.HEADING3,
    "titulo 4":  SemanticRole.HEADING4,
    # Listas
    "list paragraph":    SemanticRole.LIST_ITEM,
    "list bullet":       SemanticRole.LIST_ITEM,
    "list bullet 2":     SemanticRole.LIST_ITEM,
    "list bullet 3":     SemanticRole.LIST_ITEM,
    "list number":       SemanticRole.LIST_ITEM,
    "list number 2":     SemanticRole.LIST_ITEM,
    "list number 3":     SemanticRole.LIST_ITEM,
    "lista con viñetas": SemanticRole.LIST_ITEM,
    "lista con vietas":  SemanticRole.LIST_ITEM,
    "parrafo de lista":  SemanticRole.LIST_ITEM,
    # Citas
    "quote":             SemanticRole.BLOCKQUOTE,
    "block text":        SemanticRole.BLOCKQUOTE,
    "intense quote":     SemanticRole.BLOCKQUOTE,
    "cita":              SemanticRole.BLOCKQUOTE,
    # Caption / pie de figura
    "caption":           SemanticRole.CAPTION,
    "titulo de imagen":  SemanticRole.CAPTION,
    "titulo de tabla":   SemanticRole.CAPTION,
    # Cuerpo (normal = BODY)
    "normal":            SemanticRole.BODY,
    "body text":         SemanticRole.BODY,
    "body text 2":       SemanticRole.BODY,
    "cuerpo de texto":   SemanticRole.BODY,
    "texto independiente": SemanticRole.BODY,
    "default":           SemanticRole.BODY,
}

# Estilos Word que, si aparecen en el documento, pueden entrar en conflicto
# con la aplicacion del template (para que validator.py los detecte).
# El extractor los marca en SemanticBlock.has_conflicting_style = True.
_CONFLICTING_STYLE_NAMES: frozenset[str] = frozenset({
    "heading 1", "heading 2", "heading 3", "heading 4",
    "titulo 1", "titulo 2", "titulo 3", "titulo 4",
    "list paragraph", "list bullet", "list number",
    "quote", "intense quote", "block text",
    "caption",
})

# Stopwords simples para deteccion de idioma (heuristica, sin dependencias externas)
_SPANISH_STOPWORDS: frozenset[str] = frozenset({
    "de", "la", "el", "que", "y", "en", "a", "los", "del", "se",
    "las", "un", "por", "con", "una", "su", "para", "es", "al",
    "lo", "como", "mas", "o", "pero", "sus", "le", "ya", "o", "este",
    "si", "porque", "esta", "entre", "cuando", "muy", "sin", "sobre",
    "también", "me", "hasta", "hay", "donde", "quien", "desde", "todo",
    "nos", "durante", "estados", "todos", "uno", "les", "ni", "contra",
})
_ENGLISH_STOPWORDS: frozenset[str] = frozenset({
    "the", "of", "and", "to", "a", "in", "is", "it", "you", "that",
    "he", "was", "for", "on", "are", "as", "with", "his", "they", "at",
    "be", "this", "have", "from", "or", "one", "had", "by", "not", "but",
    "what", "all", "were", "we", "when", "your", "can", "said", "there",
    "use", "an", "each", "which", "she", "do", "how", "their", "if", "will",
})


# ===========================================================================
# API publica
# ===========================================================================

def convert_doc_to_docx(
    doc_path: Path,
    work_dir: Path,
    libreoffice_bin: str = "libreoffice",
) -> Path:
    """
    Convierte un archivo .doc a .docx usando LibreOffice headless (seccion 3).

    El archivo .docx resultante se escribe en work_dir con el mismo nombre
    base que el .doc original.

    Parameters
    ----------
    doc_path:
        Ruta al archivo .doc de entrada.
    work_dir:
        Directorio temporal donde se escribe el .docx de salida.
    libreoffice_bin:
        Comando o ruta al binario de LibreOffice headless.

    Returns
    -------
    Path
        Ruta al .docx generado en work_dir.

    Raises
    ------
    ConversionError
        Si LibreOffice no esta disponible, devuelve un codigo de error
        distinto de 0, o el archivo de salida no se crea.
    """
    cmd = [
        libreoffice_bin,
        "--headless",
        "--convert-to", "docx",
        "--outdir", str(work_dir),
        str(doc_path),
    ]
    logger.debug("Ejecutando LibreOffice: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise ConversionError(
            filename=doc_path.name,
            returncode=None,
            stderr=f"LibreOffice no encontrado en: {libreoffice_bin}",
        )
    except subprocess.TimeoutExpired:
        raise ConversionError(
            filename=doc_path.name,
            returncode=None,
            stderr="LibreOffice tardo mas de 120 segundos (timeout).",
        )

    if result.returncode != 0:
        raise ConversionError(
            filename=doc_path.name,
            returncode=result.returncode,
            stderr=result.stderr,
        )

    expected_out = work_dir / (doc_path.stem + ".docx")
    if not expected_out.exists():
        raise ConversionError(
            filename=doc_path.name,
            returncode=result.returncode,
            stderr=f"LibreOffice termino sin error pero no creo: {expected_out}",
        )

    logger.info("Conversion completada: %s -> %s", doc_path.name, expected_out.name)
    return expected_out


def extract_blocks(
    docx_path: Path,
    processing_id: str,
    original_filename: str,
) -> tuple[list[SemanticBlock], DocumentMeta]:
    """
    Abre el .docx y extrae la lista de SemanticBlock en orden de lectura,
    junto con los metadatos del documento (DocumentMeta).

    La extraccion recorre doc.element.body en orden real para respetar la
    posicion relativa de tablas y parrafos (python-docx doc.paragraphs y
    doc.tables listan cada tipo por separado y pierden el orden intercalado).

    Parameters
    ----------
    docx_path:
        Ruta al .docx (ya convertido si era .doc).
    processing_id:
        ID de sesion generado por pipeline.py. Se propaga a DocumentMeta.
    original_filename:
        Nombre del archivo original subido por el usuario.

    Returns
    -------
    tuple[list[SemanticBlock], DocumentMeta]
        Bloques en orden de lectura y metadatos del documento.

    Raises
    ------
    DocumentCorruptError
        Si el archivo no puede abrirse o su XML es invalido.
    PasswordProtectedError
        Si el documento esta protegido con contrasena.
    ScannedDocumentError
        Si el documento no tiene texto seleccionable (solo imagenes).
    EmptyDocumentError
        Si no se extrae ningun bloque de contenido.
    """
    doc = _open_docx(docx_path, original_filename)
    style_map = _build_style_id_to_name(doc)

    blocks: list[SemanticBlock] = []
    index = 0

    for child in doc.element.body:
        tag = child.tag

        if tag == _TAG_PARAGRAPH:
            new_blocks = _extract_from_paragraph(child, index, style_map)
            blocks.extend(new_blocks)
            index += len(new_blocks)

        elif tag == _TAG_TABLE:
            new_blocks = _extract_from_table(child, index)
            blocks.extend(new_blocks)
            index += len(new_blocks)

        # Otros elementos (sectPr, etc.) se ignoran

    meta = _build_meta(
        blocks=blocks,
        processing_id=processing_id,
        original_filename=original_filename,
        docx_path=docx_path,
    )

    _check_scanned_or_empty(blocks, meta, original_filename)

    return blocks, meta


# ===========================================================================
# Apertura y deteccion de errores de entrada
# ===========================================================================

def _open_docx(docx_path: Path, filename: str) -> Document:
    """
    Abre el .docx con python-docx y mapea las excepciones de bajo nivel
    a las excepciones de dominio del motor.

    Detecta DOS variantes distintas de "documento protegido" (confirmado
    con fixtures reales — ver notas de implementacion):

    1. Cifrado con contrasena ("Encrypt with Password" de Word): el archivo
       completo se guarda como un contenedor OLE/CFB (firma de bytes
       D0 CF 11 E0), no como un ZIP OOXML normal. python-docx nunca llega a abrirlo
       y lanza PackageNotFoundError con un mensaje generico ("Package not
       found at '...'") que NO contiene las palabras "encrypted"/"password".
       Se detecta ANTES de intentar abrir el archivo, leyendo su firma.

    2. Restringir edicion ("Restrict Editing" de Word): el archivo sigue
       siendo un ZIP OOXML normal y se abre sin error; la restriccion vive
       como <w:documentProtection w:enforcement="1"> en word/settings.xml.
       Se detecta DESPUES de abrir el documento, inspeccionando settings.xml.

    Raises
    ------
    PasswordProtectedError, DocumentCorruptError
    """
    # --- Variante 1: cifrado con contrasena (contenedor OLE/CFB) ---
    try:
        with open(docx_path, "rb") as f:
            signature = f.read(8)
    except OSError as exc:
        raise DocumentCorruptError(filename=filename, cause=exc) from exc

    if signature.startswith(_OLE_SIGNATURE):
        raise PasswordProtectedError(filename=filename)

    # --- Apertura normal ---
    try:
        doc = docx.Document(str(docx_path))
    except PackageNotFoundError as exc:
        # Con la variante 1 ya descartada arriba, si esto ocurre es porque
        # el ZIP esta genuinamente corrupto/malformado, no cifrado.
        raise DocumentCorruptError(filename=filename, cause=exc) from exc
    except Exception as exc:
        raise DocumentCorruptError(filename=filename, cause=exc) from exc

    # --- Variante 2: restringir edicion (documentProtection en settings.xml) ---
    if _has_document_protection(doc):
        raise PasswordProtectedError(filename=filename)

    return doc


def _has_document_protection(doc: Document) -> bool:
    """
    True si el documento tiene <w:documentProtection w:enforcement="1">
    en word/settings.xml (proteccion "Restringir edicion" de Word).

    w:enforcement="1" indica que la restriccion esta activa y requiere
    contrasena para desactivarse; si esta ausente o en "0", la proteccion
    fue definida pero no esta forzada, y no se trata como bloqueante.
    """
    settings_elem = doc.settings.element
    protection = settings_elem.find(qn("w:documentProtection"))
    if protection is None:
        return False
    return protection.get(qn("w:enforcement")) == "1"


# ===========================================================================
# Extraccion de parrafos
# ===========================================================================

def _extract_from_paragraph(
    p_elem: etree._Element,
    start_index: int,
    style_map: dict[str, str],
) -> list[SemanticBlock]:
    """
    Extrae SemanticBlock(s) de un elemento <w:p>.

    Un parrafo puede dar lugar a:
    - 0 bloques: si esta vacio (sin texto ni imagenes ni ecuaciones)
    - 1 bloque EQUATION si contiene una ecuacion OMML (se conserva el
      parrafo completo, texto incluido, como XML crudo)
    - Si contiene un dibujo/imagen: un bloque de texto con el texto propio
      del parrafo (si lo hay), el bloque IMAGE y un bloque de texto por cada
      parrafo de sus cuadros de texto (no se pierde texto, seccion 6)
    - 1 bloque de texto (BODY, HEADING*, LIST_ITEM, etc.) con el texto del parrafo
    """
    # 1. ¿Contiene ecuacion OMML?
    if _has_equation(p_elem):
        return [_make_equation_block(p_elem, start_index, style_map)]

    # 2. ¿Contiene imagen inline?
    if _has_image(p_elem):
        return _extract_from_image_paragraph(p_elem, start_index, style_map)

    # 3. Parrafo de texto
    text = _collect_text(p_elem)
    if not text:
        return []   # parrafo vacio — ignorar

    return [_make_text_block(p_elem, start_index, text, style_map)]


def _extract_from_image_paragraph(
    p_elem: etree._Element,
    start_index: int,
    style_map: dict[str, str],
) -> list[SemanticBlock]:
    """
    Bloques de un parrafo con imagen: texto propio -> imagen -> texto de los
    cuadros de texto. En un `mc:AlternateContent` el cuadro de texto aparece
    dos veces (Choice moderno y Fallback VML); solo se toma el de Choice.
    """
    blocks: list[SemanticBlock] = []

    own_text = _collect_text(p_elem, skip_embedded=True)
    if own_text:
        blocks.append(_make_text_block(p_elem, start_index + len(blocks), own_text, style_map))

    blocks.append(_make_image_block(p_elem, start_index + len(blocks), style_map))

    for txbx in p_elem.iter(_TAG_TXBX):
        if any(ancestor.tag == _TAG_FALLBACK for ancestor in txbx.iterancestors()):
            continue
        for inner in txbx.iter(qn("w:p")):
            text = _collect_text(inner)
            if text:
                blocks.append(_make_text_block(inner, start_index + len(blocks), text, style_map))

    return blocks


def _make_text_block(
    p_elem: etree._Element,
    index: int,
    text: str,
    style_map: dict[str, str],
) -> SemanticBlock:
    style_name = _get_style_name(p_elem, style_map)
    role = _style_to_role(style_name)
    heading_level = _heading_level_from_role(role)
    list_ordered, list_depth = _list_info(p_elem)

    return SemanticBlock(
        index=index,
        text=text,
        role=role,
        heading_level=heading_level,
        list_ordered=list_ordered,
        list_depth=list_depth,
        original_style_name=style_name or None,
        has_conflicting_style=_is_conflicting_style(style_name),
        raw_xml=None,    # solo se captura para ecuaciones e imagenes
    )


def _has_equation(p_elem: etree._Element) -> bool:
    """True si el parrafo contiene al menos un elemento OMML (ecuacion)."""
    return (
        p_elem.find(_TAG_OMATH) is not None
        or p_elem.find(_TAG_OMATH_R) is not None
    )


def _has_image(p_elem: etree._Element) -> bool:
    """True si el parrafo contiene una imagen inline o VML."""
    return (
        p_elem.find(f".//{_TAG_DRAWING}") is not None
        or p_elem.find(f".//{_TAG_PICT}") is not None
    )


def _make_equation_block(
    p_elem: etree._Element,
    index: int,
    style_map: dict[str, str],
) -> SemanticBlock:
    """Crea un bloque EQUATION preservando el XML crudo (§7)."""
    return SemanticBlock(
        index=index,
        text="",       # texto no es representativo para ecuaciones
        role=SemanticRole.EQUATION,
        raw_xml=etree.tostring(p_elem, encoding="unicode"),
        original_style_name=_get_style_name(p_elem, style_map) or None,
    )


def _make_image_block(
    p_elem: etree._Element,
    index: int,
    style_map: dict[str, str],
) -> SemanticBlock:
    """
    Crea un bloque IMAGE preservando el XML crudo y el rId de la imagen (§7).

    El rId permite a docx_builder.py localizar la imagen en el package
    de relaciones del .docx para copiarla al documento de salida.
    """
    # Buscar el rId de la imagen (atributo r:embed en pic:blipFill/a:blip o
    # en v:imagedata para VML)
    image_rId: str | None = None

    blip = p_elem.find(
        f".//{{{_NS['a']}}}blip"
    )
    if blip is not None:
        image_rId = blip.get(f"{{{_NS['r']}}}embed")

    if not image_rId:
        # Intentar con VML legado
        imagedata = p_elem.find(
            f".//{{urn:schemas-microsoft-com:vml}}imagedata"
        )
        if imagedata is not None:
            image_rId = imagedata.get(f"{{{_NS['r']}}}id")

    return SemanticBlock(
        index=index,
        text="",
        role=SemanticRole.IMAGE,
        raw_xml=etree.tostring(p_elem, encoding="unicode"),
        image_rId=image_rId,
        original_style_name=_get_style_name(p_elem, style_map) or None,
    )


# ===========================================================================
# Extraccion de tablas
# ===========================================================================

def _extract_from_table(
    tbl_elem: etree._Element,
    start_index: int,
) -> list[SemanticBlock]:
    """
    Extrae SemanticBlock[] de un elemento <w:tbl>.

    La primera fila se clasifica como TABLE_HEADER; las demas como TABLE_CELL.
    Cada celda con texto genera un bloque independiente.

    Cada bloque lleva table_id (identifica a que tabla pertenece — necesario
    cuando el documento tiene mas de una), row_index y col_index, para que
    docx_builder.py (Paso 5) pueda reconstruir la tabla con su forma
    original en vez de recibir una lista plana sin estructura.

    Celdas combinadas (w:gridSpan): se avanza col_index el numero de
    columnas que ocupa la celda, para que la celda siguiente en la misma
    fila quede en su posicion real de columna, no desalineada.

    Limitacion conocida: no se maneja w:vMerge (combinacion vertical) ni
    tablas anidadas dentro de una celda — quedan fuera del alcance v1 y
    deben tratarse como caso limite adicional si aparecen en documentos reales.
    """
    blocks: list[SemanticBlock] = []
    index = start_index
    table_id = f"table-{uuid.uuid4().hex[:8]}"

    rows = tbl_elem.findall(qn("w:tr"))
    for row_num, row in enumerate(rows):
        is_header_row = (row_num == 0)
        role = SemanticRole.TABLE_HEADER if is_header_row else SemanticRole.TABLE_CELL

        col_index = 0
        for cell in row.findall(qn("w:tc")):
            span = _cell_grid_span(cell)
            text = _collect_cell_text(cell)
            if text:
                blocks.append(SemanticBlock(
                    index=index,
                    text=text,
                    role=role,
                    raw_xml=None,
                    table_id=table_id,
                    row_index=row_num,
                    col_index=col_index,
                ))
                index += 1
            col_index += span

    return blocks


def _collect_cell_text(cell: etree._Element) -> str:
    """Texto de una celda: sus parrafos separados por salto de linea (si no, las palabras se pegan)."""
    parts = [_collect_text(child) for child in cell if child.tag in (qn("w:p"), qn("w:tbl"))]
    return "\n".join(text for text in parts if text)


def _cell_grid_span(cell: etree._Element) -> int:
    """
    Numero de columnas que ocupa una celda (1 si no esta combinada
    horizontalmente). Lee <w:gridSpan w:val="N"/> dentro de <w:tcPr>.
    """
    tcPr = cell.find(qn("w:tcPr"))
    if tcPr is None:
        return 1
    grid_span = tcPr.find(qn("w:gridSpan"))
    if grid_span is None:
        return 1
    try:
        return int(grid_span.get(qn("w:val"), "1"))
    except (TypeError, ValueError):
        return 1


# ===========================================================================
# Helpers de XML / texto
# ===========================================================================

def _collect_text(elem: etree._Element, skip_embedded: bool = False) -> str:
    """
    Extrae el texto plano de un elemento XML recorriendo todos sus
    descendientes <w:t>, respetando <w:br> como salto de linea.

    Con `skip_embedded=True` se ignora el texto dentro de dibujos, imagenes
    VML, objetos y `mc:AlternateContent` (p. ej. cuadros de texto): queda solo
    el texto propio del parrafo.
    """
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        for child in node:
            if skip_embedded and child.tag in _EMBEDDED_TAGS:
                continue
            if child.tag == qn("w:t"):
                parts.append(child.text or "")
            elif child.tag == qn("w:br"):
                parts.append("\n")
            elif child.tag == qn("w:tab"):
                parts.append("\t")
            walk(child)

    walk(elem)
    return "".join(parts).strip()


def _build_style_id_to_name(doc: Document) -> dict[str, str]:
    """
    Construye el mapeo styleId crudo -> nombre de estilo legible normalizado,
    leyendo word/styles.xml a traves de doc.styles.

    Los estilos integrados de Word/LibreOffice usan un styleId sin espacios
    en <w:pStyle w:val="..."> (ej. "Heading1", "ListParagraph"), pero
    _STYLE_TO_ROLE / _CONFLICTING_STYLE_NAMES estan indexados por el nombre
    legible con espacios (ej. "heading 1", "list paragraph") que es el que
    ve el usuario en Word (w:styles/w:style/w:name/@w:val). Sin este mapeo,
    _get_style_name() devolveria el styleId crudo y jamas coincidiria con
    esos diccionarios para documentos reales generados por Word.
    """
    mapping: dict[str, str] = {}
    for style in doc.styles:
        style_id = style.style_id
        if not style_id:
            continue
        name = style.name or style_id
        mapping[style_id] = name.lower().replace("-", " ").replace("_", " ")
    return mapping


def _get_style_name(p_elem: etree._Element, style_map: dict[str, str]) -> str:
    """
    Devuelve el nombre legible del estilo Word del parrafo en minusculas
    (resuelto via style_map desde el styleId crudo), o cadena vacia si no
    tiene estilo declarado.
    """
    pPr = p_elem.find(qn("w:pPr"))
    if pPr is None:
        return ""
    pStyle = pPr.find(qn("w:pStyle"))
    if pStyle is None:
        return ""
    style_id = pStyle.get(qn("w:val"), "")
    if not style_id:
        return ""
    # Si el styleId no esta en el mapeo (no deberia ocurrir en un .docx
    # valido), se normaliza el ID crudo como respaldo defensivo.
    return style_map.get(style_id, style_id.lower().replace("-", " ").replace("_", " "))


def _style_to_role(style_name: str) -> SemanticRole:
    """
    Mapea el nombre de estilo Word normalizado a un SemanticRole preliminar.
    Si no hay coincidencia, devuelve BODY (lo mas neutral).
    Gemini corregira en el Paso 3 si la heuristica falla.
    """
    if not style_name:
        return SemanticRole.BODY

    role = _STYLE_TO_ROLE.get(style_name)
    if role:
        return role

    # Intentar coincidencia parcial para variantes localizadas
    # (ej. "heading1", "ttulo1", "titol1")
    for key, mapped_role in _STYLE_TO_ROLE.items():
        if key in style_name or style_name in key:
            return mapped_role

    # Sin coincidencia: BODY por defecto
    return SemanticRole.BODY


def _heading_level_from_role(role: SemanticRole) -> int | None:
    """Extrae el nivel numerico del heading desde el enum (1-4) o None."""
    _map = {
        SemanticRole.HEADING1: 1,
        SemanticRole.HEADING2: 2,
        SemanticRole.HEADING3: 3,
        SemanticRole.HEADING4: 4,
    }
    return _map.get(role)


def _list_info(p_elem: etree._Element) -> tuple[bool | None, int]:
    """
    Detecta si el parrafo pertenece a una lista y si es ordenada o no.

    Devuelve (list_ordered, list_depth):
    - list_ordered: True=ordenada, False=desordenada, None=no es lista
    - list_depth: nivel de anidacion 0-based (0 si no es lista)
    """
    pPr = p_elem.find(qn("w:pPr"))
    if pPr is None:
        return None, 0

    numPr = pPr.find(qn("w:numPr"))
    if numPr is None:
        return None, 0

    # Nivel de anidacion (ilvl)
    ilvl_elem = numPr.find(qn("w:ilvl"))
    depth = int(ilvl_elem.get(qn("w:val"), "0")) if ilvl_elem is not None else 0

    # Tipo de lista: no podemos saberlo sin acceder al numbering.xml en detalle,
    # pero la mayoria de listas con numId distinguen ordenadas (1,2,3) de bullets.
    # Marcamos como None para que Gemini lo determine en el Paso 3.
    return None, depth


def _is_conflicting_style(style_name: str) -> bool:
    """True si el estilo tiene nombre que puede entrar en conflicto con el template."""
    if not style_name:
        return False
    for conflict in _CONFLICTING_STYLE_NAMES:
        if conflict in style_name or style_name in conflict:
            return True
    return False


# ===========================================================================
# Construccion de DocumentMeta
# ===========================================================================

def _build_meta(
    blocks: list[SemanticBlock],
    processing_id: str,
    original_filename: str,
    docx_path: Path,
) -> DocumentMeta:
    """
    Construye DocumentMeta a partir de los bloques extraidos y el archivo.
    """
    heading_roles = {
        SemanticRole.HEADING1, SemanticRole.HEADING2,
        SemanticRole.HEADING3, SemanticRole.HEADING4,
    }
    table_roles = {SemanticRole.TABLE_HEADER, SemanticRole.TABLE_CELL}

    heading_count = sum(1 for b in blocks if b.role in heading_roles)
    has_tables    = any(b.role in table_roles for b in blocks)
    has_images    = any(b.role == SemanticRole.IMAGE for b in blocks)
    has_equations = any(b.role == SemanticRole.EQUATION for b in blocks)
    has_conflicting = any(b.has_conflicting_style for b in blocks)

    # Detectar idioma
    all_text = " ".join(b.text for b in blocks if b.text)
    lang = _detect_language(all_text)

    # Formato
    suffix = Path(original_filename).suffix.lower()
    input_format = suffix.lstrip(".")   # "docx" o "doc"
    was_converted = (suffix == ".doc")

    meta = DocumentMeta(
        processing_id=processing_id,
        original_filename=original_filename,
        input_format=input_format,
        was_converted=was_converted,
        file_size_bytes=docx_path.stat().st_size,
        is_valid=False,   # validator.py lo pone en True si pasa todas las comprobaciones
        block_count=len(blocks),
        heading_count=heading_count,
        has_tables=has_tables,
        has_images=has_images,
        has_equations=has_equations,
        has_conflicting_styles=has_conflicting,
        detected_language=lang,
    )
    return meta


def _detect_language(text: str) -> DocumentLanguage:
    """
    Heuristica simple de deteccion de idioma: cuenta apariciones de
    stopwords espanolas vs inglesas en el texto del documento.

    No requiere dependencias externas (no usa langdetect).
    Retorna UNKNOWN si no hay texto suficiente para decidir.
    """
    if len(text) < 50:
        return DocumentLanguage.UNKNOWN

    words = set(text.lower().split())
    es_hits = len(words & _SPANISH_STOPWORDS)
    en_hits = len(words & _ENGLISH_STOPWORDS)

    if es_hits == 0 and en_hits == 0:
        return DocumentLanguage.UNKNOWN
    if es_hits > en_hits:
        return DocumentLanguage.SPANISH
    if en_hits > es_hits:
        return DocumentLanguage.ENGLISH
    return DocumentLanguage.UNKNOWN    # empate -> no se puede decidir


# ===========================================================================
# Comprobaciones post-extraccion
# ===========================================================================

def _check_scanned_or_empty(
    blocks: list[SemanticBlock],
    meta: DocumentMeta,
    filename: str,
) -> None:
    """
    Lanza ScannedDocumentError o EmptyDocumentError si procede.

    Se llama despues de construir la lista completa de bloques.

    Raises
    ------
    ScannedDocumentError
        Si hay imagenes pero no texto seleccionable (documento escaneado).
    EmptyDocumentError
        Si no hay ningun bloque de contenido.
    """
    if not blocks:
        meta.is_empty = True
        raise EmptyDocumentError(filename=filename, block_count=0)

    # Contar bloques con texto real vs bloques solo de imagen
    text_blocks  = [b for b in blocks if b.text]
    image_blocks = [b for b in blocks if b.role == SemanticRole.IMAGE]

    if image_blocks and not text_blocks:
        meta.is_scanned = True
        raise ScannedDocumentError(filename=filename)
