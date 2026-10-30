"""
tests/formatting/test_preview_renderer.py
============================================
Tests de engine/formatting/preview_renderer.py (Paso 6, seccion 5).

Simulan `subprocess.run` para no depender de LibreOffice instalado en la
maquina que ejecuta los tests.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.core.exceptions import PreviewRenderError
from engine.formatting import preview_renderer


def _fake_run_success(cmd, capture_output, text, timeout):
    """Crea el PNG que LibreOffice habria generado, segun el comando."""
    outdir = Path(cmd[cmd.index("--outdir") + 1])
    docx_path = Path(cmd[-1])
    (outdir / f"{docx_path.stem}.png").write_bytes(b"contenido png falso")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


class TestRenderPreviewSuccess:
    def test_generates_png_at_output_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(preview_renderer.subprocess, "run", _fake_run_success)

        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")
        output_path = tmp_path / "preview.png"

        preview_renderer.render_preview(docx_path, output_path)

        assert output_path.exists()
        assert output_path.read_bytes() == b"contenido png falso"


class TestRenderPreviewErrors:
    def test_missing_libreoffice_binary_raises(self, tmp_path):
        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        with pytest.raises(PreviewRenderError):
            preview_renderer.render_preview(
                docx_path, tmp_path / "preview.png",
                libreoffice_bin="binario-inexistente-xyz",
            )

    def test_libreoffice_nonzero_exit_raises(self, tmp_path, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            return SimpleNamespace(returncode=1, stdout="", stderr="fallo simulado")

        monkeypatch.setattr(preview_renderer.subprocess, "run", _fake_run)

        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        with pytest.raises(PreviewRenderError):
            preview_renderer.render_preview(docx_path, tmp_path / "preview.png")

    def test_libreoffice_timeout_raises(self, tmp_path, monkeypatch):
        import subprocess as subprocess_mod

        def _fake_run(cmd, capture_output, text, timeout):
            raise subprocess_mod.TimeoutExpired(cmd=cmd, timeout=timeout)

        monkeypatch.setattr(preview_renderer.subprocess, "run", _fake_run)

        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        with pytest.raises(PreviewRenderError):
            preview_renderer.render_preview(docx_path, tmp_path / "preview.png")

    def test_libreoffice_produces_no_output_raises(self, tmp_path, monkeypatch):
        def _fake_run(cmd, capture_output, text, timeout):
            return SimpleNamespace(returncode=0, stdout="", stderr="")  # "corre" pero no crea el PNG

        monkeypatch.setattr(preview_renderer.subprocess, "run", _fake_run)

        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        with pytest.raises(PreviewRenderError):
            preview_renderer.render_preview(docx_path, tmp_path / "preview.png")


class TestRenderPreviewRealLibreOffice:
    """Prueba de integracion contra el binario real de LibreOffice, si esta instalado."""

    def test_real_docx_produces_a_valid_png(self, tmp_path):
        soffice = shutil_which_libreoffice()
        if soffice is None:
            pytest.skip("LibreOffice no esta instalado en esta maquina")

        import docx

        docx_path = tmp_path / "prueba.docx"
        doc = docx.Document()
        doc.add_heading("Titulo de prueba", level=1)
        doc.add_paragraph("Parrafo de prueba para el render real de LibreOffice.")
        doc.save(docx_path)

        output_path = tmp_path / "preview.png"
        preview_renderer.render_preview(docx_path, output_path, libreoffice_bin=soffice)

        assert output_path.exists()
        assert output_path.stat().st_size > 0
        assert output_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def shutil_which_libreoffice() -> str | None:
    import shutil

    for candidate in ("soffice", "libreoffice", r"C:\Program Files\LibreOffice\program\soffice.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if Path(candidate).exists():
            return candidate
    return None
