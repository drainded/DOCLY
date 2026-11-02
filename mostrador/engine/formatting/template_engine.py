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
from engine.document.models import DocumentType, FormatStyle, SemanticBlock, SemanticRole
from engine.formatting import section_titles
from engine.formatting.templates import TEMPLATES, TemplateSpec

logger = logging.getLogger(__name__)

_EXPECTED_HEADING_LEVEL: dict[SemanticRole, int] = {
    SemanticRole.HEADING1: 1,
    SemanticRole.HEADING2: 2,
    SemanticRole.HEADING3: 3,
    SemanticRole.HEADING4: 4,
}


def apply_template(
    blocks: list[SemanticBlock],
    style: FormatStyle,
    document_type: DocumentType | None = None,
) -> list[SemanticBlock]:
    """
    Aplica el template `style` sobre los bloques ya clasificados (Paso 3).

    Parameters
    ----------
    blocks:
        Bloques clasificados por Gemini/Groq, en orden de lectura.
    style:
        Estilo de formato solicitado por el usuario (APA/IEEE/Vancouver).
    document_type:
        Caso del documento etiquetado por la IA (solo lo usan los templates
        con `apa_layout`; None se trata como OTHER).

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

    if template.apa_layout:
        _infer_missing_cover(blocks, document_type or DocumentType.OTHER)
        _ensure_cover_title(blocks)
    ordered = _reorder_cover_fields(blocks, template.cover_field_order)
    if template.apa_layout:
        return _apply_apa_layout(ordered, document_type or DocumentType.OTHER)
    return ordered


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
    _attach_labels_to_their_values(blocks)

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

    # Un cuadro de texto de portada puede repetir la misma linea (hallazgo con
    # un documento real: la institucion dos veces): se conserva la primera.
    seen: set[tuple[SemanticRole, str]] = set()
    unique_cover: list[SemanticBlock] = []
    for block in ordered_cover:
        key = (block.role, " ".join(block.text.split()))
        if key not in seen:
            seen.add(key)
            unique_cover.append(block)
    ordered_cover = unique_cover

    cover_images = _extract_cover_images(rest, blocks)
    return cover_images + ordered_cover + [b for b in rest if not b.in_cover]


def _attach_labels_to_their_values(blocks: list[SemanticBlock]) -> None:
    """
    Una etiqueta de portada ("Alumnos:", "Materia:") toma el rol del campo de
    portada que la sigue, para que el reordenado por rol no la separe de su
    valor cuando la clasificacion les dio roles distintos.
    """
    cover_fields = [b for b in blocks if b.is_cover_field()]
    for index in range(len(cover_fields) - 2, -1, -1):  # de atras adelante: encadena etiquetas seguidas
        if cover_fields[index].text.strip().endswith(":"):
            cover_fields[index].role = cover_fields[index + 1].role


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


# ===========================================================================
# Maquetacion APA 7 (template.apa_layout)
# ===========================================================================

_MAX_CAPTION_TITLE_CHARS = 250


def _apply_apa_layout(blocks: list[SemanticBlock], document_type: DocumentType) -> list[SemanticBlock]:
    """
    Estructura de un trabajo APA 7, decidida por codigo a partir del tipo de
    documento y de los roles ya clasificados:

    * portada (campos `cover_*`) en su propia pagina; en un articulo
      profesional la nota del autor se queda en esa misma pagina;
    * resumen (y palabras clave) en pagina propia;
    * el titulo se repite en negrita y centrado al comienzo del texto;
    * referencias, apendices en pagina nueva;
    * rotulos de tabla/figura ("Table 1" + titulo) reconocidos como CAPTION.

    Devuelve la lista con las marcas `page_break_before` y los bloques
    sinteticos necesarios; no cambia el texto de ningun bloque existente.
    """
    cover_size = 0
    while cover_size < len(blocks) and blocks[cover_size].belongs_to_cover():
        cover_size += 1
    cover, body = blocks[:cover_size], list(blocks[cover_size:])

    _promote_caption_labels(body)

    front_end = _front_matter_end(body)
    title_blocks = [b for b in cover if b.role == SemanticRole.COVER_TITLE]
    had_front_content = bool(cover) or front_end > 0

    if front_end < len(body):
        first_main = body[front_end]
        if title_blocks and not _is_repeated_title(first_main, title_blocks[0]):
            body[front_end:front_end] = [
                SemanticBlock(
                    index=-1, text=title.text, role=SemanticRole.HEADING1, heading_level=1,
                    synthetic=True, page_break_before=had_front_content and number == 0,
                )
                for number, title in enumerate(title_blocks)
            ]
        else:
            first_main.page_break_before = had_front_content

    _break_before_sections(body, cover, document_type)
    return cover + body


_MAX_COVER_LINES = 5            # autor, institucion, curso, profesor, fecha
_MAX_COVER_LINE_CHARS = 200

_STUDENT_COVER_ROLES = (
    SemanticRole.COVER_AUTHOR, SemanticRole.COVER_INSTITUTION, SemanticRole.COVER_COURSE,
    SemanticRole.COVER_INSTRUCTOR, SemanticRole.COVER_DATE,
)


def _infer_missing_cover(blocks: list[SemanticBlock], document_type: DocumentType) -> None:
    """
    Red de seguridad cuando la IA no marco ningun campo de portada: en un
    trabajo de estudiante o un articulo, las lineas cortas que siguen al titulo
    y preceden a "Author Note" / "Abstract" son la portada. Los roles se
    asignan por posicion (autor, afiliaciones / institucion, curso, profesor,
    fecha). Si la zona no tiene esa forma, no se toca nada.
    """
    if document_type not in (DocumentType.STUDENT_PAPER, DocumentType.PROFESSIONAL_PAPER):
        return
    if any(b.is_cover_field() for b in blocks):
        return
    boundary = next((
        i for i, b in enumerate(blocks)
        if b.role == SemanticRole.HEADING1
        and (section_titles.is_abstract_title(b.text) or section_titles.is_author_note_title(b.text))
    ), None)
    if boundary is None:
        return

    region = blocks[:boundary]
    title_count = 0
    while title_count < len(region) and region[title_count].role == SemanticRole.HEADING1:
        title_count += 1
    lines = region[title_count:]
    if title_count == 0 or not lines or len(lines) > _MAX_COVER_LINES * 3:
        return
    if any(
        b.role not in (SemanticRole.BODY, SemanticRole.UNKNOWN) or b.table_id is not None
        or len(b.text) > _MAX_COVER_LINE_CHARS
        for b in lines
    ):
        return

    for title in region[:title_count]:
        title.role, title.heading_level = SemanticRole.COVER_TITLE, None
    if document_type == DocumentType.PROFESSIONAL_PAPER:
        roles = [SemanticRole.COVER_AUTHOR] + [SemanticRole.COVER_INSTITUTION] * (len(lines) - 1)
    elif len(lines) <= len(_STUDENT_COVER_ROLES):
        roles = list(_STUDENT_COVER_ROLES[: len(lines)])
    else:
        return
    for line, role in zip(lines, roles):
        line.role = role


def _ensure_cover_title(blocks: list[SemanticBlock]) -> None:
    """
    Si hay campos de portada pero la IA dejo el titulo como encabezado (caso
    frecuente en articulos), el primer heading1 anterior al ultimo campo de
    portada pasa a ser el titulo de la portada.
    """
    last_cover_field = max((i for i, b in enumerate(blocks) if b.is_cover_field()), default=-1)
    if last_cover_field < 0 or any(b.role == SemanticRole.COVER_TITLE for b in blocks):
        return
    candidates = iter(blocks[:last_cover_field])
    for block in candidates:
        if block.role == SemanticRole.HEADING1 and not (
            section_titles.is_abstract_title(block.text) or section_titles.is_author_note_title(block.text)
        ):
            block.role, block.heading_level = SemanticRole.COVER_TITLE, None
            # un titulo de varias lineas llega como varios heading1 seguidos
            for following in candidates:
                if following.role != SemanticRole.HEADING1:
                    return
                following.role, following.heading_level = SemanticRole.COVER_TITLE, None
            return


def _promote_caption_labels(body: list[SemanticBlock]) -> None:
    """"Table 1" (y el titulo que lo sigue) pasan a CAPTION aunque la IA los haya dejado como cuerpo."""
    for position, block in enumerate(body):
        if block.table_id is not None or block.role not in (
            SemanticRole.BODY, SemanticRole.CAPTION, SemanticRole.UNKNOWN,
        ):
            continue
        if not section_titles.is_caption_label(block.text):
            continue
        block.role = SemanticRole.CAPTION
        following = body[position + 1] if position + 1 < len(body) else None
        if (
            following is not None and following.table_id is None
            and following.role in (SemanticRole.BODY, SemanticRole.CAPTION)
            and 0 < len(following.text.strip()) <= _MAX_CAPTION_TITLE_CHARS
        ):
            following.role = SemanticRole.CAPTION


def _front_matter_end(body: list[SemanticBlock]) -> int:
    """Indice del primer bloque del texto principal: tras nota del autor y resumen iniciales."""
    position = 0
    while position < len(body):
        block = body[position]
        if block.role == SemanticRole.HEADING1 and section_titles.is_author_note_title(block.text):
            position += 1
            while position < len(body) and not body[position].is_heading():
                position += 1
        elif block.role == SemanticRole.HEADING1 and section_titles.is_abstract_title(block.text):
            position = _abstract_section_end(body, position + 1)
        elif block.role in (SemanticRole.ABSTRACT, SemanticRole.KEYWORDS, SemanticRole.AUTHOR_NOTE):
            position += 1
        else:
            break
    return position


def _abstract_section_end(body: list[SemanticBlock], position: int) -> int:
    """
    Fin del resumen que empieza en `position` (tras su titulo): sus parrafos
    `abstract` y la linea de palabras clave. Si la IA dejo el resumen como un
    parrafo `body`, se acepta uno; nunca se avanza hasta el siguiente titulo
    porque el texto principal puede no tener encabezado propio.
    """
    seen_paragraph = False
    while position < len(body) and not body[position].is_heading():
        role = body[position].role
        if role == SemanticRole.KEYWORDS:
            return position + 1
        if role == SemanticRole.ABSTRACT or (role == SemanticRole.BODY and not seen_paragraph):
            seen_paragraph = True
            position += 1
            continue
        break
    return position


def _is_repeated_title(block: SemanticBlock, title_block: SemanticBlock) -> bool:
    return (
        block.role in (SemanticRole.HEADING1, SemanticRole.BODY)
        and section_titles.normalize_title(block.text) == section_titles.normalize_title(title_block.text)
    )


def _break_before_sections(
    body: list[SemanticBlock], cover: list[SemanticBlock], document_type: DocumentType,
) -> None:
    """Resumen, referencias y apendices empiezan en pagina nueva (la nota del autor, no)."""
    first_reference_marked = False
    for position, block in enumerate(body):
        if block.role == SemanticRole.HEADING1 and (
            section_titles.is_abstract_title(block.text)
            or section_titles.is_reference_title(block.text)
            or section_titles.is_appendix_title(block.text)
        ):
            block.page_break_before = position > 0 or bool(cover)
            first_reference_marked = first_reference_marked or section_titles.is_reference_title(block.text)
        elif (
            block.role == SemanticRole.REFERENCE and not first_reference_marked
            and document_type != DocumentType.ANNOTATED_BIBLIOGRAPHY
        ):
            previous = body[position - 1] if position else None
            if previous is None or not previous.is_heading():
                block.page_break_before = True
            first_reference_marked = True
