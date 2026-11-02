"""
engine/classification/_shared.py
==================================
Logica compartida entre gemini_classifier.py y fallback.py (Paso 3, seccion 5):
construccion del prompt y aplicacion de la respuesta JSON sobre los
SemanticBlock. Ambos proveedores (Gemini y el fallback Groq, seccion 9)
producen y consumen exactamente el mismo contrato, para que pipeline.py sea
indiferente a cual de los dos respondio.

No es parte de la API publica del paquete classification/: solo lo usan
gemini_classifier.py y fallback.py.

Contrato de respuesta esperado (JSON)
--------------------------------------
Un objeto (no una lista en el nivel superior — algunos proveedores en modo
"json_object", como Groq/OpenAI, exigen un objeto raiz) con la forma::

    {"document_type": "student_paper",
     "blocks": [{"index": 0, "role": "heading1"}, {"index": 1, "role": "body"}, ...]}

Un item puede incluir opcionalmente "confidence" (float 0-1). "document_type"
es opcional: si falta o no es valido, el documento se trata como "other".

Invariante del sistema (seccion 5 — principio arquitectonico clave):
    El modelo SOLO asigna `role`. Nunca decide estilo visual (color,
    tipografia, portada) — eso es exclusivo del TEMPLATES dict (Paso 4).
"""

from __future__ import annotations

import json
import logging

from engine.core.exceptions import InvalidClassificationResponseError
from engine.document.models import DocumentLanguage, DocumentType, SemanticBlock, SemanticRole

logger = logging.getLogger(__name__)

# Roles estructurales que el extractor (Paso 2) ya determina de forma
# posicional/deterministica. Reclasificar una TABLE_CELL como "body", por
# ejemplo, le haria perder la fila/columna de origen que docx_builder.py
# (Paso 5) necesita para reconstruir la tabla. EQUATION e IMAGE se
# preservan sin modificar (§7) y no tienen texto que clasificar.
_ROLES_EXCLUDED_FROM_CLASSIFICATION: frozenset[SemanticRole] = frozenset({
    SemanticRole.EQUATION,
    SemanticRole.IMAGE,
    SemanticRole.TABLE_HEADER,
    SemanticRole.TABLE_CELL,
})

_VALID_ROLE_VALUES: frozenset[str] = frozenset(role.value for role in SemanticRole)
_VALID_DOCUMENT_TYPES: frozenset[str] = frozenset(t.value for t in DocumentType)


class ClassifiedBlocks(list):
    """
    Lista de SemanticBlock que ademas lleva el tipo de documento etiquetado
    por la IA. Es una `list` normal para quien solo necesita los bloques.
    """

    document_type: DocumentType | None = None

_ROLES_FOR_PROMPT = [
    role.value for role in SemanticRole if role not in _ROLES_EXCLUDED_FROM_CLASSIFICATION
]

_HEADING_LEVEL_BY_ROLE: dict[SemanticRole, int] = {
    SemanticRole.HEADING1: 1,
    SemanticRole.HEADING2: 2,
    SemanticRole.HEADING3: 3,
    SemanticRole.HEADING4: 4,
}

# Recorte defensivo por bloque (no por documento — seccion 9 prohibe
# chunking, asi que no se trunca el documento completo, solo se evita que
# un bloque anomalo con miles de caracteres infle el prompt).
_MAX_CHARS_PER_BLOCK = 2000

_PROMPT_TEMPLATE = """Eres un clasificador de estructura semantica de documentos academicos/profesionales (formato Word).

Se te entrega una lista de bloques de texto extraidos de un documento, en su orden de lectura original. Cada bloque tiene un indice unico y un rol PRELIMINAR asignado por heuristica (basado en el nombre del estilo Word), que puede estar equivocado.

Tu unica tarea es devolver, para CADA bloque de la lista de entrada, el rol semantico definitivo. Usa exactamente uno de estos valores (en minusculas):
{roles}

Reglas:
- NUNCA inventes un rol fuera de la lista anterior.
- NUNCA modifiques, resumas ni traduzcas el texto: solo lo clasificas.
- NUNCA decidas color, tipografia, ni maquetacion — eso no es tu trabajo, lo determina codigo deterministico despues.
- cover_title / cover_author / cover_institution / cover_date / cover_course / cover_instructor: usalos SOLO para los campos de portada (titulo del trabajo, autor o autores, institucion o afiliaciones, fecha, curso, profesor o tutor) que tipicamente aparecen antes del cuerpo del documento. El titulo que se REPITE al comienzo del texto principal NO es cover_title: es heading1 (o body si no es un titulo).
- En un articulo (professional_paper) lo primero del documento es el titulo (si ocupa varias lineas, todas son cover_title), luego los nombres de los autores (cover_author) y despues las afiliaciones, normalmente numeradas (cover_institution). "Author Note" y "Abstract" son heading1.
- abstract: cada parrafo del resumen (el encabezado "Abstract"/"Resumen" en si es heading1).
- keywords: la linea de palabras clave ("Keywords: ..." / "Palabras clave: ...").
- author_note: cada parrafo de la nota del autor (el encabezado "Author Note"/"Nota del autor" en si es heading1).
- annotation: en una bibliografia anotada, cada parrafo de anotacion que sigue a una entrada (la entrada es reference).
- caption: SOLO lineas de rotulo de tabla o figura ("Table 1", "Figura 2", y el titulo que las acompana).
- reference: usalo para cada entrada individual de la bibliografia / lista de referencias (normalmente al final del documento).
- heading1..heading4: titulos de seccion, segun su nivel jerarquico real (no te fies ciegamente del rol preliminar si el texto sugiere otro nivel).
- Si un bloque no encaja claramente en ningun rol especial, usa "body".
- Idioma detectado del documento: {language}.

Ademas, indica el tipo de documento completo (campo "document_type"), usando exactamente uno de estos valores:
- student_paper: trabajo de curso/estudiante (portada con autor, institucion, curso, profesor y fecha; tambien ensayos, tesis o reportes escolares).
- professional_paper: articulo academico o profesional (autores con afiliaciones, nota del autor, resumen, palabras clave).
- annotated_bibliography: bibliografia anotada (lista de referencias, cada una con su anotacion).
- other: cualquier otro documento.

Responde EXCLUSIVAMENTE con un JSON valido, sin texto adicional antes ni despues, con esta forma exacta:
{{"document_type": "<tipo>", "blocks": [{{"index": <numero entero>, "role": "<rol>"}}, ...]}}
Debes incluir un objeto por cada bloque de entrada (mismo "index"), en cualquier orden.

Bloques de entrada:
{blocks_json}
"""


def build_prompt(
    blocks: list[SemanticBlock],
    language: DocumentLanguage,
) -> tuple[str, list[SemanticBlock]]:
    """
    Construye el prompt de clasificacion para una unica llamada (seccion 9:
    una llamada por documento, sin chunking).

    Returns
    -------
    tuple[str, list[SemanticBlock]]
        (prompt, bloques_clasificables) — bloques_clasificables excluye
        TABLE_HEADER, TABLE_CELL, EQUATION e IMAGE (ver
        _ROLES_EXCLUDED_FROM_CLASSIFICATION).
    """
    classifiable = [b for b in blocks if b.role not in _ROLES_EXCLUDED_FROM_CLASSIFICATION]

    payload = [
        {
            "index": b.index,
            "text": b.text[:_MAX_CHARS_PER_BLOCK],
            "preliminary_role": b.role.value,
            "word_style": b.original_style_name,
        }
        for b in classifiable
    ]

    prompt = _PROMPT_TEMPLATE.format(
        roles=", ".join(_ROLES_FOR_PROMPT),
        language=language.value,
        blocks_json=json.dumps(payload, ensure_ascii=False),
    )
    return prompt, classifiable


def parse_and_apply(
    raw_response: str,
    all_blocks: list[SemanticBlock],
    classifiable_blocks: list[SemanticBlock],
) -> list[SemanticBlock]:
    """
    Parsea la respuesta JSON del modelo y aplica el rol devuelto a cada
    bloque clasificable, por indice. Los bloques excluidos de la
    clasificacion (tablas, ecuaciones, imagenes) se devuelven sin tocar.

    Si el modelo devuelve un rol que no existe en SemanticRole para un
    bloque puntual, se conserva su rol preliminar (heuristica de
    extractor.py) para ese bloque y se registra un warning — un solo rol
    invalido no debe invalidar la clasificacion de todo el documento.

    Raises
    ------
    InvalidClassificationResponseError
        Si la respuesta no es JSON valido, no tiene la forma
        {"blocks": [...]}, o no cubre todos los indices de
        `classifiable_blocks`.
    """
    try:
        parsed = json.loads(_strip_code_fence(raw_response))
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidClassificationResponseError(raw_response=raw_response) from exc

    if not isinstance(parsed, dict) or not isinstance(parsed.get("blocks"), list):
        raise InvalidClassificationResponseError(raw_response=raw_response)

    role_by_index: dict[int, str] = {}
    for item in parsed["blocks"]:
        if not isinstance(item, dict) or "index" not in item or "role" not in item:
            raise InvalidClassificationResponseError(raw_response=raw_response)
        try:
            index = int(item["index"])
        except (TypeError, ValueError) as exc:
            raise InvalidClassificationResponseError(raw_response=raw_response) from exc
        role_by_index[index] = item["role"]

    expected_indices = {b.index for b in classifiable_blocks}
    missing = expected_indices - role_by_index.keys()
    if missing:
        raise InvalidClassificationResponseError(
            raw_response=(
                f"Faltan indices en la respuesta: {sorted(missing)} | raw={raw_response!r}"
            )
        )

    for block in classifiable_blocks:
        role_value = role_by_index[block.index]
        if role_value not in _VALID_ROLE_VALUES:
            logger.warning(
                "Rol invalido '%s' devuelto por el modelo para el bloque %d — "
                "se conserva el rol preliminar '%s'.",
                role_value, block.index, block.role.value,
            )
            continue
        block.role = SemanticRole(role_value)
        block.heading_level = _HEADING_LEVEL_BY_ROLE.get(block.role)

    result = ClassifiedBlocks(all_blocks)
    declared_type = parsed.get("document_type")
    if isinstance(declared_type, str) and declared_type in _VALID_DOCUMENT_TYPES:
        result.document_type = DocumentType(declared_type)
    else:
        logger.warning("Tipo de documento ausente o invalido en la respuesta (%r).", declared_type)
    return result


def _strip_code_fence(text: str) -> str:
    """
    Algunos modelos envuelven el JSON en un bloque de codigo Markdown
    (```json ... ```) aunque se les pida texto plano. Se elimina esa
    envoltura antes de parsear.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
