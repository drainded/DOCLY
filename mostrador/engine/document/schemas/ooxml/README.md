# Esquemas OpenXML (XSD) para la validacion del .docx de salida

Usados por `engine/document/xsd_validator.py` (criterio de aceptacion, seccion 6 del spec).

| Archivos | Origen |
|---|---|
| `wml.xsd`, `dml-*.xsd`, `shared-*.xsd` | ECMA-376 5.ª edicion (dic. 2016), Parte 4 — *Transitional Migration Features*, `OfficeOpenXML-XMLSchema-Transitional.zip` (https://ecma-international.org/publications-and-standards/standards/ecma-376/). Solo la clausura de imports de `wml.xsd`; sin modificar. |
| `opc-contentTypes.xsd`, `opc-relationships.xsd` | ECMA-376 5.ª edicion (dic. 2021), Parte 2 — *Open Packaging Conventions*, `OpenPackagingConventions-XMLSchema.zip`. Sin modificar. |
| `xml.xsd` | Escrito a mano: version minima del `xml.xsd` del W3C (solo `xml:lang` y `xml:space`). `wml.xsd` importa el namespace `xml` sin `schemaLocation`, y libxml2 necesita una declaracion para resolver `xml:space`. |
| `wml-validate.xsd` | Escrito a mano: esquema envoltorio que importa `xml.xsd` y luego `wml.xsd`. |

Los `.docx` de Word llevan extensiones de Microsoft (`mc:Ignorable`, `w14:`, `w15:`...) que no estan en estos
esquemas; `xsd_validator.py` las elimina antes de validar siguiendo ECMA-376 Parte 3 (MCE).

Si `engine/` se empaqueta como modulo independiente (spec seccion 9.1), esta carpeta debe incluirse como package data.
