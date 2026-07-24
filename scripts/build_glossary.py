"""Build pre-computed glossary JSON files from PokeAPI CSV data.

Downloads the required CSV files from the PokeAPI GitHub repository and writes
resources/glossary_{source}_{target}.json for use by the Meowth glossary.

Usage:
    python scripts/build_glossary.py [--source en] [--target de]
    python scripts/build_glossary.py --all      # build all supported language pairs
"""
import argparse
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

# PokeAPI raw CSV base URL
POKEAPI_CSV_URL = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/{filename}"

TERM_FILES: dict[str, tuple[str, str]] = {
    "pokemon":   ("pokemon_species_names.csv", "pokemon_species_id"),
    "moves":     ("move_names.csv",            "move_id"),
    "abilities": ("ability_names.csv",         "ability_id"),
    "items":     ("item_names.csv",            "item_id"),
    "types":     ("type_names.csv",            "type_id"),
    "natures":   ("nature_names.csv",          "nature_id"),
    "locations": ("location_names.csv",        "location_id"),
    "regions":   ("region_names.csv",          "region_id"),
}

PROSE_FILES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ability_descriptions": ("ability_prose.csv", "ability_id", ("short_effect", "effect")),
    "move_descriptions": ("move_effect_prose.csv", "move_effect_id", ("short_effect", "effect")),
}

FLAVOR_FILES: dict[str, tuple[str, str]] = {
    "ability_descriptions": ("ability_flavor_text.csv", "ability_id"),
    "move_descriptions": ("move_flavor_text.csv", "move_id"),
}

SUPPORTED_LANGUAGES: dict[str, dict] = {
    "en":      {"pokeapi_id": 9},
    "es":      {"pokeapi_id": 7},
    "fr":      {"pokeapi_id": 5},
    "de":      {"pokeapi_id": 6},
    "it":      {"pokeapi_id": 8},
    "zh-Hans": {"pokeapi_id": 12},
}

REPO_ROOT = Path(__file__).parent.parent
RESOURCES_DIR = REPO_ROOT / "resources"
CACHE_DIR = REPO_ROOT / "work" / "pokeapi_csv_cache"


def download_csv(filename: str) -> str:
    """Download a PokeAPI CSV file, using local cache if available."""
    cache_path = CACHE_DIR / filename
    if cache_path.exists():
        print(f"  [cache] {filename}")
        return cache_path.read_text(encoding="utf-8")

    url = POKEAPI_CSV_URL.format(filename=filename)
    print(f"  [download] {url}")
    with urllib.request.urlopen(url, timeout=30) as resp:
        content = resp.read().decode("utf-8")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(content, encoding="utf-8")
    return content


def build_glossary(source_lang: str, target_lang: str) -> dict:
    """Build glossary mappings from PokeAPI CSVs."""
    source_id = SUPPORTED_LANGUAGES[source_lang]["pokeapi_id"]
    target_id = SUPPORTED_LANGUAGES[target_lang]["pokeapi_id"]

    source_to_target: dict[str, str] = {}
    term_categories: dict[str, str] = {}
    ability_descriptions: dict[str, str] = {}
    move_descriptions: dict[str, str] = {}

    for category, (filename, id_col) in TERM_FILES.items():
        print(f"  Processing {category} ({filename})…")
        content = download_csv(filename)

        by_id: dict[int, dict[int, str]] = {}
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            entity_id = int(row[id_col])
            lang_id = int(row["local_language_id"])
            name = row["name"].strip()
            if entity_id not in by_id:
                by_id[entity_id] = {}
            by_id[entity_id][lang_id] = name

        added = 0
        for entity_id, names in by_id.items():
            source_name = names.get(source_id, "")
            target_name = names.get(target_id, "")
            if source_name and target_name:
                source_to_target[source_name] = target_name
                # Also store uppercase key for case-insensitive lookup
                source_to_target[source_name.upper()] = target_name
                term_categories[source_name] = category
                added += 1
        print(f"    → {added} terms")

    def collect_prose_mapping(
        filename: str,
        id_col: str,
        text_columns: tuple[str, ...],
        out_map: dict[str, str],
    ) -> int:
        content = download_csv(filename)
        by_id: dict[int, dict[int, dict[str, str]]] = {}
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            entity_id = int(row[id_col])
            lang_id = int(row["local_language_id"])
            per_lang = by_id.setdefault(entity_id, {}).setdefault(lang_id, {})
            for column in text_columns:
                text = (row.get(column) or "").strip()
                if text:
                    per_lang[column] = text

        added_local = 0
        for _, by_lang in by_id.items():
            src = by_lang.get(source_id, {})
            tgt = by_lang.get(target_id, {})
            if not src or not tgt:
                continue

            for column in text_columns:
                source_text = src.get(column, "")
                if not source_text:
                    continue
                target_text = tgt.get(column, "")
                if not target_text:
                    continue
                if source_text not in out_map:
                    out_map[source_text] = target_text
                    added_local += 1
        return added_local

    for category, (filename, id_col, text_columns) in PROSE_FILES.items():
        print(f"  Processing {category} ({filename})…")
        out_map = ability_descriptions if category == "ability_descriptions" else move_descriptions
        added = collect_prose_mapping(filename, id_col, text_columns, out_map)
        print(f"    → {added} prose entries")

    for category, (filename, id_col) in FLAVOR_FILES.items():
        print(f"  Processing {category} flavor text ({filename})…")
        content = download_csv(filename)
        by_id: dict[int, dict[int, list[tuple[int, str]]]] = {}
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            entity_id = int(row[id_col])
            lang_id = int(row["language_id"])
            version_group_id = int(row["version_group_id"])
            text = (row.get("flavor_text") or "").strip()
            if text:
                by_id.setdefault(entity_id, {}).setdefault(lang_id, []).append(
                    (version_group_id, text)
                )

        out_map = ability_descriptions if category == "ability_descriptions" else move_descriptions
        added = 0
        for by_lang in by_id.values():
            source_variants = by_lang.get(source_id, [])
            target_variants = by_lang.get(target_id, [])
            if not source_variants or not target_variants:
                continue
            _, target_text = min(target_variants, key=lambda variant: variant[0])
            for _, source_text in source_variants:
                if source_text not in out_map:
                    out_map[source_text] = target_text
                    added += 1
        print(f"    → {added} flavor entries")

    return {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_to_target": source_to_target,
        "term_categories": term_categories,
        "ability_descriptions": ability_descriptions,
        "move_descriptions": move_descriptions,
    }


def main():
    parser = argparse.ArgumentParser(description="Build Meowth glossary JSON files from PokeAPI data.")
    parser.add_argument("--source", default="en", choices=list(SUPPORTED_LANGUAGES), help="Source language (default: en)")
    parser.add_argument("--target", default="de", choices=list(SUPPORTED_LANGUAGES), help="Target language (default: de)")
    parser.add_argument("--all", action="store_true", dest="build_all", help="Build glossaries for all non-English target languages")
    args = parser.parse_args()

    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)

    targets = list(SUPPORTED_LANGUAGES.keys()) if args.build_all else [args.target]
    source = args.source

    for target in targets:
        if target == source:
            continue
        out_path = RESOURCES_DIR / f"glossary_{source}_{target}.json"
        print(f"\nBuilding glossary: {source} → {target}")
        data = build_glossary(source, target)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Written: {out_path} ({len(data['source_to_target'])} entries)")


if __name__ == "__main__":
    main()
