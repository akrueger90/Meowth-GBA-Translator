from pathlib import Path

from meowth import cli


def test_provider_config_expands_custom_terminology_path(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_load_config",
        lambda: {
            "translation": {
                "provider": "local",
                "terminology_file": "~/pokemon-terms.toml",
            }
        },
    )

    kwargs = cli._provider_kwargs(None, None, None, None)

    assert kwargs["provider"] == "local"
    assert kwargs["terminology_path"] == Path.home() / "pokemon-terms.toml"
