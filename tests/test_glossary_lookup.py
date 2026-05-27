from src.meowth.glossary import Glossary


def test_german_glossary_normalizes_special_pokemon_names():
    glossary = Glossary(source_lang="en", target_lang="de")

    assert glossary.lookup("Farfetch'd") == "Porenta"
    assert glossary.lookup("farfetch'd") == "Porenta"
    assert glossary.lookup("Mr. Mime") == "Pantimos"
    assert glossary.lookup("mr. mime") == "Pantimos"
    assert glossary.lookup("nidoran \\sm") == "Nidoran♂"
    assert glossary.lookup("nidoran \\sf") == "Nidoran♀"
    assert glossary.lookup("Ho-Oh") == "Ho-Oh"
    assert glossary.lookup("Porygon2") == "Porygon2"


def test_glossary_relaxed_lookup_handles_suffix_variants_by_category():
    glossary = Glossary(source_lang="en", target_lang="de")
    glossary.add_term("Pallet Town", "Alabastia", "locations")

    assert glossary.lookup("PALLETTOWNNORTH") is None
    assert glossary.lookup_relaxed("PALLETTOWNNORTH", categories={"locations"}) == "Alabastia"


def test_glossary_relaxed_lookup_respects_category_filter():
    glossary = Glossary(source_lang="en", target_lang="de")
    glossary.add_term("Bite", "Biss", "moves")

    assert glossary.lookup_relaxed("BITE", categories={"locations"}) is None


def test_glossary_description_lookup_supports_compact_variants():
    glossary = Glossary(source_lang="en", target_lang="de")
    glossary._index_description(
        "Inflicts regular damage and has a 10% chance to burn.",
        "Fugt regulären Schaden zu und hat eine 10%-Chance auf Verbrennung.",
        "move_descriptions",
    )

    source_variant = "Inflicts regular damage   and has a 10% chance to burn"
    assert glossary.lookup_description(source_variant, "move_descriptions") == (
        "Fugt regulären Schaden zu und hat eine 10%-Chance auf Verbrennung."
    )
