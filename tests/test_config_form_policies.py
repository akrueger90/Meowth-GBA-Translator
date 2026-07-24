from types import SimpleNamespace

from meowth.gui.components.config_form import (
    ConfigForm,
    load_form_state,
    save_form_state,
)


def test_category_policies_are_copied_and_can_disable_all_llm():
    form = SimpleNamespace(_category_policies={})
    policies = {
        "move_names": {"use_glossary": True, "use_llm": False},
        "free_texts": {"use_glossary": False, "use_llm": False},
    }

    ConfigForm.set_category_policies(form, policies)
    policies["move_names"]["use_llm"] = True

    stored = ConfigForm.get_category_policies(form)
    assert stored["move_names"]["use_llm"] is False
    assert ConfigForm.requires_llm(form) is False


def test_category_policies_round_trip_in_form_state(tmp_path):
    state_path = tmp_path / "gui-state.json"
    policies = {
        "free_texts": {"use_glossary": True, "use_llm": False},
    }

    save_form_state({"category_policies": policies}, state_path)

    assert load_form_state(state_path)["category_policies"] == policies
