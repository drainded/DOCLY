"""
engine/formatting/template_engine.py
======================================
Paso 4 del pipeline: aplicacion deterministica del template (seccion 5, Paso 4).

Expone una funcion publica (contrato firmado con pipeline.py):

    apply_template(blocks, style) -> list[SemanticBlock]

Responsabilidades
-------------------
* Validar que `style` existe en TEMPLATES (formatting/templates.py, §4).
* Validar que cada bloque de tipo heading tiene un `heading_level`
  consistente con su rol (ej. un HEADING2 con heading_level=1 indica un
  bug en un paso anterior, no un error de usuario) — TemplateApplicationError
  si no.
* Reordenar los bloques de portada (§4, punto 2: "estructura de portada...
  definida como layout fijo") al frente del documento, en el orden fijo
  que dicta TEMPLATES[style].cover_field_order — independientemente del
  orden en que aparecian en el documento original. Las imagenes de la zona
  de portada (p. ej. el logo) viajan con ella. El resto del documento
  conserva su orden de lectura original.

Lo que este modulo NO hace
----------------------------
* NO decide colores, tipografia ni maquetacion — eso vive exclusivamente
  en TEMPLATES (formatting/templates.py) y lo consume docx_builder.py
  (Paso 5) al momento de construir el documento.
* NO construye el .docx (Paso 5, docx_builder.py).
* NO inserta lineas separadoras, indice ni numeracion de encabezados o
  referencias — son decisiones de maquetacion puramente derivadas del rol
  de cada bloque (no requieren reordenar ni anotar `blocks`), y se
  resuelven directamente en Paso 5.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from engine.core.exceptions import TemplateApplicationError, TemplateNotFoundError
from engine.document.models import FormatStyle, SemanticBlock, SemanticRole
from engine.formatting.templates import TEMPLATES

logger = logging.getLogger(__name__)

_EXPECTED_HEADING_LEVEL: dict[SemanticRole, int] = {
    SemanticRole.HEADING1: 1,
    SemanticRole.HEADING2: 2,
    SemanticRole.HEADING3: 3,
    SemanticRole.HEADING4: 4,
}


def apply_template(blocks: list[SemanticBlock], style: FormatStyle) -> list[SemanticBlock]:
    """
    Aplica el template `style` sobre los bloques ya clasificados (Paso 3).

    Parameters
    ----------
    blocks:
        Bloques clasificados por Gemini/Groq, en orden de lectura.
    style:
        Estilo de formato solicitado por el usuario (APA/IEEE/Vancouver).

    Returns
    -------
    list[SemanticBlock]
        Los bloques de portada agrupados y reordenados al frente segun
        TEMPLATES[style].cover_field_order, seguidos por el resto del
        documento en su orden de lectura original.

    Raises
    ------
    TemplateNotFoundError
        Si `style` no existe en TEMPLATES (bug de integracion webapp/engine
        — el frontend deberia validar la seleccion contra FormatStyle).
    TemplateApplicationError
        Si un bloque heading tiene `heading_level` inconsistente con su rol.
    """
    template = TEMPLATES.get(style)
    if template is None:
        raise TemplateNotFoundError(style=style.value)

    for block in blocks:
        _validate_block(block)

    return _reorder_cover_fields(blocks, template.cover_field_order)


def _validate_block(block: SemanticBlock) -> None:
    """Verifica que heading_level concuerde con el rol (defensa en profundidad)."""
    expected_level = _EXPECTED_HEADING_LEVEL.get(block.role)
    if expected_level is None:
        return  # no es un heading, nada que validar aqui

    if block.heading_level != expected_level:
        raise TemplateApplicationError(
            block_index=block.index,
            block_role=block.role.value,
            cause=ValueError(
                f"heading_level={block.heading_level!r} no coincide con el "
                f"nivel esperado ({expected_level}) para el rol {block.role.value!r}"
            ),
        )


def _reorder_cover_fields(
    blocks: list[SemanticBlock],
    cover_field_order: tuple[SemanticRole, ...],
) -> list[SemanticBlock]:
    """
    Agrupa los bloques de portada por rol y los antepone al resto del
    documento, en el orden fijo `cover_field_order`. Un rol de portada sin
    bloques (ej. ningun COVER_COURSE detectado) simplemente no aporta
    ningun bloque — no es un error (§4: el curso es un campo opcional).
    """
    cover_by_role: dict[SemanticRole, list[SemanticBlock]] = defaultdict(list)
    rest: list[SemanticBlock] = []

    for block in blocks:
        if block.is_cover_field():
            cover_by_role[block.role].append(block)
        else:
            rest.append(block)

    ordered_cover: list[SemanticBlock] = []
    for role in cover_field_order:
        ordered_cover.extend(cover_by_role.get(role, []))

    if not ordered_cover:
        return rest

    cover_images = _extract_cover_images(rest, blocks)
    return cover_images + ordered_cover + [b for b in rest if not b.in_cover]


def _extract_cover_images(rest: list[SemanticBlock], blocks: list[SemanticBlock]) -> list[SemanticBlock]:
    """
    Marca (`in_cover`) las imagenes que estan dentro de la zona de portada
    del documento original: desde el inicio hasta el ultimo campo de portada,
    siempre antes del primer heading. Asi el logo de la institucion se queda
    en la portada en vez de caer detras del indice.
    """
    first_heading = next((i for i, b in enumerate(blocks) if b.is_heading()), len(blocks))
    last_cover_field = max((i for i, b in enumerate(blocks) if b.is_cover_field()), default=-1)
    cover_end = min(last_cover_field, first_heading - 1)

    images = [
        block for i, block in enumerate(blocks)
        if i <= cover_end and block.role == SemanticRole.IMAGE
    ]
    for image in images:
        image.in_cover = True
    return images
