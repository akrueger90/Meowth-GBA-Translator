from meowth.charmap import Charmap


def test_latin_charmap_accepts_line_breaks_supported_by_encoder():
    charmap = Charmap(target_lang="de")
    text = "Nur sehr effektive Treffer\nrichten Schaden an."

    assert charmap.can_encode(text) == (True, [])
    assert b"\xfe" in charmap.encode(text)
