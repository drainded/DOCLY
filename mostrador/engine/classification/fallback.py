"""
engine/classification/fallback.py
===================================
Paso 3 (fallback): clasificacion semantica via Groq cuando Gemini devuelve
rate limit (seccion 9 — recomendado para v1.1, disponible desde v1 si se
configura ProcessingConfig.groq_api_key).

Expone una funcion publica (contrato firmado con pipeline.py):

    classify_with_groq(blocks, api_key, model, language) -> list[SemanticBlock]

Usa el mismo contrato de prompt/respuesta que gemini_classifier.py (ver
engine/classification/_shared.py) para que pipeline.py sea indiferente a
cual de los dos proveedores respondio.

Groq expone una API compatible con el SDK de OpenAI (seccion 9), por lo
que se reutiliza el cliente `openai` apuntando a la URL base de Groq en vez
de depender de un SDK propietario adicional.

Regla seccion 9: este fallback SOLO se invoca cuando Gemini devuelve rate
limit y ProcessingConfig.groq_api_key no es None. Nunca se usa como
balanceo de carga activo — pipeline.py es el unico que decide cuando
llamarlo (ver core/pipeline.py::_step3_classify).
"""

from __future__ import annotations

import logging

from engine.classification._shared import build_prompt, parse_and_apply
from engine.core.exceptions import GroqAPIError, InvalidClassificationResponseError
from engine.document.models import DocumentLanguage, SemanticBlock

logger = logging.getLogger(__name__)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def classify_with_groq(
    blocks: list[SemanticBlock],
    api_key: str,
    model: str,
    language: DocumentLanguage = DocumentLanguage.UNKNOWN,
) -> list[SemanticBlock]:
    """
    Clasifica los bloques de un documento con Groq (fallback de Gemini).

    Mismo contrato que gemini_classifier.classify() — la diferencia es el
    proveedor y la excepcion de fallo: aqui no hay un segundo fallback al
    que recurrir en v1, asi que incluso un rate limit de Groq se propaga
    como GroqAPIError (fatal para el Paso 3).

    Parameters
    ----------
    blocks:
        Bloques extraidos en el Paso 2, con rol preliminar heuristico.
    api_key:
        Credencial de Groq, inyectada via ProcessingConfig.groq_api_key.
    model:
        Nombre del modelo (ej. 'llama3-70b-8192'), inyectado via
        ProcessingConfig.groq_model.
    language:
        Idioma detectado del documento (seccion 7).

    Returns
    -------
    list[SemanticBlock]
        Los mismos bloques de entrada, con `role` y `heading_level`
        actualizados donde aplica.

    Raises
    ------
    GroqAPIError
        Si la API de Groq falla por cualquier razon (rate limit incluido).
    InvalidClassificationResponseError
        Si la respuesta no puede interpretarse como el JSON esperado.
    """
    if not blocks:
        return blocks

    prompt, classifiable = build_prompt(blocks, language)
    if not classifiable:
        logger.info("[Groq] Sin bloques clasificables — se omite la llamada a la API.")
        return blocks

    logger.debug("[Groq] Clasificando %d bloques con el modelo %s.", len(classifiable), model)
    raw_response = _call_groq(prompt=prompt, api_key=api_key, model=model)
    return parse_and_apply(raw_response, all_blocks=blocks, classifiable_blocks=classifiable)


def _call_groq(prompt: str, api_key: str, model: str) -> str:
    """
    Realiza la llamada real a la API de Groq (compatible con OpenAI, seccion 9)
    y devuelve el texto crudo de la respuesta.
    """
    try:
        import openai
    except ImportError as exc:
        raise GroqAPIError(
            status_code=None,
            raw_response=f"Dependencia 'openai' no instalada: {exc}",
        ) from exc

    client = openai.OpenAI(api_key=api_key, base_url=_GROQ_BASE_URL)

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except openai.APIStatusError as exc:
        raise GroqAPIError(status_code=exc.status_code, raw_response=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — ultimo recurso: cualquier fallo de red/SDK
        raise GroqAPIError(status_code=None, raw_response=str(exc)) from exc

    text = completion.choices[0].message.content if completion.choices else None
    if not text:
        raise InvalidClassificationResponseError(raw_response=repr(completion))
    return text
