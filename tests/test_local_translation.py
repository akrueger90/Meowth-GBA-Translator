import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from meowth.local_translation import (
    LocalTranslationBackend,
    LocalTranslationError,
)
from meowth.translator import Translator


class FakeTokenizer:
    def encode(self, text, out_type):
        assert out_type is str
        return text

    def decode(self, value):
        return "".join(value)


class FakeRuntime:
    def __init__(self):
        self.calls = 0

    def translate_batch(self, texts, beam_size):
        assert beam_size == 4
        self.calls += 1
        translations = [
            text.replace("Your rival", "Dein Rivale").replace(
                "waits in", "wartet in"
            )
            for text in texts
        ]
        return [
            SimpleNamespace(hypotheses=[[translation]])
            for translation in translations
        ]


class FakeLocalBackend:
    def __init__(self):
        self.calls = 0

    def translate_batch(self, texts, glossary_context):
        self.calls += 1
        return [f"DE:{text}" for text in texts]


def _create_model_dir(root: Path) -> Path:
    model_dir = root / "en_de"
    (model_dir / "model").mkdir(parents=True)
    (model_dir / "metadata.json").write_text(
        json.dumps({"from_code": "en", "to_code": "de"}),
        encoding="utf-8",
    )
    (model_dir / "sentencepiece.model").touch()
    (model_dir / "model" / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model" / "model.bin").touch()
    return model_dir


def test_local_backend_preserves_control_codes_and_glossary_terms(tmp_path):
    model_dir = _create_model_dir(tmp_path)
    runtime = FakeRuntime()
    backend = LocalTranslationBackend(
        "en",
        "de",
        model_root=tmp_path,
        runtime_factory=lambda path: (
            runtime,
            FakeTokenizer(),
        ),
    )

    translated = backend.translate_batch(
        ["Your rival {C0} waits in Pallet Town."],
        "  Pallet Town = Alabastia",
    )

    assert translated == ["Dein Rivale {C0} wartet in Alabastia."]
    assert runtime.calls == 1
    assert backend._ensure_model() == model_dir


def test_local_backend_protects_terms_with_unchanged_official_names(tmp_path):
    runtime = FakeRuntime()
    backend = LocalTranslationBackend(
        "en",
        "de",
        model_root=tmp_path,
        runtime_factory=lambda path: (runtime, FakeTokenizer()),
    )
    _create_model_dir(tmp_path)

    translated = backend.translate_batch(
        ["PIKACHU waits on Route 1."],
        "  Pikachu = Pikachu\n  Route = Route",
    )

    assert translated == ["Pikachu waits on Route 1."]


def test_local_backend_restores_original_placeholder_spacing():
    source = "Hello!{C0}Your rival {C1} waits in {G0}."
    translated = "Hallo! {C0} Dein Rivale {C1} wartet in {G0}."

    assert LocalTranslationBackend._restore_placeholder_spacing(
        source, translated
    ) == "Hallo!{C0}Dein Rivale {C1} wartet in {G0}."


def test_local_backend_rejects_unsafe_model_archive(tmp_path):
    archive_path = tmp_path / "unsafe.argosmodel"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")

    backend = LocalTranslationBackend("en", "de", model_root=tmp_path / "models")

    with pytest.raises(LocalTranslationError, match="unsafe path"):
        backend._extract_model_archive(archive_path, tmp_path / "extract")


def test_translator_uses_per_text_cache_for_local_backend(tmp_path):
    translator = Translator(
        provider="local",
        source_lang="en",
        target_lang="de",
        cache_dir=tmp_path / "cache",
        local_model_dir=tmp_path / "models",
    )
    backend = FakeLocalBackend()
    translator._local_backend = backend

    first = translator.translate_batch(
        ["Hello", "World"],
        "Pallet Town = Alabastia",
    )
    second = translator.translate_batch(
        ["World", "Hello"],
        "Viridian City = Vertania City",
    )

    assert first == ["DE:Hello", "DE:World"]
    assert second == ["DE:World", "DE:Hello"]
    assert backend.calls == 1


def test_translator_defaults_to_local_without_remote_configuration(tmp_path):
    translator = Translator(cache_dir=tmp_path)

    assert translator.is_local is True
    assert translator.model == "argos-opus"
