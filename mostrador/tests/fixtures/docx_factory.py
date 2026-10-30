"""
tests/fixtures/docx_factory.py
================================
Genera .docx de entrada para los tests end-to-end del pipeline con python-docx
(en vez de versionar binarios). Cada fabrica devuelve ademas el texto esperado
para poder verificar el criterio "no hay perdida de contenido" (seccion 6).
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import docx

from engine.document.models import SemanticRole

# 1x1 pixel PNG rojo
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)

COVER_TITLE = "Analisis del impacto de la automatizacion"
COVER_AUTHOR = "Maria Gomez"
COVER_INSTITUTION = "Universidad Nacional"
HEADINGS = [("Introduccion", 1), ("Marco teorico", 1), ("Antecedentes", 2), ("Conclusiones", 1)]
BODY_TEXTS = [
    "El presente trabajo estudia el efecto de la automatizacion en los procesos de oficina.",
    "La literatura sugiere que la adopcion de herramientas digitales reduce los tiempos de entrega.",
    "Los resultados muestran que los equipos que automatizan obtienen mejoras sostenidas.",
]
LIST_ITEMS = ["Reduccion de costos operativos", "Mayor trazabilidad de los documentos"]
TABLE_CELLS = [["Metrica", "Valor"], ["Tiempo", "12 min"]]
REFERENCES = [
    "Perez, J. (2020). Automatizacion de oficinas. Editorial Andina.",
    "Smith, A. (2019). Digital workflows. Journal of Office Studies, 4(2), 11-25.",
]

# Rol que un clasificador (real o simulado) deberia asignar a cada texto
EXPECTED_ROLES: dict[str, SemanticRole] = {
    COVER_TITLE: SemanticRole.COVER_TITLE,
    COVER_AUTHOR: SemanticRole.COVER_AUTHOR,
    COVER_INSTITUTION: SemanticRole.COVER_INSTITUTION,
    **{ref: SemanticRole.REFERENCE for ref in REFERENCES},
}


def make_full_docx(path: Path, with_image: bool = False) -> list[str]:
    """
    Documento representativo: portada en parrafos Normal, headings de 2
    niveles, cuerpo, lista, tabla y referencias. Devuelve todos los textos
    que deben sobrevivir al formateo.
    """
    document = docx.Document()
    expected: list[str] = []

    for text in (COVER_TITLE, COVER_AUTHOR, COVER_INSTITUTION):
        document.add_paragraph(text)
        expected.append(text)

    for index, (heading, level) in enumerate(HEADINGS):
        document.add_heading(heading, level=level)
        expected.append(heading)
        if index < len(BODY_TEXTS):
            document.add_paragraph(BODY_TEXTS[index])
            expected.append(BODY_TEXTS[index])

    for item in LIST_ITEMS:
        document.add_paragraph(item, style="List Bullet")
        expected.append(item)

    table = document.add_table(rows=len(TABLE_CELLS), cols=2)
    for r, row in enumerate(TABLE_CELLS):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
            expected.append(value)

    for reference in REFERENCES:
        document.add_paragraph(reference)
        expected.append(reference)

    if with_image:
        document.add_paragraph().add_run().add_picture(io.BytesIO(base64.b64decode(_PNG_B64)))

    document.save(path)
    return expected


def make_plain_docx(path: Path) -> list[str]:
    """Documento sin estilos conflictivos (solo parrafos Normal): no pausa el pipeline."""
    document = docx.Document()
    texts = [COVER_TITLE, COVER_AUTHOR, *BODY_TEXTS]
    for text in texts:
        document.add_paragraph(text)
    document.save(path)
    return texts


def make_empty_docx(path: Path) -> None:
    docx.Document().save(path)
