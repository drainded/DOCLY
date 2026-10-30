"""
tests/document/test_extractor_style_mapping.py
=================================================
Regresion: extract_blocks() debe mapear un heading real generado por Word/
python-docx (estilo integrado) a SemanticRole.HEADING1, no a BODY.

Bug historico corregido: _get_style_name() leia el styleId crudo del XML
(<w:pStyle w:val="...">), que para los estilos integrados de Word viene SIN
espacios (ej. "Heading1", "ListParagraph"). _STYLE_TO_ROLE y
_CONFLICTING_STYLE_NAMES estan indexados por el nombre de estilo legible CON
espacio (ej. "heading 1"), que es un campo XML distinto
(w:styles/w:style/w:name/@w:val, expuesto por python-docx como
`paragraph.style.name`). Como "heading1" no es substring de "heading 1" ni
viceversa, la coincidencia (exacta y parcial) fallaba siempre para
documentos reales con estilos integrados, y todo parrafo con estilo Word
nativo caia en BODY por defecto — incluyendo headings reales. Esto ademas
rompia el mensaje de advertencia "el documento no tiene headings" en el
Paso 2c y la deteccion de has_conflicting_style.

_get_style_name() ahora resuelve el styleId crudo al nombre legible via un
mapeo construido desde doc.styles (_build_style_id_to_name), antes de
buscarlo en _STYLE_TO_ROLE.
"""

import docx
import pytest

from extractor import extract_blocks
from models import SemanticRole


class TestBuiltinHeadingStyleMapping:
    def test_real_word_heading1_maps_to_heading1_role(self, tmp_path):
        """
        Un .docx generado con Document().add_heading(level=1) usa el
        estilo integrado de Word, cuyo styleId crudo en el XML es
        "Heading1" (sin espacio) pero cuyo nombre legible es "Heading 1"
        (con espacio). El bloque resultante debe tener
        role == SemanticRole.HEADING1 ANTES de llegar a la clasificacion
        de Gemini (Paso 3).
        """
        d = docx.Document()
        d.add_heading("Titulo de prueba", level=1)
        d.add_paragraph("Texto de cuerpo normal.")

        docx_path = tmp_path / "heading_test.docx"
        d.save(str(docx_path))

        blocks, meta = extract_blocks(
            docx_path=docx_path,
            processing_id="test-proc-id",
            original_filename="heading_test.docx",
        )

        heading_blocks = [b for b in blocks if b.text == "Titulo de prueba"]
        assert len(heading_blocks) == 1, (
            "No se encontro el bloque del heading en los bloques extraidos."
        )

        heading_block = heading_blocks[0]
        assert heading_block.role == SemanticRole.HEADING1, (
            f"El heading real (styleId crudo 'Heading1') se clasifico como "
            f"{heading_block.role!r} en vez de SemanticRole.HEADING1. "
            f"_get_style_name() esta devolviendo el styleId crudo sin "
            f"resolverlo al nombre legible del estilo."
        )
        assert heading_block.heading_level == 1
        assert meta.heading_count >= 1, (
            "DocumentMeta.heading_count deberia contar el heading real; "
            "esto es lo que dispara (o evita, incorrectamente) la "
            "advertencia de 'documento sin headings' en el Paso 2c."
        )


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
