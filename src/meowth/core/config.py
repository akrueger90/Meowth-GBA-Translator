"""Unified configuration management for translation pipeline."""

import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..toml_compat import load_toml_file


def _get_default_work_dir() -> Path:
    """Get default work directory in a writable location."""
    # For GUI apps, use system cache directory
    if getattr(sys, '_MEIPASS', None):  # Running in PyInstaller bundle
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Caches" / "Meowth" / "work"
        elif sys.platform == "win32":
            # Windows: use AppData/Local/Meowth/Cache
            return Path.home() / "AppData" / "Local" / "Meowth" / "Cache" / "work"
        else:
            # Linux: use ~/.cache/Meowth
            return Path.home() / ".cache" / "Meowth" / "work"
    # For CLI, use current directory
    return Path("work")


def _get_default_output_dir() -> Path:
    """Get default output directory in a writable location."""
    # For GUI apps, use user's Documents directory
    if getattr(sys, '_MEIPASS', None):  # Running in PyInstaller bundle
        return Path.home() / "Documents" / "Meowth" / "outputs"
    # For CLI, use current directory
    return Path("outputs")


def _get_default_category_policies() -> dict[str, dict[str, bool]]:
    """Get default per-category translation policies.
    
    Returns:
        Dict mapping category name to {use_glossary, use_llm} flags.
        - use_glossary: Try glossary lookup first (PokeAPI data)
        - use_llm: Use LLM fallback if glossary misses
    """
    return {
        # Names: glossary-only (PokeAPI has authoritative translations)
        "pokemon_names": {"use_glossary": True, "use_llm": False},
        "move_names": {"use_glossary": True, "use_llm": False},
        "ability_names": {"use_glossary": True, "use_llm": False},
        "item_names": {"use_glossary": True, "use_llm": False},
        "type_names": {"use_glossary": True, "use_llm": False},
        "nature_names": {"use_glossary": True, "use_llm": False},
        "trainer_classes": {"use_glossary": True, "use_llm": False},
        "map_names": {"use_glossary": True, "use_llm": False},
        # Descriptions: glossary-first, LLM fallback for better context
        "ability_descriptions": {"use_glossary": True, "use_llm": True},
        "move_descriptions": {"use_glossary": True, "use_llm": True},
        "battle_text": {"use_glossary": True, "use_llm": True},
        # Free text: LLM-primary for context-aware translation
        "free_texts": {"use_glossary": True, "use_llm": True},
    }


@dataclass
class TranslationConfig:
    """Configuration for the translation pipeline.

    This class unifies configuration from CLI arguments, GUI forms,
    and meowth.toml files.
    """

    # Language settings
    source_lang: str = "en"
    target_lang: str = "zh-Hans"

    # LLM API settings
    provider: str | None = None
    api_base: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    model: str | None = None

    # Translation settings
    batch_size: int = 30
    max_workers: int = 10
    llm_for_tables: bool = False
    test_limit_texts: int | None = None  # For testing: limit to N texts (None or 0 = all texts)
    use_env_test_limit: bool = True
    category_policies: dict[str, dict[str, bool]] = field(default_factory=_get_default_category_policies)

    # File paths
    rom_path: Path | None = None
    output_dir: Path = field(default_factory=_get_default_output_dir)
    work_dir: Path = field(default_factory=_get_default_work_dir)

    # Game detection (auto-detected if not specified)
    game: str = "firered"

    # Optional context about the game to help the LLM translate better
    game_context: str = ""

    def get_category_policy(self, category: str) -> dict[str, bool]:
        """Get translation policy for a category.
        
        Args:
            category: The category name (e.g., 'pokemon_names', 'free_texts')
            
        Returns:
            Dict with {use_glossary, use_llm} flags, or defaults if category not found.
        """
        if category in self.category_policies:
            return self.category_policies[category]
        # Return defaults for unknown categories
        return _get_default_category_policies().get(category, {"use_glossary": True, "use_llm": True})

    def set_category_policy(self, category: str, use_glossary: bool, use_llm: bool) -> None:
        """Set translation policy for a category.
        
        Args:
            category: The category name
            use_glossary: Whether to use glossary lookup
            use_llm: Whether to use LLM fallback
        """
        self.category_policies[category] = {"use_glossary": use_glossary, "use_llm": use_llm}

    @classmethod
    def from_toml(cls, path: Path) -> "TranslationConfig":
        """Load configuration from a meowth.toml file.

        Args:
            path: Path to the meowth.toml file

        Returns:
            TranslationConfig instance with values from the TOML file
        """
        if not path.exists():
            return cls()

        data = load_toml_file(path)
        translation = data.get("translation", {})
        api = translation.get("api", {})
        category_policies_raw = translation.get("category_policies", {})
        
        # Merge loaded policies with defaults
        category_policies = _get_default_category_policies()
        if isinstance(category_policies_raw, dict):
            for cat, policy in category_policies_raw.items():
                if isinstance(policy, dict):
                    category_policies[cat] = {
                        "use_glossary": policy.get("use_glossary", True),
                        "use_llm": policy.get("use_llm", True),
                    }

        return cls(
            source_lang=translation.get("source_language", "en"),
            target_lang=translation.get("target_language", "zh-Hans"),
            provider=translation.get("provider"),
            api_base=api.get("base_url"),
            api_key_env=api.get("key_env"),
            model=translation.get("model"),
            batch_size=translation.get("batch_size", 30),
            max_workers=translation.get("max_workers", 10),
            llm_for_tables=translation.get("llm_for_tables", False),
            category_policies=category_policies,
        )

    @classmethod
    def from_cli_args(cls, **kwargs) -> "TranslationConfig":
        """Create configuration from CLI arguments.

        Args:
            **kwargs: Keyword arguments matching TranslationConfig fields

        Returns:
            TranslationConfig instance
        """
        # Filter out None values to use defaults
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        return cls(**filtered)

    def merge_with_toml(self, toml_path: Path) -> "TranslationConfig":
        """Merge this config with values from a TOML file.

        TOML values are used as defaults; existing non-None values take precedence.

        Args:
            toml_path: Path to the meowth.toml file

        Returns:
            New TranslationConfig with merged values
        """
        toml_config = self.from_toml(toml_path)

        # Use current values if set, otherwise fall back to TOML
        return TranslationConfig(
            source_lang=self.source_lang if self.source_lang != "en" else toml_config.source_lang,
            target_lang=self.target_lang if self.target_lang != "zh-Hans" else toml_config.target_lang,
            provider=self.provider or toml_config.provider,
            api_base=self.api_base or toml_config.api_base,
            api_key_env=self.api_key_env or toml_config.api_key_env,
            api_key=self.api_key,
            model=self.model or toml_config.model,
            batch_size=self.batch_size if self.batch_size != 30 else toml_config.batch_size,
            max_workers=self.max_workers if self.max_workers != 10 else toml_config.max_workers,
            llm_for_tables=self.llm_for_tables,
            category_policies=self.category_policies,
            rom_path=self.rom_path or toml_config.rom_path,
            output_dir=self.output_dir if self.output_dir != Path("outputs") else toml_config.output_dir,
            work_dir=self.work_dir if self.work_dir != Path("work") else toml_config.work_dir,
            game=self.game if self.game != "firered" else toml_config.game,
        )
