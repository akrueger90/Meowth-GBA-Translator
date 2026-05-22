"""Embedded review panel for translation workflow."""

from typing import Any, Callable
from tkinter import ttk
from tkinter import messagebox

import customtkinter as ctk


class ReviewPanel(ctk.CTkFrame):
    """Persistent review panel shown inside the main window."""

    def __init__(self, master, on_action: Callable[[str, dict[str, Any]], None]):
        super().__init__(master, corner_radius=10)
        self.on_action = on_action
        self.candidates: list[dict[str, str]] = []
        self._row_id_to_index: dict[str, int] = {}
        self._active_keys: set[str] = set()
        self._build_ui()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(header, text="Review", font=("", 14, "bold")).pack(side="left")
        self.summary_label = ctk.CTkLabel(
            header,
            text="No run loaded",
            text_color=("gray45", "gray65"),
            font=("", 11),
        )
        self.summary_label.pack(side="right")

        self.activity_label = ctk.CTkLabel(
            self,
            text="Activity: Idle",
            text_color=("gray45", "gray65"),
            font=("", 11),
            anchor="w",
        )
        self.activity_label.pack(fill="x", padx=12, pady=(0, 6))

        table_container = ctk.CTkFrame(self)
        table_container.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        columns = ("key", "id", "category", "original", "translated")
        self.tree = ttk.Treeview(
            table_container,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("id", text="Entry ID")
        self.tree.heading("category", text="Category")
        self.tree.heading("original", text="Original")
        self.tree.heading("translated", text="Translated")

        self.tree.column("key", width=0, minwidth=0, stretch=False)
        self.tree.column("id", width=120, minwidth=90, stretch=False)
        self.tree.column("category", width=120, minwidth=100, stretch=False)
        self.tree.column("original", width=250, minwidth=180, stretch=True)
        self.tree.column("translated", width=250, minwidth=180, stretch=True)
        self.tree.tag_configure("suspect", background="#3f1d1d", foreground="#f8d7da")
        self.tree.tag_configure("active", background="#1e3a8a", foreground="#dbeafe")
        self.tree.tag_configure("suspect_active", background="#4c1d95", foreground="#f5d0fe")

        y_scroll = ttk.Scrollbar(table_container, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)

        editor = ctk.CTkFrame(self, fg_color="transparent")
        editor.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(editor, text="Selected Original", font=("", 11, "bold")).pack(anchor="w")
        self.original_text = ctk.CTkTextbox(editor, height=70)
        self.original_text.pack(fill="x", pady=(2, 6))
        self.original_text.configure(state="disabled")

        ctk.CTkLabel(editor, text="Manual Translation", font=("", 11, "bold")).pack(anchor="w")
        self.manual_translation = ctk.CTkTextbox(editor, height=70)
        self.manual_translation.pack(fill="x", pady=(2, 0))

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(controls, text="Refresh", width=90, command=self._refresh).pack(side="left")
        ctk.CTkButton(controls, text="Select Suspects", width=120, command=self._select_suspects).pack(side="left", padx=(6, 0))
        ctk.CTkButton(controls, text="Next Untranslated", width=140, command=self._select_next_untranslated).pack(side="left", padx=(6, 0))
        ctk.CTkButton(controls, text="Clear", width=90, command=self._clear_selection).pack(side="left", padx=(6, 0))

        self.start_button = ctk.CTkButton(
            controls,
            text="Start",
            width=90,
            command=self._start_translation,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.start_button.pack(side="left", padx=(10, 0))

        self.stop_button = ctk.CTkButton(
            controls,
            text="Stop",
            width=90,
            command=self._stop_translation,
            state="disabled",
            fg_color="#4b5563",
            hover_color="#6b7280",
        )
        self.stop_button.pack(side="left", padx=(6, 0))

        ctk.CTkButton(
            controls,
            text="Save Manual",
            width=110,
            command=self._save_manual,
            fg_color="#f59e0b",
            hover_color="#d97706",
        ).pack(side="right")
        ctk.CTkButton(
            controls,
            text="Resume Row",
            width=110,
            command=self._resume_from_row,
            fg_color="#14b8a6",
            hover_color="#0f766e",
        ).pack(side="right", padx=(0, 6))
        ctk.CTkButton(
            controls,
            text="LLM Selected",
            width=110,
            command=self._llm_selected,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
        ).pack(side="right", padx=(0, 6))

    def set_run_state(self, is_running: bool) -> None:
        if is_running:
            self.start_button.configure(state="disabled", fg_color="#4b5563")
            self.stop_button.configure(state="normal", fg_color="#dc2626", hover_color="#b91c1c")
            return

        self.start_button.configure(state="normal", fg_color="#2563eb")
        self.stop_button.configure(state="disabled", fg_color="#4b5563", hover_color="#6b7280")

    def set_activity(self, message: str, is_busy: bool = False) -> None:
        """Show current translation activity for review operations."""
        color = "#22c55e" if is_busy else ("gray45", "gray65")
        self.activity_label.configure(text=f"Activity: {message}", text_color=color)

    def clear_activity(self) -> None:
        """Reset activity indicator to idle."""
        self.set_activity("Idle", is_busy=False)

    def set_rows(self, candidates: list[dict[str, str]], suspect_count: int) -> None:
        self.candidates = candidates
        self._row_id_to_index.clear()
        self._active_keys = {k for k in self._active_keys if any(c.get("key") == k for c in candidates)}

        for row_id in self.tree.get_children():
            self.tree.delete(row_id)

        for idx, candidate in enumerate(candidates):
            row_id = self.tree.insert(
                "",
                "end",
                iid=f"row_{idx}",
                values=(
                    candidate.get("key", ""),
                    candidate.get("entry_id", ""),
                    candidate.get("category", ""),
                    candidate.get("original", ""),
                    candidate.get("translated", ""),
                ),
            )
            self._row_id_to_index[row_id] = idx

        self._apply_row_tags()

        self.summary_label.configure(
            text=f"Rows: {len(candidates)} | Suspects: {suspect_count}"
        )

        if self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self._on_selection_changed()
        else:
            self.original_text.configure(state="normal")
            self.original_text.delete("1.0", "end")
            self.original_text.configure(state="disabled")
            self.manual_translation.delete("1.0", "end")

    def set_active_keys(self, keys: list[str]) -> None:
        """Highlight rows that are currently being translated."""
        self._active_keys = {str(k).strip() for k in keys if str(k).strip()}
        self._apply_row_tags()

    def clear_active_keys(self) -> None:
        """Clear active translation row highlights."""
        self._active_keys.clear()
        self._apply_row_tags()

    def _apply_row_tags(self) -> None:
        """Apply visual tags based on suspect and active state."""
        for row_id in self.tree.get_children():
            values = self.tree.item(row_id, "values")
            key = str(values[0]).strip() if values else ""
            idx = self._row_id_to_index.get(row_id)
            is_suspect = (
                idx is not None
                and 0 <= idx < len(self.candidates)
                and self.candidates[idx].get("suspect") == "true"
            )
            is_active = bool(key) and key in self._active_keys

            if is_suspect and is_active:
                tags = ("suspect_active",)
            elif is_active:
                tags = ("active",)
            elif is_suspect:
                tags = ("suspect",)
            else:
                tags = ()

            self.tree.item(row_id, tags=tags)

    def _selected_row_id(self) -> str | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return selected[0]

    def _selected_keys(self) -> list[str]:
        keys: list[str] = []
        for row_id in self.tree.selection():
            values = self.tree.item(row_id, "values")
            if values and values[0]:
                keys.append(str(values[0]))
        return keys

    def _selected_key(self) -> str | None:
        row_id = self._selected_row_id()
        if not row_id:
            return None
        values = self.tree.item(row_id, "values")
        if not values:
            return None
        key = str(values[0]).strip()
        return key or None

    def _on_selection_changed(self, _event=None):
        row_id = self._selected_row_id()
        if not row_id:
            return
        values = self.tree.item(row_id, "values")
        if not values:
            return

        original = str(values[3])
        translated = str(values[4])

        self.original_text.configure(state="normal")
        self.original_text.delete("1.0", "end")
        self.original_text.insert("1.0", original)
        self.original_text.configure(state="disabled")

        self.manual_translation.delete("1.0", "end")
        self.manual_translation.insert("1.0", translated)

    def _update_row_translation(self, key: str, translated: str) -> None:
        for row_id in self.tree.get_children():
            values = list(self.tree.item(row_id, "values"))
            if values and values[0] == key:
                values[4] = translated
                self.tree.item(row_id, values=values)
                idx = self._row_id_to_index.get(row_id)
                if idx is not None and 0 <= idx < len(self.candidates):
                    self.candidates[idx]["translated"] = translated
                break

    def _refresh(self):
        self.on_action("refresh", {})

    def _start_translation(self):
        self.on_action("start_translation", {})

    def _stop_translation(self):
        self.on_action("stop_translation", {})

    def _select_suspects(self):
        suspect_rows = [
            row_id for row_id in self.tree.get_children()
            if "suspect" in self.tree.item(row_id, "tags")
        ]
        self.tree.selection_set(suspect_rows)

    def _clear_selection(self):
        self.tree.selection_remove(self.tree.selection())

    def _select_next_untranslated(self):
        rows = list(self.tree.get_children())
        if not rows:
            return

        selected = self._selected_row_id()
        start_index = -1
        if selected in rows:
            start_index = rows.index(selected)

        for offset in range(1, len(rows) + 1):
            idx = (start_index + offset) % len(rows)
            row_id = rows[idx]
            values = self.tree.item(row_id, "values")
            translated = str(values[4]).strip() if values and len(values) > 4 else ""
            if translated:
                continue

            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            self.tree.see(row_id)
            self._on_selection_changed()
            return

        messagebox.showinfo("No Untranslated Rows", "All rows already have translated text.")

    def _llm_selected(self):
        selected_keys = self._selected_keys()
        if not selected_keys:
            messagebox.showwarning("No Selection", "Select at least one row.")
            return
        self.on_action("llm_selected", {"selected_keys": selected_keys})

    def _resume_from_row(self):
        start_key = self._selected_key()
        if not start_key:
            messagebox.showwarning("No Selection", "Select a row to resume from.")
            return
        self.on_action("resume_from_row", {"start_key": start_key})

    def _save_manual(self):
        key = self._selected_key()
        if not key:
            messagebox.showwarning("No Selection", "Select a row first.")
            return

        translated = self.manual_translation.get("1.0", "end").strip()
        self.on_action("manual_save", {"key": key, "translated": translated})
        self._update_row_translation(key, translated)
