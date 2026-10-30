"""
tests/classification/test_gemini_classifier.py
=================================================
Tests de engine/classification/gemini_classifier.py (Paso 3, seccion 5).

Simulan la SDK real `google-genai` monkeypatcheando `genai.Client` para no
depender de red ni de una API key real, cubriendo los tres caminos que
pipeline.py necesita distinguir: exito, rate limit (429) y error generico.
"""

import json
from types import SimpleNamespace

import pytest

from engine.classification import gemini_classifier
from engine.core.exceptions import (
    GeminiAPIError,
    GeminiRateLimitError,
    InvalidClassificationResponseError,
)
from engine.document.models import DocumentLanguage, SemanticBlock, SemanticRole


def _block(index, role, text="algun texto", **kwargs) -> SemanticBlock:
    return SemanticBlock(index=index, text=text, role=role, **kwargs)


class _FakeModels:
    def __init__(self, response_text=None, exception=None):
        self._response_text = response_text
        self._exception = exception
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append((model, contents, config))
        if self._exception is not None:
            raise self._exception
        return SimpleNamespace(text=self._response_text)


class _FakeClient:
    def __init__(self, response_text=None, exception=None):
        self.models = _FakeModels(response_text=response_text, exception=exception)


def _patch_client(monkeypatch, *, response_text=None, exception=None):
    from google import genai as genai_module

    fake_client = _FakeClient(response_text=response_text, exception=exception)
    monkeypatch.setattr(genai_module, "Client", lambda api_key: fake_client)
    return fake_client


class TestClassifySuccess:
    def test_applies_roles_from_gemini_response(self, monkeypatch):
        blocks = [
            _block(0, SemanticRole.BODY, text="Trabajo de investigacion"),
            _block(1, SemanticRole.BODY, text="Introduccion al problema"),
        ]
        response_json = json.dumps({
            "blocks": [
                {"index": 0, "role": "cover_title"},
                {"index": 1, "role": "heading1"},
            ]
        })
        _patch_client(monkeypatch, response_text=response_json)

        result = gemini_classifier.classify(
            blocks=blocks, api_key="fake-key", model="gemini-1.5-flash",
            language=DocumentLanguage.SPANISH,
        )

        assert result[0].role == SemanticRole.COVER_TITLE
        assert result[1].role == SemanticRole.HEADING1
        assert result[1].heading_level == 1

    def test_empty_blocks_list_short_circuits_without_calling_api(self, monkeypatch):
        from google import genai as genai_module

        def _fail(*args, **kwargs):
            raise AssertionError("no deberia llamarse a la API con blocks vacio")

        monkeypatch.setattr(genai_module, "Client", _fail)

        assert gemini_classifier.classify(blocks=[], api_key="k", model="m") == []

    def test_only_non_classifiable_blocks_skips_api_call(self, monkeypatch):
        from google import genai as genai_module

        def _fail(*args, **kwargs):
            raise AssertionError("no deberia llamarse a la API sin bloques clasificables")

        monkeypatch.setattr(genai_module, "Client", _fail)

        blocks = [_block(0, SemanticRole.IMAGE, text="")]
        result = gemini_classifier.classify(blocks=blocks, api_key="k", model="m")

        assert result[0].role == SemanticRole.IMAGE


class TestClassifyErrors:
    def test_rate_limit_maps_to_gemini_rate_limit_error(self, monkeypatch):
        from google.genai import errors as genai_errors

        rate_limit_exc = genai_errors.ClientError(429, {"error": {"message": "rate limited"}})
        _patch_client(monkeypatch, exception=rate_limit_exc)

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(GeminiRateLimitError):
            gemini_classifier.classify(blocks=blocks, api_key="k", model="m")

    def test_other_client_error_maps_to_gemini_api_error(self, monkeypatch):
        from google.genai import errors as genai_errors

        bad_request_exc = genai_errors.ClientError(400, {"error": {"message": "bad request"}})
        _patch_client(monkeypatch, exception=bad_request_exc)

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(GeminiAPIError):
            gemini_classifier.classify(blocks=blocks, api_key="k", model="m")

    def test_unexpected_exception_maps_to_gemini_api_error(self, monkeypatch):
        _patch_client(monkeypatch, exception=ConnectionError("network down"))

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(GeminiAPIError):
            gemini_classifier.classify(blocks=blocks, api_key="k", model="m")

    def test_empty_response_text_raises_invalid_classification(self, monkeypatch):
        _patch_client(monkeypatch, response_text=None)

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(InvalidClassificationResponseError):
            gemini_classifier.classify(blocks=blocks, api_key="k", model="m")

    def test_malformed_json_response_raises_invalid_classification(self, monkeypatch):
        _patch_client(monkeypatch, response_text="esto no es json")

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(InvalidClassificationResponseError):
            gemini_classifier.classify(blocks=blocks, api_key="k", model="m")
