"""
engine/formatting/docx_builder.py
====================================
Paso 5 del pipeline: generacion del .docx final via python-docx (seccion 5,
Paso 5). Traduce el TEMPLATES[style] (formatting/templates.py, seccion 4)
en un documento Word concreto a partir de los SemanticBlock ya reordenados
por template_engine.py (Paso 4).

Expone una funcion publica (contrato firmado con pipeline.py):

    build_docx(blocks, style, output_path, source_docx_path, language) -> None

Estructura del documento generado
------------------------------------
1. Portada: campos COVER_* en el orden fijo del template, con salto de
   pagina al final (seccion 4, punto 2).
2. Indice: generado POR CODIGO recorriendo los bloques HEADING1-4 ya
   clasificados (seccion 4, punto 4) — NO se usa el campo TOC nativo de
   Word. Se eligio la version por codigo porque un campo TOC nativo
   aparece vacio ("haga clic para actualizar") hasta que alguien lo abre
   en Word y presiona F9; como la vista previa de Paso 6 se genera en
   headless sin intervencion humana, un TOC nativo violaria el criterio
   de aceptacion de la seccion 6 ("la vista previa coincide visualmente
   con el template"). La contrapartida documentada: al no correr una
   pasada de paginacion real, las entradas del indice no llevan numero de
   pagina, solo el texto del heading indentado por nivel.
3. Cuerpo: cada bloque se renderiza segun su rol usando la tipografia de
   TEMPLATES[style].fonts (seccion 4, punto 5). Casos especiales:
   - HEADING1: numeracion + linea separadora inferior (seccion 4, punto 3).
   - TABLE_HEADER/TABLE_CELL: se agrupan por `table_id` y se reconstruyen
     como una unica tabla real en su posicion original (seccion 7).
   - EQUATION: se reinserta el XML OMML capturado por extractor.py sin
     modificar (seccion 7) — autocontenido, no requiere relaciones del
     paquete origen.
   - IMAGE: se copian los BYTES de la imagen desde el documento origen
     (via `image_rId`) y se insertan con `add_picture`, en vez de
     reinyectar el XML crudo — un `r:embed` copiado literalmente
     apuntaria a una relacion que no existe en el paquete nuevo. Esto
     preserva el contenido visual (seccion 7) aunque la estructura XML
     interna del run de imagen no sea byte-identica a la original.
   - REFERENCE: se antepone una unica vez el titulo de seccion
     ("Referencias"/"References") y se numera cada entrada segun
     TEMPLATES[style].reference_numbering.

Limitaciones conocidas de v1 (documentadas, no bugs)
-------------------------------------------------------
* Celdas con combinacion vertical (w:vMerge) o tablas anidadas: extractor.py
  ya no las modela (ver su docstring); aqui se reconstruyen como celdas
  independientes.
* `SemanticBlock.list_ordered` siempre es None en v1 (extractor.py no
  resuelve numFmt desde numbering.xml) — se trata como lista no ordenada
  (bullet) por defecto.
* La "norma de citacion" (APA/IEEE/Vancouver) solo afecta tipografia y
  numeracion del bloque de referencias, no el contenido de cada cita
  individual (ver docstring de formatting/templates.py).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import docx
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

from engine.core.exceptions import DocxBuildError
from engine.document.models import DocumentLanguage, FormatStyle, SemanticBlock, SemanticRole
from engine.formatting.templates import (
    TEMPLATES,
    Alignment,
    FontSpec,
    HeadingNumbering,
    ReferenceNumbering,
    TemplateSpec,
)

logger = logging.getLogger(__name__)

_ALIGNMENT_MAP = {
    Alignment.LEFT: WD_ALIGN_PARAGRAPH.LEFT,
    Alignment.CENTER: WD_ALIGN_PARAGRAPH.CENTER,
    Alignment.RIGHT: WD_ALIGN_PARAGRAPH.RIGHT,
    Alignment.JUSTIFY: WD_ALIGN_PARAGRAPH.JUSTIFY,
}

_HEADING_ROLE_BY_LEVEL: dict[int, SemanticRole] = {
    1: SemanticRole.HEADING1, 2: SemanticRole.HEADING2,
    3: SemanticRole.HEADING3, 4: SemanticRole.HEADING4,
}

_LIST_STYLE_BY_DEPTH_ORDERED = {0: "List Number", 1: "List Number 2", 2: "List Number 3"}
_LIST_STYLE_BY_DEPTH_UNORDERED = {0: "List Bullet", 1: "List Bullet 2", 2: "List Bullet 3"}

_EXISTING_REFERENCE_NUMBER = re.compile(r"^\s*(?:\[\d+\]\s*|\(\d+\)\s*|\d+[.)]\s+)")
_IMAGE_MAX_WIDTH_INCHES = 6.0
_COVER_IMAGE_MAX_WIDTH_INCHES = 3.0  # logo de portada: no debe desplazar el resto de la portada

_ROMAN_NUMERAL_TABLE = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


# ===========================================================================
# API publica
# ===========================================================================

def build_docx(
    blocks: list[SemanticBlock],
    style: FormatStyle,
    output_path: Path,
    source_docx_path: Path | None = None,
    language: DocumentLanguage = DocumentLanguage.UNKNOWN,
) -> None:
    """
    Construye el .docx final aplicando TEMPLATES[style] sobre `blocks`.

    Parameters
    ----------
    blocks:
        Bloques ya reordenados por template_engine.py (Paso 4): los
        campos de portada van primero, en el orden fijo del template.
    style:
        Estilo de formato — debe existir en TEMPLATES (ya validado en
        Paso 4 por template_engine.apply_template).
    output_path:
        Ruta donde se escribe el .docx generado.
    source_docx_path:
        Ruta al .docx de trabajo del que se extrajeron los bloques
        (ctx.working_docx en pipeline.py). Necesaria para copiar los
        bytes de las imagenes embebidas (seccion 7); si es None, los
        bloques IMAGE se omiten con un warning en vez de fallar.
    language:
        Idioma detectado del documento (seccion 7), usado para el titulo
        del indice y de la seccion de referencias.

    Raises
    ------
    DocxBuildError
        Si python-docx no puede construir o guardar el documento.
    """
    template = TEMPLATES[style]

    try:
        document = docx.Document()
        _fix_template_settings(document)
        style_names = _register_content_styles(document, template)
        toc_style_names = _register_toc_entry_styles(document, template)

        cover_blocks = [b for b in blocks if b.belongs_to_cover()]
        remaining = [b for b in blocks if not b.belongs_to_cover()]
        heading_blocks = [b for b in remaining if b.is_heading()]

        _add_cover_page(document, cover_blocks, template, style_names, source_docx_path)
        _add_toc_section(document, heading_blocks, template, toc_style_names, language)
        _add_body(document, remaining, template, style_names, language, source_docx_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(output_path))
    except DocxBuildError:
        raise
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de python-docx se envuelve
        raise DocxBuildError(cause=exc) from exc


def _fix_template_settings(document: docx.Document) -> None:
    """
    La plantilla por defecto de python-docx escribe `<w:zoom/>` sin el
    atributo obligatorio `w:percent`, lo que hace fallar la validacion XSD
    del paquete (seccion 6). Se completa con el 100 % que escribe Word.
    """
    zoom = document.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")


# ===========================================================================
# Registro de estilos personalizados (styles.xml del documento de salida)
# ===========================================================================

def _register_content_styles(document: docx.Document, template: TemplateSpec) -> dict[SemanticRole, str]:
    """Registra un estilo de parrafo por cada rol de TEMPLATES[style].fonts."""
    style_names: dict[SemanticRole, str] = {}
    for role, font_spec in template.fonts.items():
        name = f"Mostrador {role.value}"
        style = document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        _apply_font_spec_to_style(style, font_spec)
        style_names[role] = name
    return style_names


def _register_toc_entry_styles(document: docx.Document, template: TemplateSpec) -> dict[int, str]:
    """
    Registra un estilo por nivel de heading (1-4) para las entradas del
    indice: mismo color/familia que el heading correspondiente, pero mas
    pequeño y sin negrita/mayusculas (TEMPLATES[style].toc_entry_font_scale),
    para diferenciarlo visualmente del cuerpo del documento.
    """
    style_names: dict[int, str] = {}
    for level, role in _HEADING_ROLE_BY_LEVEL.items():
        base_font = template.fonts[role]
        entry_font = replace(
            base_font,
            size_pt=round(base_font.size_pt * template.toc_entry_font_scale, 1),
            bold=False, italic=False, all_caps=False,
            alignment=Alignment.LEFT,
            first_line_indent_pt=0.0,
            left_indent_pt=(level - 1) * 18.0,
            space_before_pt=2.0, space_after_pt=2.0, line_spacing=None,
        )
        name = f"Mostrador toc_entry_{level}"
        style = document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        _apply_font_spec_to_style(style, entry_font)
        style_names[level] = name
    return style_names


def _apply_font_spec_to_style(style, font_spec: FontSpec) -> None:
    style.font.name = font_spec.name
    style.font.size = Pt(font_spec.size_pt)
    style.font.bold = font_spec.bold
    style.font.italic = font_spec.italic
    style.font.all_caps = font_spec.all_caps
    style.font.color.rgb = RGBColor.from_string(font_spec.color_hex)
    _apply_paragraph_format(style.paragraph_format, font_spec)


def _apply_font_spec_to_run(run, font_spec: FontSpec) -> None:
    run.font.name = font_spec.name
    run.font.size = Pt(font_spec.size_pt)
    run.font.bold = font_spec.bold
    run.font.italic = font_spec.italic
    run.font.all_caps = font_spec.all_caps
    run.font.color.rgb = RGBColor.from_string(font_spec.color_hex)


def _apply_paragraph_format(pf, font_spec: FontSpec) -> None:
    pf.alignment = _ALIGNMENT_MAP[font_spec.alignment]
    pf.space_before = Pt(font_spec.space_before_pt)
    pf.space_after = Pt(font_spec.space_after_pt)
    if font_spec.line_spacing is not None:
        pf.line_spacing = font_spec.line_spacing
    if font_spec.left_indent_pt:
        pf.left_indent = Pt(font_spec.left_indent_pt)
    if font_spec.first_line_indent_pt:
        pf.first_line_indent = Pt(font_spec.first_line_indent_pt)


# ===========================================================================
# Portada (seccion 4, punto 2)
# ===========================================================================

def _add_cover_page(
    document: docx.Document,
    cover_blocks: list[SemanticBlock],
    template: TemplateSpec,
    style_names: dict[SemanticRole, str],
    source_docx_path: Path | None,
) -> None:
    if not cover_blocks:
        return

    source_document: docx.Document | None = None
    for block in cover_blocks:
        if block.role == SemanticRole.IMAGE:
            if source_document is None and source_docx_path is not None:
                source_document = docx.Document(str(source_docx_path))
            _add_image(document, block, source_document, _COVER_IMAGE_MAX_WIDTH_INCHES)
            continue
        paragraph = document.add_paragraph(block.text, style=style_names[block.role])
        if block.role == SemanticRole.COVER_TITLE:
            # Acento de portada (seccion 4, punto 1): linea bajo el titulo.
            _add_bottom_border(paragraph, template.separator_line.color_hex, template.separator_line.weight_pt)

    document.add_page_break()


# ===========================================================================
# Indice generado por codigo (seccion 4, punto 4 — ver docstring del modulo)
# ===========================================================================

def _add_toc_section(
    document: docx.Document,
    heading_blocks: list[SemanticBlock],
    template: TemplateSpec,
    toc_style_names: dict[int, str],
    language: DocumentLanguage,
) -> None:
    if not heading_blocks:
        return  # sin headings no hay nada que indexar (validator.py ya lo advirtio)

    title = template.toc_title.get(language, template.toc_title[DocumentLanguage.UNKNOWN])
    document.add_paragraph(title, style=f"Mostrador {SemanticRole.HEADING1.value}")

    for block in heading_blocks:
        level = block.heading_level or 1
        style_name = toc_style_names.get(level, toc_style_names[1])
        document.add_paragraph(block.text, style=style_name)

    document.add_page_break()


# ===========================================================================
# Cuerpo del documento
# ===========================================================================

def _add_body(
    document: docx.Document,
    blocks: list[SemanticBlock],
    template: TemplateSpec,
    style_names: dict[SemanticRole, str],
    language: DocumentLanguage,
    source_docx_path: Path | None,
) -> None:
    tables_by_id: dict[str, list[SemanticBlock]] = defaultdict(list)
    for block in blocks:
        if block.table_id is not None:
            tables_by_id[block.table_id].append(block)

    processed_table_ids: set[str] = set()
    heading1_counter = 0
    reference_counter = 0
    reference_section_started = False
    source_document: docx.Document | None = None

    for block in blocks:
        if block.table_id is not None:
            if block.table_id in processed_table_ids:
                continue  # ya se reconstruyo esta tabla completa
            _build_table(document, tables_by_id[block.table_id], template)
            processed_table_ids.add(block.table_id)
            continue

        if block.role == SemanticRole.EQUATION:
            _add_equation_paragraph(document, block)
            continue

        if block.role == SemanticRole.IMAGE:
            if source_document is None and source_docx_path is not None:
                source_document = docx.Document(str(source_docx_path))
            _add_image(document, block, source_document)
            continue

        if block.role == SemanticRole.REFERENCE:
            if not reference_section_started:
                title = template.reference_section_title.get(
                    language, template.reference_section_title[DocumentLanguage.UNKNOWN]
                )
                document.add_paragraph(title, style=style_names[SemanticRole.HEADING1])
                reference_section_started = True
            reference_counter += 1
            text = _with_reference_prefix(block.text, template.reference_numbering, reference_counter)
            document.add_paragraph(text, style=style_names[SemanticRole.REFERENCE])
            continue

        if block.role == SemanticRole.LIST_ITEM:
            _add_list_item(document, block, template)
            continue

        if block.role == SemanticRole.HEADING1:
            heading1_counter += 1
            text = _with_heading_prefix(block.text, template.heading1_numbering, heading1_counter)
            paragraph = document.add_paragraph(text, style=style_names[SemanticRole.HEADING1])
            _add_bottom_border(paragraph, template.separator_line.color_hex, template.separator_line.weight_pt)
            continue

        style_name = style_names.get(block.role)
        if style_name is None:
            # Rol UNKNOWN u otro no cubierto por el template: se preserva
            # tal cual, sin decoracion (ver SemanticRole.UNKNOWN docstring).
            document.add_paragraph(block.text)
            continue

        document.add_paragraph(block.text, style=style_name)


def _with_heading_prefix(text: str, numbering: HeadingNumbering, counter: int) -> str:
    if numbering == HeadingNumbering.ROMAN:
        return f"{_int_to_roman(counter)}. {text}"
    if numbering == HeadingNumbering.DECIMAL:
        return f"{counter}. {text}"
    return text


def _with_reference_prefix(text: str, numbering: ReferenceNumbering, counter: int) -> str:
    if numbering == ReferenceNumbering.BRACKETS:
        return f"[{counter}] {_strip_reference_number(text)}"
    if numbering == ReferenceNumbering.DECIMAL_DOT:
        return f"{counter}. {_strip_reference_number(text)}"
    return text


def _strip_reference_number(text: str) -> str:
    """Quita el numero de lista que ya traia la referencia ("[3] ", "3. ", "3) ", "(3) ")."""
    return _EXISTING_REFERENCE_NUMBER.sub("", text, count=1)


def _int_to_roman(number: int) -> str:
    parts: list[str] = []
    for value, symbol in _ROMAN_NUMERAL_TABLE:
        count, number = divmod(number, value)
        parts.append(symbol * count)
    return "".join(parts)


# ===========================================================================
# Listas (seccion 4; ver limitacion de list_ordered en el docstring del modulo)
# ===========================================================================

def _add_list_item(document: docx.Document, block: SemanticBlock, template: TemplateSpec) -> None:
    depth = min(block.list_depth, 2)
    ordered = bool(block.list_ordered)  # None -> False (bullet), limitacion documentada
    style_name = (_LIST_STYLE_BY_DEPTH_ORDERED if ordered else _LIST_STYLE_BY_DEPTH_UNORDERED)[depth]

    paragraph = document.add_paragraph(block.text, style=style_name)
    if paragraph.runs:
        _apply_font_spec_to_run(paragraph.runs[0], template.fonts[SemanticRole.LIST_ITEM])


# ===========================================================================
# Tablas (seccion 7: "se les aplica el estilo del template tambien")
# ===========================================================================

def _build_table(document: docx.Document, table_blocks: list[SemanticBlock], template: TemplateSpec) -> None:
    max_row = max(b.row_index for b in table_blocks if b.row_index is not None)
    max_col = max(b.col_index for b in table_blocks if b.col_index is not None)
    table = document.add_table(rows=max_row + 1, cols=max_col + 1)
    table.style = "Table Grid"

    header_bg_hex = _lighten_hex(template.accent_color_hex, factor=0.75)

    for block in table_blocks:
        if block.row_index is None or block.col_index is None:
            continue  # dato inconsistente — celda ya validada en Paso 4, no deberia ocurrir
        cell = table.cell(block.row_index, block.col_index)
        paragraph = cell.paragraphs[0]
        run = paragraph.add_run(block.text)

        is_header = block.role == SemanticRole.TABLE_HEADER
        font_spec = template.fonts[SemanticRole.TABLE_HEADER if is_header else SemanticRole.TABLE_CELL]
        _apply_font_spec_to_run(run, font_spec)
        paragraph.alignment = _ALIGNMENT_MAP[font_spec.alignment]

        if is_header:
            _set_cell_background(cell, header_bg_hex)


def _lighten_hex(hex_color: str, factor: float) -> str:
    """Mezcla `hex_color` con blanco (factor=0 -> original, factor=1 -> blanco)."""
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = round(r + (255 - r) * factor)
    g = round(g + (255 - g) * factor)
    b = round(b + (255 - b) * factor)
    return f"{r:02X}{g:02X}{b:02X}"


def _set_cell_background(cell, hex_color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


# ===========================================================================
# Lineas separadoras (seccion 4, punto 3)
# ===========================================================================

def _add_bottom_border(paragraph, color_hex: str, weight_pt: float) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(max(int(weight_pt * 8), 2)))  # octavos de punto
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), color_hex)
    pBdr.append(bottom)
    pPr.append(pBdr)


# ===========================================================================
# Ecuaciones OMML preservadas (seccion 7)
# ===========================================================================

def _add_equation_paragraph(document: docx.Document, block: SemanticBlock) -> None:
    if not block.raw_xml:
        logger.warning(
            "Bloque EQUATION sin raw_xml (index=%d) — se omite (no deberia ocurrir).",
            block.index,
        )
        return
    try:
        p_element = etree.fromstring(block.raw_xml.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        logger.warning(
            "No se pudo re-parsear la ecuacion OMML del bloque %d — se omite: %s",
            block.index, exc,
        )
        return

    body = document.element.body
    sectPr = body.find(qn("w:sectPr"))
    if sectPr is not None:
        sectPr.addprevious(p_element)
    else:
        body.append(p_element)


# ===========================================================================
# Imagenes embebidas (seccion 7 — ver docstring del modulo)
# ===========================================================================

def _add_image(
    document: docx.Document,
    block: SemanticBlock,
    source_document,
    max_width_inches: float = _IMAGE_MAX_WIDTH_INCHES,
) -> None:
    if source_document is None or not block.image_rId:
        logger.warning(
            "Bloque IMAGE sin documento fuente o sin image_rId (index=%d) — se omite.",
            block.index,
        )
        return

    try:
        image_part = source_document.part.rels[block.image_rId].target_part
        image_bytes = image_part.blob
    except KeyError:
        logger.warning(
            "No se encontro la relacion '%s' en el documento fuente para la imagen "
            "del bloque %d — se omite.", block.image_rId, block.index,
        )
        return

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    try:
        run.add_picture(BytesIO(image_bytes), width=Inches(max_width_inches))
    except Exception as exc:  # noqa: BLE001 — formato de imagen no reconocido por python-docx
        logger.warning("No se pudo insertar la imagen del bloque %d: %s", block.index, exc)
