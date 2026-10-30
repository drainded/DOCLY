"""
tests/classification/test_shared.py
=====================================
Tests del contrato de prompt/respuesta compartido entre gemini_classifier.py
y fallback.py (engine/classification/_shared.py, Paso 3, seccion 5).
"""

import json

import pytest

from engine.classification._shared import build_prompt, parse_and_apply
from engine.core.exceptions import InvalidClassificationResponseError
from engine.document.models import DocumentLanguage, SemanticBlock, SemanticRole


def _block(index, role, text="algun texto", **kwargs) -> SemanticBlock:
    return SemanticBlock(index=index, text=text, role=role, **kwargs)


class TestBuildPrompt:
    def test_excludes_structural_and_preserved_roles(self):
        blocks = [
            _block(0, SemanticRole.BODY),
            _block(1, SemanticRole.TABLE_HEADER, table_id="t1", row_index=0, col_index=0),
            _block(2, SemanticRole.TABLE_CELL, table_id="t1", row_index=1, col_index=0),
            _block(3, SemanticRole.EQUATION, text=""),
            _block(4, SemanticRole.IMAGE, text=""),
            _block(5, SemanticRole.HEADING1),
        ]

        prompt, classifiable = build_prompt(blocks, DocumentLanguage.SPANISH)

        assert [b.index for b in classifiable] == [0, 5]
        assert "\"index\": 0" in prompt
        assert "\"index\": 5" in prompt
        # Los bloques estructurales/preservados no deben aparecer en el payload
        assert "\"index\": 1" not in prompt
        assert "\"index\": 2" not in prompt
        assert "\"index\": 3" not in prompt
        assert "\"index\": 4" not in prompt

    def test_prompt_mentions_detected_language(self):
        blocks = [_block(0, SemanticRole.BODY)]
        prompt, _ = build_prompt(blocks, DocumentLanguage.ENGLISH)
        assert "en" in prompt


class TestParseAndApply:
    def test_applies_roles_and_heading_level_to_classifiable_blocks(self):
        blocks = [
            _block(0, SemanticRole.BODY, text="Introduccion"),
            _block(1, SemanticRole.BODY, text="cita textual"),
        ]
        response = json.dumps({
            "blocks": [
                {"index": 0, "role": "heading1"},
                {"index": 1, "role": "blockquote"},
            ]
        })

        result = parse_and_apply(response, all_blocks=blocks, classifiable_blocks=blocks)

        assert result[0].role == SemanticRole.HEADING1
        assert result[0].heading_level == 1
        assert result[1].role == SemanticRole.BLOCKQUOTE
        assert result[1].heading_level is None

    def test_leaves_excluded_blocks_untouched(self):
        classifiable = [_block(0, SemanticRole.BODY)]
        excluded = _block(1, SemanticRole.TABLE_CELL, table_id="t1", row_index=0, col_index=0)
        all_blocks = [classifiable[0], excluded]
        response = json.dumps({"blocks": [{"index": 0, "role": "cover_title"}]})

        parse_and_apply(response, all_blocks=all_blocks, classifiable_blocks=classifiable)

        assert excluded.role == SemanticRole.TABLE_CELL
        assert excluded.table_id == "t1"

    def test_strips_markdown_code_fence(self):
        blocks = [_block(0, SemanticRole.BODY)]
        fenced = "```json\n" + json.dumps({"blocks": [{"index": 0, "role": "reference"}]}) + "\n```"

        parse_and_apply(fenced, all_blocks=blocks, classifiable_blocks=blocks)

        assert blocks[0].role == SemanticRole.REFERENCE

    def test_invalid_role_keeps_preliminary_role(self):
        blocks = [_block(0, SemanticRole.BODY)]
        response = json.dumps({"blocks": [{"index": 0, "role": "invented_role"}]})

        parse_and_apply(response, all_blocks=blocks, classifiable_blocks=blocks)

        assert blocks[0].role == SemanticRole.BODY  # sin cambios

    @pytest.mark.parametrize(
        "raw_response",
        [
            "no es json en absoluto",
            json.dumps([{"index": 0, "role": "body"}]),        # lista, no objeto
            json.dumps({"not_blocks": []}),                      # falta la clave "blocks"
            json.dumps({"blocks": [{"role": "body"}]}),          # falta "index"
            json.dumps({"blocks": [{"index": "no-numero", "role": "body"}]}),
        ],
    )
    def test_malformed_response_raises(self, raw_response):
        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(InvalidClassificationResponseError):
            parse_and_apply(raw_response, all_blocks=blocks, classifiable_blocks=blocks)

    def test_missing_index_in_response_raises(self):
        blocks = [_block(0, SemanticRole.BODY), _block(1, SemanticRole.BODY)]
        response = json.dumps({"blocks": [{"index": 0, "role": "body"}]})  # falta el indice 1

        with pytest.raises(InvalidClassificationResponseError):
            parse_and_apply(response, all_blocks=blocks, classifiable_blocks=blocks)
