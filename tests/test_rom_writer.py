from meowth.rom_writer import RomWriter


class DummyCharmap:
    def encode(self, text):
        return text.encode("ascii") + b"\xFF"


def _stats():
    return {
        "in_place": 0,
        "relocated": 0,
        "skipped": 0,
        "skipped_partial_ptrs": 0,
        "unsafe_ptrs": 0,
        "errors": 0,
        "expanded_in_place": 0,
        "truncated": 0,
        "size_diagnostics": [],
    }


def test_longer_label_uses_full_fixed_width_table_slot():
    address = RomWriter.MIN_POINTER_SOURCE + 0x100
    rom = bytearray(address + 32)
    rom[address : address + 13] = b"GLARE\xFF" + b"\x00" * 7
    writer = RomWriter(DummyCharmap(), target_lang="de")
    stats = _stats()

    writer._process_entry_v2(
        rom,
        {
            "id": "tbl_move_names_00001",
            "category": "move_names",
            "address": hex(address),
            "original": "GLARE",
            "translated": "SILBERBLICK",
            "byte_length": 13,
            "is_pointer_based": False,
            "table_name": "data.pokemon.moves.names",
        },
        stats,
    )

    assert rom[address : address + 12] == b"SILBERBLICK\xFF"
    assert stats["expanded_in_place"] == 1
    assert stats["truncated"] == 0


def test_non_table_text_without_pointer_still_stays_in_original_footprint():
    address = RomWriter.MIN_POINTER_SOURCE + 0x100
    rom = bytearray(address + 32)
    rom[address : address + 13] = b"GLARE\xFF" + b"\x00" * 7
    writer = RomWriter(DummyCharmap(), target_lang="de")
    stats = _stats()

    writer._process_entry_v2(
        rom,
        {
            "id": "manual_text",
            "category": "scripts",
            "address": hex(address),
            "original": "GLARE",
            "translated": "SILBERBLICK",
            "byte_length": 13,
            "is_pointer_based": False,
        },
        stats,
    )

    assert rom[address : address + 6] == b"SILBE\xFF"
    assert stats["expanded_in_place"] == 0
    assert stats["truncated"] == 1
