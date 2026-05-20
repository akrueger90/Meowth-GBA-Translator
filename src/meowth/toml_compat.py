"""TOML parsing compatibility helpers for Python 3.10+."""

import importlib
import sys
from pathlib import Path
from typing import Any


def _get_toml_module_name() -> str:
    """Return the TOML parser module name for the running Python version."""
    if sys.version_info >= (3, 11):
        return "tomllib"
    return "tomli"


def loads_toml(content: str) -> dict[str, Any]:
    """Parse TOML content into a dictionary."""
    toml_module = importlib.import_module(_get_toml_module_name())
    return toml_module.loads(content)


def load_toml_file(path: Path) -> dict[str, Any]:
    """Parse a TOML file and return its dictionary content."""
    return loads_toml(path.read_text(encoding="utf-8"))
