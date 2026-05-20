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
