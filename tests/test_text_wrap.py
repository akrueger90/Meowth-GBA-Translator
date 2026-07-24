from meowth.text_wrap import wrap_text


def test_wrap_keeps_ellipsis_together_at_line_boundary():
    wrapped = wrap_text(
        "Pokémon hide in the grass.\nWho knows when they'll pop out...",
        target_lang="de",
    )

    assert wrapped.endswith("...")
    assert "\\p." not in wrapped
    assert "\\n." not in wrapped


def test_wrap_does_not_start_line_with_exclamation_mark():
    wrapped = wrap_text(
        "Wow, your POKéGEAR is impressive!\nDid your mom get it for you?",
        target_lang="de",
    )

    assert "\\n!" not in wrapped
    assert "\\p!" not in wrapped
