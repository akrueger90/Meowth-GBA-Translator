"""Main CustomTkinter GUI application."""

import json
import platform
import queue
import shutil
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from ..core import TranslationEngine
from ..core.engine import convert_format
from ..translator import TranslationStoppedError
from .callbacks import GUICallbacks
from .components import ConfigForm, LogView, ReviewPanel


_APP_NAME = "Meowth Translator"
_SETTINGS_PANEL_WIDTH = 520


def _setup_macos_app_name() -> None:
    """Best-effort: set the macOS menu-bar / dock process name via pyobjc."""
    if platform.system() != "Darwin":
        return
    try:
        from Foundation import NSBundle  # type: ignore[import]
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = _APP_NAME
            info["CFBundleDisplayName"] = _APP_NAME
    except Exception:
        pass


class MeowthGUI(ctk.CTk):
    """Main application window for Meowth GBA Translator."""

    def __init__(self):
        """Initialize the GUI application."""
        _setup_macos_app_name()
        super().__init__()

        self.title(_APP_NAME)
        self.geometry("1600x920")
        self.minsize(1280, 700)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.engine = None
        self.translation_thread = None
        self.is_running = False
        self._stop_event = threading.Event()
        self._active_run_dir: Path | None = None
        self._ui_queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = queue.Queue()
        self.debug_log_path = Path.home() / ".meowth" / "logs" / "gui-debug.log"
        self.debug_log_path.parent.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.config_form.load_state()
        self._autoload_resumable_run()
        self.after(16, self._process_ui_queue)
        self.after(1200, self._auto_refresh_review_panel)
        self._debug("GUI initialized")

    def _panel_action(self, action: str, payload: dict[str, Any]):
        if action == "start_translation":
            # start_translation can now have start_key and category_filter
            start_key = payload.get("start_key") if isinstance(payload, dict) else None
            category_filter = payload.get("category_filter") if isinstance(payload, dict) else None

            if start_key or category_filter:
                # Resume from selected row or process only filtered category.
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
                # Empty start_key means "start from beginning", constrained by category_filter.
                self._start_review_job(
                    "resume_from_row",
                    translated_path,
                    (str(start_key or ""), category_filter),
                )
            else:
                # Normal start translation
                self._start_translation()
            return

        if action == "stop_translation":
            self._stop_translation()
            return

        if action == "prepare":
            self._prepare_workspace()
            return

        if action == "category_settings":
            self._show_category_settings()
            return

        if action == "build_rom":
            self._build_from_run_files(finalize=False)
            return

        if action == "finalize":
            self._build_from_run_files(finalize=True)
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
                self._start_review_job("llm_selected", translated_path, selected_keys)
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
                self._start_review_job("resume_from_row", translated_path, start_key)
            return

    def _show_category_settings(self):
        """Open category settings dialog."""
        from .components import CategorySettingsDialog
        
        def on_settings_apply(policies: dict[str, dict[str, bool]]) -> None:
            """Handle category settings apply."""
            if not self.engine:
                self.engine = TranslationEngine(
                    config=self.config_form.get_config(),
                    stop_event=self._stop_event,
                )
            
            # Update config with new policies
            self.engine.config.category_policies = policies
            self.config_form.config.category_policies = policies
            
            self.log_view.append("info", "Category policies updated.")
        
        # Show dialog
        dialog = CategorySettingsDialog(
            self,
            category_policies=self.config_form.get_config().category_policies,
            on_apply=on_settings_apply,
        )

    def _auto_refresh_review_panel(self):
        """Keep embedded review panel in sync while translation is active."""
        try:
            # Refresh less aggressively while background work is active to keep
            # the main Tk loop responsive under heavy JSON/log traffic.
            if not self.is_running:
                self._refresh_review_panel(silent=True)
        except Exception as exc:
            self._debug(f"Auto refresh review failed: {exc}")
        finally:
            self.after(1500, self._auto_refresh_review_panel)

    def _runs_root(self, work_dir: Path) -> Path:
        return work_dir / "runs"

    def _archive_root(self, work_dir: Path) -> Path:
        return work_dir / "archive"

    def _run_source_rom(self, run_dir: Path) -> Path:
        return run_dir / "source_rom.gba"

    def _run_texts(self, run_dir: Path) -> Path:
        return run_dir / "texts.json"

    def _run_translated(self, run_dir: Path) -> Path:
        return run_dir / "texts_translated.json"

    def _run_config(self, run_dir: Path) -> Path:
        return run_dir / "run_config.json"

    def _run_output_name_source(self, run_dir: Path, fallback_rom: Path) -> Path:
        """Return path used to derive output ROM filename for this run."""
        config_path = self._run_config(run_dir)
        if not config_path.exists():
            # Fallback for legacy/prepared runs without metadata:
            # derive from run directory slug (name before "__timestamp").
            slug = run_dir.name.split("__", 1)[0].strip()
            if slug:
                return Path(f"{slug}.gba")
            return fallback_rom
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            original_rom = data.get("original_rom") if isinstance(data, dict) else None
            if isinstance(original_rom, str) and original_rom.strip():
                return Path(original_rom)
        except Exception as exc:
            self._debug(f"Failed to read run output naming source from {config_path}: {exc}")
        return fallback_rom

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

    def _autoload_resumable_run(self) -> None:
        """Load the latest resumable run into the review panel at startup."""
        try:
            config = self.config_form.get_config()
            resumables = self._find_resumable_runs(config.work_dir)
            if not resumables:
                return

            latest = resumables[0]
            self._active_run_dir = latest
            self._refresh_review_panel(silent=True)

            translated_path = self._run_translated(latest)
            total, pending = self._count_pending_entries(translated_path)
            if total > 0:
                summary = f"{pending}/{total} pending"
            else:
                summary = "no translated file yet"

            self.log_view.append("info", f"Loaded existing run: {latest.name} ({summary}).")
            self._debug(
                f"Auto-loaded resumable run at startup: {latest} "
                f"(pending={pending}, total={total})"
            )
        except Exception as exc:
            # Startup auto-load should never block opening the GUI.
            self._debug(f"Startup auto-load skipped due to error: {exc}")

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

    def _archive_run_dir_zip(self, run_dir: Path, work_dir: Path) -> Path:
        archive_root = self._archive_root(work_dir)
        archive_root.mkdir(parents=True, exist_ok=True)

        base_name = run_dir.name
        archive_name = f"{base_name}.zip"
        destination = archive_root / archive_name
        if destination.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            destination = archive_root / f"{base_name}__{stamp}.zip"

        shutil.make_archive(
            str(destination.with_suffix("")),
            "zip",
            root_dir=run_dir.parent,
            base_dir=run_dir.name,
        )
        shutil.rmtree(run_dir)
        return destination

    def _build_from_run_files(self, finalize: bool) -> None:
        """Build ROM from current run files, optionally finalizing (zip + cleanup)."""
        if self.is_running:
            self.log_view.append("warning", "Another operation is already running.")
            return

        is_valid, error_message = self.config_form.validate()
        if not is_valid:
            self.log_view.append("error", error_message)
            messagebox.showerror("Invalid Configuration", error_message)
            return

        config = self.config_form.get_config()
        self.config_form.save_state()

        run_dir = self._resolve_review_run()
        if not run_dir:
            self.log_view.append("warning", "No active/resumable run available.")
            return

        translated_path = self._ensure_translated_file(run_dir)
        if not translated_path.exists():
            self.log_view.append("warning", "No translated file available yet.")
            return

        self._active_run_dir = run_dir
        self._ensure_engine_for_review()

        action_label = "Finalize" if finalize else "Build Rom"
        self.is_running = True
        self.review_panel.set_run_state(True)
        self.review_panel.set_activity(f"{action_label} running...", is_busy=True)
        self.log_view.append("info", f"Starting {action_label.lower()} from run files...")

        thread = threading.Thread(
            target=self._run_build_job,
            args=(run_dir, translated_path, finalize, config),
            daemon=True,
        )
        thread.start()

    def _run_build_job(self, run_dir: Path, translated_path: Path, finalize: bool, config) -> None:
        """Background build worker for Build Rom / Finalize actions."""
        try:
            if not self.engine:
                raise RuntimeError("Translation engine not initialized")

            source_rom = self._run_source_rom(run_dir)
            if not source_rom.exists():
                raise RuntimeError(f"Run is missing source ROM: {source_rom}")

            _, _, _, _, _, output_path = self.engine._resolve_run_context(
                rom_path=source_rom,
                output_dir=config.output_dir,
                work_dir=run_dir,
                output_name_source=self._run_output_name_source(run_dir, source_rom),
            )

            self.engine.build_from_translations(
                rom_path=source_rom,
                translations_path=translated_path,
                output_path=output_path,
            )

            if finalize:
                archived_path = self._archive_run_dir_zip(run_dir, config.work_dir)
                self.call_on_main_thread(
                    self._on_translation_complete,
                    output_path,
                    archived_path,
                    True,
                    "Finalize completed.",
                )
            else:
                self.call_on_main_thread(
                    self._on_translation_complete,
                    output_path,
                    None,
                    False,
                    "Build completed.",
                )
        except TranslationStoppedError:
            self.call_on_main_thread(self._on_translation_stopped)
        except Exception as exc:
            self._debug(f"Build/finalize failed: {exc}")
            self._debug(traceback.format_exc())
            self.call_on_main_thread(self._on_translation_error, exc)

    def call_on_main_thread(self, func, *args, **kwargs):
        """Schedule a callable to run on the Tk main thread."""
        self._ui_queue.put((func, args, kwargs))

    def _process_ui_queue(self):
        """Drain cross-thread UI tasks from worker threads on the Tk main thread."""
        processed = 0
        max_per_tick = 30
        while processed < max_per_tick:
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

        delay_ms = 1 if not self._ui_queue.empty() else 16
        self.after(delay_ms, self._process_ui_queue)

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

    def _is_quota_or_rate_limit_error(self, error: Exception | str) -> bool:
        """Heuristic classifier for provider quota/rate-limit failures."""
        text = str(error).lower()
        markers = (
            "429",
            "rate limit",
            "quota",
            "free-tier",
            "free tier",
            "daily limit",
            "requests per day",
            "free-models-per-day",
            "retry window",
            "insufficient",
            "credits",
            "billing",
            "no endpoints found",
            "model eligibility",
        )
        return any(marker in text for marker in markers)

    def _quota_warning_message(self, error: Exception | str) -> str:
        """User-facing warning for safely stopped runs due to provider limits."""
        return (
            "Provider quota/rate limit reached. The job stopped safely.\n"
            "All already completed batches were saved to texts_translated.json.\n\n"
            f"Provider detail: {error}"
        )

    def _build_ui(self):
        """Build the user interface."""
        # --- Main split layout ---
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=24, pady=(20, 12))

        left_shell = ctk.CTkFrame(content, width=_SETTINGS_PANEL_WIDTH, fg_color="transparent")
        left_shell.pack(side="left", fill="y", expand=False, padx=(0, 10))
        left_shell.pack_propagate(False)

        left = ctk.CTkScrollableFrame(left_shell, fg_color="transparent")
        left.pack(fill="both", expand=True)

        right = ctk.CTkFrame(content)
        right.pack(side="right", fill="both", expand=True)

        # Title
        header_frame = ctk.CTkFrame(left, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(
            header_frame, text="🐱 Meowth GBA Translator",
            font=("", 24, "bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            header_frame,
            text="Translate Pokémon GBA ROMs with AI",
            font=("", 12),
            text_color=("gray50", "gray55"),
        ).pack(side="left", padx=(12, 0), pady=(6, 0))

        # Config form
        self.config_form = ConfigForm(left)
        self.config_form.pack(fill="x", pady=(0, 8))

        # Log view
        self.log_view = LogView(left)
        self.log_view.pack(fill="x")

        self.review_panel = ReviewPanel(right, self._panel_action)
        self.review_panel.pack(fill="both", expand=True, padx=8, pady=8)

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

        choice, run_dir = self._ask_resume_or_new(config)
        if choice == "cancel":
            self._debug("Start aborted by user at resume/new prompt")
            return
        if choice == "new":
            run_dir = self._create_new_run_dir(config.work_dir, config.rom_path)
        self._active_run_dir = run_dir

        self._debug(
            "Config prepared: "
            f"rom={config.rom_path}, output={config.output_dir}, work={config.work_dir}, "
            f"provider={config.provider}, model={config.model}, batch={config.batch_size}, workers={config.max_workers}, "
            f"run={self._active_run_dir}, mode={choice}"
        )

        self.log_view.append("info", "Starting translation...")
        self.log_view.append("info", f"Debug log: {self.debug_log_path}")
        self.review_panel.set_activity("Full translation running", is_busy=True)

        self.is_running = True
        self.review_panel.set_run_state(True)

        callbacks = GUICallbacks(self, self.log_view)
        self._stop_event = threading.Event()

        try:
            self._debug("Initializing TranslationEngine")
            self.engine = TranslationEngine(config, callbacks, stop_event=self._stop_event)
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
            args=(config, choice),
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

    def _run_translation(self, config, run_mode: str):
        """Run translation in background thread."""
        try:
            self._debug("Entered _run_translation")
            if not self._active_run_dir:
                raise RuntimeError("Run directory was not initialized")

            run_dir = self._active_run_dir
            source_rom = self._run_source_rom(run_dir)
            texts_path = self._run_texts(run_dir)
            translated_path = self._run_translated(run_dir)

            if run_mode == "new":
                self._prepare_new_run_files(run_dir, config)
            else:
                if not source_rom.exists() or not texts_path.exists():
                    raise RuntimeError(
                        f"Selected run is missing required files: {run_dir}"
                    )
                self.call_on_main_thread(
                    self.log_view.append,
                    "info",
                    f"Resuming run: {run_dir.name}",
                )

            self.engine.callbacks.on_stage_change("translate", "started")
            self.call_on_main_thread(self.log_view.append, "info", "Translating from run files...")
            self.engine.translate_texts(texts_path, translated_path)
            self.engine.callbacks.on_stage_change("translate", "completed")

            self.call_on_main_thread(self._refresh_review_panel, True)
            self._debug(f"Translation completed for run={run_dir.name}; awaiting build/finalize action")
            self.call_on_main_thread(
                self._on_translation_complete,
                None,
                None,
                False,
                "Translation completed. Review entries, then use Build Rom or Finalize.",
            )
        except TranslationStoppedError:
            self._debug("Translation stopped by user")
            self.call_on_main_thread(self._on_translation_stopped)
        except Exception as e:
            self._debug(f"review/build flow raised: {e}")
            self._debug(traceback.format_exc())
            self.call_on_main_thread(self._on_translation_error, e)

    def _ensure_translated_file(self, run_dir: Path) -> Path:
        texts_path = self._run_texts(run_dir)
        translated_path = self._run_translated(run_dir)
        if not translated_path.exists() and texts_path.exists():
            shutil.copy2(texts_path, translated_path)
        return translated_path

    def _resolve_review_run(self) -> Path | None:
        if self._active_run_dir and self._active_run_dir.exists():
            return self._active_run_dir

        config = self.config_form.get_config()
        resumables = self._find_resumable_runs(config.work_dir)
        if not resumables:
            return None
        return resumables[0]

    def _ensure_engine_for_review(self):
        # Always recreate from current form config so profile switches take effect.
        config = self.config_form.get_config()
        callbacks = GUICallbacks(self, self.log_view)
        self.engine = TranslationEngine(config, callbacks)

    def _get_review_text_limit(self) -> int | None:
        """Return effective text limit for review actions, if configured."""
        if not self.engine:
            return None

        getter = getattr(self.engine, "_get_effective_text_limit", None)
        if not callable(getter):
            return None

        try:
            limit = getter()
        except Exception as exc:
            self._debug(f"Failed to resolve review text limit: {exc}")
            return None

        if isinstance(limit, int) and limit > 0:
            return limit
        return None

    def _start_review_job(self, job_type: str, translated_path: Path, payload: Any) -> None:
        """Run review translation actions off the Tk main thread."""
        if self.is_running:
            self.log_view.append("warning", "Translation is already running.")
            return

        self.is_running = True
        self.review_panel.set_run_state(True)
        self.review_panel.set_activity(f"{job_type} preparing...", is_busy=True)
        self.log_view.append("info", f"Starting {job_type} in background...")
        payload_size = len(payload) if isinstance(payload, (list, tuple, dict)) else 1
        self._debug(
            "Review job start: "
            f"type={job_type}, translated_path={translated_path}, payload_size={payload_size}"
        )

        thread = threading.Thread(
            target=self._run_review_job,
            args=(job_type, translated_path, payload),
            daemon=True,
        )
        thread.start()

    def _run_review_job(self, job_type: str, translated_path: Path, payload: Any) -> None:
        """Background worker for llm_selected and resume_from_row actions."""
        def _report_activity(message: str, active_keys: list[str] | None = None) -> None:
            self.call_on_main_thread(self.review_panel.set_activity, message, True)
            if active_keys is not None:
                self.call_on_main_thread(self.review_panel.set_active_keys, active_keys)

        try:
            self._debug(f"Review worker entered: type={job_type}")
            if job_type == "llm_selected":
                selected_keys = payload if isinstance(payload, list) else []
                self._debug(f"LLM selected payload keys={len(selected_keys)}")
                retried, improved = self._retry_selected_entries(
                    translated_path,
                    selected_keys,
                    progress_callback=_report_activity,
                )
                self._debug(
                    f"LLM selected result: retried={retried}, improved={improved}, path={translated_path}"
                )
                self.call_on_main_thread(
                    self.log_view.append,
                    "info",
                    f"LLM translated {retried} selected entries ({improved} improved).",
                )
            elif job_type == "resume_from_row":
                start_key = str(payload)
                self._debug(f"Resume-from-row payload: start_key={start_key}")
                # payload can be a string (start_key only) or a tuple (start_key, category_filter)
                start_key = str(payload[0]) if isinstance(payload, tuple) else str(payload)
                category_filter = payload[1] if isinstance(payload, tuple) and len(payload) > 1 else None
                self._debug(f"Resume-from-row: start_key={start_key}, category_filter={category_filter}")
                processed = self._resume_translation_from_key(
                    translated_path, start_key,
                    category_filter=category_filter,
                    progress_callback=_report_activity,
                )
                self._debug(
                    f"Resume-from-row result: processed={processed}, start_key={start_key}, path={translated_path}"
                )
                self.call_on_main_thread(
                    self.log_view.append,
                    "info",
                    f"Resumed translation from {start_key}: {processed} entries processed.",
                )
            else:
                self.call_on_main_thread(
                    self.log_view.append,
                    "warning",
                    f"Unknown review job: {job_type}",
                )
        except TranslationStoppedError:
            self.call_on_main_thread(self.log_view.append, "warning", "Review job stopped by user.")
        except Exception as exc:
            if self._is_quota_or_rate_limit_error(exc):
                warning = self._quota_warning_message(exc)
                self._debug(f"Review job stopped by provider limits: {exc}")
                self.call_on_main_thread(self.log_view.append, "warning", warning)
                self.call_on_main_thread(
                    messagebox.showwarning,
                    "Provider Limit Reached",
                    warning,
                )
                return
            self._debug(f"Review job failed: {exc}")
            self._debug(traceback.format_exc())
            self.call_on_main_thread(self.log_view.append, "error", f"Review job failed: {exc}")
        finally:
            self.call_on_main_thread(self._finish_review_job)

    def _finish_review_job(self) -> None:
        """Finalize review action state on the UI thread."""
        try:
            self._refresh_review_panel(silent=False)
        finally:
            self.is_running = False
            self.review_panel.set_run_state(False)
            self.review_panel.clear_active_keys()
            self.review_panel.clear_activity()
            self._debug("Review job finished")

    def _apply_manual_translation(self, translated_path: Path, key: str, translated: str) -> bool:
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        data = convert_format(data)
        indexed = self._index_translation_entries(data)
        item = indexed.get(key)
        if not item:
            self._debug(f"Manual save skipped: key not found ({key})")
            return False
        item["entry"]["translated"] = translated
        translated_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True

    def _resume_translation_from_key(
        self,
        translated_path: Path,
        start_key: str,
        category_filter: str | None = None,
        progress_callback: Callable[[str, list[str] | None], None] | None = None,
    ) -> int:
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        data = convert_format(data)
        indexed = self._index_translation_entries(data)
        ordered_keys = list(indexed.keys())

        if start_key and start_key not in indexed:
            self._debug(f"Resume skipped: start key missing ({start_key})")
            return 0

        start_idx = ordered_keys.index(start_key) if start_key else 0
        remaining_keys = ordered_keys[start_idx:]
        limit = self._get_review_text_limit()

        table_items: list[tuple[str, str, dict]] = []
        free_items: list[tuple[str, dict]] = []
        for key in remaining_keys:
            item = indexed[key]
            entry = item["entry"]

            # Skip entries that don't match category filter if one is active.
            if category_filter and str(item.get("category", "")) != category_filter:
                continue

            # Resume should retry entries that still look untranslated/suspect,
            # not only strictly empty ones.
            if not self._is_suspect_entry(entry):
                continue
            if item["source"] == "table":
                table_items.append((key, str(item.get("category", "")), entry))
            else:
                free_items.append((key, entry))

        if limit is not None:
            allowed = max(0, limit)
            if len(table_items) >= allowed:
                table_items = table_items[:allowed]
                free_items = []
            else:
                free_items = free_items[: max(0, allowed - len(table_items))]

        self._debug(
            "Resume candidates: "
            f"start_key={start_key or '<begin>'}, category_filter={category_filter}, "
            f"remaining={len(remaining_keys)}, "
            f"table={len(table_items)}, free={len(free_items)}, limit={limit}"
        )

        processed = 0

        def _persist_progress(reason: str) -> None:
            translated_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._debug(
                f"Resume progress saved ({reason}): path={translated_path}, processed={processed}"
            )

        batch_size = max(1, int(getattr(self.engine.config, "batch_size", 30)))
        table_total_batches = (len(table_items) + batch_size - 1) // batch_size
        free_total_batches = (len(free_items) + batch_size - 1) // batch_size

        for batch_idx, i in enumerate(range(0, len(table_items), batch_size), start=1):
            chunk = table_items[i:i + batch_size]
            chunk_keys = [key for key, _, _ in chunk]
            if progress_callback and chunk_keys:
                progress_callback(
                    f"Resume table {batch_idx}/{table_total_batches}: {chunk_keys[0]} -> {chunk_keys[-1]}",
                    chunk_keys,
                )
            self._debug(
                f"Resume table batch {batch_idx}/{table_total_batches}: "
                f"size={len(chunk)}, first={chunk_keys[0]}, last={chunk_keys[-1]}"
            )

            # Process each table category with its configured policy.
            # This avoids unintended LLM usage for glossary-only categories.
            by_category: dict[str, list[dict]] = {}
            for _, category, entry in chunk:
                by_category.setdefault(category, []).append(entry)

            for category, entries_for_category in by_category.items():
                policy = self.engine.config.get_category_policy(category)
                allow_table_llm = bool(self.engine.config.llm_for_tables and policy.get("use_llm", True))
                table_stub = {"category": category, "entries": entries_for_category}
                self.engine._translate_table(
                    table_stub,
                    run_llm=allow_table_llm,
                    entries=entries_for_category,
                )
            processed += len(chunk)
            _persist_progress(f"table-batch-{batch_idx}")

        for batch_idx, i in enumerate(range(0, len(free_items), batch_size), start=1):
            chunk = free_items[i:i + batch_size]
            chunk_keys = [key for key, _ in chunk]
            if progress_callback and chunk_keys:
                progress_callback(
                    f"Resume free {batch_idx}/{free_total_batches}: {chunk_keys[0]} -> {chunk_keys[-1]}",
                    chunk_keys,
                )
            self._debug(
                f"Resume free batch {batch_idx}/{free_total_batches}: "
                f"size={len(chunk)}, first={chunk_keys[0]}, last={chunk_keys[-1]}"
            )
            self.engine._translate_free_batch([entry for _, entry in chunk])
            processed += len(chunk)
            _persist_progress(f"free-batch-{batch_idx}")

        _persist_progress("final")
        self._debug(f"Resume write complete: path={translated_path}, processed={processed}")
        return processed

    def _refresh_review_panel(self, silent: bool = True):
        run_dir = self._resolve_review_run()
        if not run_dir:
            self.review_panel.set_rows([], 0)
            return

        translated_path = self._ensure_translated_file(run_dir)
        if not translated_path.exists():
            if not silent:
                messagebox.showerror(
                    "Missing Files",
                    f"Could not find translation file in {run_dir}",
                )
            return

        self._active_run_dir = run_dir
        self._ensure_engine_for_review()

        try:
            review_rows, suspect_count = self._load_review_candidates(translated_path)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            if not silent:
                self.log_view.append("warning", f"Review refresh skipped: {exc}")
            return
        self.review_panel.set_rows(review_rows, suspect_count)

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
        data = convert_format(data)
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

    def _retry_selected_entries(
        self,
        translated_path: Path,
        selected_keys: list[str],
        progress_callback: Callable[[str, list[str] | None], None] | None = None,
    ) -> tuple[int, int]:
        """Retry selected entries in-place using engine translation helpers."""
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        data = convert_format(data)
        indexed = self._index_translation_entries(data)

        table_items: list[tuple[str, dict]] = []
        free_items: list[tuple[str, dict]] = []
        before_state: dict[str, str] = {}

        for key in selected_keys:
            item = indexed.get(key)
            if not item:
                continue
            entry = item["entry"]
            before_state[key] = str(entry.get("translated", ""))
            if item["source"] == "table":
                table_items.append((key, entry))
            else:
                free_items.append((key, entry))

        def _persist_progress(reason: str) -> None:
            translated_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._debug(
                f"LLM selected progress saved ({reason}): path={translated_path}, retried={len(before_state)}"
            )

        batch_size = max(1, int(getattr(self.engine.config, "batch_size", 30)))
        table_total_batches = (len(table_items) + batch_size - 1) // batch_size
        free_total_batches = (len(free_items) + batch_size - 1) // batch_size
        self._debug(
            "LLM selected candidates: "
            f"selected={len(selected_keys)}, resolved={len(before_state)}, "
            f"table={len(table_items)}, free={len(free_items)}"
        )

        for batch_idx, i in enumerate(range(0, len(table_items), batch_size), start=1):
            chunk = table_items[i:i + batch_size]
            chunk_keys = [key for key, _ in chunk]
            if progress_callback and chunk_keys:
                progress_callback(
                    f"LLM selected table {batch_idx}/{table_total_batches}: {chunk_keys[0]} -> {chunk_keys[-1]}",
                    chunk_keys,
                )
            self._debug(
                f"LLM selected table batch {batch_idx}/{table_total_batches}: "
                f"size={len(chunk)}, first={chunk_keys[0]}, last={chunk_keys[-1]}"
            )
            self.engine._translate_table_llm_batch([entry for _, entry in chunk])
            _persist_progress(f"table-batch-{batch_idx}")

        for batch_idx, i in enumerate(range(0, len(free_items), batch_size), start=1):
            chunk = free_items[i:i + batch_size]
            chunk_keys = [key for key, _ in chunk]
            if progress_callback and chunk_keys:
                progress_callback(
                    f"LLM selected free {batch_idx}/{free_total_batches}: {chunk_keys[0]} -> {chunk_keys[-1]}",
                    chunk_keys,
                )
            self._debug(
                f"LLM selected free batch {batch_idx}/{free_total_batches}: "
                f"size={len(chunk)}, first={chunk_keys[0]}, last={chunk_keys[-1]}"
            )
            self.engine._translate_free_batch([entry for _, entry in chunk])
            _persist_progress(f"free-batch-{batch_idx}")

        improved = 0
        for key in before_state:
            item = indexed.get(key)
            if not item:
                continue
            entry = item["entry"]
            after_translated = str(entry.get("translated", ""))
            if after_translated != before_state[key] and not self._is_suspect_entry(entry):
                improved += 1

        _persist_progress("final")
        self._debug(
            f"LLM selected write complete: path={translated_path}, retried={len(before_state)}, improved={improved}"
        )
        return len(before_state), improved

    def _on_translation_complete(
        self,
        output_path: Path | None,
        archived_run: Path | None = None,
        clear_active_run: bool = False,
        message: str | None = None,
    ):
        """Handle translation completion."""
        self._debug(f"UI completion callback invoked: output={output_path}")
        if message:
            self.log_view.append("info", message)
        if output_path:
            self.log_view.append("info", f"Output ROM: {output_path}")
        if archived_run:
            self.log_view.append("info", f"Archived run files: {archived_run}")
        if clear_active_run:
            self._active_run_dir = None
        self._refresh_review_panel(silent=True)
        self._reset_buttons()

    def _on_translation_error(self, error: Exception):
        """Handle translation error."""
        self._debug(f"UI error callback invoked: {error}")
        if self._is_quota_or_rate_limit_error(error):
            warning = self._quota_warning_message(error)
            self.log_view.append("warning", warning)
            messagebox.showwarning("Provider Limit Reached", warning)
            self._reset_buttons()
            return

        self.log_view.append("error", f"Translation failed: {error}")
        messagebox.showerror("Translation Failed", str(error))
        self._reset_buttons()

    def _on_translation_stopped(self):
        """Handle user-requested translation stop."""
        self.log_view.append("warning", "Translation stopped by user.")
        self._reset_buttons()

    def _stop_translation(self):
        """Stop the translation process."""
        if self.engine and self.is_running:
            self.log_view.append("warning", "Stopping translation...")
            self.review_panel.set_activity("Stopping...", is_busy=True)
            self._stop_event.set()
            self.engine.request_stop()
            self.review_panel.set_run_state(True)

    def _prepare_workspace(self):
        """Prepare workspace: copy ROM, create files, refresh PokeAPI cache, extract texts."""
        self._debug("Prepare workspace clicked")
        is_valid, error_message = self.config_form.validate()
        if not is_valid:
            self._debug(f"Validation failed: {error_message}")
            self.log_view.append("error", error_message)
            messagebox.showerror("Invalid Configuration", error_message)
            return

        config = self.config_form.get_config()
        self.config_form.save_state()

        try:
            # Create new run directory
            run_dir = self._create_new_run_dir(config.work_dir, config.rom_path)
            self._active_run_dir = run_dir
            
            self.log_view.append("info", f"Preparing workspace in: {run_dir.name}")
            self.review_panel.set_activity("Preparing workspace...", is_busy=True)
            
            # Copy ROM to work folder
            source_rom = self._run_source_rom(run_dir)
            shutil.copy2(config.rom_path, source_rom)
            self.log_view.append("info", f"ROM copied: {source_rom.name}")

            # Copy HexManiac metadata if present so extraction can use it.
            original_rom = Path(config.rom_path)
            metadata_candidates = [
                original_rom.with_suffix(".toml"),
                Path(str(original_rom) + ".toml"),
            ]
            source_metadata = next((p for p in metadata_candidates if p.exists()), None)
            if source_metadata is not None:
                copied_metadata = source_rom.with_suffix(".toml")
                shutil.copy2(source_metadata, copied_metadata)
                self.log_view.append("info", f"Metadata copied: {copied_metadata.name}")
            
            # Create necessary files
            texts_path = self._run_texts(run_dir)
            translated_path = self._run_translated(run_dir)
            texts_path.parent.mkdir(parents=True, exist_ok=True)

            run_meta = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "original_rom": str(config.rom_path),
                "source_rom": str(source_rom),
                "texts": str(texts_path),
                "translated": str(translated_path),
                "source_lang": config.source_lang,
                "target_lang": config.target_lang,
                "provider": config.provider,
                "model": config.model,
            }
            self._run_config(run_dir).write_text(
                json.dumps(run_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            
            # Initialize engine for preparation
            self._debug("Initializing TranslationEngine for preparation")
            self.engine = TranslationEngine(config, stop_event=self._stop_event)
            self._debug("Engine initialized successfully")
            
            # Refresh PokeAPI cache
            self.log_view.append("info", "Refreshing PokeAPI cache tables...")
            try:
                self.engine.glossary._update_pokeapi_cache()
                self.log_view.append("info", "PokeAPI cache refreshed")
            except Exception as e:
                self.log_view.append("warning", f"PokeAPI cache update failed (non-critical): {e}")
            
            # Extract texts from ROM
            self.log_view.append("info", "Extracting texts from ROM...")
            self.engine.extract_texts(source_rom, texts_path)
            self.log_view.append("info", f"Texts extracted: {len(list(texts_path.read_text().split(chr(10))))} entries")
            
            # Load extracted texts into review panel
            self._refresh_review_panel(silent=False)
            
            self.log_view.append("info", f"✓ Workspace prepared. Ready to start translation.")
            self.review_panel.set_activity("Workspace ready", is_busy=False)
            
            self._debug("Prepare workspace completed successfully")
            
        except Exception as e:
            self._debug(f"Prepare workspace failed: {e}")
            self._debug(traceback.format_exc())
            self.log_view.append("error", f"Prepare failed: {e}")
            messagebox.showerror("Preparation Failed", str(e))
            self.review_panel.set_activity("Prepare failed", is_busy=False)

    def _reset_buttons(self):
        """Reset button states."""
        self.is_running = False
        self.review_panel.set_run_state(False)
        self.review_panel.clear_active_keys()
        self.review_panel.clear_activity()


def main():
    """Entry point for the GUI application."""
    app = MeowthGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
