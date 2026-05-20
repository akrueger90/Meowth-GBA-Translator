"""Main CustomTkinter GUI application."""

import json
import platform
import queue
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import Canvas
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from ..core import TranslationEngine
from .callbacks import GUICallbacks
from .components import ConfigForm, LogView, ProgressView, ReviewDialog


def _fix_mousewheel(scrollable_frame: ctk.CTkScrollableFrame):
    """Fix trackpad/mousewheel scrolling on macOS for CTkScrollableFrame."""
    # Access the internal canvas
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
        self._ui_queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = queue.Queue()
        self.debug_log_path = Path.home() / ".meowth" / "logs" / "gui-debug.log"
        self.debug_log_path.parent.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.config_form.load_state()
        self.after(16, self._process_ui_queue)
        self._debug("GUI initialized")

    def call_on_main_thread(self, func, *args, **kwargs):
        """Schedule a callable to run on the Tk main thread."""
        self._ui_queue.put((func, args, kwargs))

    def _process_ui_queue(self):
        """Drain cross-thread UI tasks from worker threads on the Tk main thread."""
        while True:
            try:
                func, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            try:
                func(*args, **kwargs)
            except Exception as exc:
                self._debug(f"UI queue task failed: {exc}")
                self._debug(traceback.format_exc())

        self.after(16, self._process_ui_queue)

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
            self.engine = TranslationEngine(config, callbacks)
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
                candidates = self._load_review_candidates(translated_path)
                if not candidates:
                    self.log_view.append("info", "No suspect entries found. Continuing to build.")
                    result["action"] = "continue"
                    done.set()
                    return

                self.log_view.append(
                    "info",
                    f"Review step: {len(candidates)} suspect entries available for retry. Click Continue Build to finish.",
                )

                def _on_action(action: str, selected_keys: list[str]):
                    result["action"] = action
                    result["selected_keys"] = selected_keys
                    done.set()

                dialog = ReviewDialog(self, candidates, _on_action)
                dialog.focus_force()
            except Exception as exc:
                self._debug(f"Review dialog failed: {exc}")
                self._debug(traceback.format_exc())
                result["action"] = "cancel"
                done.set()

        self.call_on_main_thread(_show_dialog)
        done.wait()
        return result

    @staticmethod
    def _is_suspect_entry(entry: dict) -> bool:
        """Return True when an entry looks untranslated and worth retrying."""
        original = str(entry.get("original", "")).strip().strip('"')
        translated = str(entry.get("translated", "")).strip().strip('"')
        if not translated:
            return True
        return translated == original

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

    def _load_review_candidates(self, translated_path: Path) -> list[dict[str, str]]:
        """Load untranslated/suspect entries from translated JSON for review."""
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        indexed = self._index_translation_entries(data)

        candidates: list[dict[str, str]] = []
        for item in indexed.values():
            entry = item["entry"]
            if not self._is_suspect_entry(entry):
                continue
            candidates.append(
                {
                    "key": item["key"],
                    "entry_id": str(entry.get("id", item["key"])),
                    "category": str(item.get("category", "")),
                    "original": str(entry.get("original", "")),
                    "translated": str(entry.get("translated", "")),
                }
            )

        return candidates

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

    def _stop_translation(self):
        """Stop the translation process."""
        if self.engine and self.is_running:
            self.log_view.append("warning", "Stopping translation...")
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
