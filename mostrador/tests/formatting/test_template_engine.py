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

    def test_missing_optional_cover_field_does_not_error(self):
        # Sin COVER_COURSE ni COVER_INSTITUTION: no debe fallar (son opcionales)
        blocks = [_block(0, SemanticRole.COVER_TITLE), _block(1, SemanticRole.BODY)]
        result = template_engine.apply_template(blocks, FormatStyle.IEEE)
        assert result[0].role == SemanticRole.COVER_TITLE

    def test_no_cover_fields_leaves_order_untouched(self):
        blocks = [_block(0, SemanticRole.BODY), _block(1, SemanticRole.LIST_ITEM)]
        result = template_engine.apply_template(blocks, FormatStyle.VANCOUVER)
        assert [b.index for b in result] == [0, 1]
