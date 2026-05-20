"""Review dialog for translation retry workflow."""

from tkinter import ttk

import customtkinter as ctk


class ReviewDialog(ctk.CTkToplevel):
    """Modal dialog to review suspect translations and choose next action."""

    def __init__(self, master, candidates: list[dict], on_action):
        super().__init__(master)
        self.title("Review Translations")
        self.geometry("1100x620")
        self.minsize(900, 500)
        self.candidates = candidates
        self.on_action = on_action

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._build_ui()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            header,
            text="Review Suspect Entries",
            font=("", 18, "bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=(
                "Entries shown below were untranslated or unchanged. "
                "Select any rows and retry only those entries."
            ),
            text_color=("gray40", "gray70"),
            font=("", 12),
        ).pack(anchor="w", pady=(2, 0))

        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(
            summary,
            text=f"Suspect entries: {len(self.candidates)}",
            font=("", 12, "bold"),
        ).pack(anchor="w")

        table_container = ctk.CTkFrame(self)
        table_container.pack(fill="both", expand=True, padx=16, pady=(0, 12))

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

        # Internal key column is hidden but kept for robust selection mapping.
        self.tree.column("key", width=0, minwidth=0, stretch=False)
        self.tree.column("id", width=160, minwidth=120, stretch=False)
        self.tree.column("category", width=150, minwidth=120, stretch=False)
        self.tree.column("original", width=360, minwidth=220, stretch=True)
        self.tree.column("translated", width=360, minwidth=220, stretch=True)

        y_scroll = ttk.Scrollbar(table_container, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)

        for idx, candidate in enumerate(self.candidates):
            self.tree.insert(
                "",
                "end",
                iid=f"row_{idx}",
                values=(
                    candidate["key"],
                    candidate.get("entry_id", ""),
                    candidate.get("category", ""),
                    candidate.get("original", ""),
                    candidate.get("translated", ""),
                ),
            )

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(
            controls,
            text="Select All",
            width=100,
            command=self._select_all,
        ).pack(side="left")

        ctk.CTkButton(
            controls,
            text="Clear Selection",
            width=130,
            command=self._clear_selection,
            fg_color="#4b5563",
            hover_color="#374151",
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            controls,
            text="Cancel",
            width=100,
            command=self._cancel,
            fg_color="#4b5563",
            hover_color="#374151",
        ).pack(side="right")

        ctk.CTkButton(
            controls,
            text="Continue Build",
            width=130,
            command=self._continue,
            fg_color="#16a34a",
            hover_color="#15803d",
        ).pack(side="right", padx=(0, 8))

        ctk.CTkButton(
            controls,
            text="Retry Selected",
            width=130,
            command=self._retry_selected,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        ).pack(side="right", padx=(0, 8))

    def _selected_keys(self) -> list[str]:
        keys: list[str] = []
        for row_id in self.tree.selection():
            values = self.tree.item(row_id, "values")
            if values and values[0]:
                keys.append(values[0])
        return keys

    def _select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def _clear_selection(self):
        self.tree.selection_remove(self.tree.selection())

    def _retry_selected(self):
        self.on_action("retry", self._selected_keys())
        self.destroy()

    def _continue(self):
        self.on_action("continue", [])
        self.destroy()

    def _cancel(self):
        self.on_action("cancel", [])
        self.destroy()
