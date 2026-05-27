"""Category-level translation policy settings dialog."""

from typing import Callable, Any
from tkinter import ttk

import customtkinter as ctk


class CategorySettingsDialog(ctk.CTkToplevel):
    """Dialog for managing per-category translation policies."""

    def __init__(
        self,
        master,
        category_policies: dict[str, dict[str, bool]],
        on_apply: Callable[[dict[str, dict[str, bool]]], None],
    ):
        super().__init__(master)
        self.title("Category Settings")
        self.geometry("600x500")
        self.resizable(True, True)
        
        self.category_policies = {cat: policy.copy() for cat, policy in category_policies.items()}
        self.on_apply = on_apply
        self._category_widgets: dict[str, dict[str, ctk.CTkCheckBox]] = {}
        
        self._build_ui()
        
        # Make dialog modal
        self.transient(master)
        self.grab_set()

    def _build_ui(self):
        """Build the settings dialog UI."""
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 12))
        
        ctk.CTkLabel(
            header,
            text="Translation Policies by Category",
            font=("", 14, "bold"),
        ).pack(anchor="w")
        
        ctk.CTkLabel(
            header,
            text="Configure which categories use glossary (PokeAPI) and LLM translation.",
            font=("", 11),
            text_color=("gray45", "gray65"),
            wraplength=550,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # Scrollable frame for categories
        canvas_frame = ctk.CTkFrame(self)
        canvas_frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        
        self.canvas = ctk.CTkCanvas(
            canvas_frame,
            bg=self._apply_appearance_mode(("#f0f0f0", "#212121")),
            highlightthickness=0,
            height=300,
        )
        self.canvas.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        self.scrollable_frame = ctk.CTkFrame(
            self.canvas,
            fg_color=self._apply_appearance_mode(("#f0f0f0", "#212121")),
        )
        self.canvas_window = self.canvas.create_window(
            0, 0, window=self.scrollable_frame, anchor="nw"
        )
        
        # Bind canvas resize to update scroll region
        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Build category rows
        for category in sorted(self.category_policies.keys()):
            policy = self.category_policies[category]
            self._build_category_row(category, policy)

        # Control buttons
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=16, pady=(0, 16))
        
        ctk.CTkButton(
            controls,
            text="Apply",
            width=100,
            command=self._on_apply,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        ).pack(side="right", padx=(6, 0))
        
        ctk.CTkButton(
            controls,
            text="Cancel",
            width=100,
            command=self.destroy,
        ).pack(side="right")

    def _build_category_row(self, category: str, policy: dict[str, bool]) -> None:
        """Build a row for a single category."""
        row = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(8, 0))
        
        # Category name
        display_name = category.replace("_", " ").title()
        ctk.CTkLabel(
            row,
            text=display_name,
            font=("", 11, "bold"),
            width=200,
            anchor="w",
        ).pack(side="left", padx=(0, 12))
        
        # Checkboxes
        if category not in self._category_widgets:
            self._category_widgets[category] = {}
        
        use_glossary_var = ctk.BooleanVar(value=policy.get("use_glossary", True))
        use_llm_var = ctk.BooleanVar(value=policy.get("use_llm", True))
        
        glossary_cb = ctk.CTkCheckBox(
            row,
            text="Use Glossary",
            variable=use_glossary_var,
            font=("", 10),
            width=20,
        )
        glossary_cb.pack(side="left", padx=6)
        self._category_widgets[category]["glossary"] = glossary_cb
        
        llm_cb = ctk.CTkCheckBox(
            row,
            text="Use LLM",
            variable=use_llm_var,
            font=("", 10),
            width=20,
        )
        llm_cb.pack(side="left", padx=6)
        self._category_widgets[category]["llm"] = llm_cb
        
        # Store variable references for later retrieval
        self._category_widgets[category]["glossary_var"] = use_glossary_var
        self._category_widgets[category]["llm_var"] = use_llm_var

    def _on_frame_configure(self, event: Any = None) -> None:
        """Update scroll region when frame resizes."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: Any = None) -> None:
        """Update scrollable frame width when canvas resizes."""
        self.scrollable_frame.configure(width=event.width)

    def _on_apply(self) -> None:
        """Save category policies and close dialog."""
        # Collect updated policies
        updated_policies = {}
        for category, widgets in self._category_widgets.items():
            updated_policies[category] = {
                "use_glossary": widgets.get("glossary_var", ctk.BooleanVar(value=True)).get(),
                "use_llm": widgets.get("llm_var", ctk.BooleanVar(value=True)).get(),
            }
        
        # Call callback
        self.on_apply(updated_policies)
        
        # Close dialog
        self.destroy()

    @staticmethod
    def _apply_appearance_mode(colors: tuple[str, str]) -> str:
        """Get color based on current appearance mode."""
        import customtkinter as ctk
        mode = ctk.get_appearance_mode()
        return colors[1] if mode == "Dark" else colors[0]
