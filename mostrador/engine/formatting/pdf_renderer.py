"""
engine/formatting/pdf_renderer.py
====================================
Vista previa completa en PDF del documento ya formateado (SPEC seccion 3:
"imagen o PDF de solo lectura ... para revision visual antes de descargar").

Expone una funcion publica:

    render_pdf(docx_path, output_path, libreoffice_bin) -> None

A diferencia de preview_renderer (PNG de la primera pagina, paso 6 del pipeline,
siempre), este modulo NO se ejecuta dentro del pipeline: webapp lo invoca bajo
demanda la primera vez que el usuario abre la vista previa de un documento y
guarda el resultado junto al .docx (store.StoredDocument.pdf_path), de modo que
las aperturas siguientes no vuelven a convertir.

Perfil aislado de LibreOffice
------------------------------
Cada conversion usa su propio perfil de usuario (`-env:UserInstallation`).
Sin eso, dos procesos soffice a la vez comparten el perfil por defecto y el
segundo termina en silencio sin convertir nada: la vista previa en PDF puede
pedirse mientras el pipeline renderiza el PNG de otro documento.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from engine.core.exceptions import PreviewRenderError

logger = logging.getLogger(__name__)

# Un documento largo con imagenes tarda mas que la primera pagina en PNG.
_CONVERT_TIMEOUT_SECONDS = 180


def render_pdf(
    docx_path: Path,
    output_path: Path,
    libreoffice_bin: str = "libreoffice",
) -> None:
    """
    Convierte `docx_path` a PDF y lo deja en `output_path`.

    Raises
    ------
    PreviewRenderError
        Si LibreOffice no esta disponible, falla, excede el tiempo o no
        produce el archivo esperado.
    """
    with tempfile.TemporaryDirectory(prefix="mostrador_pdf_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        profile_uri = (tmp_dir / "perfil").as_uri()
        cmd = [
            libreoffice_bin, f"-env:UserInstallation={profile_uri}",
            "--headless", "--convert-to", "pdf",
            "--outdir", str(tmp_dir), str(docx_path),
        ]
        _run(cmd, timeout=_CONVERT_TIMEOUT_SECONDS, binary_name=libreoffice_bin)

        pdf_path = tmp_dir / (docx_path.stem + ".pdf")
        if not pdf_path.exists():
            raise PreviewRenderError(
                returncode=None,
                stderr=f"LibreOffice no genero el PDF esperado en: {pdf_path}",
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pdf_path), str(output_path))

    logger.info("[PDF] Vista previa en PDF generada: %s", output_path)


def _run(cmd: list[str], timeout: int, binary_name: str) -> None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise PreviewRenderError(
            returncode=None, stderr=f"Binario no encontrado: {binary_name} ({exc})",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PreviewRenderError(
            returncode=None, stderr=f"{binary_name} supero el timeout de {timeout}s",
        ) from exc

    if result.returncode != 0:
        raise PreviewRenderError(returncode=result.returncode, stderr=result.stderr)
