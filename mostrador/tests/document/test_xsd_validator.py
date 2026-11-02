"""
tests/document/test_xsd_validator.py
=======================================
Tests de engine/document/xsd_validator.py (criterio de aceptacion, seccion 6)
y de su integracion en el Paso 5 del pipeline.
"""

import base64
import io
import zipfile

import docx
import pytest

from engine.core import pipeline
from engine.document.models import FormatStyle, ProcessingConfig, SemanticBlock, SemanticRole
from engine.document.xsd_validator import validate_docx_against_xsd
from engine.formatting.docx_builder import build_docx
from tests.fixtures import docx_factory

_OMML_PARAGRAPH = (
    '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
    '<m:oMath><m:r><m:t>x=y+1</m:t></m:r></m:oMath></w:p>'
)
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _blocks() -> list[SemanticBlock]:
    return [
        SemanticBlock(index=0, role=SemanticRole.COVER_TITLE, text="Titulo"),
        SemanticBlock(index=1, role=SemanticRole.COVER_AUTHOR, text="Autora"),
        SemanticBlock(index=2, role=SemanticRole.HEADING1, text="Introduccion", heading_level=1),
        SemanticBlock(index=3, role=SemanticRole.HEADING2, text="Contexto", heading_level=2),
        SemanticBlock(index=4, role=SemanticRole.BODY, text="Texto de cuerpo."),
        SemanticBlock(index=5, role=SemanticRole.LIST_ITEM, text="Elemento", list_depth=1),
        SemanticBlock(index=6, role=SemanticRole.TABLE_HEADER, text="A", table_id="t", row_index=0, col_index=0),
        SemanticBlock(index=7, role=SemanticRole.TABLE_CELL, text="1", table_id="t", row_index=1, col_index=0),
        SemanticBlock(index=8, role=SemanticRole.EQUATION, raw_xml=_OMML_PARAGRAPH),
        SemanticBlock(index=9, role=SemanticRole.REFERENCE, text="Autor (2020). Obra."),
    ]


@pytest.mark.parametrize("style", list(FormatStyle))
def test_builder_output_is_schema_valid_for_every_template(tmp_path, style):
    out = tmp_path / "out.docx"
    build_docx(blocks=_blocks(), style=style, output_path=out)

    assert validate_docx_against_xsd(out) == []


def test_builder_output_with_embedded_image_is_schema_valid(tmp_path):
    source = docx.Document()
    source.add_paragraph().add_run().add_picture(io.BytesIO(_PNG))
    source_path = tmp_path / "source.docx"
    source.save(source_path)
    rid = next(rid for rid, rel in source.part.rels.items() if "image" in rel.reltype)
    blocks = [
        SemanticBlock(index=0, role=SemanticRole.BODY, text="Con imagen"),
        SemanticBlock(index=1, role=SemanticRole.IMAGE, image_rId=rid),
    ]
    out = tmp_path / "out.docx"

    build_docx(blocks=blocks, style=FormatStyle.APA, output_path=out, source_docx_path=source_path)

    assert validate_docx_against_xsd(out) == []


def test_word_ordering_of_math_run_properties_is_tolerated(tmp_path):
    # Word escribe w:rPr antes de m:rPr (el XSD exige lo contrario); lo
    # verificamos con un .docx de ecuaciones real. No debe contar como error.
    omml = (
        '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:oMath><m:r>'
        '<w:rPr><w:i/></w:rPr><m:rPr><m:sty m:val="p"/></m:rPr><m:t>x</m:t>'
        '</m:r></m:oMath></w:p>'
    )
    out = tmp_path / "out.docx"
    build_docx(
        blocks=[SemanticBlock(index=0, role=SemanticRole.EQUATION, raw_xml=omml)],
        style=FormatStyle.APA, output_path=out,
    )

    assert validate_docx_against_xsd(out) == []


def test_unknown_element_in_document_body_is_reported(tmp_path):
    valid = tmp_path / "valid.docx"
    build_docx(blocks=_blocks(), style=FormatStyle.APA, output_path=valid)
    broken = tmp_path / "broken.docx"
    _rewrite_part(valid, broken, "word/document.xml", lambda xml: xml.replace(b"<w:body>", b"<w:body><w:bogus/>", 1))

    errors = validate_docx_against_xsd(broken)

    assert errors and all(error.startswith("word/document.xml:") for error in errors)
    assert any("bogus" in error for error in errors)


def test_malformed_xml_part_is_reported(tmp_path):
    valid = tmp_path / "valid.docx"
    build_docx(blocks=_blocks(), style=FormatStyle.APA, output_path=valid)
    broken = tmp_path / "broken.docx"
    _rewrite_part(valid, broken, "word/styles.xml", lambda xml: xml[: len(xml) // 2])

    errors = validate_docx_against_xsd(broken)

    assert any(error.startswith("word/styles.xml: XML mal formado") for error in errors)


def test_non_zip_file_raises(tmp_path):
    not_a_zip = tmp_path / "x.docx"
    not_a_zip.write_bytes(b"no soy un zip")

    with pytest.raises(zipfile.BadZipFile):
        validate_docx_against_xsd(not_a_zip)


class TestPipelineIntegration:
    @staticmethod
    def _run(tmp_path, monkeypatch, validate: bool):
        monkeypatch.setattr(
            "engine.classification.gemini_classifier.classify",
            lambda blocks, api_key, model, language: blocks,
        )

        def build_invalid(blocks, style, output_path, source_docx_path=None, language=None, document_type=None):
            document = docx.Document()
            document.add_paragraph("texto")
            document.save(output_path)
            _rewrite_part(output_path, output_path, "word/document.xml",
                          lambda xml: xml.replace(b"<w:body>", b"<w:body><w:bogus/>", 1))

        monkeypatch.setattr("engine.formatting.docx_builder.build_docx", build_invalid)
        source = tmp_path / "entrada.docx"
        docx_factory.make_plain_docx(source)
        config = ProcessingConfig(
            gemini_api_key="k", output_dir=tmp_path / "out",
            libreoffice_bin=str(tmp_path / "no-soffice"), validate_output_xsd=validate,
        )
        return pipeline.run(source, config), config

    def test_invalid_output_fails_and_is_deleted(self, tmp_path, monkeypatch):
        result, config = self._run(tmp_path, monkeypatch, validate=True)

        assert (result.success, result.error_code) == (False, "OUTPUT_SCHEMA_INVALID")
        assert not list(config.output_dir.glob("*.docx"))

    def test_validation_can_be_disabled(self, tmp_path, monkeypatch):
        result, _ = self._run(tmp_path, monkeypatch, validate=False)

        assert result.success


def _rewrite_part(source, target, part_name, transform):
    """Copia un .docx sustituyendo el contenido de una parte."""
    with zipfile.ZipFile(source) as zin:
        parts = {name: zin.read(name) for name in zin.namelist()}
    parts[part_name] = transform(parts[part_name])
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in parts.items():
            zout.writestr(name, data)
