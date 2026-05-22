"""GUI callback implementation for CustomTkinter interface."""

import threading
import time

from ..core import TranslationCallbacks


class GUICallbacks(TranslationCallbacks):
    """CustomTkinter implementation of translation callbacks.

    All UI updates are scheduled on the Tk main thread.
    """

    def __init__(self, app, progress_view, log_view):
        self.app = app
        self.progress_view = progress_view
        self.log_view = log_view
        self._last_log_key: tuple[str, str] | None = None
        self._last_log_time = 0.0
        self._last_debug_info_time = 0.0
        self._log_lock = threading.Lock()
        self._log_buffer: list[tuple[str, str]] = []
        self._log_flush_scheduled = False
        self._progress_lock = threading.Lock()
        self._latest_progress: tuple[str, int, int, str] | None = None
        self._progress_flush_scheduled = False

    def _dispatch(self, func, *args):
        """Dispatch UI work safely onto Tk main thread."""
        if hasattr(self.app, "call_on_main_thread"):
            self.app.call_on_main_thread(func, *args)
        else:
            # Fallback for older app implementations.
            self.app.after(0, func, *args)

    def on_progress(self, stage: str, current: int, total: int, message: str):
        with self._progress_lock:
            self._latest_progress = (stage, current, total, message)
            if self._progress_flush_scheduled:
                return
            self._progress_flush_scheduled = True

        self._dispatch(self._flush_progress_ui)

    def _flush_progress_ui(self):
        payload: tuple[str, int, int, str] | None
        with self._progress_lock:
            payload = self._latest_progress
            self._latest_progress = None
            self._progress_flush_scheduled = False

        if payload:
            self.progress_view.update(*payload)

    def on_log(self, level: str, message: str):
        # Collapse rapid duplicate logs (common during provider retries/rate limits)
        # so the UI queue doesn't get saturated by identical messages.
        now = time.monotonic()
        key = (level, message)
        if self._last_log_key == key and (now - self._last_log_time) < 0.75:
            return
        self._last_log_key = key
        self._last_log_time = now

        schedule_flush = False
        with self._log_lock:
            self._log_buffer.append((level, message))
            if not self._log_flush_scheduled:
                self._log_flush_scheduled = True
                schedule_flush = True

        if schedule_flush:
            self._dispatch(self._flush_logs_ui)

    def _flush_logs_ui(self):
        batch: list[tuple[str, str]]
        with self._log_lock:
            if not self._log_buffer:
                self._log_flush_scheduled = False
                return
            batch = self._log_buffer[:40]
            del self._log_buffer[:40]

        self.log_view.append_many(batch)

        with self._log_lock:
            has_more = bool(self._log_buffer)
            if not has_more:
                self._log_flush_scheduled = False

        if has_more:
            self._dispatch(self._flush_logs_ui)

        # Mirror pipeline logs to debug stream so users can see stage details
        # (including table local/LLM counts) in terminal/debug output.
        if hasattr(self.app, "_debug"):
            try:
                now = time.monotonic()
                level_ref = batch[-1][0] if batch else "info"
                message_ref = batch[-1][1] if batch else ""
                if level_ref in {"warning", "error"} or (now - self._last_debug_info_time) >= 0.5:
                    self.app._debug(f"[{level_ref}] {message_ref}")
                    if level_ref == "info":
                        self._last_debug_info_time = now
            except Exception:
                pass

    def on_stage_change(self, stage: str, status: str):
        self._dispatch(self.progress_view.set_stage, stage, status)

    def on_error(self, error: Exception):
        self._dispatch(self.log_view.append, "error", f"Error: {error}")
