"""
tests/document/test_extractor_image_paragraphs.py
====================================================
Regresion: un parrafo que mezcla texto e imagen (o cuadro de texto) se
extraia solo como bloque IMAGE y su texto se perdia (hallazgo con un
documento real; criterio "sin perdida de contenido", seccion 6).
"""

import base64
import io

import docx
from lxml import etree

from engine.document.extractor import extract_blocks
from engine.document.models import FormatStyle, SemanticRole
from engine.formatting.docx_builder import build_docx

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"

_TEXTBOX_ALTERNATE = f"""
<mc:AlternateContent xmlns:mc="{_MC}" xmlns:w="{_W}">
  <mc:Choice Requires="wps">
    <w:drawing><w:txbxContent><w:p><w:r><w:t>Figura 1: pie de figura</w:t></w:r></w:p></w:txbxContent></w:drawing>
  </mc:Choice>
  <mc:Fallback>
    <w:pict><w:txbxContent><w:p><w:r><w:t>Figura 1: pie de figura</w:t></w:r></w:p></w:txbxContent></w:pict>
  </mc:Fallback>
</mc:AlternateContent>
"""


def _extract(document, tmp_path):
    path = tmp_path / "in.docx"
    document.save(path)
    return extract_blocks(docx_path=path, processing_id="t", original_filename="in.docx")[0]


def test_paragraph_with_text_and_image_keeps_both_in_order(tmp_path):
    document = docx.Document()
    paragraph = document.add_paragraph("Dibujado de las cajas: ")
    paragraph.add_run().add_picture(io.BytesIO(_PNG))

    blocks = _extract(document, tmp_path)

    assert [(b.role, b.text) for b in blocks] == [
        (SemanticRole.BODY, "Dibujado de las cajas:"),
        (SemanticRole.IMAGE, ""),
    ]
    assert [b.index for b in blocks] == [0, 1]


def test_image_only_paragraph_still_yields_just_the_image(tmp_path):
    document = docx.Document()
    document.add_paragraph("Texto")
    document.add_paragraph().add_run().add_picture(io.BytesIO(_PNG))

    blocks = _extract(document, tmp_path)

    assert [b.role for b in blocks] == [SemanticRole.BODY, SemanticRole.IMAGE]


def test_textbox_text_is_kept_once_despite_fallback_copy(tmp_path):
    document = docx.Document()
    paragraph = document.add_paragraph("Texto propio.")
    paragraph.runs[0]._r.append(etree.fromstring(_TEXTBOX_ALTERNATE))

    blocks = _extract(document, tmp_path)

    assert [(b.role, b.text) for b in blocks] == [
        (SemanticRole.BODY, "Texto propio."),
        (SemanticRole.IMAGE, ""),
        (SemanticRole.BODY, "Figura 1: pie de figura"),
    ]


def test_text_next_to_image_survives_the_whole_build(tmp_path):
    document = docx.Document()
    paragraph = document.add_paragraph("Texto junto a la imagen")
    paragraph.add_run().add_picture(io.BytesIO(_PNG))
    source = tmp_path / "in.docx"
    document.save(source)
    blocks = extract_blocks(docx_path=source, processing_id="t", original_filename="in.docx")[0]
    out = tmp_path / "out.docx"

    build_docx(blocks=blocks, style=FormatStyle.APA, output_path=out, source_docx_path=source)

    result = docx.Document(out)
    assert "Texto junto a la imagen" in [p.text for p in result.paragraphs]
    assert len(result.inline_shapes) == 1


def test_table_cell_paragraphs_are_separated_not_glued(tmp_path):
    document = docx.Document()
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "Primera pregunta."
    cell.add_paragraph("Segunda pregunta.")

    blocks = _extract(document, tmp_path)

    assert [b.text for b in blocks if b.table_id] == ["Primera pregunta.\nSegunda pregunta."]
