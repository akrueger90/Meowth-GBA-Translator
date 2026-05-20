from pathlib import Path

import httpx
import pytest

from meowth.core import TranslationConfig, TranslationEngine
from meowth.translator import LLMAuthenticationError, Translator


class DummyCharmap:
    def can_encode(self, text):
        return True, None


class DummyGlossary:
    def lookup(self, text):
        return None

    def get_context_terms(self, text):
        return {}

    def add_term(self, source, target, category):
        return None


def test_call_api_raises_auth_error_on_unauthorized(monkeypatch):
    translator = Translator(api_key="bad-key", base_url="https://api.example.com")

    def fake_post(*args, **kwargs):
        request = httpx.Request("POST", "https://api.example.com/chat/completions")
        response = httpx.Response(
            401,
            request=request,
            json={"error": {"message": "Invalid API key"}},
        )
        raise httpx.HTTPStatusError("Unauthorized", request=request, response=response)

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(LLMAuthenticationError, match="Invalid API key"):
        translator._call_api("system", "user", max_retries=1)


def test_engine_propagates_auth_error_in_free_batch(tmp_path: Path):
    config = TranslationConfig(work_dir=tmp_path, target_lang="zh-Hans")
    engine = TranslationEngine(
        config=config,
        charmap=DummyCharmap(),
        glossary=DummyGlossary(),
    )

    def raise_auth_error(*args, **kwargs):
        raise LLMAuthenticationError("LLM authentication failed (401)")

    engine.translator.translate_batch = raise_auth_error

    with pytest.raises(LLMAuthenticationError):
        engine._translate_free_batch([
            {"id": "1", "original": "Hello there"},
        ])


def test_engine_propagates_auth_error_in_table_batch(tmp_path: Path):
    config = TranslationConfig(work_dir=tmp_path, target_lang="zh-Hans")
    engine = TranslationEngine(
        config=config,
        charmap=DummyCharmap(),
        glossary=DummyGlossary(),
    )

    def raise_auth_error(*args, **kwargs):
        raise LLMAuthenticationError("LLM authentication failed (403)")

    engine.translator.translate_batch = raise_auth_error

    with pytest.raises(LLMAuthenticationError):
        engine._translate_table_llm_batch([
            {"id": "1", "original": "Description text"},
        ])