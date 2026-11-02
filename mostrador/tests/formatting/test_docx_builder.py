"""
tests/formatting/test_docx_builder.py
========================================
Tests de engine/formatting/docx_builder.py (Paso 5, seccion 5).

Construye documentos reales con python-docx y reabre el .docx generado
para verificar su contenido — no se usan mocks de python-docx en si (solo
de los fallos de I/O), ya que el objetivo es confirmar que el documento
de salida es un OOXML valido y visualmente correcto.
"""

import base64
import io

import docx
import pytest

from engine.core.exceptions import DocxBuildError
from engine.document.models import DocumentLanguage, FormatStyle, SemanticBlock, SemanticRole
from engine.formatting.docx_builder import build_docx

# 1x1 pixel PNG rojo, para probar la copia de imagenes embebidas
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)
_FAKE_OMATH = (
    '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
    '<w:r><m:oMath><m:r><m:t>x=y+1</m:t></m:r></m:oMath></w:r></w:p>'
)


def _block(index, role, text="", **kwargs) -> SemanticBlock:
    return SemanticBlock(index=index, text=text, role=role, **kwargs)


def _make_source_docx_with_image(tmp_path):
    """Crea un .docx real con una imagen embebida y devuelve (path, rId)."""
    source = docx.Document()
    paragraph = source.add_paragraph()
    run = paragraph.add_run()
    run.add_picture(io.BytesIO(base64.b64decode(_PNG_B64)))
    source_path = tmp_path / "source.docx"
    source.save(source_path)

    image_rid = next(
        rid for rid, rel in source.part.rels.items() if "image" in rel.reltype
    )
    return source_path, image_rid


class TestBuildDocxBasicContent:
    def test_body_and_heading_blocks_are_written(self, tmp_path):
        blocks = [
            _block(0, SemanticRole.HEADING1, "Introduccion", heading_level=1),
            _block(1, SemanticRole.BODY, "Cuerpo del documento."),
        ]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.APA, output_path=out)

        result = docx.Document(out)
        texts = [p.text for p in result.paragraphs]
        assert "Introduccion" in texts
        assert "Cuerpo del documento." in texts

    @pytest.mark.parametrize(
        "style, expected_heading_text",
        [
            (FormatStyle.APA, "Introduccion"),
            (FormatStyle.IEEE, "I. Introduccion"),
            (FormatStyle.VANCOUVER, "1. Introduccion"),
        ],
    )
    def test_heading1_numbering_matches_template(self, tmp_path, style, expected_heading_text):
        blocks = [_block(0, SemanticRole.HEADING1, "Introduccion", heading_level=1)]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=style, output_path=out)

        texts = [p.text for p in docx.Document(out).paragraphs]
        assert expected_heading_text in texts

    @pytest.mark.parametrize(
        "style, expected_reference_text",
        [
            (FormatStyle.APA, "Smith, J. (2020)."),
            (FormatStyle.IEEE, "[1] Smith, J. (2020)."),
            (FormatStyle.VANCOUVER, "1. Smith, J. (2020)."),
        ],
    )
    def test_reference_numbering_matches_template(self, tmp_path, style, expected_reference_text):
        blocks = [_block(0, SemanticRole.REFERENCE, "Smith, J. (2020).")]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=style, output_path=out)

        texts = [p.text for p in docx.Document(out).paragraphs]
        assert expected_reference_text in texts
        # El titulo de seccion de referencias debe insertarse una sola vez
        assert texts.count("Referencias") == 1

    @pytest.mark.parametrize("existing_number", ["[1] ", "1. ", "1) ", "(1) ", "[1]"])
    def test_reference_with_its_own_number_is_not_numbered_twice(self, tmp_path, existing_number):
        blocks = [_block(0, SemanticRole.REFERENCE, f"{existing_number}Smith, J. (2020).")]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.IEEE, output_path=out)

        texts = [p.text for p in docx.Document(out).paragraphs]
        assert "[1] Smith, J. (2020)." in texts

    def test_reference_starting_with_a_decimal_number_keeps_it(self, tmp_path):
        blocks = [_block(0, SemanticRole.REFERENCE, "3.5 mm audio standard.")]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.VANCOUVER, output_path=out)

        assert "1. 3.5 mm audio standard." in [p.text for p in docx.Document(out).paragraphs]

    def test_cover_logo_stays_on_cover_before_the_toc(self, tmp_path):
        source_path, rid = _make_source_docx_with_image(tmp_path)
        blocks = [
            _block(0, SemanticRole.IMAGE, image_rId=rid, in_cover=True),
            _block(1, SemanticRole.COVER_TITLE, "Mi trabajo"),
            _block(2, SemanticRole.HEADING1, "Introduccion", heading_level=1),
            _block(3, SemanticRole.BODY, "Cuerpo."),
        ]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.IEEE, output_path=out, source_docx_path=source_path)

        paragraphs = docx.Document(out).paragraphs
        has_image = [bool(p._p.xpath(".//w:drawing")) for p in paragraphs]
        texts = [p.text for p in paragraphs]
        assert has_image.index(True) < texts.index("Mi trabajo") < texts.index("Índice")
        assert sum(has_image) == 1

    def test_cover_fields_rendered_before_page_break(self, tmp_path):
        blocks = [
            _block(0, SemanticRole.COVER_TITLE, "Mi trabajo"),
            _block(1, SemanticRole.COVER_AUTHOR, "Autor X"),
            _block(2, SemanticRole.BODY, "Cuerpo."),
        ]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.APA, output_path=out)

        texts = [p.text for p in docx.Document(out).paragraphs]
        assert texts[0] == "Mi trabajo"
        assert texts[1] == "Autor X"

    def test_toc_section_lists_headings_with_language_title(self, tmp_path):
        blocks = [
            _block(0, SemanticRole.HEADING1, "Capitulo Uno", heading_level=1),
            _block(1, SemanticRole.BODY, "Cuerpo."),
        ]
        out = tmp_path / "out.docx"

        build_docx(
            blocks=blocks, style=FormatStyle.IEEE, output_path=out,
            language=DocumentLanguage.ENGLISH,
        )

        texts = [p.text for p in docx.Document(out).paragraphs]
        assert "Table of Contents" in texts

    def test_no_headings_skips_toc_section(self, tmp_path):
        blocks = [_block(0, SemanticRole.BODY, "Solo cuerpo, sin encabezados.")]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.APA, output_path=out)

        texts = [p.text for p in docx.Document(out).paragraphs]
        assert "Índice" not in texts


class TestBuildDocxTables:
    def test_table_blocks_reconstructed_with_original_shape(self, tmp_path):
        blocks = [
            _block(0, SemanticRole.TABLE_HEADER, "Col A", table_id="t1", row_index=0, col_index=0),
            _block(1, SemanticRole.TABLE_HEADER, "Col B", table_id="t1", row_index=0, col_index=1),
            _block(2, SemanticRole.TABLE_CELL, "dato1", table_id="t1", row_index=1, col_index=0),
            _block(3, SemanticRole.TABLE_CELL, "dato2", table_id="t1", row_index=1, col_index=1),
        ]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.APA, output_path=out)

        result = docx.Document(out)
        assert len(result.tables) == 1
        table = result.tables[0]
        assert len(table.rows) == 2 and len(table.columns) == 2
        assert table.cell(0, 0).text == "Col A"
        assert table.cell(1, 1).text == "dato2"


class TestBuildDocxEquationsAndImages:
    def test_equation_block_is_embedded_without_crashing(self, tmp_path):
        blocks = [
            _block(0, SemanticRole.BODY, "Antes"),
            _block(1, SemanticRole.EQUATION, raw_xml=_FAKE_OMATH),
            _block(2, SemanticRole.BODY, "Despues"),
        ]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.APA, output_path=out)

        result = docx.Document(out)
        texts = [p.text for p in result.paragraphs]
        assert "Antes" in texts and "Despues" in texts

    def test_image_bytes_copied_from_source_document(self, tmp_path):
        source_path, image_rid = _make_source_docx_with_image(tmp_path)
        blocks = [_block(0, SemanticRole.IMAGE, image_rId=image_rid)]
        out = tmp_path / "out.docx"

        build_docx(
            blocks=blocks, style=FormatStyle.APA, output_path=out,
            source_docx_path=source_path,
        )

        result = docx.Document(out)
        image_rels = [rel for rel in result.part.rels.values() if "image" in rel.reltype]
        assert len(image_rels) == 1
        assert image_rels[0].target_part.blob == base64.b64decode(_PNG_B64)

    def test_missing_image_relationship_is_skipped_gracefully(self, tmp_path):
        source_path, _ = _make_source_docx_with_image(tmp_path)
        blocks = [
            _block(0, SemanticRole.IMAGE, image_rId="rIdNoExiste"),
            _block(1, SemanticRole.BODY, "Sigue el documento."),
        ]
        out = tmp_path / "out.docx"

        build_docx(
            blocks=blocks, style=FormatStyle.APA, output_path=out,
            source_docx_path=source_path,
        )  # no debe lanzar

        texts = [p.text for p in docx.Document(out).paragraphs]
        assert "Sigue el documento." in texts

    def test_image_without_source_docx_path_is_skipped_gracefully(self, tmp_path):
        blocks = [
            _block(0, SemanticRole.IMAGE, image_rId="rId9"),
            _block(1, SemanticRole.BODY, "Sigue el documento."),
        ]
        out = tmp_path / "out.docx"

        build_docx(blocks=blocks, style=FormatStyle.APA, output_path=out)  # sin source_docx_path

        texts = [p.text for p in docx.Document(out).paragraphs]
        assert "Sigue el documento." in texts


class TestBuildDocxErrorHandling:
    def test_unexpected_failure_raises_docx_build_error(self, tmp_path, monkeypatch):
        real_document_class = docx.Document().__class__

        def _boom_save(self, *args, **kwargs):
            raise RuntimeError("disco lleno")

        monkeypatch.setattr(real_document_class, "save", _boom_save)

        blocks = [_block(0, SemanticRole.BODY, "x")]
        with pytest.raises(DocxBuildError):
            build_docx(blocks=blocks, style=FormatStyle.APA, output_path=tmp_path / "out.docx")
