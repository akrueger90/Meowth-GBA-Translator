"""Main CustomTkinter GUI application."""

import json
import os
import platform
import queue
import shutil
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import Canvas
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from ..core import TranslationEngine
from ..core.engine import convert_format
from ..translator import TranslationStoppedError
from .callbacks import GUICallbacks
from .components import ConfigForm, LogView, ProgressView, ReviewDialog


_APP_NAME = "Meowth Translator"
_SETTINGS_PANEL_WIDTH = 640
_UI_QUEUE_MAX_TASKS_PER_TICK = 12
_UI_QUEUE_FAST_POLL_MS = 1
_UI_QUEUE_IDLE_POLL_MS = 16
_UI_QUEUE_BACKPRESSURE_THRESHOLD = 240
_DROPPABLE_UI_FUNCS = {"append", "append_many", "update"}


def _setup_macos_app_name() -> None:
    """Best-effort: set the macOS menu-bar / dock process name via pyobjc."""
    if platform.system() != "Darwin":
        return


def _fix_mousewheel(scrollable_frame: ctk.CTkScrollableFrame):
    """Fix trackpad/mousewheel scrolling on macOS for CTkScrollableFrame."""
    canvas = None
    for child in scrollable_frame.winfo_children():
        if isinstance(child, Canvas):
            canvas = child
            break
    if not canvas:
        return

    def _on_mousewheel(event):
        if platform.system() == "Darwin":
            canvas.yview_scroll(-1 * event.delta, "units")
        else:
            canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _bind_wheel(event):
        if platform.system() == "Darwin":
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        else:
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _unbind_wheel(event):
        canvas.unbind_all("<MouseWheel>")

    canvas.bind("<Enter>", _bind_wheel)
    canvas.bind("<Leave>", _unbind_wheel)


class MeowthGUI(ctk.CTk):
    """Main application window for Meowth GBA Translator."""

    def __init__(self):
        """Initialize the GUI application."""
        super().__init__()

        self.title("Meowth GBA Translator")
        self.geometry("860x780")
        self.minsize(700, 600)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.engine = None
        self.translation_thread = None
        self.is_running = False
        self._stop_event = threading.Event()
        self._engine_config_signature: tuple[Any, ...] | None = None
        self._active_run_dir: Path | None = None
        self._last_review_refresh_file: Path | None = None
        self._last_review_refresh_mtime: float | None = None
        self._ui_queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = queue.Queue()
        self.debug_log_path = Path.home() / ".meowth" / "logs" / "gui-debug.log"
        self.debug_log_path.parent.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.config_form.load_state()
        self._load_last_run_into_review_panel()
        self.after(_UI_QUEUE_IDLE_POLL_MS, self._process_ui_queue)
        self.after(1200, self._auto_refresh_review_panel)
        self._debug("GUI initialized")

    def _panel_action(self, action: str, payload: dict[str, Any]):
        if action == "start_translation":
            self._start_translation()
            return

        if action == "stop_translation":
            self._stop_translation()
            return

        if self.is_running:
            self.log_view.append("warning", "Review actions are disabled while translation is still running/stopping.")
            return

        run_dir = self._resolve_review_run()
        if not run_dir:
            self.log_view.append("warning", "No active/resumable run for review actions.")
            return

        translated_path = self._ensure_translated_file(run_dir)
        if not translated_path.exists():
            self.log_view.append("warning", "No translated file available yet.")
            return

        self._active_run_dir = run_dir
        self._ensure_engine_for_review()

        if action == "refresh":
            self._refresh_review_panel(silent=False)
            return

        if action == "llm_selected":
            selected_keys = payload.get("selected_keys", []) if isinstance(payload, dict) else []
            if selected_keys:
                def _run_llm():
                    try:
                        self._ensure_engine_for_review(force_recreate=True)
                        retried, improved = self._retry_selected_entries(translated_path, selected_keys)
                        self.call_on_main_thread(
                            self.log_view.append,
                            "info",
                            f"LLM translated {retried} selected entries ({improved} improved).",
                        )
                        self.call_on_main_thread(self._refresh_review_panel, False)
                    except TranslationStoppedError:
                        self.call_on_main_thread(
                            self.log_view.append, "warning", "Review LLM action was cancelled."
                        )
                    except Exception as exc:
                        self.call_on_main_thread(
                            self.log_view.append, "error", f"LLM retry failed: {exc}"
                        )

                threading.Thread(target=_run_llm, daemon=True).start()
            return

        if action == "manual_save":
            key = payload.get("key") if isinstance(payload, dict) else None
            translated = payload.get("translated") if isinstance(payload, dict) else ""
            if isinstance(key, str) and self._apply_manual_translation(translated_path, key, str(translated)):
                self.log_view.append("info", f"Saved manual translation for {key}.")
                self._refresh_review_panel(silent=False)
            return

        if action == "resume_from_row":
            start_key = payload.get("start_key") if isinstance(payload, dict) else None
            if isinstance(start_key, str) and start_key:
                def _run_resume():
                    try:
                        self._ensure_engine_for_review(force_recreate=True)
                        processed = self._resume_translation_from_key(translated_path, start_key)
                        self.call_on_main_thread(
                            self.log_view.append,
                            "info",
                            f"Resumed translation from {start_key}: {processed} entries processed.",
                        )
                        self.call_on_main_thread(self._refresh_review_panel, False)
                    except TranslationStoppedError:
                        self.call_on_main_thread(
                            self.log_view.append, "warning", "Resume action was cancelled."
                        )
                    except Exception as exc:
                        self.call_on_main_thread(
                            self.log_view.append, "error", f"Resume failed: {exc}"
                        )

                threading.Thread(target=_run_resume, daemon=True).start()
            return

    def _auto_refresh_review_panel(self):
        """Keep embedded review panel in sync while translation is active."""
        try:
            if self.is_running:
                # Full review-table rebuilds are expensive for large runs and can
                # monopolize the Tk thread while translation is active.
                # Keep UI responsive and refresh explicitly on completion/manual action.
                return
        except Exception as exc:
            self._debug(f"Auto refresh review failed: {exc}")
        finally:
            self.after(1200, self._auto_refresh_review_panel)

    def _runs_root(self, work_dir: Path) -> Path:
        return work_dir / "runs"

    def _archive_root(self, work_dir: Path) -> Path:
        return work_dir / "archive"

    def _run_source_rom(self, run_dir: Path) -> Path:
        return run_dir / "source_rom.gba"

    def _config_signature(self, config) -> tuple[Any, ...]:
        """Build a comparable signature for config-sensitive engine behavior."""
        return (
            config.source_lang,
            config.target_lang,
            config.provider,
            config.api_base,
            config.api_key_env,
            config.api_key,
            config.model,
            config.batch_size,
            config.max_workers,
            str(config.work_dir),
        )

    def _run_texts(self, run_dir: Path) -> Path:
        return run_dir / "texts.json"

    def _run_translated(self, run_dir: Path) -> Path:
        return run_dir / "texts_translated.json"

    def _ensure_translated_file(self, run_dir: Path) -> Path:
        """Return the path to the translated texts file for a run directory."""
        return self._run_translated(run_dir)

    def _run_config(self, run_dir: Path) -> Path:
        return run_dir / "run_config.json"

    def _count_pending_entries(self, translated_path: Path) -> tuple[int, int]:
        if not translated_path.exists():
            return 0, 0
        try:
            data = json.loads(translated_path.read_text(encoding="utf-8"))
        except Exception:
            return 0, 0

        total = 0
        pending = 0

        for table in data.get("tables", []):
            for entry in table.get("entries", []):
                total += 1
                if not str(entry.get("translated", "")).strip():
                    pending += 1

        for entry in data.get("free_texts", []):
            total += 1
            if not str(entry.get("translated", "")).strip():
                pending += 1

        return total, pending

    def _find_resumable_runs(self, work_dir: Path) -> list[Path]:
        runs: list[Path] = []

        candidate_roots: list[Path] = []
        runs_root = self._runs_root(work_dir)
        if runs_root.exists():
            candidate_roots.append(runs_root)
        if work_dir.exists():
            candidate_roots.append(work_dir)

        for root in candidate_roots:
            for candidate in root.iterdir():
                if not candidate.is_dir():
                    continue
                if candidate.name in {"runs", "archive", "cache"}:
                    continue
                if not self._run_source_rom(candidate).exists():
                    continue
                if not self._run_texts(candidate).exists():
                    continue
                runs.append(candidate)

        runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return runs

    def _log_resumable_hint(self) -> None:
        state = self.config_form.get_state()
        output_dir = state.get("output_dir") if isinstance(state.get("output_dir"), str) else ""
        if not output_dir:
            return
        work_dir = Path(output_dir).expanduser() / "work"
        resumables = self._find_resumable_runs(work_dir)
        if resumables:
            latest = resumables[0]
            self._debug(f"Found {len(resumables)} resumable run(s), latest={latest.name}")

    def _load_last_run_into_review_panel(self) -> None:
        """Auto-load latest resumable run into review panel on app launch."""
        self._log_resumable_hint()

        run_dir = self._resolve_review_run()
        if not run_dir:
            return

        self._active_run_dir = run_dir
        self._refresh_review_panel(silent=True)
        self.log_view.append("info", f"Loaded last run for review: {run_dir.name}")

    def _ask_resume_or_new(self, config) -> tuple[str, Path | None]:
        resumables = self._find_resumable_runs(config.work_dir)
        if not resumables:
            return "new", None

        latest = resumables[0]
        translated_path = self._run_translated(latest)
        total, pending = self._count_pending_entries(translated_path)
        pending_msg = (
            f"Pending entries: {pending}/{total}." if total > 0 else "No translated file yet."
        )
        if len(resumables) > 1:
            pending_msg = f"{pending_msg} {len(resumables) - 1} other resumable run(s) found."

        choice = messagebox.askyesnocancel(
            "Resume Previous Translation",
            (
                f"Found resumable translation run:\n\n"
                f"{latest.name}\n\n"
                f"{pending_msg}\n\n"
                f"Yes = Resume latest run\n"
                f"No = Start new run\n"
                f"Cancel = Abort"
            ),
        )

        if choice is None:
            return "cancel", None
        if choice:
            return "resume", latest
        return "new", None

    def _create_new_run_dir(self, work_dir: Path, rom_path: Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = rom_path.stem.replace(" ", "_")
        run_dir = self._runs_root(work_dir) / f"{slug}__{stamp}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def _prepare_new_run_files(self, run_dir: Path, config) -> None:
        source_rom = self._run_source_rom(run_dir)
        texts_path = self._run_texts(run_dir)

        shutil.copy2(config.rom_path, source_rom)
        self._debug(f"Copied source ROM to run folder: {source_rom}")
        self.call_on_main_thread(self.log_view.append, "info", f"Run folder: {run_dir}")
        self.call_on_main_thread(self.log_view.append, "info", "Extracting ROM text into run folder...")
        self.engine.extract_texts(source_rom, texts_path)

        run_meta = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "original_rom": str(config.rom_path),
            "source_rom": str(source_rom),
            "texts": str(texts_path),
            "translated": str(self._run_translated(run_dir)),
            "source_lang": config.source_lang,
            "target_lang": config.target_lang,
            "provider": config.provider,
            "model": config.model,
        }
        self._run_config(run_dir).write_text(
            json.dumps(run_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _archive_run_dir(self, run_dir: Path, work_dir: Path) -> Path:
        archive_root = self._archive_root(work_dir)
        archive_root.mkdir(parents=True, exist_ok=True)

        destination = archive_root / run_dir.name
        if destination.exists():
            destination = archive_root / f"{run_dir.name}__{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        shutil.move(str(run_dir), str(destination))
        return destination

    def call_on_main_thread(self, func, *args, **kwargs):
        """Schedule a callable to run on the Tk main thread."""
        try:
            func_name = getattr(func, "__name__", "")
            if (
                func_name in _DROPPABLE_UI_FUNCS
                and self._ui_queue.qsize() >= _UI_QUEUE_BACKPRESSURE_THRESHOLD
            ):
                return
        except Exception:
            pass
        self._ui_queue.put((func, args, kwargs))

    def _process_ui_queue(self):
        """Drain cross-thread UI tasks from worker threads on the Tk main thread."""
        processed = 0
        while processed < _UI_QUEUE_MAX_TASKS_PER_TICK:
            try:
                func, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            try:
                func(*args, **kwargs)
            except Exception as exc:
                self._debug(f"UI queue task failed: {exc}")
                self._debug(traceback.format_exc())
            finally:
                processed += 1

        # Always yield back to Tk so buttons/events stay responsive even
        # while background workers are producing many updates.
        if processed >= _UI_QUEUE_MAX_TASKS_PER_TICK:
            self.after(_UI_QUEUE_FAST_POLL_MS, self._process_ui_queue)
        else:
            self.after(_UI_QUEUE_IDLE_POLL_MS, self._process_ui_queue)

    def _debug(self, message: str):
        """Write diagnostics for thread/debug-session analysis."""
        try:
            thread_name = threading.current_thread().name
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            line = f"[{ts}][{thread_name}] {message}\n"
            with self.debug_log_path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
            print(line, end="")
        except Exception:
            # Never let diagnostics break the GUI flow.
            pass

    def _on_start_button_mouse_down(self, _event):
        """Capture physical click events even if command callback is skipped."""
        try:
            state = self.start_button.cget("state")
        except Exception:
            state = "unknown"
        self._debug(f"Start button mouse down (state={state})")

    def _build_ui(self):
        """Build the user interface."""
        # --- Bottom buttons (pack FIRST so they always show) ---
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=24, pady=(0, 20))

        self.start_button = ctk.CTkButton(
            bottom,
            text="Start Translation",
            command=self._start_translation,
            height=44,
            font=("", 15, "bold"),
            corner_radius=8,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.start_button.bind("<Button-1>", self._on_start_button_mouse_down)
        self.start_button.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.stop_button = ctk.CTkButton(
            bottom,
            text="Stop",
            command=self._stop_translation,
            height=44,
            font=("", 14),
            corner_radius=8,
            fg_color="#4b5563",
            hover_color="#6b7280",
            state="disabled",
            width=100,
        )
        self.stop_button.pack(side="right")

        # --- Scrollable main content ---
        main = ctk.CTkScrollableFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=(20, 12))
        _fix_mousewheel(main)

        # Title
        ctk.CTkLabel(
            main, text="Meowth GBA Translator",
            font=("", 22, "bold"),
        ).pack(pady=(0, 12))

        # Config form
        self.config_form = ConfigForm(main)
        self.config_form.pack(fill="x", pady=(0, 8))

        # Progress view
        self.progress_view = ProgressView(main)
        self.progress_view.pack(fill="x", pady=(0, 8))

        # Log view
        self.log_view = LogView(main)
        self.log_view.pack(fill="x")

    def _on_window_close(self):
        """Persist form input before the window closes."""
        try:
            self.config_form.save_state()
        except Exception as exc:
            self._debug(f"Failed to save form state on close: {exc}")
        self.destroy()

    def _start_translation(self):
        """Start the translation process."""
        self._debug("Start button clicked")
        is_valid, error_message = self.config_form.validate()
        if not is_valid:
            self._debug(f"Validation failed: {error_message}")
            self.log_view.append("error", error_message)
            messagebox.showerror("Invalid Configuration", error_message)
            return

        config = self.config_form.get_config()
        self.config_form.save_state()
        self._debug(
            "Config prepared: "
            f"rom={config.rom_path}, output={config.output_dir}, work={config.work_dir}, "
            f"provider={config.provider}, model={config.model}, batch={config.batch_size}, workers={config.max_workers}"
        )

        self.progress_view.reset()
        self.log_view.append("info", "Starting translation...")
        self.log_view.append("info", f"Debug log: {self.debug_log_path}")

        self.start_button.configure(state="disabled", fg_color="#4b5563")
        self.stop_button.configure(state="normal", fg_color="#dc2626", hover_color="#b91c1c")
        self.is_running = True

        callbacks = GUICallbacks(self, self.progress_view, self.log_view)

        try:
            self._debug("Initializing TranslationEngine")
            self.engine = TranslationEngine(config, callbacks, stop_event=self._stop_event)
            self._engine_config_signature = self._config_signature(config)
            self._debug("TranslationEngine initialized successfully")
        except Exception as e:
            self._debug(f"Engine initialization failed: {e}")
            self._debug(traceback.format_exc())
            self.log_view.append("error", f"Failed to initialize: {e}")
            messagebox.showerror("Initialization Failed", str(e))
            self._reset_buttons()
            return

        self.translation_thread = threading.Thread(
            target=self._run_translation,
            args=(config,),
            daemon=True,
        )
        self.translation_thread.start()
        self._debug(
            f"Background thread started: name={self.translation_thread.name}, "
            f"ident={self.translation_thread.ident}, alive={self.translation_thread.is_alive()}"
        )
        self.after(400, self._check_translation_thread_started)

    def _check_translation_thread_started(self):
        """Sanity-check that the translation worker is running shortly after start."""
        if not self.translation_thread:
            self._debug("Thread check: no translation thread object")
            self.log_view.append("error", "Debug: translation thread was not created")
            return

        alive = self.translation_thread.is_alive()
        self._debug(f"Thread check after 400ms: alive={alive}")
        if not alive and self.is_running:
            self.log_view.append("error", "Debug: translation thread exited immediately; see debug log")

    def _run_translation(self, config):
        """Run translation in background thread."""
        try:
            self._debug("Entered _run_translation")
            rom_path, translated_path, output_path = self.engine.run_extract_translate(
                rom_path=config.rom_path,
                output_dir=config.output_dir,
                work_dir=config.work_dir,
            )

            while True:
                review_result = self._run_review_step(translated_path)
                action = review_result.get("action")
                selected_keys = review_result.get("selected_keys", [])

                if action == "continue":
                    break

                if action == "cancel":
                    raise RuntimeError("Translation cancelled during review")

                if action == "retry":
                    if not selected_keys:
                        self.call_on_main_thread(
                            self.log_view.append,
                            "warning",
                            "No entries selected for retry.",
                        )
                        continue
                    retried, improved = self._retry_selected_entries(translated_path, selected_keys)
                    self.call_on_main_thread(
                        self.log_view.append,
                        "info",
                        f"Retried {retried} entries ({improved} improved).",
                    )
                    continue

                raise RuntimeError(f"Unknown review action: {action}")

            self.engine.build_from_translations(
                rom_path=rom_path,
                translations_path=translated_path,
                output_path=output_path,
            )
            self._debug(f"Review/build flow completed successfully: output={output_path}")
            self.call_on_main_thread(self._on_translation_complete, output_path)
        except Exception as e:
            self._debug(f"review/build flow raised: {e}")
            self._debug(traceback.format_exc())
            self.call_on_main_thread(self._on_translation_error, e)

    def _run_review_step(self, translated_path: Path) -> dict[str, Any]:
        """Pause worker thread and run the review dialog on the main UI thread."""
        done = threading.Event()
        result: dict[str, Any] = {"action": "continue", "selected_keys": []}

        def _show_dialog():
            try:
                review_rows, suspect_count = self._load_review_candidates(translated_path)
                if suspect_count == 0:
                    self.log_view.append("info", "No suspect entries found. Continuing to build.")
                    result["action"] = "continue"
                    done.set()
                    return

                self.log_view.append(
                    "info",
                    f"Review step: {suspect_count} suspect entries highlighted across {len(review_rows)} rows. Click Continue Build to finish.",
                )

                def _on_action(action: str, selected_keys: list[str]):
                    result["action"] = action
                    result["selected_keys"] = selected_keys
                    done.set()

                dialog = ReviewDialog(self, review_rows, suspect_count, _on_action)
                dialog.focus_force()
            except Exception as exc:
                self._debug(f"Review dialog failed: {exc}")
                self._debug(traceback.format_exc())
                result["action"] = "cancel"
                done.set()

        self.call_on_main_thread(_show_dialog)
        done.wait()
        return result

    def _resolve_review_run(self) -> "Path | None":
        config = self.config_form.get_config()
        resumables = self._find_resumable_runs(config.work_dir)
        if not resumables:
            return None
        return resumables[0]

    def _ensure_engine_for_review(self, force_recreate: bool = False):
        config = self.config_form.get_config()
        config_signature = self._config_signature(config)

        if (
            not force_recreate
            and self.engine
            and not self._stop_event.is_set()
            and self._engine_config_signature == config_signature
        ):
            return

        callbacks = GUICallbacks(self, self.progress_view, self.log_view)
        self._stop_event = threading.Event()
        self.engine = TranslationEngine(config, callbacks, stop_event=self._stop_event)
        self._engine_config_signature = config_signature

    def _apply_manual_translation(self, translated_path: Path, key: str, translated: str) -> bool:
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        indexed = self._index_translation_entries(data)
        item = indexed.get(key)
        if not item:
            return False
        item["entry"]["translated"] = translated
        translated_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True

    def _resume_translation_from_key(self, translated_path: Path, start_key: str) -> int:
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        data = convert_format(data)
        indexed = self._index_translation_entries(data)
        ordered_keys = list(indexed.keys())
        if start_key not in indexed:
            return 0

        start_idx = ordered_keys.index(start_key)
        remaining_keys = ordered_keys[start_idx:]

        remaining_items: list[dict[str, Any]] = []
        for key in remaining_keys:
            item = indexed[key]
            entry = item["entry"]
            if str(entry.get("translated", "")).strip():
                continue
            remaining_items.append(item)

        processed = 0
        batch_size = max(1, int(getattr(self.engine.config, "batch_size", 30)))

        chunk: list[dict] = []
        chunk_source: str | None = None

        def flush_chunk() -> int:
            if not chunk or not chunk_source:
                return 0
            if chunk_source == "table":
                self.engine._translate_table_llm_batch(chunk)
            else:
                self.engine._translate_free_batch(chunk)
            count = len(chunk)
            chunk.clear()
            return count

        for item in remaining_items:
            source = str(item.get("source", "free"))
            entry = item["entry"]

            if chunk and (source != chunk_source or len(chunk) >= batch_size):
                processed += flush_chunk()

            if not chunk:
                chunk_source = source
            chunk.append(entry)

        processed += flush_chunk()

        translated_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return processed

    def _refresh_review_panel(self, silent: bool = True):
        run_dir = self._resolve_review_run()
        if not run_dir:
            return

        translated_path = self._ensure_translated_file(run_dir)
        if not translated_path.exists():
            if not silent:
                messagebox.showerror(
                    "Missing Files",
                    f"Could not find translation file in {run_dir}",
                )
            return

        try:
            review_rows, suspect_count = self._load_review_candidates(translated_path)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            if not silent:
                self.log_view.append("warning", f"Review refresh skipped: {exc}")
            return
        self._last_review_refresh_file = translated_path
        try:
            self._last_review_refresh_mtime = translated_path.stat().st_mtime
        except OSError:
            self._last_review_refresh_mtime = None

    def _is_suspect_entry(self, entry: dict) -> bool:
        """Return True when an entry looks untranslated and worth retrying."""
        original = str(entry.get("original", "")).strip().strip('"')
        translated = str(entry.get("translated", "")).strip().strip('"')
        if not translated:
            return True
        if translated != original:
            return False

        glossary = getattr(self.engine, "glossary", None)
        if glossary and glossary.matches_expected_translation(original, translated):
            return False

        return True

    def _index_translation_entries(self, data: dict) -> dict[str, dict[str, Any]]:
        """Build a stable key-index for translated entries."""
        indexed: dict[str, dict[str, Any]] = {}

        for table in data.get("tables", []):
            category = table.get("category", "")
            for idx, entry in enumerate(table.get("entries", [])):
                key = f"table:{category}:{idx}"
                indexed[key] = {
                    "key": key,
                    "source": "table",
                    "category": category,
                    "entry": entry,
                }

        for idx, entry in enumerate(data.get("free_texts", [])):
            key = f"free:{idx}"
            indexed[key] = {
                "key": key,
                "source": "free",
                "category": entry.get("category", "free_texts"),
                "entry": entry,
            }

        return indexed

    def _load_review_candidates(self, translated_path: Path) -> tuple[list[dict[str, str]], int]:
        """Load all translated entries for review and flag suspect ones."""
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        indexed = self._index_translation_entries(data)

        candidates: list[dict[str, str]] = []
        suspect_count = 0
        for item in indexed.values():
            entry = item["entry"]
            is_suspect = self._is_suspect_entry(entry)
            if is_suspect:
                suspect_count += 1
            candidates.append(
                {
                    "key": item["key"],
                    "entry_id": str(entry.get("id", item["key"])),
                    "category": str(item.get("category", "")),
                    "original": str(entry.get("original", "")),
                    "translated": str(entry.get("translated", "")),
                    "suspect": "true" if is_suspect else "false",
                }
            )

        return candidates, suspect_count

    def _retry_selected_entries(self, translated_path: Path, selected_keys: list[str]) -> tuple[int, int]:
        """Retry selected entries in-place using engine translation helpers."""
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        indexed = self._index_translation_entries(data)

        table_entries: list[dict] = []
        free_entries: list[dict] = []
        before_state: dict[str, str] = {}

        for key in selected_keys:
            item = indexed.get(key)
            if not item:
                continue
            entry = item["entry"]
            before_state[key] = str(entry.get("translated", ""))
            if item["source"] == "table":
                table_entries.append(entry)
            else:
                free_entries.append(entry)

        if table_entries:
            self.engine._translate_table_llm_batch(table_entries)
        if free_entries:
            self.engine._translate_free_batch(free_entries)

        improved = 0
        for key in before_state:
            item = indexed.get(key)
            if not item:
                continue
            entry = item["entry"]
            after_translated = str(entry.get("translated", ""))
            if after_translated != before_state[key] and not self._is_suspect_entry(entry):
                improved += 1

        translated_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return len(before_state), improved

    def _on_translation_complete(self, output_path: Path):
        """Handle translation completion."""
        self._debug(f"UI completion callback invoked: output={output_path}")
        self.log_view.append("info", f"Translation completed! Output: {output_path}")
        self._reset_buttons()

    def _on_translation_error(self, error: Exception):
        """Handle translation error."""
        self._debug(f"UI error callback invoked: {error}")
        self.log_view.append("error", f"Translation failed: {error}")
        messagebox.showerror("Translation Failed", str(error))
        self._reset_buttons()

    def _on_translation_stopped(self):
        """Handle user-requested translation stop."""
        self.log_view.append("warning", "Translation stopped by user.")
        # Keep review actions usable after stop by clearing stale stop state.
        self.engine = None
        self._engine_config_signature = None
        self._stop_event = threading.Event()
        self._reset_buttons()


    def _stop_translation(self):
        """Stop the translation process."""
        if self.is_running:
            self.log_view.append("warning", "Stopping translation...")
            self._stop_event.set()
            if self.engine:
                self.engine.request_stop()
            self.is_running = False
            self._reset_buttons()

    def _reset_buttons(self):
        """Reset button states."""
        self.start_button.configure(state="normal", fg_color="#2563eb")
        self.stop_button.configure(state="disabled", fg_color="#4b5563")
        self.is_running = False


def main():
    """Entry point for the GUI application."""
    app = MeowthGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
