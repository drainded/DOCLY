"""
engine/formatting/section_titles.py
=====================================
Reconocimiento deterministico de titulos de seccion con un papel fijo en la
maquetacion APA (resumen, nota del autor, referencias, apendices) y de los
rotulos de tabla/figura. Funciona en espanol e ingles; no usa IA.

Lo comparten template_engine.py (saltos de pagina, titulo repetido) y
docx_builder.py (no duplicar el titulo de referencias, formato de rotulos).
"""

from __future__ import annotations

import re
import unicodedata

_ABSTRACT_TITLES = frozenset({"abstract", "resumen"})
_AUTHOR_NOTE_TITLES = frozenset({"author note", "nota del autor", "nota de autor", "nota de los autores"})
_REFERENCE_TITLES = frozenset({
    "references", "reference list", "referencias", "lista de referencias", "referencias bibliograficas",
    "bibliografia", "bibliography", "works cited", "fuentes de informacion", "fuentes consultadas",
})
_APPENDIX_PREFIX = re.compile(r"^(appendix|appendices|apendice|apendices|anexo|anexos)\b")
_CAPTION_LABEL = re.compile(r"^(table|figure|tabla|figura)\s+[a-z]?\d+(\.\d+)?\s*[.:]?$")


def normalize_title(text: str) -> str:
    """Minusculas, sin tildes, sin signos finales y con espacios colapsados."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.split()).strip(" .:")


def is_abstract_title(text: str) -> bool:
    return normalize_title(text) in _ABSTRACT_TITLES


def is_author_note_title(text: str) -> bool:
    return normalize_title(text) in _AUTHOR_NOTE_TITLES


def is_reference_title(text: str) -> bool:
    return normalize_title(text) in _REFERENCE_TITLES


def is_appendix_title(text: str) -> bool:
    return bool(_APPENDIX_PREFIX.match(normalize_title(text)))


def is_caption_label(text: str) -> bool:
    """True para una linea que es solo el rotulo: "Table 1", "Figura 2.", "Tabla A1"."""
    return bool(_CAPTION_LABEL.match(normalize_title(text)))
