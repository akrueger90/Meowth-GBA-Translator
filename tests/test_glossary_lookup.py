import pytest

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


def test_glossary_relaxed_lookup_is_strict_for_pokemon_names():
    glossary = Glossary(source_lang="en", target_lang="de")

    # Minor typo in the canonical Pokemon name should still match.
    assert glossary.lookup_relaxed("Charmeleonn", categories={"pokemon"}) == "Glutexo"

    # Similar but wrong names must not be substituted for Pokemon tables.
    assert glossary.lookup_relaxed("Charmeleon", categories={"pokemon"}) == "Glutexo"
    assert glossary.lookup_relaxed("Charmeleon", categories={"pokemon"}) != "Flamara"


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


def test_glossary_loads_official_ability_and_move_flavor_text():
    glossary = Glossary(source_lang="en", target_lang="de")

    assert glossary.lookup_description(
        "Summons rain in battle.", "ability_descriptions"
    ) == "Ruft im Kampf Regen herbei."
    assert glossary.lookup_description(
        r"\qoSuper effective\qc hits.", "ability_descriptions"
    ) == "Nur sehr effektive Treffer\nrichten Schaden an."
    assert glossary.lookup_description(
        "A physical attack delivered with a long tail or a foreleg, etc.",
        "move_descriptions",
    ) == "Ein Hieb mit den Vorderbeinen oder dem Schweif."
    assert glossary.lookup_description(
        "The foe is attacked with a sharp chop. It has a high critical-hit ratio.",
        "move_descriptions",
    ) == "Gute Möglichkeit, einen Volltreffer zu landen."


def test_glossary_fails_clearly_when_official_data_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="git submodule update --init pokeapi"):
        Glossary(
            pokeapi_dir=tmp_path / "missing",
            source_lang="en",
            target_lang="de",
        )


def test_apply_to_text_replaces_longest_terms_without_partial_words():
    glossary = Glossary(source_lang="en", target_lang="de")
    glossary.add_term("Dig", "Schaufler", "moves")
    glossary.add_term("Diglett", "Digda", "pokemon")

    translated = glossary.apply_to_text("Diglett can Dig near Indigobox.")

    assert translated == "Digda can Schaufler near Indigobox."


def test_placeholder_terms_cannot_corrupt_punctuation():
    glossary = Glossary(source_lang="en", target_lang="de")
    glossary.add_term("", "???", "dynamic")
    glossary.add_term("???", "???", "dynamic")

    text = "Wow, your POKéGEAR is impressive! Did your mom get it for you?"

    assert glossary.lookup("") is None
    assert glossary.lookup("???") is None
    assert glossary.apply_to_text(text) == text


def test_user_terminology_is_created_and_overrides_defaults(tmp_path):
    terminology_path = tmp_path / "terminology.toml"
    glossary = Glossary(
        source_lang="en",
        target_lang="de",
        terminology_path=terminology_path,
    )

    assert terminology_path.exists()
    assert glossary.lookup("HM") == "VM"
    assert glossary.lookup("Your Partys full!") == "Dein Team ist voll!"
    assert glossary.lookup("The BAG is full") == "Der Beutel ist voll"
    assert glossary.lookup("Do you want the DOME FOSSIL?") == (
        "Willst du das Domfossil?"
    )

    terminology_path.write_text(
        '[en.de]\n"HM" = "Versteckte Maschine"\n',
        encoding="utf-8",
    )
    reloaded = Glossary(
        source_lang="en",
        target_lang="de",
        terminology_path=terminology_path,
    )

    assert reloaded.lookup("HM") == "Versteckte Maschine"


def test_context_protects_pokeapi_names_and_uppercase_moves_and_items(tmp_path):
    glossary = Glossary(
        source_lang="en",
        target_lang="de",
        terminology_path=tmp_path / "terminology.toml",
    )

    terms = glossary.get_context_terms(
        "PIKACHU used CUT near Pallet Town with the DOME FOSSIL."
    )

    assert terms["Pikachu"] == "Pikachu"
    assert terms["Cut"] == "Zerschneider"
    assert terms["Pallet Town"] == "Alabastia"
    assert terms["Dome Fossil"] == "Domfossil"
    assert "Cut" not in glossary.get_context_terms("Please cut this rope.")
