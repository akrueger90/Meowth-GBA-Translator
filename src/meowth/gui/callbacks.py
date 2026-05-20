"""GUI callback implementation for CustomTkinter interface."""

from ..core import TranslationCallbacks


class GUICallbacks(TranslationCallbacks):
    """CustomTkinter implementation of translation callbacks.

    All UI updates are scheduled on the Tk main thread.
    """

    def __init__(self, app, progress_view, log_view):
        self.app = app
        self.progress_view = progress_view
        self.log_view = log_view

    def _dispatch(self, func, *args):
        """Dispatch UI work safely onto Tk main thread."""
        if hasattr(self.app, "call_on_main_thread"):
            self.app.call_on_main_thread(func, *args)
        else:
            # Fallback for older app implementations.
            self.app.after(0, func, *args)

    def on_progress(self, stage: str, current: int, total: int, message: str):
        self._dispatch(self.progress_view.update, stage, current, total, message)

    def on_log(self, level: str, message: str):
        self._dispatch(self.log_view.append, level, message)
        # Mirror pipeline logs to debug stream so users can see stage details
        # (including table local/LLM counts) in terminal/debug output.
        if hasattr(self.app, "_debug"):
            try:
                self.app._debug(f"[{level}] {message}")
            except Exception:
                pass

    def on_stage_change(self, stage: str, status: str):
        self._dispatch(self.progress_view.set_stage, stage, status)

    def on_error(self, error: Exception):
        self._dispatch(self.log_view.append, "error", f"Error: {error}")
