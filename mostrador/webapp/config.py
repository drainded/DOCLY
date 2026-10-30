"""
webapp/config.py
=================
Unico lugar del proyecto que lee variables de entorno (seccion 9.1: engine/
nunca lo hace). Carga ".env" desde la raiz del proyecto y construye el
ProcessingConfig que se inyecta en engine.core.pipeline.run().

Uso::

    from webapp.config import load_processing_config
    config = load_processing_config(style=FormatStyle.APA)
    result = run(doc_path, config)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from engine.document.models import FormatStyle, ProcessingConfig

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")


class MissingAPIKeyError(RuntimeError):
    """GEMINI_API_KEY no esta configurada en el entorno ni en .env."""


def load_processing_config(style: FormatStyle) -> ProcessingConfig:
    """
    Construye un ProcessingConfig a partir de las variables de entorno.

    Raises
    ------
    MissingAPIKeyError
        Si GEMINI_API_KEY no esta definida (es obligatoria, seccion 9).
    """
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_api_key:
        raise MissingAPIKeyError(
            "GEMINI_API_KEY no esta configurada. Copia .env.example a .env "
            "y completa tu clave (https://aistudio.google.com/apikey)."
        )

    groq_api_key = os.environ.get("GROQ_API_KEY", "").strip() or None

    return ProcessingConfig(
        gemini_api_key=gemini_api_key,
        groq_api_key=groq_api_key,
        style=style,
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
        groq_model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        max_file_size_bytes=int(os.environ.get("MAX_FILE_SIZE_BYTES", 50 * 1024 * 1024)),
        output_dir=Path(os.environ.get("OUTPUT_DIR", "output")),
        libreoffice_bin=os.environ.get("LIBREOFFICE_BIN", "libreoffice"),
    )
