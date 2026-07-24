from pathlib import Path

from meowth.core import TranslationConfig, TranslationEngine


class DummyCharmap:
    def _sanitize(self, text):
        return text

    def can_encode(self, text):
        return True, None


class DummyGlossary:
    def lookup(self, text):
        if text == "PALLET TOWN":
            return "Alabastia"
        return None

    def lookup_relaxed(self, text, categories=None):
        if text == "PALLETTOWNNORTH" and categories == {"locations", "regions"}:
            return "Alabastia"
        return None

    def lookup_description(self, text, category):
        if category == "move_descriptions" and text == "Inflicts regular damage.":
            return "Verursacht normalen Schaden."
        return None

    def get_context_terms(self, text):
        return {}

    def add_term(self, source, target, category):
        return None


class FailingTranslator:
    def translate_batch(self, *args, **kwargs):
        raise AssertionError("LLM must not be called for tables when llm_for_tables is disabled")


class RecordingTranslator:
    def __init__(self):
        self.calls = []

    def translate_batch(self, texts, glossary_context=""):
        self.calls.append(texts)
        return ["Unbekanntes Gebiet" for _ in texts]


def test_default_policy_uses_glossary_then_provider_fallback(tmp_path: Path):
    texts_path = tmp_path / "texts.json"
    output_path = tmp_path / "out.json"
    texts_path.write_text(
        """
{
  "entries": [
    {"id": "tbl_map_names_00001", "category": "map_names", "original": "PALLETTOWNNORTH"},
    {"id": "tbl_map_names_00002", "category": "map_names", "original": "UNKNOWN AREA"}
  ]
}
""".strip(),
        encoding="utf-8",
    )

    config = TranslationConfig(work_dir=tmp_path)
    engine = TranslationEngine(
        config=config,
        charmap=DummyCharmap(),
        glossary=DummyGlossary(),
    )
    translator = RecordingTranslator()
    engine.translator = translator

    engine.translate_texts(texts_path, output_path)

    import json

    data = json.loads(output_path.read_text(encoding="utf-8"))
    entries = [
        entry
        for table in data["tables"]
        for entry in table["entries"]
    ]
    by_id = {entry["id"]: entry for entry in entries}

    assert config.llm_for_tables is True
    assert config.get_category_policy("map_names")["use_llm"] is True
    assert by_id["tbl_map_names_00001"]["translated"] == "Alabastia"
    assert by_id["tbl_map_names_00002"]["translated"] == "Unbekanntes Gebiet"
    assert translator.calls == [["UNKNOWN AREA"]]


def test_translate_texts_keeps_unresolved_table_entries_without_llm(tmp_path: Path):
    texts_path = tmp_path / "texts.json"
    output_path = tmp_path / "out.json"
    texts_path.write_text(
        """
{
  "entries": [
    {"id": "tbl_map_names_00001", "category": "map_names", "original": "PALLETTOWNNORTH"},
    {"id": "tbl_map_names_00002", "category": "map_names", "original": "UNKNOWN AREA"}
  ]
}
""".strip(),
        encoding="utf-8",
    )

    config = TranslationConfig(work_dir=tmp_path, llm_for_tables=False)
    engine = TranslationEngine(
        config=config,
        charmap=DummyCharmap(),
        glossary=DummyGlossary(),
    )
    engine.translator = FailingTranslator()

    engine.translate_texts(texts_path, output_path)

    import json

    data = json.loads(output_path.read_text(encoding="utf-8"))
    entries = [
        entry
        for table in data.get("tables", [])
        for entry in table.get("entries", [])
    ]
    by_id = {entry["id"]: entry for entry in entries}

    assert by_id["tbl_map_names_00001"]["translated"] == "Alabastia"
    assert by_id["tbl_map_names_00002"].get("translated", "") == ""


def test_translate_texts_uses_local_move_description_mapping_without_llm(tmp_path: Path):
        texts_path = tmp_path / "texts_desc.json"
        output_path = tmp_path / "out_desc.json"
        texts_path.write_text(
                """
{
    "entries": [
        {"id": "tbl_move_descriptions_00001", "category": "move_descriptions", "original": "Inflicts regular damage."}
    ]
}
""".strip(),
                encoding="utf-8",
        )

        config = TranslationConfig(work_dir=tmp_path, llm_for_tables=False)
        engine = TranslationEngine(
                config=config,
                charmap=DummyCharmap(),
                glossary=DummyGlossary(),
        )
        engine.translator = FailingTranslator()

        engine.translate_texts(texts_path, output_path)

        result = output_path.read_text(encoding="utf-8")
        assert "Verursacht normalen Schaden." in result
