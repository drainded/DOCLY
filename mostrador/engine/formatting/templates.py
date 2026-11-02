"""
engine/formatting/templates.py
================================
El `TEMPLATES` dict (seccion 4 del spec): la unica fuente de verdad para
toda decision de estilo visual en Mostrador. Nada de lo que hay aqui se
decide "on the fly" ni se deja a interpretacion de Gemini en tiempo de
ejecucion (seccion 4, principio de "mejora de estilo sin ambiguedad").

Quien lo consume:
  - engine/formatting/template_engine.py (Paso 4): valida el estilo
    solicitado y reordena los campos de portada segun `cover_field_order`.
  - engine/formatting/docx_builder.py (Paso 5): traduce cada TemplateSpec
    en estilos de Word concretos (fuente, color, espaciado, numeracion).

Alcance deliberado de v1
-------------------------
La "norma de citacion" (APA/IEEE/Vancouver) se aplica aqui unicamente a la
TIPOGRAFIA Y MAQUETACION del bloque de referencias (sangria francesa vs.
numeracion con corchetes vs. numeracion decimal) y de los encabezados
(numeracion romana/decimal, mayusculas). Mostrador v1 NO reescribe el
contenido de cada cita individual (autor, año, titulo...) porque
SemanticBlock solo transporta texto plano sin campos bibliograficos
estructurados (seccion 5: Gemini clasifica el rol de un bloque, nunca
reinterpreta su contenido) — reescribir citas requeriria un parser
bibliografico completo, fuera de alcance de v1 (seccion 8).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from engine.document.models import DocumentLanguage, FormatStyle, SemanticRole


# ---------------------------------------------------------------------------
# Enums de opciones de maquetacion (todas fijas por template, seccion 4)
# ---------------------------------------------------------------------------

class Alignment(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class HeadingNumbering(str, Enum):
    """Prefijo deterministico para encabezados de nivel 1 (seccion 4)."""
    NONE = "none"
    ROMAN = "roman"        # "I. ", "II. ", ... (convencion IEEE)
    DECIMAL = "decimal"    # "1. ", "2. ", ...   (convencion Vancouver)


class ReferenceNumbering(str, Enum):
    """Prefijo deterministico para cada entrada de la lista de referencias."""
    NONE = "none"                # sangria francesa, sin numero (convencion APA)
    BRACKETS = "brackets"        # "[1] "  (convencion IEEE)
    DECIMAL_DOT = "decimal_dot"  # "1. "   (convencion Vancouver)


class TableStyle(str, Enum):
    """Aspecto de las tablas (fijo por template)."""
    SHADED_GRID = "shaded_grid"  # cuadricula con fila de encabezado sombreada (IEEE, Vancouver)
    APA_RULES = "apa_rules"      # solo lineas horizontales: sobre el encabezado, bajo el encabezado y al pie


# ---------------------------------------------------------------------------
# Especificacion tipografica de un rol de contenido
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FontSpec:
    """
    Tipografia y espaciado de un rol de contenido. Cada campo se traduce
    1:1 a una propiedad de python-docx en docx_builder.py — nada se
    interpreta ni se decide fuera de esta clase.
    """
    name: str
    size_pt: float
    bold: bool = False
    italic: bool = False
    all_caps: bool = False
    color_hex: str = "000000"          # sin '#', 6 hex digits
    alignment: Alignment = Alignment.LEFT
    space_before_pt: float = 0.0
    space_after_pt: float = 0.0
    line_spacing: float | None = None   # None = sencillo (1.0)
    left_indent_pt: float = 0.0
    first_line_indent_pt: float = 0.0


@dataclass(frozen=True)
class SeparatorLineSpec:
    """Linea de separacion bajo cada encabezado de nivel 1 (seccion 4, punto 3)."""
    color_hex: str
    weight_pt: float


# ---------------------------------------------------------------------------
# Especificacion completa de un template (una entrada de TEMPLATES)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TemplateSpec:
    style: FormatStyle
    display_name: str

    # Paleta (seccion 4, punto 1): colores exactos, fijos por template.
    accent_color_hex: str
    separator_line: SeparatorLineSpec

    # Tipografia por rol de contenido (seccion 4, punto 5).
    fonts: dict[SemanticRole, FontSpec]

    # Estructura de portada (seccion 4, punto 2): orden fijo de los campos
    # que SI aparecieron en el documento (un campo ausente simplemente no
    # se renderiza, no es un error — COVER_COURSE es opcional).
    cover_field_order: tuple[SemanticRole, ...]

    # Titulos de secciones sinteticas que el builder inserta (no vienen
    # del documento original), por idioma detectado (seccion 7).
    toc_title: dict[DocumentLanguage, str]
    reference_section_title: dict[DocumentLanguage, str]
    toc_entry_font_scale: float  # factor aplicado al tamano del heading para su entrada de indice

    # Numeracion deterministica de encabezados y referencias (seccion 4).
    heading1_numbering: HeadingNumbering
    reference_numbering: ReferenceNumbering

    # Maquetacion global (valores por defecto = comportamiento de IEEE/Vancouver).
    include_toc: bool = True               # indice generado por codigo tras la portada
    separator_lines: bool = True           # linea bajo cada heading1 y bajo el titulo de portada
    table_style: TableStyle = TableStyle.SHADED_GRID
    page_numbers: bool = False             # numero de pagina arriba a la derecha
    cover_group_gap_pt: float = 18.0       # hueco entre grupos de campos de portada
    apa_layout: bool = False               # estructura APA 7 (portada por caso, resumen, titulo repetido, saltos)


# ---------------------------------------------------------------------------
# Helper: paleta compartida de portada/tabla derivada del accent_color_hex
# (evita que cada template tenga que declarar 6 tonos manualmente).
# ---------------------------------------------------------------------------

def _cover_fonts(accent_hex: str, title_all_caps: bool = False) -> dict[SemanticRole, FontSpec]:
    """Tipografia de los 5 campos de portada, con el mismo acento por template."""
    return {
        SemanticRole.COVER_TITLE: FontSpec(
            name="Times New Roman", size_pt=18, bold=True, all_caps=title_all_caps,
            color_hex=accent_hex, alignment=Alignment.CENTER,
            space_before_pt=36, space_after_pt=12, line_spacing=1.5,
        ),
        SemanticRole.COVER_AUTHOR: FontSpec(
            name="Times New Roman", size_pt=13, alignment=Alignment.CENTER,
            space_after_pt=4,
        ),
        SemanticRole.COVER_INSTITUTION: FontSpec(
            name="Times New Roman", size_pt=12, italic=True, alignment=Alignment.CENTER,
            space_after_pt=4,
        ),
        SemanticRole.COVER_COURSE: FontSpec(
            name="Times New Roman", size_pt=12, alignment=Alignment.CENTER,
            space_after_pt=4,
        ),
        SemanticRole.COVER_INSTRUCTOR: FontSpec(
            name="Times New Roman", size_pt=12, alignment=Alignment.CENTER,
            space_after_pt=4,
        ),
        SemanticRole.COVER_DATE: FontSpec(
            name="Times New Roman", size_pt=12, alignment=Alignment.CENTER,
            space_before_pt=24,
        ),
    }


def _extra_role_fonts(body: FontSpec) -> dict[SemanticRole, FontSpec]:
    """Roles de articulo (resumen, palabras clave, nota, anotacion) derivados del cuerpo."""
    return {
        SemanticRole.ABSTRACT: replace(body, first_line_indent_pt=0.0),
        SemanticRole.KEYWORDS: body,
        SemanticRole.AUTHOR_NOTE: body,
        SemanticRole.ANNOTATION: replace(body, first_line_indent_pt=0.0, left_indent_pt=28.0),
    }


_COVER_FIELD_ORDER = (
    SemanticRole.COVER_TITLE,
    SemanticRole.COVER_AUTHOR,
    SemanticRole.COVER_INSTITUTION,
    SemanticRole.COVER_COURSE,
    SemanticRole.COVER_INSTRUCTOR,
    SemanticRole.COVER_DATE,
)


# ---------------------------------------------------------------------------
# APA (7.a edicion), segun los trabajos de ejemplo oficiales de APA: todo en
# negro, sin indice ni lineas decorativas, doble espacio, texto alineado a la
# izquierda con sangria de primera linea de 0.5", encabezados de niveles 1-4,
# numero de pagina arriba a la derecha, tablas solo con lineas horizontales y
# referencias con sangria francesa sin numerar (el orden alfabetico se asume
# ya presente en el documento de entrada — Mostrador no reordena contenido
# bibliografico, ver docstring del modulo). La portada y las secciones
# (resumen, nota del autor, titulo repetido, saltos de pagina) dependen del
# tipo de documento y se resuelven en template_engine.py (`apa_layout`).
# ---------------------------------------------------------------------------

_APA_FONT = "Times New Roman"
_APA_HALF_INCH_PT = 36.0


def _apa_font(**overrides) -> FontSpec:
    """FontSpec base de APA 7: 12 pt, negro, doble espacio, sin espacio entre parrafos."""
    base = dict(name=_APA_FONT, size_pt=12, line_spacing=2.0)
    base.update(overrides)
    return FontSpec(**base)


_APA_BODY = _apa_font(first_line_indent_pt=_APA_HALF_INCH_PT)
_APA_COVER_LINE = _apa_font(alignment=Alignment.CENTER)

_APA_TEMPLATE = TemplateSpec(
    style=FormatStyle.APA,
    display_name="APA (7.a edicion)",
    accent_color_hex="000000",
    separator_line=SeparatorLineSpec(color_hex="000000", weight_pt=0.5),  # no se usa (separator_lines=False)
    fonts={
        SemanticRole.COVER_TITLE: _apa_font(bold=True, alignment=Alignment.CENTER, space_before_pt=72),
        SemanticRole.COVER_AUTHOR: _APA_COVER_LINE,
        SemanticRole.COVER_INSTITUTION: _APA_COVER_LINE,
        SemanticRole.COVER_COURSE: _APA_COVER_LINE,
        SemanticRole.COVER_INSTRUCTOR: _APA_COVER_LINE,
        SemanticRole.COVER_DATE: _APA_COVER_LINE,
        SemanticRole.HEADING1: _apa_font(bold=True, alignment=Alignment.CENTER),
        SemanticRole.HEADING2: _apa_font(bold=True),
        SemanticRole.HEADING3: _apa_font(bold=True, italic=True),
        SemanticRole.HEADING4: _apa_font(bold=True, first_line_indent_pt=_APA_HALF_INCH_PT),
        SemanticRole.BODY: _APA_BODY,
        SemanticRole.LIST_ITEM: _apa_font(),
        SemanticRole.BLOCKQUOTE: _apa_font(left_indent_pt=_APA_HALF_INCH_PT),
        SemanticRole.CAPTION: _apa_font(),
        SemanticRole.REFERENCE: _apa_font(
            left_indent_pt=_APA_HALF_INCH_PT, first_line_indent_pt=-_APA_HALF_INCH_PT,
        ),
        SemanticRole.ABSTRACT: _apa_font(),
        SemanticRole.KEYWORDS: _APA_BODY,
        SemanticRole.AUTHOR_NOTE: _APA_BODY,
        SemanticRole.ANNOTATION: _apa_font(left_indent_pt=_APA_HALF_INCH_PT),
        SemanticRole.TABLE_HEADER: _apa_font(bold=True, line_spacing=None),
        SemanticRole.TABLE_CELL: _apa_font(line_spacing=None),
    },
    cover_field_order=_COVER_FIELD_ORDER,
    toc_title={
        DocumentLanguage.SPANISH: "Índice", DocumentLanguage.ENGLISH: "Table of Contents",
        DocumentLanguage.UNKNOWN: "Índice",
    },
    reference_section_title={
        DocumentLanguage.SPANISH: "Referencias", DocumentLanguage.ENGLISH: "References",
        DocumentLanguage.UNKNOWN: "Referencias",
    },
    toc_entry_font_scale=0.85,
    heading1_numbering=HeadingNumbering.NONE,
    reference_numbering=ReferenceNumbering.NONE,
    include_toc=False,
    separator_lines=False,
    table_style=TableStyle.APA_RULES,
    page_numbers=True,
    cover_group_gap_pt=0.0,
    apa_layout=True,
)


# ---------------------------------------------------------------------------
# IEEE: espaciado sencillo, encabezados de nivel 1 en mayusculas con
# numeracion romana, referencias numeradas entre corchetes.
# ---------------------------------------------------------------------------

_IEEE_ACCENT = "00629B"  # azul institucional IEEE

_IEEE_TEMPLATE = TemplateSpec(
    style=FormatStyle.IEEE,
    display_name="IEEE",
    accent_color_hex=_IEEE_ACCENT,
    separator_line=SeparatorLineSpec(color_hex="4A90C2", weight_pt=1.25),
    fonts={
        **_cover_fonts(_IEEE_ACCENT, title_all_caps=True),
        SemanticRole.HEADING1: FontSpec(
            name="Times New Roman", size_pt=12, bold=True, all_caps=True, color_hex=_IEEE_ACCENT,
            alignment=Alignment.LEFT, space_before_pt=18, space_after_pt=6,
        ),
        SemanticRole.HEADING2: FontSpec(
            name="Times New Roman", size_pt=11, bold=True, italic=True,
            alignment=Alignment.LEFT, space_before_pt=12, space_after_pt=4,
        ),
        SemanticRole.HEADING3: FontSpec(
            name="Times New Roman", size_pt=10.5, italic=True,
            alignment=Alignment.LEFT, space_before_pt=8, space_after_pt=4,
        ),
        SemanticRole.HEADING4: FontSpec(
            name="Times New Roman", size_pt=10, italic=True,
            alignment=Alignment.LEFT, first_line_indent_pt=14, space_before_pt=6,
        ),
        SemanticRole.BODY: FontSpec(
            name="Times New Roman", size_pt=10, alignment=Alignment.JUSTIFY,
            first_line_indent_pt=14, space_after_pt=4,
        ),
        SemanticRole.LIST_ITEM: FontSpec(name="Times New Roman", size_pt=10),
        SemanticRole.BLOCKQUOTE: FontSpec(
            name="Times New Roman", size_pt=10, italic=True, left_indent_pt=28,
        ),
        SemanticRole.CAPTION: FontSpec(
            name="Times New Roman", size_pt=9, alignment=Alignment.CENTER,
        ),
        SemanticRole.REFERENCE: FontSpec(
            name="Times New Roman", size_pt=9, left_indent_pt=28,
            first_line_indent_pt=-28, space_after_pt=4,
        ),
        SemanticRole.TABLE_HEADER: FontSpec(
            name="Times New Roman", size_pt=9, bold=True, color_hex="FFFFFF",
            alignment=Alignment.CENTER,
        ),
        SemanticRole.TABLE_CELL: FontSpec(name="Times New Roman", size_pt=9),
    },
    cover_field_order=_COVER_FIELD_ORDER,
    toc_title={
        DocumentLanguage.SPANISH: "Índice", DocumentLanguage.ENGLISH: "Table of Contents",
        DocumentLanguage.UNKNOWN: "Índice",
    },
    reference_section_title={
        DocumentLanguage.SPANISH: "Referencias", DocumentLanguage.ENGLISH: "References",
        DocumentLanguage.UNKNOWN: "Referencias",
    },
    toc_entry_font_scale=0.85,
    heading1_numbering=HeadingNumbering.ROMAN,
    reference_numbering=ReferenceNumbering.BRACKETS,
)


# ---------------------------------------------------------------------------
# Vancouver: convencion habitual en articulos biomedicos — encabezados
# numerados decimalmente, referencias numeradas con punto (no corchetes).
# ---------------------------------------------------------------------------

_VANCOUVER_ACCENT = "006633"

_VANCOUVER_TEMPLATE = TemplateSpec(
    style=FormatStyle.VANCOUVER,
    display_name="Vancouver",
    accent_color_hex=_VANCOUVER_ACCENT,
    separator_line=SeparatorLineSpec(color_hex="7FAF8C", weight_pt=1.0),
    fonts={
        **_cover_fonts(_VANCOUVER_ACCENT),
        SemanticRole.HEADING1: FontSpec(
            name="Times New Roman", size_pt=13, bold=True, color_hex=_VANCOUVER_ACCENT,
            alignment=Alignment.LEFT, space_before_pt=20, space_after_pt=8, line_spacing=1.5,
        ),
        SemanticRole.HEADING2: FontSpec(
            name="Times New Roman", size_pt=12, bold=True,
            alignment=Alignment.LEFT, space_before_pt=14, space_after_pt=6, line_spacing=1.5,
        ),
        SemanticRole.HEADING3: FontSpec(
            name="Times New Roman", size_pt=12, italic=True,
            alignment=Alignment.LEFT, space_before_pt=10, space_after_pt=4, line_spacing=1.5,
        ),
        SemanticRole.HEADING4: FontSpec(
            name="Times New Roman", size_pt=12, italic=True,
            alignment=Alignment.LEFT, first_line_indent_pt=18, space_before_pt=6, line_spacing=1.5,
        ),
        SemanticRole.BODY: FontSpec(
            name="Times New Roman", size_pt=12, alignment=Alignment.JUSTIFY,
            line_spacing=1.5, space_after_pt=6,
        ),
        SemanticRole.LIST_ITEM: FontSpec(name="Times New Roman", size_pt=12, line_spacing=1.5),
        SemanticRole.BLOCKQUOTE: FontSpec(
            name="Times New Roman", size_pt=12, italic=True, left_indent_pt=36, line_spacing=1.5,
        ),
        SemanticRole.CAPTION: FontSpec(
            name="Times New Roman", size_pt=10, italic=True, alignment=Alignment.CENTER,
        ),
        SemanticRole.REFERENCE: FontSpec(
            name="Times New Roman", size_pt=11, left_indent_pt=28,
            first_line_indent_pt=-28, space_after_pt=6,
        ),
        SemanticRole.TABLE_HEADER: FontSpec(
            name="Times New Roman", size_pt=11, bold=True, color_hex="FFFFFF",
            alignment=Alignment.CENTER,
        ),
        SemanticRole.TABLE_CELL: FontSpec(name="Times New Roman", size_pt=11),
    },
    cover_field_order=_COVER_FIELD_ORDER,
    toc_title={
        DocumentLanguage.SPANISH: "Índice", DocumentLanguage.ENGLISH: "Table of Contents",
        DocumentLanguage.UNKNOWN: "Índice",
    },
    reference_section_title={
        DocumentLanguage.SPANISH: "Referencias", DocumentLanguage.ENGLISH: "References",
        DocumentLanguage.UNKNOWN: "Referencias",
    },
    toc_entry_font_scale=0.85,
    heading1_numbering=HeadingNumbering.DECIMAL,
    reference_numbering=ReferenceNumbering.DECIMAL_DOT,
)


# IEEE y Vancouver no distinguen resumen/nota/anotacion: heredan el cuerpo.
for _template in (_IEEE_TEMPLATE, _VANCOUVER_TEMPLATE):
    for _role, _font in _extra_role_fonts(_template.fonts[SemanticRole.BODY]).items():
        _template.fonts.setdefault(_role, _font)


# ---------------------------------------------------------------------------
# API publica del modulo
# ---------------------------------------------------------------------------

TEMPLATES: dict[FormatStyle, TemplateSpec] = {
    FormatStyle.APA: _APA_TEMPLATE,
    FormatStyle.IEEE: _IEEE_TEMPLATE,
    FormatStyle.VANCOUVER: _VANCOUVER_TEMPLATE,
}
