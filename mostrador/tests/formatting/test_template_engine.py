"""
tests/formatting/test_template_engine.py
==========================================
Tests de engine/formatting/template_engine.py (Paso 4, seccion 5).
"""

import pytest

from engine.core.exceptions import TemplateApplicationError, TemplateNotFoundError
from engine.document.models import FormatStyle, SemanticBlock, SemanticRole
from engine.formatting import template_engine


def _block(index, role, **kwargs) -> SemanticBlock:
    return SemanticBlock(index=index, text=f"texto {index}", role=role, **kwargs)


class TestApplyTemplateValidation:
    def test_unknown_style_raises_template_not_found(self, monkeypatch):
        monkeypatch.setattr(template_engine, "TEMPLATES", {})
        with pytest.raises(TemplateNotFoundError):
            template_engine.apply_template([], FormatStyle.APA)

    def test_heading_level_mismatch_raises_template_application_error(self):
        blocks = [_block(0, SemanticRole.HEADING1, heading_level=2)]  # inconsistente
        with pytest.raises(TemplateApplicationError):
            template_engine.apply_template(blocks, FormatStyle.APA)

    def test_consistent_heading_levels_pass(self):
        blocks = [
            _block(0, SemanticRole.HEADING1, heading_level=1),
            _block(1, SemanticRole.HEADING2, heading_level=2),
        ]
        result = template_engine.apply_template(blocks, FormatStyle.APA)
        assert len(result) == 2


class TestCoverFieldReordering:
    def test_cover_fields_moved_to_front_in_fixed_order(self):
        blocks = [
            _block(0, SemanticRole.BODY),
            _block(1, SemanticRole.COVER_DATE),
            _block(2, SemanticRole.COVER_TITLE),
            _block(3, SemanticRole.HEADING1, heading_level=1),
            _block(4, SemanticRole.COVER_AUTHOR),
        ]

        result = template_engine.apply_template(blocks, FormatStyle.APA)

        # cover_field_order = TITLE, AUTHOR, INSTITUTION, COURSE, DATE
        assert [b.role for b in result[:3]] == [
            SemanticRole.COVER_TITLE, SemanticRole.COVER_AUTHOR, SemanticRole.COVER_DATE,
        ]
        # el resto conserva su orden de lectura original
        assert [b.role for b in result[3:]] == [SemanticRole.BODY, SemanticRole.HEADING1]

    def test_images_inside_the_cover_zone_travel_with_the_cover(self):
        blocks = [
            _block(0, SemanticRole.IMAGE),                     # logo antes del titulo
            _block(1, SemanticRole.COVER_TITLE),
            _block(2, SemanticRole.IMAGE),                     # entre campos de portada
            _block(3, SemanticRole.COVER_DATE),
            _block(4, SemanticRole.HEADING1, heading_level=1),
            _block(5, SemanticRole.IMAGE),                     # figura del cuerpo
        ]

        result = template_engine.apply_template(blocks, FormatStyle.APA)

        assert [b.index for b in result] == [0, 2, 1, 3, 4, 5]
        assert [b.in_cover for b in result] == [True, True, False, False, False, False]

    def test_label_follows_the_role_of_its_value(self):
        blocks = [
            SemanticBlock(index=0, text="Materia:", role=SemanticRole.COVER_AUTHOR),
            SemanticBlock(index=1, text="Taller II", role=SemanticRole.COVER_COURSE),
            SemanticBlock(index=2, text="Alumno X", role=SemanticRole.COVER_AUTHOR),
            SemanticBlock(index=3, text="Fecha", role=SemanticRole.COVER_DATE),
        ]

        result = template_engine.apply_template(blocks, FormatStyle.APA)

        assert [b.text for b in result] == ["Alumno X", "Materia:", "Taller II", "Fecha"]

    def test_repeated_cover_line_is_kept_once(self):
        blocks = [
            SemanticBlock(index=0, text="Instituto X", role=SemanticRole.COVER_INSTITUTION),
            SemanticBlock(index=1, text="Titulo", role=SemanticRole.COVER_TITLE),
            SemanticBlock(index=2, text="Instituto  X", role=SemanticRole.COVER_INSTITUTION),
            SemanticBlock(index=3, text="Autor", role=SemanticRole.COVER_AUTHOR),
            SemanticBlock(index=4, text="Autor", role=SemanticRole.COVER_AUTHOR),
        ]

        result = template_engine.apply_template(blocks, FormatStyle.APA)

        assert [b.text for b in result] == ["Titulo", "Autor", "Instituto X"]

    def test_images_without_a_cover_are_left_in_place(self):
        blocks = [_block(0, SemanticRole.IMAGE), _block(1, SemanticRole.BODY)]

        result = template_engine.apply_template(blocks, FormatStyle.APA)

        assert [b.index for b in result] == [0, 1]
        assert not any(b.in_cover for b in result)

    def test_missing_optional_cover_field_does_not_error(self):
        # Sin COVER_COURSE ni COVER_INSTITUTION: no debe fallar (son opcionales)
        blocks = [_block(0, SemanticRole.COVER_TITLE), _block(1, SemanticRole.BODY)]
        result = template_engine.apply_template(blocks, FormatStyle.IEEE)
        assert result[0].role == SemanticRole.COVER_TITLE

    def test_no_cover_fields_leaves_order_untouched(self):
        blocks = [_block(0, SemanticRole.BODY), _block(1, SemanticRole.LIST_ITEM)]
        result = template_engine.apply_template(blocks, FormatStyle.VANCOUVER)
        assert [b.index for b in result] == [0, 1]
