"""Core translation engine - refactored from Pipeline with callback support."""

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..charmap import Charmap
from ..control_codes import protect, restore
from ..font_patch import apply_font_patch
from ..glossary import Glossary
from ..i18n import Messages
from ..languages import is_cjk_language
from ..pcs_codes import FD_MACROS
from ..rom_writer import RomWriter
from ..text_wrap import wrap_text
from ..translator import Translator
from ..translator import LLMAuthenticationError
from ..translator import TranslationStoppedError
from .callbacks import TranslationCallbacks
from .config import TranslationConfig

# Game detection from ROM header
_GAME_CODES: dict[str, str] = {
    "BPRE": "firered",
    "BPGE": "leafgreen",
    "BPEE": "emerald",
    "AXVE": "ruby",
    "AXPE": "sapphire",
}

# Table categories (routed through _translate_table instead of LLM free-text batches)
TABLE_CATEGORIES = {
    "pokemon_names", "move_names", "ability_names", "nature_names",
    "type_names", "item_names", "trainer_classes", "map_names",
    "battle_text",  # Emerald battle messages with \\00/\\0F/\\34 runtime variables
}

# Hardcoded translations (FireRed + Chinese only)
_HARDCODED_TRANSLATIONS: dict[str, str] = {
    "scr_02219": (
        "你将成为主角，\n探索宝可梦的世界！"
        "\n\n通过与人们交谈并解开谜题，\n新的道路将为你敞开。"
        "\n\n与你出色的宝可梦一起，\n朝着目标努力吧！"
    ),
    "scr_02329": (
        "你好啊！\n很高兴见到你！"
        "\n\n欢迎来到宝可梦火红VX！"
        "\n\n我叫大木。"
        "\n\n人们亲切地称呼我为\n宝可梦博士。\n\n"
    ),
    "scr_02330": "这个世界",
    "scr_02331": "到处都栖息着被称为\n宝可梦的生物。\n\n",
    "scr_02332": (
        "对有些人来说，宝可梦是宠物。\n也有人用它们来对战。"
        "\n\n至于我自己……"
        "\n\n我把研究宝可梦当作职业。"
    ),
    "scr_02333": "不过首先，\n请告诉我一些关于你自己的事。",
    "scr_02334": "先从你的名字开始吧。\n你叫什么名字？",
    "scr_02335": "好的……\n\n原来你叫[player]。",
    "scr_02336": (
        "这是我的孙子。"
        "\n\n从你们还是婴儿的时候起，\n他就一直是你的劲敌。"
        "\n\n呃，他叫什么名字来着？"
    ),
    "scr_02339": "没错！我想起来了！\n他的名字是[rival]！",
    "scr_02340": (
        "[player]！"
        "\n\n属于你自己的宝可梦传奇\n即将展开！"
        "\n\n充满梦想与冒险的宝可梦世界\n正等待着你！出发吧！"
    ),
}

# Manual trainer class translations
_TRAINER_CLASS_OVERRIDES: dict[str, str] = {
    "RIVAL": "劲敌",
}

# Term overrides by original text (applied before LLM, all games, Chinese only)
_TERM_OVERRIDES: dict[str, str] = {
    "POKéDEX": "图鉴",
    "POKéMON": "宝可梦",
    "POKéNAV": "导航仪",
}


def detect_game(rom_path: Path) -> str:
    """Detect game type from GBA ROM header (bytes 0xAC-0xAF)."""
    with open(rom_path, "rb") as f:
        f.seek(0xAC)
        code = f.read(4).decode("ascii", errors="replace")
    return _GAME_CODES.get(code, "unknown")


# Known font-rendering function addresses and expected THUMB prologue bytes for
# official binary ROMs. Decomp ROMs (pokeemerald, pokefirered, etc.) are
# recompiled from source, so these addresses contain completely different code.
_FONT_HOOK_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "firered":   [(0x5790, b"\x70\xb5"), (0x5ed4, b"\xf0\xb5")],
    "leafgreen": [(0x5790, b"\x70\xb5"), (0x5ed4, b"\xf0\xb5")],
    "emerald":   [(0x57b4, b"\x70\xb5"), (0x5ed8, b"\xf0\xb5")],
}


def is_decomp_rom(rom_path: Path, game: str) -> bool:
    """Return True if this ROM is incompatible with the font patch.

    Checks whether the bytes at known font-rendering function addresses match
    the official binary ROM. Decomp ROMs (pokeemerald, pokefirered, etc.) are
    recompiled from source, so these addresses contain completely different code.
    Binary hacks applied on top of the original ROM preserve these bytes.
    """
    sigs = _FONT_HOOK_SIGNATURES.get(game)
    if sigs is None:
        return False  # unknown game, skip check
    with open(rom_path, "rb") as f:
        for offset, expected in sigs:
            f.seek(offset)
            if f.read(len(expected)) != expected:
                return True
    return False


def convert_format(data: dict) -> dict:
    """Convert MeowthBridge entries format to tables + free_texts format."""
    if "tables" in data:
        return data
    entries = data["entries"]
    tables_by_cat: dict[str, list] = {}
    free_texts: list = []
    for e in entries:
        cat = e.get("category", "")
        if cat in TABLE_CATEGORIES:
            tables_by_cat.setdefault(cat, []).append(e)
        else:
            free_texts.append(e)
    return {
        "tables": [{"category": c, "entries": es} for c, es in tables_by_cat.items()],
        "free_texts": free_texts,
    }


def _strip_llm_newlines(text: str) -> str:
    """Remove literal newlines inserted by the LLM for formatting."""
    _PARA = "\x00PARA\x00"
    text = text.replace("\n\n", _PARA)
    text = text.replace("\n", "")
    text = text.replace(_PARA, "\n\n")
    return text


def _has_meaningful_translation(entry: dict) -> bool:
    """Return True when entry already has a non-empty translated value."""
    translated = entry.get("translated")
    if translated is None:
        return False
    return bool(str(translated).strip())


def _postprocess_fd_macros(json_path: Path):
    """Replace HMA's raw FD escape sequences with named macros."""
    _HMA_KNOWN = {0x01, 0x02, 0x03, 0x04, 0x06}
    replacements = {}
    for code, name in FD_MACROS.items():
        if code not in _HMA_KNOWN:
            replacements[f"\\\\\\\\{code:02X}"] = name
    if not replacements:
        return
    text = json_path.read_text(encoding="utf-8")
    for raw, macro in replacements.items():
        text = text.replace(raw, macro)
    json_path.write_text(text, encoding="utf-8")


class TranslationEngine:
    """Core translation engine with callback support.

    This is the refactored version of Pipeline that uses callbacks
    instead of print() statements, enabling both CLI and GUI interfaces.
    """

    def __init__(
        self,
        config: TranslationConfig,
        callbacks: TranslationCallbacks | None = None,
        charmap: Charmap | None = None,
        glossary: Glossary | None = None,
        translator: Translator | None = None,
        stop_event: threading.Event | None = None,
    ):
        """Initialize the translation engine.

        Args:
            config: Translation configuration
            callbacks: Callback handler for progress and logging
            charmap: Character mapping (auto-created if None)
            glossary: Glossary for term translation (auto-created if None)
            translator: LLM translator (auto-created if None)
        """
        self.config = config
        self.callbacks = callbacks or TranslationCallbacks()
        self._stop_event = stop_event or threading.Event()

        self.charmap = charmap or Charmap(target_lang=config.target_lang)
        self.glossary = glossary or Glossary(
            source_lang=config.source_lang,
            target_lang=config.target_lang
        )
        self.translator = translator or Translator(
            source_lang=config.source_lang,
            target_lang=config.target_lang,
            provider=config.provider,
            base_url=config.api_base,
            api_key=config.api_key,
            api_key_env=config.api_key_env,
            model=config.model,
            cache_dir=config.work_dir / "cache",
            stop_event=self._stop_event,
        )

    def request_stop(self) -> None:
        """Request cooperative cancellation for ongoing translation work."""
        self._stop_event.set()

    def _check_stop(self) -> None:
        if self._stop_event.is_set():
            raise TranslationStoppedError("Translation stopped by user")

    def _log(self, level: str, message: str):
        """Internal helper to send log messages via callbacks."""
        self.callbacks.on_log(level, message)

    def _get_effective_text_limit(self) -> int | None:
        """Return configured positive text limit, or None for no limit."""
        import os

        value = self.config.test_limit_texts
        if value is None and getattr(self.config, "use_env_test_limit", True):
            env_value = os.environ.get("MEOWTH_TEST_LIMIT_TEXTS", "").strip()
            if env_value:
                try:
                    value = int(env_value)
                except ValueError:
                    value = None

        if value is None or value <= 0:
            return None
        return value

    def _apply_text_limit_to_file(self, texts_path: Path, limit: int) -> int:
        """Trim extracted JSON to first N entries, preserving file format."""
        data = json.loads(texts_path.read_text(encoding="utf-8"))

        if "entries" in data and isinstance(data["entries"], list):
            original_count = len(data["entries"])
            data["entries"] = data["entries"][:limit]
            texts_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return original_count

        # Already in converted format: flatten in stable order, then rebuild.
        converted = convert_format(data)
        flattened: list[dict] = []
        for table in converted.get("tables", []):
            flattened.extend(table.get("entries", []))
        flattened.extend(converted.get("free_texts", []))

        original_count = len(flattened)
        limited = flattened[:limit]
        limited_data = convert_format({"entries": limited})
        texts_path.write_text(json.dumps(limited_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return original_count

    def _save_translation_snapshot(self, data: dict, output_path: Path) -> None:
        """Persist current translation state so work survives early stop/restart."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(output_path)

    def translate_texts(
        self, texts_path: Path, output_path: Path
    ) -> Path:
        """Translate extracted texts JSON with parallel workers."""
        self._check_stop()
        base_path = output_path if output_path.exists() else texts_path
        data = json.loads(base_path.read_text(encoding="utf-8"))
        data = convert_format(data)

        # Phase 1: local/glossary table translation only.
        # This gives immediate visible progress before any LLM waits.
        pending_table_llm: list[tuple[dict, list[dict]]] = []
        for table in data["tables"]:
            self._check_stop()
            unresolved_entries = [
                entry for entry in table.get("entries", [])
                if not _has_meaningful_translation(entry)
            ]
            # On resume, skip fully translated table groups entirely.
            if not unresolved_entries:
                continue

            needs_llm = self._translate_table(
                table,
                run_llm=False,
                entries=unresolved_entries,
            )
            if needs_llm:
                pending_table_llm.append((table, needs_llm))
            # Persist progress after each table, even when later tables block
            # on LLM retries, so review pane and resume state stay up to date.
            self._save_translation_snapshot(data, output_path)

        # Phase 2: LLM fallback only for unresolved table entries.
        for table, needs_llm in pending_table_llm:
            self._check_stop()
            category = table.get("category", "unknown")
            self._log("info", f"Table {category}: running LLM fallback for {len(needs_llm)} entries")
            self._translate_table_llm_batch(needs_llm)
            self._inject_dynamic_terms(table)
            self._save_translation_snapshot(data, output_path)

        # Translate free texts in parallel batches
        free_texts = [entry for entry in data["free_texts"] if not _has_meaningful_translation(entry)]
        self._log(
            "info",
            (
                f"Translatable payload: {len(data['tables'])} table groups, "
                f"{len(free_texts)} pending free-text entries"
            ),
        )

        batches = [
            free_texts[i : i + self.config.batch_size]
            for i in range(0, len(free_texts), self.config.batch_size)
        ]
        total = len(batches)
        self._log("info", Messages.BATCH_PROGRESS.format(
            total=total, workers=self.config.max_workers
        ))
        if total == 0:
            self._log(
                "warning",
                "No free-text batches to process. This usually means the extraction subset contains only table entries.",
            )

        done_count = 0

        def process_batch(idx_batch):
            idx, batch = idx_batch
            self._translate_free_batch(batch)
            return idx, batch

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(process_batch, (i, b)): i
                for i, b in enumerate(batches)
            }
            for future in as_completed(futures):
                try:
                    self._check_stop()
                    idx, batch = future.result()
                except TranslationStoppedError:
                    self._save_translation_snapshot(data, output_path)
                    for pending in futures:
                        pending.cancel()
                    raise

                done_count += 1
                self._log("info", Messages.BATCH_COMPLETE.format(
                    current=done_count, total=total, batch_id=idx + 1
                ))
                sample = next((e for e in batch if e.get("translated")), None)
                if sample:
                    print(f"  e.g. {sample['original']!r} → {sample['translated']!r}")
                self.callbacks.on_progress("translate", done_count, total,
                    f"Batch {idx + 1} completed")

                # Save completed batch progress continuously for resume/stop.
                self._save_translation_snapshot(data, output_path)

        self._save_translation_snapshot(data, output_path)
        return output_path

    def _inject_dynamic_terms(self, table: dict) -> None:
        """Inject translated map/pokemon names into glossary for later context."""
        category = table.get("category", "")
        if category not in ("map_names", "pokemon_names"):
            return

        for entry in table.get("entries", []):
            original = entry.get("original", "").strip('"')
            translated = entry.get("translated", "")
            if translated and translated != original:
                self.glossary.add_term(original, translated, "dynamic")

    def _translate_table(
        self,
        table: dict,
        run_llm: bool = True,
        entries: list[dict] | None = None,
    ) -> list[dict]:
        """Translate a table's entries using glossary first, optional LLM fallback."""
        self._check_stop()
        category = table["category"]
        target_entries = entries if entries is not None else table["entries"]
        needs_llm: list[dict] = []  # entries deferred to batch LLM call
        local_count = 0
        encode_fallback_count = 0
        glossary_miss_count = 0

        for entry in target_entries:
            if _has_meaningful_translation(entry):
                continue

            original = entry["original"].strip('"')
            # Check term overrides (all games, Chinese only)
            if self.config.target_lang == "zh-Hans" and original in _TERM_OVERRIDES:
                entry["translated"] = _TERM_OVERRIDES[original]
                continue
            # Check manual overrides
            if (category == "trainer_classes" and
                self.config.target_lang == "zh-Hans" and
                original in _TRAINER_CLASS_OVERRIDES):
                entry["translated"] = _TRAINER_CLASS_OVERRIDES[original]
                continue
            # Try glossary lookup
            zh = self.glossary.lookup(original)
            if zh:
                # Sanitize glossary output for target language/PCS constraints
                # before deciding to fall back to LLM.
                candidate = self.charmap._sanitize(zh)
                ok, bad = self.charmap.can_encode(candidate)
                if ok:
                    entry["translated"] = candidate
                    local_count += 1
                    continue
                # Glossary match exists but can't be encoded — treat as no match
                encode_fallback_count += 1
                zh = None

            glossary_miss_count += 1

            # No glossary match: always defer to LLM
            # (the LLM batch filters out pure control codes / garbage automatically)
            needs_llm.append(entry)

        # Batch translate all deferred LLM entries
        if run_llm and needs_llm:
            self._log(
                "info",
                (
                    f"Table {category}: local={local_count}, "
                    f"llm_pending={len(needs_llm)}, encode_fallback={encode_fallback_count}, "
                    f"glossary_miss={glossary_miss_count}"
                ),
            )
            self._translate_table_llm_batch(needs_llm)

        self._log(
            "info",
            (
                f"Table {category}: local={local_count}, "
                f"llm={len(needs_llm) if run_llm else 0}, "
                f"llm_pending={len(needs_llm) if not run_llm else 0}, "
                f"encode_fallback={encode_fallback_count}, "
                f"glossary_miss={glossary_miss_count}"
            ),
        )
        self._inject_dynamic_terms(table)
        return needs_llm

    def _translate_table_llm_batch(self, entries: list[dict]):
        """Batch LLM translate table entries (descriptions, map names, battle text).

        Filters out entries that are pure control codes (nothing for LLM to
        translate), then sends the rest in batches of batch_size, same as
        free-text processing.
        """
        import re

        self._check_stop()

        # Separate: entries with real text vs pure control-code entries
        to_translate: list[tuple[dict, str, list]] = []  # (entry, protected, codes)
        for entry in entries:
            original = entry["original"].strip('"')
            protected, codes = protect(original)
            # Count actual alphabetic letters after stripping {C0}-style placeholders
            cleaned = re.sub(r"\{C\d+\}", "", protected)
            if sum(c.isalpha() for c in cleaned) >= 2:
                to_translate.append((entry, protected, codes))
            else:
                # Pure control codes – keep original, nothing to translate
                entry["translated"] = original

        if not to_translate:
            return

        # Batch translate in groups of batch_size (same as free texts)
        batch_size = self.config.batch_size
        for i in range(0, len(to_translate), batch_size):
            chunk = to_translate[i : i + batch_size]
            protected_list = [p for _, p, _ in chunk]
            all_text = " ".join(e["original"] for e, _, _ in chunk)
            glossary_ctx = self._format_glossary(all_text)

            try:
                results = self.translator.translate_batch(protected_list, glossary_ctx)
            except TranslationStoppedError:
                raise
            except LLMAuthenticationError:
                raise
            except Exception as e:
                print(f"[Table batch LLM failed: {e}, keeping originals]")
                for entry, _, _ in chunk:
                    entry["translated"] = entry["original"].strip('"')
                continue

            for (entry, _, codes), result in zip(chunk, results):
                clean = _strip_llm_newlines(result)
                entry["translated"] = restore(clean, codes)

    def _translate_free_batch(self, batch: list[dict]):
        """Translate a batch of free text entries via LLM."""
        self._check_stop()
        # Apply hardcoded overrides
        remaining = []
        for entry in batch:
            entry_id = entry.get("id", "")
            original = entry.get("original", "").strip('"')
            if (self.config.target_lang == "zh-Hans" and
                original in _TERM_OVERRIDES):
                entry["translated"] = _TERM_OVERRIDES[original]
            elif (self.config.game == "firered" and
                self.config.target_lang == "zh-Hans" and
                entry_id in _HARDCODED_TRANSLATIONS):
                entry["translated"] = _HARDCODED_TRANSLATIONS[entry_id]
            else:
                remaining.append(entry)

        if not remaining:
            return

        originals = [e["original"] for e in remaining]

        # Protect control codes
        protected_list = []
        codes_list = []
        for text in originals:
            protected, codes = protect(text)
            protected_list.append(protected)
            codes_list.append(codes)

        # Build glossary context
        all_text = " ".join(originals)
        glossary_ctx = self._format_glossary(all_text)

        # Translate
        try:
            results = self.translator.translate_batch(protected_list, glossary_ctx)
        except TranslationStoppedError:
            raise
        except LLMAuthenticationError:
            raise
        except Exception as e:
            print(f"[Batch failed after retries: {e}, keeping originals]")
            for entry in remaining:
                entry["translated"] = entry["original"]
            return

        # Restore and wrap
        for i, entry in enumerate(remaining):
            clean = _strip_llm_newlines(results[i])
            translated = restore(clean, codes_list[i])
            entry["translated"] = wrap_text(translated, target_lang=self.config.target_lang)

    def _format_glossary(self, text: str) -> str:
        terms = self.glossary.get_context_terms(text)
        if not terms:
            return ""
        return "\n".join(f"  {src} = {tgt}" for src, tgt in terms.items())

    def build_rom(
        self,
        original_rom: Path,
        translations_path: Path,
        output_path: Path,
    ) -> Path:
        """Build final translated ROM."""
        # Auto-detect game
        detected = detect_game(original_rom)
        if detected != "unknown":
            self.config.game = detected
            self._log("info", Messages.DETECTED_GAME.format(game=self.config.game))

        data = json.loads(translations_path.read_text(encoding="utf-8"))
        data = convert_format(data)

        writer = RomWriter(self.charmap, game=self.config.game,
                          target_lang=self.config.target_lang)

        # Load and expand ROM
        self._log("info", Messages.LOADING_ROM)
        rom = writer.load_rom(original_rom)
        rom = writer.expand_rom(rom)
        self._log("info", Messages.ROM_EXPANDED.format(size=len(rom) // (1024*1024)))

        # Apply font patch for CJK languages
        if is_cjk_language(self.config.target_lang):
            self._log("info", Messages.APPLYING_FONT_PATCH)
            temp_rom = output_path.parent / "temp_fontpatch.gba"
            writer.save_rom(rom, temp_rom)
            apply_font_patch(temp_rom, temp_rom, game=self.config.game)
            rom = writer.load_rom(temp_rom)
            temp_rom.unlink(missing_ok=True)
            self._log("info", Messages.FONT_PATCH_APPLIED)
        else:
            self._log("info", Messages.SKIPPING_FONT_PATCH.format(lang=self.config.target_lang))

        # Collect all entries
        all_entries = []
        for table in data["tables"]:
            for entry in table["entries"]:
                if "translated" in entry:
                    all_entries.append(entry)
        for entry in data["free_texts"]:
            if "translated" in entry:
                all_entries.append(entry)

        # Load manual entries (FireRed-specific, Chinese only).
        # Skip these when a test limit is active so build writes only the limited set.
        limit = self._get_effective_text_limit()
        if self.config.game == "firered" and limit is None and self.config.target_lang == "zh-Hans":
            manual_path = Path(__file__).parent.parent / "manual_entries.json"
            if manual_path.exists():
                manual = json.loads(manual_path.read_text(encoding="utf-8"))
                all_entries.extend(manual)
                self._log("info", Messages.ADDED_MANUAL_ENTRIES.format(count=len(manual)))

        # Inject texts
        self._log("info", Messages.INJECTING_TEXTS.format(count=len(all_entries)))
        rom, stats = writer.inject_texts(rom, all_entries)
        self._log("info", Messages.INJECTION_STATS.format(
            in_place=stats['in_place'],
            relocated=stats['relocated'],
            skipped=stats['skipped'],
            partial_ptr=stats.get('skipped_partial_ptrs', 0),
            unsafe_ptr=stats.get('unsafe_ptrs', 0)
        ))

        # Save
        writer.save_rom(rom, output_path)
        self._log("info", Messages.SAVED_ROM.format(path=output_path))
        return output_path

    @staticmethod
    def find_meowth_bridge() -> Path:
        """Locate the MeowthBridge executable."""
        from ..binaries import find_meowth_bridge
        return find_meowth_bridge()

    @staticmethod
    def extract_texts(rom_path: Path, output_path: Path) -> Path:
        """Extract texts from ROM using MeowthBridge."""
        import os
        import shutil as _shutil
        from ..resource_path import get_resource_path

        def _resolve_resources_dir() -> Path | None:
            """Locate HexManiac resource files for MeowthBridge.

            Expected content includes hma.py and various reference files.
            """
            candidates = [
                get_resource_path("resources"),
                get_resource_path("HexManiacAdvance/src/HexManiac.Core/Models/Code"),
                Path(__file__).resolve().parents[1] / "binaries" / "macos" / "Models" / "Code",
                Path(__file__).resolve().parents[1] / "binaries" / "windows" / "Models" / "Code",
            ]
            for candidate in candidates:
                if candidate.exists() and (candidate / "hma.py").exists():
                    return candidate
            return None

        exe = TranslationEngine.find_meowth_bridge()
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rom_abs = rom_path.resolve()

        # Use output_path.parent (the work dir) as MeowthBridge's CWD.
        # This is always a writable directory (e.g. ~/Library/Caches/Meowth/work).
        cwd = output_path.parent

        # MeowthBridge (via HMA) needs resources/ to exist in its CWD.
        # Find the actual resources directory and symlink/copy it into cwd.
        resources_src = _resolve_resources_dir()
        resources_dst = cwd / "resources"
        if resources_src and not resources_dst.exists():
            try:
                os.symlink(resources_src, resources_dst)
            except (OSError, NotImplementedError):
                _shutil.copytree(str(resources_src), str(resources_dst))
        if not resources_dst.exists():
            raise RuntimeError(
                "HexManiac resources not found. Expected hma.py in one of: "
                "resources/, HexManiacAdvance/src/HexManiac.Core/Models/Code, or bundled binaries Models/Code."
            )

        result = subprocess.run(
            [str(exe), "extract", str(rom_abs)],
            capture_output=True, text=True,
            cwd=str(cwd),
        )
        if result.returncode != 0:
            raise RuntimeError(
                Messages.MEOWTH_BRIDGE_FAILED.format(
                    code=result.returncode, stderr=result.stderr
                )
            )

        # MeowthBridge writes output to <cwd>/work/text.json
        hardcoded = cwd / "work" / "text.json"
        if hardcoded.exists():
            _shutil.move(str(hardcoded), str(output_path))
        if not output_path.exists():
            raise RuntimeError(Messages.MEOWTH_BRIDGE_NO_OUTPUT.format(path=output_path))

        _postprocess_fd_macros(output_path)
        return output_path

    def run_full(
        self,
        rom_path: Path | None = None,
        output_dir: Path | None = None,
        work_dir: Path | None = None,
    ) -> Path:
        """Run the full translation pipeline: extract -> translate -> build."""
        rom_path, translated_path, output_path = self.run_extract_translate(
            rom_path=rom_path,
            output_dir=output_dir,
            work_dir=work_dir,
        )
        self.build_from_translations(
            rom_path=rom_path,
            translations_path=translated_path,
            output_path=output_path,
        )
        return output_path

    def run_extract_translate(
        self,
        rom_path: Path | None = None,
        output_dir: Path | None = None,
        work_dir: Path | None = None,
    ) -> tuple[Path, Path, Path]:
        """Run only extract + translate stages.

        Returns:
            Tuple of (rom_path, translated_texts_path, output_rom_path).
        """
        self._check_stop()
        rom_path, _, _, texts_path, translated_path, output_path = self._resolve_run_context(
            rom_path=rom_path,
            output_dir=output_dir,
            work_dir=work_dir,
        )

        # Stage 1: Extract
        self.callbacks.on_stage_change("extract", "started")
        self._log("info", Messages.STAGE_EXTRACT)
        bridge_path = self.find_meowth_bridge()
        self._log("info", f"MeowthBridge executable: {bridge_path}")
        self._log("info", f"Starting extraction for ROM: {rom_path}")
        self.extract_texts(rom_path, texts_path)
        self._check_stop()
        self._log("info", f"Extraction finished: {texts_path}")
        limit = self._get_effective_text_limit()
        if limit is not None:
            original_count = self._apply_text_limit_to_file(texts_path, limit)
            self._log("info", f"[TESTING] Extracted {min(limit, original_count)} / {original_count} texts")
        self.callbacks.on_stage_change("extract", "completed")

        # Stage 2: Translate
        self.callbacks.on_stage_change("translate", "started")
        self._log("info", Messages.STAGE_TRANSLATE)
        self.translate_texts(texts_path, translated_path)
        self._check_stop()
        self.callbacks.on_stage_change("translate", "completed")

        return rom_path, translated_path, output_path

    def build_from_translations(
        self,
        rom_path: Path,
        translations_path: Path,
        output_path: Path,
    ) -> Path:
        """Run build stage from an existing translated texts JSON file."""
        self.callbacks.on_stage_change("build", "started")
        self._log("info", Messages.STAGE_BUILD)
        self.build_rom(rom_path, translations_path, output_path)
        self.callbacks.on_stage_change("build", "completed")
        self._log("info", Messages.COMPLETE.format(output=output_path))
        return output_path

    def _resolve_run_context(
        self,
        rom_path: Path | None = None,
        output_dir: Path | None = None,
        work_dir: Path | None = None,
    ) -> tuple[Path, Path, Path, Path, Path, Path]:
        """Resolve and validate input/output paths for a translation run."""
        rom_path = rom_path or self.config.rom_path
        output_dir = output_dir or self.config.output_dir
        work_dir = work_dir or self.config.work_dir

        if rom_path is None:
            raise ValueError("rom_path must be provided")

        rom_path = Path(rom_path).resolve()
        output_dir = Path(output_dir).resolve()
        work_dir = Path(work_dir).resolve()

        # Auto-detect game
        detected = detect_game(rom_path)
        if detected != "unknown":
            self.config.game = detected
            self._log("info", Messages.DETECTED_GAME.format(game=self.config.game))
        else:
            self._log("warning", Messages.GAME_DETECTION_FAILED.format(game=self.config.game))

        # Compatibility check 1: reject Ruby/Sapphire
        if self.config.game in ("ruby", "sapphire"):
            raise RuntimeError(Messages.ROM_UNSUPPORTED_GAME.format(game=self.config.game))

        # Compatibility check 2: reject decomp hacks when targeting CJK
        if is_cjk_language(self.config.target_lang) and is_decomp_rom(rom_path, self.config.game):
            with open(rom_path, "rb") as _f:
                _f.seek(0xAC)
                _raw_code = _f.read(4).decode("ascii", errors="replace")
            raise RuntimeError(Messages.ROM_DECOMP_HACK.format(code=_raw_code))

        original_name = rom_path.stem
        lang_code = self.config.target_lang.split("-")[0]

        texts_path = work_dir / "texts.json"
        translated_path = work_dir / "texts_translated.json"
        output_path = output_dir / f"{original_name}_{lang_code}.gba"
        return rom_path, output_dir, work_dir, texts_path, translated_path, output_path
