from meowth.gui.components.config_form import (
    load_form_state,
    provider_requires_api_key,
    provider_runtime_defaults,
    save_form_state,
)


def test_removed_category_policies_are_ignored_in_form_state(tmp_path):
    state_path = tmp_path / "gui-state.json"
    save_form_state(
        {
            "provider": "local",
            "category_policies": {
                "free_texts": {"use_glossary": False, "use_llm": False},
            },
        },
        state_path,
    )

    assert load_form_state(state_path) == {"provider": "local"}


def test_local_provider_does_not_require_api_key():
    assert provider_requires_api_key("local") is False
    assert provider_requires_api_key("groq") is True


def test_provider_runtime_values_are_fixed():
    assert provider_runtime_defaults("local") == (16, 1)
    assert provider_runtime_defaults("groq") == (6, 2)
    assert provider_runtime_defaults("openrouter") == (4, 1)
    assert provider_runtime_defaults("deepseek") == (30, 10)
