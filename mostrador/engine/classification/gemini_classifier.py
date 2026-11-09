"""
engine/classification/gemini_classifier.py
============================================
Paso 3 del pipeline: clasificacion semantica de bloques via Google Gemini
(seccion 5, Paso 3; seccion 10 — structured output).

Expone una funcion publica (contrato firmado con pipeline.py):

    classify(blocks, api_key, model, language) -> list[SemanticBlock]

Ver engine/classification/_shared.py para el contrato de prompt/respuesta,
compartido con el fallback de Groq (seccion 9).

Invariante del sistema (seccion 5 — principio arquitectonico clave):
    Gemini SOLO asigna SemanticRole a cada bloque. NUNCA decide color,
    tipografia, estructura de portada ni espaciado — eso es exclusivo del
    TEMPLATES dict (Paso 4, formatting/template_engine.py).

Regla seccion 9 (una llamada por documento): esta funcion hace como maximo
una llamada a la API de Gemini por invocacion. No hay chunking ni reintento
automatico — si Gemini devuelve rate limit, se propaga GeminiRateLimitError
para que pipeline.py decida si intenta el fallback a Groq (classification/fallback.py).

Dependencia en tiempo de ejecucion: `google-genai`, importada de forma
perezosa dentro de _call_gemini() para que el resto del motor pueda
importarse (y probarse) sin la dependencia instalada mientras no se
alcance el Paso 3.
"""

from __future__ import annotations

import logging

from engine.classification._shared import build_prompt, parse_and_apply
from engine.core.exceptions import (
    GeminiAPIError,
    GeminiRateLimitError,
    InvalidClassificationResponseError,
)
from engine.document.models import DocumentLanguage, SemanticBlock

logger = logging.getLogger(__name__)

_HTTP_TOO_MANY_REQUESTS = 429
_API_VERSION = "v1beta"


def classify(
    blocks: list[SemanticBlock],
    api_key: str,
    model: str,
    language: DocumentLanguage = DocumentLanguage.UNKNOWN,
) -> list[SemanticBlock]:
    """
    Clasifica los bloques de un documento con Gemini en una unica llamada.

    Parameters
    ----------
    blocks:
        Bloques extraidos en el Paso 2, con rol preliminar heuristico
        (extractor.py). Se modifican y devuelven in-place.
    api_key:
        Credencial de Gemini, inyectada via ProcessingConfig.gemini_api_key
        (regla seccion 9.1 — nunca leida de os.environ dentro de engine/).
    model:
        Nombre del modelo (ej. 'gemini-1.5-flash'), inyectado via
        ProcessingConfig.gemini_model.
    language:
        Idioma detectado del documento (seccion 7), usado para orientar
        el prompt hacia ES/EN.

    Returns
    -------
    list[SemanticBlock]
        Los mismos bloques de entrada, con `role` y `heading_level`
        actualizados donde aplica. Los bloques TABLE_HEADER, TABLE_CELL,
        EQUATION e IMAGE no se envian al modelo y se devuelven sin tocar.

    Raises
    ------
    GeminiRateLimitError
        Si Gemini devuelve HTTP 429 (limite de solicitudes, seccion 9).
    GeminiAPIError
        Si Gemini falla por cualquier otra razon (credencial invalida,
        red, timeout, dependencia no instalada).
    InvalidClassificationResponseError
        Si la respuesta no puede interpretarse como el JSON esperado.
    """
    if not blocks:
        return blocks

    prompt, classifiable = build_prompt(blocks, language)
    if not classifiable:
        # Documento compuesto solo por tablas/ecuaciones/imagenes: no hay
        # nada que clasificar, no vale la pena gastar una llamada a la API.
        logger.info("[Gemini] Sin bloques clasificables — se omite la llamada a la API.")
        return blocks

    logger.debug("[Gemini] Clasificando %d bloques con el modelo %s.", len(classifiable), model)
    raw_response = _call_gemini(prompt=prompt, api_key=api_key, model=model)
    return parse_and_apply(raw_response, all_blocks=blocks, classifiable_blocks=classifiable)


def _call_gemini(prompt: str, api_key: str, model: str) -> str:
    """
    Realiza la llamada real a la API de Gemini y devuelve el texto crudo
    de la respuesta. Mapea los errores de transporte a las excepciones de
    dominio del motor (core/exceptions.py).
    """
    try:
        from google import genai
        from google.genai import errors as genai_errors
        from google.genai import types as genai_types
    except ImportError as exc:
        raise GeminiAPIError(
            status_code=None,
            raw_response=f"Dependencia 'google-genai' no instalada: {exc}",
        ) from exc

    try:
        # Version de API fijada: los alias "-latest" (p. ej. gemini-flash-lite-latest) solo existen en
        # v1beta, y segun la version del SDK el valor por defecto puede ser v1 (404 NOT_FOUND).
        client = genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(api_version=_API_VERSION))
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
            ),
        )
    except genai_errors.APIError as exc:
        status_code = getattr(exc, "code", None)
        if status_code == _HTTP_TOO_MANY_REQUESTS:
            raise GeminiRateLimitError() from exc
        raise GeminiAPIError(status_code=status_code, raw_response=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — ultimo recurso: cualquier fallo de red/SDK
        raise GeminiAPIError(status_code=None, raw_response=str(exc)) from exc

    text = getattr(response, "text", None)
    if not text:
        raise InvalidClassificationResponseError(raw_response=repr(response))
    return text
