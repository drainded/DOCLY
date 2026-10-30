"""
engine/formatting/preview_renderer.py
========================================
Paso 6 del pipeline: renderizado de la vista previa via LibreOffice
headless (seccion 5, Paso 6; seccion 3: "imagen o PDF de solo lectura...
para revision visual antes de descargar").

Expone una funcion publica (contrato firmado con pipeline.py):

    render_preview(docx_path, output_path, libreoffice_bin) -> None

Este paso es NO FATAL (seccion 3 y 5): pipeline.py captura
PreviewRenderError, deja preview_path=None y continua — el .docx de
salida sigue siendo valido y descargable. El manejo de "no fatal" vive en
pipeline.py; este modulo solo lanza la excepcion cuando algo falla.

Estrategia
-----------
LibreOffice headless exporta el .docx directamente a PNG con su filtro
`writer_png_Export` (`--convert-to png`), que renderiza UNICAMENTE la
primera pagina — exactamente la "imagen... para revision visual" que pide
el spec, sin necesitar paginar el documento completo.

Se descarto la ruta docx -> PDF -> pdftoppm (usada en una version anterior
de este modulo): anadia una dependencia externa mas (poppler-utils, sin
instalador oficial para Windows) para el mismo resultado que LibreOffice
ya produce solo. Verificado empiricamente: `soffice --convert-to png`
sobre un documento de varias paginas exporta solo la pagina 1.

Dependencia en tiempo de ejecucion: binario `libreoffice`/`soffice` en
PATH o en la ruta inyectada via ProcessingConfig.libreoffice_bin.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from engine.core.exceptions import PreviewRenderError

logger = logging.getLogger(__name__)

_CONVERT_TIMEOUT_SECONDS = 120


def render_preview(
    docx_path: Path,
    output_path: Path,
    libreoffice_bin: str = "libreoffice",
) -> None:
    """
    Genera una imagen PNG de la primera pagina de `docx_path` en `output_path`.

    Raises
    ------
    PreviewRenderError
        Si LibreOffice no esta disponible, falla, o no produce el archivo
        esperado.
    """
    with tempfile.TemporaryDirectory(prefix="mostrador_preview_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        png_path = _convert_docx_to_png(docx_path, tmp_dir, libreoffice_bin)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(png_path), str(output_path))

    logger.info("[Paso 6] Preview generada: %s", output_path)


def _convert_docx_to_png(docx_path: Path, tmp_dir: Path, libreoffice_bin: str) -> Path:
    cmd = [
        libreoffice_bin, "--headless", "--convert-to", "png",
        "--outdir", str(tmp_dir), str(docx_path),
    ]
    _run(cmd, timeout=_CONVERT_TIMEOUT_SECONDS, binary_name=libreoffice_bin)

    png_path = tmp_dir / (docx_path.stem + ".png")
    if not png_path.exists():
        raise PreviewRenderError(
            returncode=None,
            stderr=f"LibreOffice no genero el PNG esperado en: {png_path}",
        )
    return png_path


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
