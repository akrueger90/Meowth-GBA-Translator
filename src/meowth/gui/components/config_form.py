"""Configuration form component using CustomTkinter."""

import json
import os
from pathlib import Path
from tkinter import filedialog
from tkinter import messagebox
from tkinter import simpledialog
from tkinter import ttk

import customtkinter as ctk

from ...core import TranslationConfig
from ...translator import PROVIDER_PRESETS

# Language display name -> language code (must match languages.py)
LANGUAGES = {
    "English": "en",
    "Chinese": "zh-Hans",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
}

LANG_NAMES = list(LANGUAGES.keys())
LANGUAGE_CODES_TO_NAMES = {code: name for name, code in LANGUAGES.items()}
STATE_FILE_PATH = Path.home() / ".meowth" / "gui-form-state.json"
LLM_PROFILE_FIELDS = ("provider", "model", "api_key", "batch_size", "max_workers")


def _sanitize_llm_profiles(value: object) -> dict[str, dict[str, str]]:
    """Return validated LLM profiles loaded from persisted form state."""
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, dict[str, str]] = {}
    for profile_name, profile_data in value.items():
        if not isinstance(profile_name, str) or not profile_name.strip():
            continue
        if not isinstance(profile_data, dict):
            continue

        normalized: dict[str, str] = {}
        for field_name in LLM_PROFILE_FIELDS:
            raw_value = profile_data.get(field_name)
            if isinstance(raw_value, str):
                normalized[field_name] = raw_value

        if normalized:
            cleaned[profile_name.strip()] = normalized
    return cleaned


def load_form_state(path: Path = STATE_FILE_PATH) -> dict[str, object]:
    """Load persisted GUI form state from disk."""
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as state_file:
            data = json.load(state_file)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}

    if not isinstance(data, dict):
        return {}

    state: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, (str, bool)):
            state[key] = value
        elif key == "llm_profiles":
            state[key] = _sanitize_llm_profiles(value)
    return state


def save_form_state(state: dict[str, object], path: Path = STATE_FILE_PATH) -> None:
    """Persist GUI form state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, ensure_ascii=True, indent=2, sort_keys=True)


class ConfigForm(ctk.CTkFrame):
    """Configuration form for translation settings."""

    def __init__(self, master):
        """Initialize configuration form."""
        super().__init__(master, corner_radius=10)

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        # --- Row 1: ROM File ---
        ctk.CTkLabel(inner, text="ROM File", font=("", 12, "bold")).pack(anchor="w")
        rom_row = ctk.CTkFrame(inner, fg_color="transparent")
        rom_row.pack(fill="x", pady=(2, 8))
        self.rom_entry = ctk.CTkEntry(
            rom_row, placeholder_text="Select a GBA ROM file...", height=30
        )
        self.rom_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            rom_row, text="Browse", width=80, height=30, command=self._browse_rom
        ).pack(side="right")

        # --- Row 1.5: Output Directory ---
        ctk.CTkLabel(inner, text="Output Directory", font=("", 12, "bold")).pack(anchor="w")
        output_row = ctk.CTkFrame(inner, fg_color="transparent")
        output_row.pack(fill="x", pady=(2, 8))
        self.output_entry = ctk.CTkEntry(
            output_row, placeholder_text="Select output directory...", height=30
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            output_row, text="Browse", width=80, height=30, command=self._browse_output
        ).pack(side="right")

        # --- Row 2: Languages ---
        ctk.CTkLabel(inner, text="Languages", font=("", 12, "bold")).pack(anchor="w")
        lang_row = ctk.CTkFrame(inner, fg_color="transparent")
        lang_row.pack(fill="x", pady=(2, 8))

        src_frame = ctk.CTkFrame(lang_row, fg_color="transparent")
        src_frame.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(src_frame, text="Source:", font=("", 11)).pack(anchor="w")
        self.source_lang = ttk.Combobox(src_frame, values=LANG_NAMES, state="readonly", width=25)
        self.source_lang.set("English")
        self.source_lang.pack(fill="x", pady=(2, 0))

        tgt_frame = ctk.CTkFrame(lang_row, fg_color="transparent")
        tgt_frame.pack(side="right", fill="x", expand=True, padx=(6, 0))
        ctk.CTkLabel(tgt_frame, text="Target:", font=("", 11)).pack(anchor="w")
        self.target_lang = ttk.Combobox(tgt_frame, values=LANG_NAMES, state="readonly", width=25)
        self.target_lang.set("Chinese")
        self.target_lang.pack(fill="x", pady=(2, 0))

        # --- LLM Profile Presets ---
        self.llm_profiles: dict[str, dict[str, str]] = {}
        ctk.CTkLabel(inner, text="LLM Profiles", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
        profile_row = ctk.CTkFrame(inner, fg_color="transparent")
        profile_row.pack(fill="x", pady=(0, 8))

        self.llm_profile = ttk.Combobox(profile_row, values=[], state="readonly", height=5)
        self.llm_profile.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.llm_profile.bind("<<ComboboxSelected>>", lambda e: self._on_llm_profile_selected())

        ctk.CTkButton(
            profile_row,
            text="Save",
            width=64,
            height=30,
            corner_radius=8,
            command=self._save_current_llm_profile,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            profile_row,
            text="Delete",
            width=70,
            height=30,
            corner_radius=8,
            fg_color=("#B0413E", "#7B2E2C"),
            hover_color=("#972F2C", "#632321"),
            command=self._delete_selected_llm_profile,
        ).pack(side="left")

        # --- Provider + Model ---
        ctk.CTkLabel(inner, text="LLM Provider", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
        pm_row = ctk.CTkFrame(inner, fg_color="transparent")
        pm_row.pack(fill="x", pady=(2, 4))

        prov_frame = ctk.CTkFrame(pm_row, fg_color="transparent")
        prov_frame.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(prov_frame, text="Provider:", font=("", 11)).pack(anchor="w")
        self.provider = ttk.Combobox(prov_frame, values=list(PROVIDER_PRESETS.keys()), state="readonly", width=25)
        self.provider.set("deepseek")
        self.provider.bind("<<ComboboxSelected>>", lambda e: self._on_provider_change(self.provider.get()))
        self.provider.pack(fill="x", pady=(2, 0))

        model_frame = ctk.CTkFrame(pm_row, fg_color="transparent")
        model_frame.pack(side="right", fill="x", expand=True, padx=(6, 0))
        ctk.CTkLabel(model_frame, text="Model:", font=("", 11)).pack(anchor="w")
        self.model_entry = ctk.CTkEntry(model_frame, height=30)
        self.model_entry.insert(0, PROVIDER_PRESETS["deepseek"][1])
        self.model_entry.pack(fill="x", pady=(2, 0))

        # --- Row 4: API Key ---
        ctk.CTkLabel(inner, text="API Key:", font=("", 11)).pack(anchor="w", pady=(4, 0))
        self.api_key_entry = ctk.CTkEntry(
            inner, placeholder_text="sk-xxxxxxxxxxxxxxxxxxxxxxxx", height=30
        )
        self.api_key_entry.pack(fill="x", pady=(2, 0))

        # --- Advanced (collapsible) ---
        self.advanced_visible = False
        self.advanced_button = ctk.CTkButton(
            inner, text="+ Advanced", command=self._toggle_advanced,
            fg_color="transparent", text_color=("gray40", "gray60"),
            hover_color=("gray85", "gray25"), height=24, font=("", 11),
        )
        self.advanced_button.pack(anchor="w", pady=(6, 0))

        self.advanced_frame = ctk.CTkFrame(inner, fg_color="transparent")
        adv_row = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        adv_row.pack(fill="x", pady=(4, 0))

        bf = ctk.CTkFrame(adv_row, fg_color="transparent")
        bf.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(bf, text="Batch Size:", font=("", 11)).pack(anchor="w")
        self.batch_size = ctk.CTkEntry(bf, height=30)
        self.batch_size.insert(0, "30")
        self.batch_size.pack(fill="x", pady=(2, 0))

        wf = ctk.CTkFrame(adv_row, fg_color="transparent")
        wf.pack(side="right", fill="x", expand=True, padx=(6, 0))
        ctk.CTkLabel(wf, text="Max Workers:", font=("", 11)).pack(anchor="w")
        self.max_workers = ctk.CTkEntry(wf, height=30)
        self.max_workers.insert(0, "10")
        self.max_workers.pack(fill="x", pady=(2, 0))

        adv_row2 = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        adv_row2.pack(fill="x", pady=(4, 0))

        tlf = ctk.CTkFrame(adv_row2, fg_color="transparent")
        tlf.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(tlf, text="Test Limit (texts):", font=("", 11)).pack(anchor="w")
        self.test_limit_texts = ctk.CTkEntry(tlf, height=30)
        self.test_limit_texts.insert(0, "")
        self.test_limit_texts.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(tlf, text="Leave empty or 0 to translate all texts", font=("", 9), text_color="gray").pack(anchor="w", pady=(2, 0))

    def _refresh_llm_profiles(self, selected_name: str | None = None) -> None:
        """Update profile dropdown values and selected profile."""
        names = sorted(self.llm_profiles.keys())
        self.llm_profile.configure(values=names)

        if not names:
            self.llm_profile.set("")
            return

        if selected_name and selected_name in self.llm_profiles:
            self.llm_profile.set(selected_name)
            return

        current = self.llm_profile.get().strip()
        if current in self.llm_profiles:
            self.llm_profile.set(current)
            return

        self.llm_profile.set(names[0])

    def _current_llm_profile_values(self) -> dict[str, str]:
        """Collect current LLM controls into a profile-shaped dict."""
        return {
            "provider": self.provider.get().strip(),
            "model": self.model_entry.get().strip(),
            "api_key": self.api_key_entry.get(),
            "batch_size": self.batch_size.get().strip(),
            "max_workers": self.max_workers.get().strip(),
        }

    def _apply_llm_profile_values(self, profile: dict[str, str]) -> None:
        """Apply a saved LLM profile to visible form controls."""
        provider = profile.get("provider", "").strip()
        if provider and provider in PROVIDER_PRESETS:
            self.provider.set(provider)

        model = profile.get("model")
        if isinstance(model, str):
            self._set_entry_value(self.model_entry, model)

        api_key = profile.get("api_key")
        if isinstance(api_key, str):
            self._set_entry_value(self.api_key_entry, api_key)

        batch_size = profile.get("batch_size")
        if isinstance(batch_size, str):
            self._set_entry_value(self.batch_size, batch_size)

        max_workers = profile.get("max_workers")
        if isinstance(max_workers, str):
            self._set_entry_value(self.max_workers, max_workers)

    def _on_llm_profile_selected(self) -> None:
        """Apply selected LLM profile values."""
        profile_name = self.llm_profile.get().strip()
        profile = self.llm_profiles.get(profile_name)
        if profile:
            self._apply_llm_profile_values(profile)

    def _save_current_llm_profile(self) -> None:
        """Save current LLM controls under a profile name."""
        suggested_name = self.llm_profile.get().strip() or self.provider.get().strip() or "default"
        profile_name = simpledialog.askstring(
            "Save LLM Profile",
            "Profile name:",
            initialvalue=suggested_name,
            parent=self,
        )
        if profile_name is None:
            return

        name = profile_name.strip()
        if not name:
            messagebox.showwarning("Invalid Name", "Please enter a profile name.")
            return

        self.llm_profiles[name] = self._current_llm_profile_values()
        self._refresh_llm_profiles(selected_name=name)
        self.save_state()

    def _delete_selected_llm_profile(self) -> None:
        """Delete currently selected LLM profile from persisted state."""
        profile_name = self.llm_profile.get().strip()
        if not profile_name:
            messagebox.showwarning("No Profile Selected", "Please select a profile to delete.")
            return
        if profile_name not in self.llm_profiles:
            return

        confirmed = messagebox.askyesno(
            "Delete LLM Profile",
            f"Delete profile '{profile_name}'?",
            parent=self,
        )
        if not confirmed:
            return

        del self.llm_profiles[profile_name]
        self._refresh_llm_profiles()
        self.save_state()

    def _on_provider_change(self, provider_name: str):
        """Update default model when provider changes."""
        preset = PROVIDER_PRESETS.get(provider_name)
        if preset:
            self.model_entry.delete(0, "end")
            self.model_entry.insert(0, preset[1])
        if provider_name == "groq":
            # Free Groq accounts are heavily TPM-limited.
            # Safer defaults reduce rate-limit failures.
            self._set_entry_value(self.batch_size, "6")
            self._set_entry_value(self.max_workers, "2")

    def _browse_rom(self):
        """Open file dialog to select ROM."""
        filename = filedialog.askopenfilename(
            title="Select GBA ROM",
            filetypes=[("GBA ROM files", "*.gba"), ("All files", "*.*")],
        )
        if filename:
            self.rom_entry.delete(0, "end")
            self.rom_entry.insert(0, filename)

    def _browse_output(self):
        """Open directory dialog to select output directory."""
        dirname = filedialog.askdirectory(
            title="Select Output Directory",
        )
        if dirname:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, dirname)

    def _toggle_advanced(self):
        """Toggle advanced settings visibility."""
        if self.advanced_visible:
            self.advanced_frame.pack_forget()
            self.advanced_button.configure(text="+ Advanced")
            self.advanced_visible = False
        else:
            self.advanced_frame.pack(fill="x")
            self.advanced_button.configure(text="- Advanced")
            self.advanced_visible = True

    def _lang_name_to_code(self, name: str) -> str:
        return LANGUAGES.get(name, "en")

    def _lang_code_to_name(self, code: str) -> str:
        return LANGUAGE_CODES_TO_NAMES.get(code, "English")

    def _set_entry_value(self, entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)

    def get_state(self) -> dict[str, object]:
        """Return current form values in a serializable shape."""
        return {
            "rom_path": self.rom_entry.get().strip(),
            "output_dir": self.output_entry.get().strip(),
            "source_lang": self._lang_name_to_code(self.source_lang.get()),
            "target_lang": self._lang_name_to_code(self.target_lang.get()),
            "llm_profiles": self.llm_profiles,
            "selected_llm_profile": self.llm_profile.get().strip(),
            "provider": self.provider.get().strip(),
            "model": self.model_entry.get().strip(),
            "api_key": self.api_key_entry.get(),
            "batch_size": self.batch_size.get().strip(),
            "max_workers": self.max_workers.get().strip(),
            "test_limit_texts": self.test_limit_texts.get().strip(),
            "advanced_visible": self.advanced_visible,
        }

    def apply_state(self, state: dict[str, object]) -> None:
        """Apply previously saved values to the form."""
        rom_path = state.get("rom_path")
        if isinstance(rom_path, str):
            self._set_entry_value(self.rom_entry, rom_path)

        output_dir = state.get("output_dir")
        if isinstance(output_dir, str):
            self._set_entry_value(self.output_entry, output_dir)

        source_lang = state.get("source_lang")
        if isinstance(source_lang, str):
            self.source_lang.set(self._lang_code_to_name(source_lang))

        target_lang = state.get("target_lang")
        if isinstance(target_lang, str):
            self.target_lang.set(self._lang_code_to_name(target_lang))

        llm_profiles = _sanitize_llm_profiles(state.get("llm_profiles"))
        if llm_profiles:
            self.llm_profiles = llm_profiles
        self._refresh_llm_profiles()

        selected_llm_profile = state.get("selected_llm_profile")
        if isinstance(selected_llm_profile, str) and selected_llm_profile in self.llm_profiles:
            self.llm_profile.set(selected_llm_profile)
            self._on_llm_profile_selected()

        provider = state.get("provider")
        if isinstance(provider, str) and provider in PROVIDER_PRESETS:
            self.provider.set(provider)

        model = state.get("model")
        if isinstance(model, str):
            self._set_entry_value(self.model_entry, model)

        api_key = state.get("api_key")
        if isinstance(api_key, str):
            self._set_entry_value(self.api_key_entry, api_key)

        batch_size = state.get("batch_size")
        if isinstance(batch_size, str):
            self._set_entry_value(self.batch_size, batch_size)

        max_workers = state.get("max_workers")
        if isinstance(max_workers, str):
            self._set_entry_value(self.max_workers, max_workers)

        test_limit_texts = state.get("test_limit_texts")
        if isinstance(test_limit_texts, str):
            self._set_entry_value(self.test_limit_texts, test_limit_texts)

        advanced_visible = state.get("advanced_visible")
        if isinstance(advanced_visible, bool) and advanced_visible != self.advanced_visible:
            self._toggle_advanced()

    def load_state(self, path: Path = STATE_FILE_PATH) -> None:
        """Load saved form values from disk, if present."""
        self.apply_state(load_form_state(path))

        if not self.llm_profiles:
            # Bootstrap with one profile so users can switch/save quickly.
            self.llm_profiles = {"default": self._current_llm_profile_values()}
            self._refresh_llm_profiles(selected_name="default")

    def save_state(self, path: Path = STATE_FILE_PATH) -> None:
        """Write current form values to disk."""
        save_form_state(self.get_state(), path)

    def get_config(self) -> TranslationConfig:
        """Get current configuration."""
        provider = self.provider.get()
        preset = PROVIDER_PRESETS.get(provider)
        api_key = self.api_key_entry.get().strip()
        defaults = TranslationConfig()

        output_value = self.output_entry.get().strip()
        if output_value:
            output_dir = Path(output_value).expanduser()
            # Keep temporary work artifacts close to selected output directory.
            work_dir = output_dir / "work"
        else:
            output_dir = defaults.output_dir
            work_dir = defaults.work_dir

        test_limit_value = self.test_limit_texts.get().strip()
        test_limit = int(test_limit_value) if test_limit_value and test_limit_value.isdigit() and int(test_limit_value) > 0 else None

        return TranslationConfig(
            source_lang=self._lang_name_to_code(self.source_lang.get()),
            target_lang=self._lang_name_to_code(self.target_lang.get()),
            provider=provider if provider else None,
            model=self.model_entry.get().strip() or (preset[1] if preset else None),
            api_key_env=preset[2] if preset else None,
            api_key=api_key if api_key else None,
            batch_size=int(self.batch_size.get()) if self.batch_size.get().isdigit() else 30,
            max_workers=int(self.max_workers.get()) if self.max_workers.get().isdigit() else 10,
            test_limit_texts=test_limit,
            use_env_test_limit=False,
            rom_path=Path(self.rom_entry.get()) if self.rom_entry.get() else None,
            output_dir=output_dir,
            work_dir=work_dir,
        )

    def validate(self) -> tuple[bool, str]:
        """Validate configuration."""
        if not self.rom_entry.get():
            return False, "Please select a ROM file"
        rom_path = Path(self.rom_entry.get())
        if not rom_path.exists():
            return False, f"ROM file not found: {rom_path}"

        if not self.api_key_entry.get().strip():
            provider = self.provider.get()
            preset = PROVIDER_PRESETS.get(provider)
            env_var = preset[2] if preset and len(preset) > 2 else None
            if not env_var or not os.environ.get(env_var):
                if env_var:
                    return False, f"Please enter your API key or set {env_var}"
                return False, "Please enter your API key"

        return True, ""


