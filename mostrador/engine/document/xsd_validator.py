"""
engine/document/xsd_validator.py
===================================
Validacion del .docx de salida contra los esquemas XSD de OpenXML (criterio
de aceptacion de la seccion 6: "el .docx de salida pasa validacion contra el
esquema XSD de OpenXML").

Expone una funcion publica:

    validate_docx_against_xsd(docx_path) -> list[str]

Devuelve la lista de errores (vacia si el paquete es valido). No lanza por
documento invalido; el caller (pipeline.py) decide que hacer. Solo lanza
FileNotFoundError / zipfile.BadZipFile si el archivo no existe o no es un ZIP.

Que se valida
--------------
* `[Content_Types].xml` y los `.rels` contra los esquemas OPC (ECMA-376 Parte 2).
* Todas las partes WordprocessingML (raiz en el namespace `w:`: document,
  styles, numbering, settings, fontTable, ...) contra `wml.xsd` transitional
  (ECMA-376 Parte 4).
* NO se validan las partes DrawingML sueltas (tema), propiedades de documento
  ni ecuaciones fuera del cuerpo: no las genera Mostrador.

Preprocesado MCE
------------------
Word y python-docx escriben extensiones (`mc:Ignorable="w14 w15..."`,
`mc:AlternateContent`) que los XSD base no conocen. ECMA-376 Parte 3 manda
descartarlas antes de validar: se eliminan los elementos y atributos de los
namespaces declarados ignorables, y cada `mc:AlternateContent` se sustituye
por su `mc:Fallback` (o se quita si no lo tiene).

Los esquemas viven en `schemas/ooxml/` (ver su README para el origen).
"""

from __future__ import annotations

import io
import logging
import zipfile
from functools import lru_cache
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)

_SCHEMA_DIR = Path(__file__).parent / "schemas" / "ooxml"

_NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_NS_WML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS_MATH = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_NS_CONTENT_TYPES ="http://schemas.openxmlformats.org/package/2006/content-types"
_NS_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"

_MAX_ERRORS_PER_PART = 20


# ===========================================================================
# API publica
# ===========================================================================

def validate_docx_against_xsd(docx_path: Path) -> list[str]:
    """
    Valida el paquete OOXML `docx_path` contra los XSD de ECMA-376.

    Returns
    -------
    list[str]
        Mensajes con formato "<parte>:<linea>: <motivo>". Vacia si es valido.
    """
    errors: list[str] = []
    with zipfile.ZipFile(docx_path) as package:
        for name in package.namelist():
            if not name.endswith((".xml", ".rels")):
                continue
            try:
                root = etree.fromstring(package.read(name))
            except etree.XMLSyntaxError as exc:
                errors.append(f"{name}: XML mal formado: {exc}")
                continue

            schema_name = _schema_for_root(root)
            if schema_name is None:
                continue  # parte fuera del alcance (tema, docProps, ...)

            if schema_name == "wml":
                root = _normalize_word_deviations(_apply_mce(root))
            errors.extend(_validate_part(name, root, _load_schema(schema_name)))

    return errors


# ===========================================================================
# Internos
# ===========================================================================

def _schema_for_root(root: etree._Element) -> str | None:
    namespace = etree.QName(root).namespace
    return {
        _NS_WML: "wml",
        _NS_CONTENT_TYPES: "contentTypes",
        _NS_RELATIONSHIPS: "relationships",
    }.get(namespace)


@lru_cache(maxsize=None)
def _load_schema(schema_name: str) -> etree.XMLSchema:
    file_name = {
        "wml": "wml-validate.xsd",  # envoltorio: importa xml.xsd antes que wml.xsd
        "contentTypes": "opc-contentTypes.xsd",
        "relationships": "opc-relationships.xsd",
    }[schema_name]
    return etree.XMLSchema(etree.parse(str(_SCHEMA_DIR / file_name)))


def _validate_part(name: str, root: etree._Element, schema: etree.XMLSchema) -> list[str]:
    if schema.validate(root):
        return []
    errors = [f"{name}:{e.line}: {e.message}" for e in schema.error_log]
    return errors[:_MAX_ERRORS_PER_PART]


def _apply_mce(root: etree._Element) -> etree._Element:
    """Aplica el preprocesado de Markup Compatibility (ver docstring del modulo)."""
    root = etree.parse(io.BytesIO(etree.tostring(root))).getroot()  # copia: no tocar el original

    ignorable = _collect_ignorable_namespaces(root)

    for alternate in list(root.iter(f"{{{_NS_MC}}}AlternateContent")):
        _replace_with_fallback(alternate)

    for element in list(root.iter()):
        if not isinstance(element.tag, str):
            continue  # comentarios / PIs
        if etree.QName(element).namespace in ignorable and element.getparent() is not None:
            _remove_keeping_tail(element)
            continue
        for attribute in list(element.attrib):
            namespace = etree.QName(attribute).namespace
            if namespace in ignorable or namespace == _NS_MC:
                del element.attrib[attribute]

    return root


def _normalize_word_deviations(root: etree._Element) -> etree._Element:
    """
    Corrige desviaciones conocidas de Word respecto al XSD, para no rechazar
    contenido de ecuaciones que Mostrador preserva sin modificar (spec §7).
    Solo actua sobre la copia que se valida; el archivo de salida no cambia.

    * En `m:r`, Word escribe `w:rPr` ANTES de `m:rPr`; el XSD exige el orden
      inverso (verificado con un .docx de ecuaciones generado por Word, cuyo
      original ya falla la validacion).
    """
    math_run = f"{{{_NS_MATH}}}r"
    math_run_props = f"{{{_NS_MATH}}}rPr"
    for run in root.iter(math_run):
        props = run.find(math_run_props)
        if props is not None and run.index(props) > 0:
            run.remove(props)
            run.insert(0, props)
    return root


def _collect_ignorable_namespaces(root: etree._Element) -> set[str]:
    namespaces: set[str] = set()
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        value = element.get(f"{{{_NS_MC}}}Ignorable")
        if not value:
            continue
        for prefix in value.split():
            namespace = element.nsmap.get(prefix)
            if namespace:
                namespaces.add(namespace)
    return namespaces


def _replace_with_fallback(alternate: etree._Element) -> None:
    parent = alternate.getparent()
    if parent is None:
        return
    fallback = alternate.find(f"{{{_NS_MC}}}Fallback")
    index = parent.index(alternate)
    if fallback is not None:
        for offset, child in enumerate(list(fallback)):
            parent.insert(index + offset, child)
    _remove_keeping_tail(alternate)


def _remove_keeping_tail(element: etree._Element) -> None:
    parent = element.getparent()
    if element.tail:
        previous = element.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + element.tail
        else:
            parent.text = (parent.text or "") + element.tail
    parent.remove(element)
