"""
tests/formatting/test_pdf_renderer.py
========================================
Tests de engine/formatting/pdf_renderer.py (vista previa completa en PDF).

Simulan `subprocess.run` para no depender de LibreOffice instalado; la prueba
de integracion real solo corre si encuentra `soffice`.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.core.exceptions import PreviewRenderError
from engine.formatting import pdf_renderer


def _fake_run_success(cmd, capture_output, text, timeout):
    """Crea el PDF que LibreOffice habria generado, segun el comando."""
    outdir = Path(cmd[cmd.index("--outdir") + 1])
    docx_path = Path(cmd[-1])
    (outdir / f"{docx_path.stem}.pdf").write_bytes(b"%PDF-1.7 falso")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


class TestRenderPdfSuccess:
    def test_generates_pdf_at_output_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pdf_renderer.subprocess, "run", _fake_run_success)
        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")
        output_path = tmp_path / "salida" / "documento.pdf"

        pdf_renderer.render_pdf(docx_path, output_path)

        assert output_path.read_bytes() == b"%PDF-1.7 falso"

    def test_uses_an_isolated_libreoffice_profile(self, tmp_path, monkeypatch):
        """Sin perfil propio, dos soffice a la vez compiten por el perfil por defecto."""
        captured = {}

        def _run(cmd, capture_output, text, timeout):
            captured["cmd"] = cmd
            return _fake_run_success(cmd, capture_output, text, timeout)

        monkeypatch.setattr(pdf_renderer.subprocess, "run", _run)
        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        pdf_renderer.render_pdf(docx_path, tmp_path / "documento.pdf")

        profile_args = [a for a in captured["cmd"] if a.startswith("-env:UserInstallation=file:")]
        assert len(profile_args) == 1
        assert "--convert-to" in captured["cmd"] and "pdf" in captured["cmd"]


class TestRenderPdfErrors:
    def test_missing_libreoffice_binary_raises(self, tmp_path):
        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        with pytest.raises(PreviewRenderError):
            pdf_renderer.render_pdf(
                docx_path, tmp_path / "documento.pdf", libreoffice_bin="binario-inexistente-xyz",
            )

    def test_libreoffice_nonzero_exit_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            pdf_renderer.subprocess, "run",
            lambda cmd, capture_output, text, timeout: SimpleNamespace(returncode=1, stdout="", stderr="fallo"),
        )
        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        with pytest.raises(PreviewRenderError):
            pdf_renderer.render_pdf(docx_path, tmp_path / "documento.pdf")

    def test_libreoffice_timeout_raises(self, tmp_path, monkeypatch):
        import subprocess as subprocess_mod

        def _run(cmd, capture_output, text, timeout):
            raise subprocess_mod.TimeoutExpired(cmd=cmd, timeout=timeout)

        monkeypatch.setattr(pdf_renderer.subprocess, "run", _run)
        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        with pytest.raises(PreviewRenderError):
            pdf_renderer.render_pdf(docx_path, tmp_path / "documento.pdf")

    def test_libreoffice_produces_no_output_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            pdf_renderer.subprocess, "run",
            lambda cmd, capture_output, text, timeout: SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        docx_path = tmp_path / "documento.docx"
        docx_path.write_bytes(b"fake docx")

        with pytest.raises(PreviewRenderError):
            pdf_renderer.render_pdf(docx_path, tmp_path / "documento.pdf")


class TestRenderPdfRealLibreOffice:
    def test_real_docx_produces_a_valid_pdf(self, tmp_path):
        soffice = _find_libreoffice()
        if soffice is None:
            pytest.skip("LibreOffice no esta instalado en esta maquina")

        import docx

        docx_path = tmp_path / "prueba.docx"
        doc = docx.Document()
        doc.add_heading("Titulo de prueba", level=1)
        doc.add_paragraph("Parrafo de prueba para el render real de LibreOffice.")
        doc.save(docx_path)

        output_path = tmp_path / "prueba.pdf"
        pdf_renderer.render_pdf(docx_path, output_path, libreoffice_bin=soffice)

        assert output_path.read_bytes().startswith(b"%PDF-")


def _find_libreoffice() -> str | None:
    import shutil

    for candidate in ("soffice", "libreoffice", r"C:\Program Files\LibreOffice\program\soffice.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if Path(candidate).exists():
            return candidate
    return None
