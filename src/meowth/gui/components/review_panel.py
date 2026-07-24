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
        self._current_category_filter: str | None = None  # None means show all
        self._category_buttons: dict[str, ctk.CTkButton] = {}
        self._visible_row_ids: set[str] = set()  # Track currently visible rows
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

        # Category filter button bar
        self.category_filter_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.category_filter_frame.pack(fill="both", expand=False, padx=12, pady=(0, 6))
        
        ctk.CTkLabel(self.category_filter_frame, text="Filter:", font=("", 10)).pack(side="left", padx=(0, 8))
        self.category_buttons_frame = ctk.CTkFrame(self.category_filter_frame, fg_color="transparent")
        self.category_buttons_frame.pack(side="left", fill="both", expand=True, anchor="nw")

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
        ctk.CTkButton(
            controls,
            text="Prepare",
            width=90,
            command=self._prepare,
            fg_color="#65a30d",
            hover_color="#54a80d",
        ).pack(side="left", padx=(6, 0))
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

        self.build_button = ctk.CTkButton(
            controls,
            text="Build Rom",
            width=110,
            command=self._build_rom,
            fg_color="#0f766e",
            hover_color="#0d9488",
        )
        self.build_button.pack(side="right")

        self.finalize_button = ctk.CTkButton(
            controls,
            text="Finalize",
            width=110,
            command=self._finalize,
            fg_color="#b91c1c",
            hover_color="#991b1b",
        )
        self.finalize_button.pack(side="right", padx=(0, 6))

        ctk.CTkButton(
            controls,
            text="Save Manual",
            width=110,
            command=self._save_manual,
            fg_color="#f59e0b",
            hover_color="#d97706",
        ).pack(side="right", padx=(0, 6))
        ctk.CTkButton(
            controls,
            text="LLM Selected",
            width=110,
            command=self._llm_selected,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
        ).pack(side="right", padx=(0, 6))

    def _create_category_buttons(self, categories: set[str]) -> None:
        """Create and display category filter buttons with wrapping."""
        # Clear existing buttons
        for widget in self.category_buttons_frame.winfo_children():
            widget.destroy()
        self._category_buttons.clear()

        # Sort categories for consistent display, with "All" first
        sorted_cats = sorted(categories)
        
        # Build button list: all category buttons (All is treated separately)
        button_specs = [(None, "All")] + [(cat, cat.replace("_", " ").title()) for cat in sorted_cats]
        
        # Calculate buttons per row: assume ~90px per button (80w + 4px padding + 6px margin)
        # Use grid to let buttons naturally wrap based on container width
        buttons_per_row = 6  # Default, but will adapt based on available space
        
        current_row = 0
        row_frame = None
        buttons_in_row = 0
        
        for cat, display_name in button_specs:
            # Create new row frame if needed
            if buttons_in_row == 0:
                row_frame = ctk.CTkFrame(self.category_buttons_frame, fg_color="transparent")
                row_frame.pack(fill="x", pady=2)
                current_row += 1
            
            # Create button
            btn = ctk.CTkButton(
                row_frame,
                text=display_name,
                width=80,
                height=28,
                font=("", 10),
                command=lambda c=cat: self._on_category_filter_click(c),
                fg_color="#1e40af" if self._current_category_filter == cat else "#4b5563",
                hover_color="#1e3a8a",
            )
            btn.pack(side="left", padx=2, pady=1)
            self._category_buttons[cat] = btn
            
            buttons_in_row += 1
            if buttons_in_row >= buttons_per_row:
                buttons_in_row = 0

    def _on_category_filter_click(self, category: str | None) -> None:
        """Handle category filter button click."""
        self._current_category_filter = category
        
        # Update button colors
        for cat, btn in self._category_buttons.items():
            if cat == category:
                btn.configure(fg_color="#1e40af")
            else:
                btn.configure(fg_color="#4b5563")
        
        # Re-filter the table
        self._apply_category_filter()

    def _apply_category_filter(self) -> None:
        """Filter table rows based on current category filter."""
        # Remove all rows
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        
        self._visible_row_ids.clear()
        
        # Re-add matching rows
        if self._current_category_filter is None:
            # Show all rows
            for idx, candidate in enumerate(self.candidates):
                row_id = f"row_{idx}"
                self.tree.insert(
                    "",
                    "end",
                    iid=row_id,
                    values=(
                        candidate.get("key", ""),
                        candidate.get("entry_id", ""),
                        candidate.get("category", ""),
                        candidate.get("original", ""),
                        candidate.get("translated", ""),
                    ),
                )
                self._visible_row_ids.add(row_id)
        else:
            # Show only matching rows
            for idx, candidate in enumerate(self.candidates):
                if candidate.get("category", "") == self._current_category_filter:
                    row_id = f"row_{idx}"
                    self.tree.insert(
                        "",
                        "end",
                        iid=row_id,
                        values=(
                            candidate.get("key", ""),
                            candidate.get("entry_id", ""),
                            candidate.get("category", ""),
                            candidate.get("original", ""),
                            candidate.get("translated", ""),
                        ),
                    )
                    self._visible_row_ids.add(row_id)
        
        # Re-apply tags to visible rows
        self._apply_row_tags()
        
        # Select first row if available
        if self.tree.get_children():
            first_row = self.tree.get_children()[0]
            self.tree.selection_set(first_row)
            self._on_selection_changed()

    def set_run_state(self, is_running: bool) -> None:
        if is_running:
            self.start_button.configure(state="disabled", fg_color="#4b5563")
            self.stop_button.configure(state="normal", fg_color="#dc2626", hover_color="#b91c1c")
            self.build_button.configure(state="disabled", fg_color="#4b5563")
            self.finalize_button.configure(state="disabled", fg_color="#4b5563")
            return

        self.start_button.configure(state="normal", fg_color="#2563eb")
        self.stop_button.configure(state="disabled", fg_color="#4b5563", hover_color="#6b7280")
        self.build_button.configure(state="normal", fg_color="#0f766e")
        self.finalize_button.configure(state="normal", fg_color="#b91c1c")

    def set_activity(self, message: str, is_busy: bool = False) -> None:
        """Show current translation activity for review operations."""
        color = "#22c55e" if is_busy else ("gray45", "gray65")
        self.activity_label.configure(text=f"Activity: {message}", text_color=color)

    def clear_activity(self) -> None:
        """Reset activity indicator to idle."""
        self.set_activity("Idle", is_busy=False)

    def set_rows(self, candidates: list[dict[str, str]], suspect_count: int) -> None:
        # Save current selection before clearing rows
        previous_selection = self._selected_keys()
        
        self.candidates = candidates
        self._row_id_to_index.clear()
        self._active_keys = {k for k in self._active_keys if any(c.get("key") == k for c in candidates)}

        # Extract unique categories and create filter buttons
        categories = {c.get("category", "") for c in candidates if c.get("category", "")}
        self._create_category_buttons(categories)

        # Apply filter (this will re-populate the table with filtered rows)
        self._apply_category_filter()

        self._apply_row_tags()

        self.summary_label.configure(
            text=f"Rows: {len(candidates)} | Suspects: {suspect_count}"
        )

        if self.tree.get_children():
            # Try to restore previous selection if those rows still exist
            rows_to_select = []
            if previous_selection:
                for row_id in self.tree.get_children():
                    values = self.tree.item(row_id, "values")
                    if values and values[0] in previous_selection:
                        rows_to_select.append(row_id)
            
            # If we restored some selection, use it; otherwise select first row
            if rows_to_select:
                self.tree.selection_set(rows_to_select)
            else:
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


    def _prepare(self):
        """Prepare workspace: copy ROM, create files, refresh PokeAPI, extract texts."""
        self.on_action("prepare", {})

    def _start_translation(self):
        # With an active category filter, start only that subset.
        # Do not pass start_key by default because table auto-selection would
        # accidentally force row-based resume semantics.
        payload: dict[str, str] = {}
        if self._current_category_filter is not None:
            payload["category_filter"] = self._current_category_filter
        self.on_action("start_translation", payload)

    def _stop_translation(self):
        self.on_action("stop_translation", {})

    def _build_rom(self):
        self.on_action("build_rom", {})

    def _finalize(self):
        confirmed = messagebox.askyesno(
            "Finalize Run",
            "Finalize will build the ROM, zip the current run folder, and remove the run from work. Continue?",
        )
        if not confirmed:
            return
        self.on_action("finalize", {})

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

    def _save_manual(self):
        key = self._selected_key()
        if not key:
            messagebox.showwarning("No Selection", "Select a row first.")
            return

        translated = self.manual_translation.get("1.0", "end").strip()
        self.on_action("manual_save", {"key": key, "translated": translated})
        self._update_row_translation(key, translated)
