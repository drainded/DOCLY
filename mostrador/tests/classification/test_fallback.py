"""
tests/classification/test_fallback.py
========================================
Tests de engine/classification/fallback.py — clasificacion via Groq cuando
Gemini devuelve rate limit (seccion 9).

Simulan el cliente `openai.OpenAI` (Groq expone una API compatible, seccion 9)
monkeypatcheandolo para no depender de red ni de una API key real.
"""

import json
from types import SimpleNamespace

import httpx2
import pytest

from engine.classification import fallback
from engine.core.exceptions import GroqAPIError, InvalidClassificationResponseError
from engine.document.models import DocumentLanguage, SemanticBlock, SemanticRole


def _block(index, role, text="algun texto", **kwargs) -> SemanticBlock:
    return SemanticBlock(index=index, text=text, role=role, **kwargs)


class _FakeCompletions:
    def __init__(self, content=None, exception=None):
        self._content = content
        self._exception = exception
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exception is not None:
            raise self._exception
        message = SimpleNamespace(content=self._content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class _FakeChat:
    def __init__(self, content=None, exception=None):
        self.completions = _FakeCompletions(content=content, exception=exception)


class _FakeOpenAIClient:
    def __init__(self, *, api_key=None, base_url=None, content=None, exception=None):
        self.chat = _FakeChat(content=content, exception=exception)


def _patch_client(monkeypatch, *, content=None, exception=None):
    import openai as openai_module

    def factory(*, api_key, base_url):
        return _FakeOpenAIClient(api_key=api_key, base_url=base_url, content=content, exception=exception)

    monkeypatch.setattr(openai_module, "OpenAI", factory)


def _fake_status_error(error_cls, status_code):
    request = httpx2.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx2.Response(status_code, request=request, json={"error": {"message": "boom"}})
    return error_cls("boom", response=response, body=None)


class TestClassifyWithGroqSuccess:
    def test_applies_roles_from_groq_response(self, monkeypatch):
        blocks = [_block(0, SemanticRole.BODY, text="Referencias bibliograficas")]
        content = json.dumps({"blocks": [{"index": 0, "role": "reference"}]})
        _patch_client(monkeypatch, content=content)

        result = fallback.classify_with_groq(
            blocks=blocks, api_key="fake-key", model="llama3-70b-8192",
            language=DocumentLanguage.SPANISH,
        )

        assert result[0].role == SemanticRole.REFERENCE

    def test_empty_blocks_list_short_circuits_without_calling_api(self, monkeypatch):
        import openai as openai_module

        def _fail(*args, **kwargs):
            raise AssertionError("no deberia llamarse a la API con blocks vacio")

        monkeypatch.setattr(openai_module, "OpenAI", _fail)

        assert fallback.classify_with_groq(blocks=[], api_key="k", model="m") == []


class TestClassifyWithGroqErrors:
    def test_rate_limit_maps_to_groq_api_error(self, monkeypatch):
        import openai as openai_module

        exc = _fake_status_error(openai_module.RateLimitError, 429)
        _patch_client(monkeypatch, exception=exc)

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(GroqAPIError):
            fallback.classify_with_groq(blocks=blocks, api_key="k", model="m")

    def test_other_status_error_maps_to_groq_api_error(self, monkeypatch):
        import openai as openai_module

        exc = _fake_status_error(openai_module.BadRequestError, 400)
        _patch_client(monkeypatch, exception=exc)

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(GroqAPIError):
            fallback.classify_with_groq(blocks=blocks, api_key="k", model="m")

    def test_unexpected_exception_maps_to_groq_api_error(self, monkeypatch):
        _patch_client(monkeypatch, exception=ConnectionError("network down"))

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(GroqAPIError):
            fallback.classify_with_groq(blocks=blocks, api_key="k", model="m")

    def test_empty_content_raises_invalid_classification(self, monkeypatch):
        _patch_client(monkeypatch, content=None)

        blocks = [_block(0, SemanticRole.BODY)]
        with pytest.raises(InvalidClassificationResponseError):
            fallback.classify_with_groq(blocks=blocks, api_key="k", model="m")
