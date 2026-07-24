"""User-editable terminology layered on top of official PokeAPI names."""

from __future__ import annotations

import json
from pathlib import Path

from .toml_compat import load_toml_file


DEFAULT_TERMINOLOGY_PATH = Path.home() / ".meowth" / "terminology.toml"

DEFAULT_TERMINOLOGY: dict[tuple[str, str], dict[str, str]] = {
    ("en", "de"): {
        "HM": "VM",
        "HP": "KP",
        "BAG": "Beutel",
        "MAIL": "Brief",
        "PARTY": "Team",
        "Route": "Route",
        "LOST WOODS": "Verlorener Wald",
        "Deposit in which BOX?": "In welcher Box ablegen?",
        "Your Partys full!": "Dein Team ist voll!",
        "Your Party's full!": "Dein Team ist voll!",
        "The BAG is full": "Der Beutel ist voll",
        "MAIL cant be stored": "Brief kann nicht gelagert werden",
        "Not enough HP": "Nicht genug KP",
        "Do you want the DOME FOSSIL?": "Willst du das Domfossil?",
        "Would you like the DOME FOSSIL?": "Möchtest du das Domfossil?",
        "Do you want": "Willst du",
        "Would you like": "Möchtest du",
    },
}


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def ensure_terminology_file(path: Path = DEFAULT_TERMINOLOGY_PATH) -> None:
    """Create an editable terminology file with the built-in defaults once."""
    path = Path(path).expanduser()
    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# User terminology overrides for Meowth.",
        "# Edit this file and restart the application; no rebuild is required.",
        "# Matching is case-insensitive and longer phrases take priority.",
        "",
    ]
    for (source_lang, target_lang), terms in DEFAULT_TERMINOLOGY.items():
        lines.append(f"[{_toml_string(source_lang)}.{_toml_string(target_lang)}]")
        for source, target in terms.items():
            lines.append(f"{_toml_string(source)} = {_toml_string(target)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def load_terminology(
    source_lang: str,
    target_lang: str,
    path: Path | None = None,
) -> dict[str, str]:
    """Load built-in terms and apply user overrides for one language pair."""
    terms = dict(DEFAULT_TERMINOLOGY.get((source_lang, target_lang), {}))
    if path is None:
        return terms

    path = Path(path).expanduser()
    ensure_terminology_file(path)
    try:
        data = load_toml_file(path)
    except Exception as exc:
        raise ValueError(f"Invalid terminology file {path}: {exc}") from exc

    source_section = data.get(source_lang, {})
    if not isinstance(source_section, dict):
        raise ValueError(
            f"Invalid terminology file {path}: [{source_lang}] must be a table"
        )
    target_section = source_section.get(target_lang, {})
    if not isinstance(target_section, dict):
        raise ValueError(
            f"Invalid terminology file {path}: "
            f"[{source_lang}.{target_lang}] must be a table"
        )

    for source, target in target_section.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError(
                f"Invalid terminology entry in {path}: sources and targets must be strings"
            )
        source = source.strip()
        target = target.strip()
        if not source or not target:
            raise ValueError(
                f"Invalid terminology entry in {path}: empty terms are not allowed"
            )
        terms[source] = target
    return terms
