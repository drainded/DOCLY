"""
tests/test_pipeline_e2e.py
============================
Pruebas end-to-end de engine.core.pipeline.run() con documentos .docx reales.

Solo se simula el Paso 3 (la llamada de red a Gemini/Groq): el clasificador
falso asigna los roles definidos en tests/fixtures/docx_factory.py. Todo lo
demas (extraccion, validacion, template, build) corre de verdad. Verifica los
criterios de aceptacion de la seccion 6 que son comprobables sin Word.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import docx
import pytest

from engine.core import pipeline
from engine.core.exceptions import GeminiRateLimitError
from engine.document.models import FormatStyle, ProcessingConfig, SemanticBlock
from tests.fixtures import docx_factory

_SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")
if _SOFFICE is None and Path(r"C:\Program Files\LibreOffice\program\soffice.exe").exists():
    _SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"


def _fake_classify(blocks, api_key, model, language):
    """Sustituto determinista de gemini_classifier.classify (sin red)."""
    for block in blocks:
        role = docx_factory.EXPECTED_ROLES.get(block.text)
        if role is not None:
            block.role = role
    return blocks


def _config(tmp_path: Path, style: FormatStyle = FormatStyle.APA, **overrides) -> ProcessingConfig:
    values = dict(
        gemini_api_key="test-key",
        style=style,
        output_dir=tmp_path / "out",
        libreoffice_bin=str(tmp_path / "no-such-soffice"),  # el preview falla (no fatal)
    )
    values.update(overrides)
    return ProcessingConfig(**values)


@pytest.fixture(autouse=True)
def _patch_gemini(monkeypatch):
    monkeypatch.setattr("engine.classification.gemini_classifier.classify", _fake_classify)


def _output_texts(path: Path) -> list[str]:
    document = docx.Document(path)
    texts = [p.text for p in document.paragraphs]
    for table in document.tables:
        texts.extend(cell.text for row in table.rows for cell in row.cells)
    return texts


class TestHappyPath:
    @pytest.mark.parametrize("style", list(FormatStyle))
    def test_full_document_is_formatted_without_losing_text(self, tmp_path, style):
        source = tmp_path / "entrada.docx"
        expected = docx_factory.make_full_docx(source)

        result = pipeline.run(source, _config(tmp_path, style), overwrite_styles=True)

        assert result.success, result.error_message
        assert result.output_docx_path.exists()
        output = _output_texts(result.output_docx_path)
        for text in expected:
            # los prefijos de numeracion ("1. ", "[1] ") no cuentan como perdida
            assert any(text in line for line in output), f"se perdio: {text!r}"

    def test_every_heading_appears_in_the_generated_toc(self, tmp_path):
        source = tmp_path / "entrada.docx"
        docx_factory.make_full_docx(source)

        result = pipeline.run(source, _config(tmp_path), overwrite_styles=True)

        document = docx.Document(result.output_docx_path)
        toc_entries = [p.text for p in document.paragraphs if p.style.name.startswith("Mostrador toc_entry")]
        assert toc_entries == [heading for heading, _ in docx_factory.HEADINGS]

    def test_cover_fields_come_first_in_template_order(self, tmp_path):
        source = tmp_path / "entrada.docx"
        docx_factory.make_full_docx(source)

        result = pipeline.run(source, _config(tmp_path), overwrite_styles=True)

        first = [p.text for p in docx.Document(result.output_docx_path).paragraphs if p.text][:3]
        assert set(first) == {
            docx_factory.COVER_TITLE, docx_factory.COVER_AUTHOR, docx_factory.COVER_INSTITUTION,
        }

    def test_embedded_image_is_preserved(self, tmp_path):
        source = tmp_path / "entrada.docx"
        docx_factory.make_full_docx(source, with_image=True)

        result = pipeline.run(source, _config(tmp_path), overwrite_styles=True)

        assert result.success, result.error_message
        assert len(docx.Document(result.output_docx_path).inline_shapes) == 1

    def test_missing_libreoffice_does_not_fail_the_pipeline(self, tmp_path):
        source = tmp_path / "entrada.docx"
        docx_factory.make_plain_docx(source)

        result = pipeline.run(source, _config(tmp_path))

        assert result.success
        assert result.preview_path is None

    def test_original_file_is_untouched_and_temp_dir_removed(self, tmp_path, monkeypatch):
        source = tmp_path / "entrada.docx"
        docx_factory.make_plain_docx(source)
        before = source.read_bytes()
        created: list[Path] = []
        real_mkdtemp = pipeline.tempfile.mkdtemp

        def spy(*args, **kwargs):
            path = Path(real_mkdtemp(*args, **kwargs))
            created.append(path)
            return str(path)

        monkeypatch.setattr(pipeline.tempfile, "mkdtemp", spy)

        result = pipeline.run(source, _config(tmp_path))

        assert result.success
        assert source.read_bytes() == before
        assert created and not any(path.exists() for path in created)


@pytest.mark.skipif(_SOFFICE is None, reason="LibreOffice no esta instalado")
def test_preview_png_is_generated_with_libreoffice(tmp_path):
    source = tmp_path / "entrada.docx"
    docx_factory.make_plain_docx(source)

    result = pipeline.run(source, _config(tmp_path, libreoffice_bin=_SOFFICE))

    assert result.success
    assert result.preview_path is not None and result.preview_path.stat().st_size > 0


class TestConflictingStylesFlow:
    def test_pauses_then_continues_when_user_confirms(self, tmp_path):
        source = tmp_path / "entrada.docx"
        docx_factory.make_full_docx(source)
        config = _config(tmp_path)

        paused = pipeline.run(source, config)
        assert not paused.success
        assert paused.error_code == "CONFLICTING_STYLES"
        assert not list(config.output_dir.glob("*.docx"))

        resumed = pipeline.run(source, config, overwrite_styles=True)
        assert resumed.success
        assert resumed.processing_id != paused.processing_id


class TestRejections:
    def test_unsupported_extension(self, tmp_path):
        source = tmp_path / "entrada.pdf"
        source.write_bytes(b"%PDF-1.4")

        result = pipeline.run(source, _config(tmp_path))

        assert (result.success, result.error_code) == (False, "UNSUPPORTED_FORMAT")

    def test_file_over_size_limit(self, tmp_path):
        source = tmp_path / "entrada.docx"
        docx_factory.make_plain_docx(source)

        result = pipeline.run(source, _config(tmp_path, max_file_size_bytes=10))

        assert (result.success, result.error_code) == (False, "FILE_SIZE_EXCEEDED")

    def test_corrupt_docx(self, tmp_path):
        source = tmp_path / "entrada.docx"
        source.write_bytes(b"esto no es un zip")

        result = pipeline.run(source, _config(tmp_path))

        assert (result.success, result.error_code) == (False, "DOCUMENT_CORRUPTED")

    def test_empty_docx(self, tmp_path):
        source = tmp_path / "entrada.docx"
        docx_factory.make_empty_docx(source)

        result = pipeline.run(source, _config(tmp_path))

        assert not result.success
        assert result.error_code in {"EMPTY_DOCUMENT", "SCANNED_DOCUMENT"}


class TestClassificationFailures:
    def test_rate_limit_without_fallback_asks_to_retry_later(self, tmp_path, monkeypatch):
        def raise_rate_limit(*args, **kwargs):
            raise GeminiRateLimitError()

        monkeypatch.setattr("engine.classification.gemini_classifier.classify", raise_rate_limit)
        source = tmp_path / "entrada.docx"
        docx_factory.make_plain_docx(source)

        result = pipeline.run(source, _config(tmp_path))

        assert (result.success, result.error_code) == (False, "RATE_LIMIT_GEMINI")
        assert result.gemini_rate_limited

    def test_rate_limit_with_groq_key_uses_fallback(self, tmp_path, monkeypatch):
        def raise_rate_limit(*args, **kwargs):
            raise GeminiRateLimitError()

        def fake_groq(blocks, api_key, model, language) -> list[SemanticBlock]:
            return _fake_classify(blocks, api_key, model, language)

        monkeypatch.setattr("engine.classification.gemini_classifier.classify", raise_rate_limit)
        monkeypatch.setattr("engine.classification.fallback.classify_with_groq", fake_groq)
        source = tmp_path / "entrada.docx"
        docx_factory.make_plain_docx(source)

        result = pipeline.run(source, _config(tmp_path, groq_api_key="groq-key"))

        assert result.success
        assert result.fallback_used and result.gemini_rate_limited
