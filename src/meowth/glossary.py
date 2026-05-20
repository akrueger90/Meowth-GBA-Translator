"""Load official Pokemon terminology from PokeAPI CSV files."""

import csv
import re
import unicodedata
from pathlib import Path

from .languages import SUPPORTED_LANGUAGES
from .resource_path import get_resource_path

POKEAPI_DIR = get_resource_path("pokeapi/data/v2/csv")

# CSV files and their name column
TERM_FILES = {
    "pokemon": ("pokemon_species_names.csv", "pokemon_species_id"),
    "moves": ("move_names.csv", "move_id"),
    "abilities": ("ability_names.csv", "ability_id"),
    "items": ("item_names.csv", "item_id"),
    "types": ("type_names.csv", "type_id"),
    "natures": ("nature_names.csv", "nature_id"),
    "locations": ("location_names.csv", "location_id"),
    "regions": ("region_names.csv", "region_id"),
}

# Categories that should be included in LLM context (proper nouns only)
# These are terms that won't appear in everyday dialogue
CONTEXT_SAFE_CATEGORIES = {
    "pokemon",      # Pokemon names (BULBASAUR, PIKACHU)
    "locations",    # Location names (PALLET TOWN, VIRIDIAN CITY)
    "regions",      # Region names (KANTO, JOHTO)
}

# Categories excluded from context to avoid false matches
# These contain common words that might appear in dialogue
CONTEXT_UNSAFE_CATEGORIES = {
    "moves",        # Move names (bite, tackle, surf - common words!)
    "abilities",    # Ability names (overgrow, blaze)
    "items",        # Item names (potion, ball)
    "types",        # Type names (fire, water - very common!)
    "natures",      # Nature names (brave, timid - common adjectives!)
}

# Manual overrides per target language: source_text → target_text
# These take priority over PokeAPI glossary data
MANUAL_OVERRIDES: dict[str, dict[str, str]] = {
    "zh-Hans": {
        "Pokédex": "图鉴",
        "Pokedex": "图鉴",
        "POKEDEX": "图鉴",
        "POKéDEX": "图鉴",
    },
    "de": {
        "Pokédex": "Pokédex",
        "Pokedex": "Pokédex",
        "POKEDEX": "Pokédex",
        "POKéDEX": "Pokédex",
        "POKéMON": "Pokémon",
        "POKéNAV": "PokéNav",
    },
}


_GENDER_MACROS = {
    r"\\sm": "♂",
    r"\\sf": "♀",
}

# ROM-extracted name variants → canonical PokeAPI names
# Handles truncation, spacing issues, and GBA encoding quirks
ROM_NAME_VARIANTS: dict[str, str] = {
    # Items - common variants
    "BLK APRICORN": "Black Apricorn",
    "BLU APRICORN": "Blue Apricorn",
    "GRN APRICORN": "Green Apricorn",
    "PNK APRICORN": "Pink Apricorn",
    "RED APRICORN": "Red Apricorn",
    "WHT APRICORN": "White Apricorn",
    "YLW APRICORN": "Yellow Apricorn",
    "ITEMFINDER": "Item Finder",
    "POKéGEAR": "Pokégear",
    "POKEGEAR": "Pokégear",
    "SLOPOKETAIL": "Slowpoke Tail",
    "PARALYZ HEAL": "Paralyze Heal",
    "PARLYZ HEAL": "Paralyze Heal",  # spelling variant
    "POKEFLUTE": "Poké Flute",
    "SILKSCARF": "Silk Scarf",
    "SILVERPOWDER": "Silver Powder",
    "SOFTSAND": "Soft Sand",
    "CHARCOAL": "Charcoal",
    "WATERTAIL": "Water Tail",
    "MIRACLESEED": "Miracle Seed",
    "MAGNET": "Magnet",
    "NEVERMELT": "Never-Melt Ice",
    "DRAGONSCALE": "Dragon Scale",
    "LEFTOVERS": "Leftovers",
    "LIGHT BALL": "Light Ball",
    "THICKCLUB": "Thick Club",
    "X DEFEND": "X Defense",
    "X SPECIAL": "X Sp. Atk",
    "STICK": "Leek",
    # Moves - capitalization and spacing variants
    "SMELLINGSALT": "Smelling Salt",
    "SmellingSalt": "Smelling Salt",
    "VICEGRIP": "Vice Grip",
    "Vicegrip": "Vice Grip",
    "HIJUMPKICK": "Hi Jump Kick",
    "Hi Jump Kick": "Hi Jump Kick",
    "FAINTATTACK": "Faint Attack",
    "Faint Attack": "Faint Attack",
    # Types - ROM truncations
    "ELECTR": "Electric",
    "FIGHT": "Fighting",
    "PSYCHC": "Psychic",
    # Game-specific / Custom items (not in PokeAPI, keep as-is for LLM)
    "DNA SAMPLE": "DNA SAMPLE",
    "GBP CARD": "GBP CARD",
    "MAP CARD": "MAP CARD",
    "POKé TAR": "POKé TAR",
    "PROGRAM": "PROGRAM",
    "SATURN ROCK": "SATURN ROCK",
}


def _normalize_lookup_key(text: str) -> str:
    """Normalize ROM and PokeAPI term variants to one lookup key."""
    normalized = unicodedata.normalize("NFKC", text).strip()
    for macro, symbol in _GENDER_MACROS.items():
        normalized = re.sub(macro, symbol, normalized, flags=re.IGNORECASE)
    normalized = normalized.casefold()
    return "".join(ch for ch in normalized if ch.isalnum() or ch in "♀♂")


class Glossary:
    def __init__(
        self,
        pokeapi_dir: Path = POKEAPI_DIR,
        source_lang: str = "en",
        target_lang: str = "zh-Hans",
    ):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.source_id = SUPPORTED_LANGUAGES[source_lang]["pokeapi_id"]
        self.target_id = SUPPORTED_LANGUAGES[target_lang]["pokeapi_id"]

        self.source_to_target: dict[str, str] = {}
        # Separate index for context matching: uppercase key → (original_source, target, category)
        self._upper_index: dict[str, tuple[str, str, str]] = {}
        # Compact key index for punctuation/spacing variants and ROM macro forms.
        self._compact_index: dict[str, str] = {}
        # Category mapping: term → category
        self._term_category: dict[str, str] = {}

        # Try loading from pre-built JSON first, fall back to CSV
        json_path = Path(__file__).parent.parent.parent / "resources" / f"glossary_{source_lang}_{target_lang}.json"
        if json_path.exists():
            self._load_json(json_path)
        else:
            self._load_all(pokeapi_dir)

        # Apply manual overrides (highest priority, overwrite PokeAPI data)
        overrides = MANUAL_OVERRIDES.get(target_lang, {})
        for source, target in overrides.items():
            self._index_term(source, target, "manual")

    def _index_term(self, source: str, target: str, category: str) -> None:
        """Index a glossary term for direct, case-insensitive, and compact lookup."""
        self.source_to_target[source] = target
        self.source_to_target[source.upper()] = target
        self._upper_index[source.upper()] = (source, target, category)
        self._term_category[source] = category
        self._compact_index[_normalize_lookup_key(source)] = target

    def _load_json(self, path: Path):
        """Load glossary from pre-built JSON file."""
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        self.source_to_target = data.get("source_to_target", {})
        term_categories = data.get("term_categories", {})

        # Build uppercase index and compact index
        for source, target in self.source_to_target.items():
            category = term_categories.get(source, "unknown")
            self._upper_index[source.upper()] = (source, target, category)
            self._term_category[source] = category
            self._compact_index[_normalize_lookup_key(source)] = target


    def _load_all(self, base_dir: Path):
        for category, (filename, id_col) in TERM_FILES.items():
            path = base_dir / filename
            if not path.exists():
                continue
            self._load_csv(path, id_col, category)

    def _load_csv(self, path: Path, id_col: str, category: str):
        """Load a PokeAPI names CSV and build source->target mapping."""
        # Group by entity ID
        by_id: dict[int, dict[int, str]] = {}
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entity_id = int(row[id_col])
                lang_id = int(row["local_language_id"])
                name = row["name"].strip()
                if entity_id not in by_id:
                    by_id[entity_id] = {}
                by_id[entity_id][lang_id] = name

        # Build source -> target mapping
        for entity_id, names in by_id.items():
            source_name = names.get(self.source_id, "")
            target_name = names.get(self.target_id, "")
            if source_name and target_name:
                self._index_term(source_name, target_name, category)

    def lookup(self, source_text: str) -> str | None:
        """Look up target translation for a source term.

        Tries direct lookup first, then ROM variant mapping, then compact matching
        for GBA's truncated names like THUNDERPUNCH → Thunder Punch.
        """
        # Try direct lookup
        result = self.source_to_target.get(source_text) or self.source_to_target.get(source_text.upper())
        if result:
            return result
        
        # Try ROM variant mapping (e.g., PARALYZ HEAL → Paralyze Heal)
        canonical = ROM_NAME_VARIANTS.get(source_text) or ROM_NAME_VARIANTS.get(source_text.upper())
        if canonical:
            result = self.source_to_target.get(canonical) or self.source_to_target.get(canonical.upper())
            if result:
                return result
        
        # Try compact matching (no spaces/hyphens)
        return self._compact_index.get(_normalize_lookup_key(source_text))

    def matches_expected_translation(self, source_text: str, translated_text: str) -> bool:
        """Return True when translated_text matches the glossary result for source_text.

        Normalizes ROM forms and uses normalized comparison so variants like
        ``PARALYZ HEAL`` match canonical glossary forms like ``Paralyze Heal``.
        """
        # First normalize ROM form if it's a known variant
        canonical_source = ROM_NAME_VARIANTS.get(source_text) or ROM_NAME_VARIANTS.get(source_text.upper())
        if canonical_source:
            source_text = canonical_source
        
        expected = self.lookup(source_text)
        if not expected:
            return False
        return _normalize_lookup_key(expected) == _normalize_lookup_key(translated_text)

    def add_term(self, source: str, target: str, category: str = "dynamic") -> None:
        """Add a dynamic term to the glossary (e.g. from translated tables)."""
        self._index_term(source, target, category)

    def apply_to_text(self, text: str) -> str:
        """Apply glossary replacements to text using word-boundary matching."""
        import re

        result = text
        # Sort by length (longest first) to avoid partial replacements
        for source, target in sorted(self.source_to_target.items(), key=lambda x: -len(x[0])):
            # Use word boundaries to avoid matching substrings inside other words
            # e.g. "Dig" should not match inside "Indigo"
            pattern = re.compile(r"(?<![A-Za-z])" + re.escape(source) + r"(?![A-Za-z])")
            result = pattern.sub(target, result)
        return result

    def get_context_terms(self, text: str, limit: int = 20) -> dict[str, str]:
        """Find terms in text that have known translations (for LLM context).

        Only includes proper nouns (Pokemon names, locations, regions) to avoid
        false matches with common words like "bite" (move name) or "fire" (type).

        Uses the uppercase index for efficient case-insensitive matching.
        Only checks each unique term once against the text.
        """
        found: dict[str, str] = {}
        text_upper = text.upper()
        for upper_key, (source, target, category) in self._upper_index.items():
            # Include safe categories (proper nouns) and manual overrides
            if category not in CONTEXT_SAFE_CATEGORIES and category not in ("manual", "dynamic"):
                continue
            if upper_key in text_upper:
                found[source] = target
                if len(found) >= limit:
                    break
        return found
