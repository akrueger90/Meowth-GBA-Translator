"""Configuration form component using CustomTkinter."""

import json
import os
from pathlib import Path
from tkinter import filedialog
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
LLM_PROFILES_FILE = Path.home() / ".meowth" / "llm-profiles.json"

# Shape stored per profile: {provider, model, api_key}
_LLMProfile = dict[str, str]


def provider_requires_api_key(provider: str) -> bool:
    """Return whether a translation provider requires remote credentials."""
    return provider != "local"


def provider_runtime_defaults(provider: str) -> tuple[int, int]:
    """Return fixed batch and worker values tuned for each provider."""
    if provider == "local":
        return 16, 1
    if provider == "groq":
        return 6, 2
    if provider == "openrouter":
        return 4, 1
    return 30, 10


def load_llm_profiles(path: Path = LLM_PROFILES_FILE) -> dict[str, _LLMProfile]:
    """Load named LLM profiles from disk."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, dict)}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_llm_profiles(profiles: dict[str, _LLMProfile], path: Path = LLM_PROFILES_FILE) -> None:
    """Persist named LLM profiles to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=True, indent=2, sort_keys=True)


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
        super().__init__(master, corner_radius=12, fg_color=("gray95", "gray14"))
        # Use a regular frame, not scrollable - the parent handles scrolling
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14, pady=12)

        # --- ROM File ---
        ctk.CTkLabel(inner, text="ROM File", font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))
        rom_row = ctk.CTkFrame(inner, fg_color="transparent")
        rom_row.pack(fill="x", pady=(0, 8))
        self.rom_entry = ctk.CTkEntry(
            rom_row, placeholder_text="Select a .gba ROM file…", height=32,
        )
        self.rom_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            rom_row, text="Browse", width=80, height=32,
            corner_radius=8, command=self._browse_rom,
        ).pack(side="right")

        # --- Output Directory ---
        ctk.CTkLabel(inner, text="Output Directory", font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))
        output_row = ctk.CTkFrame(inner, fg_color="transparent")
        output_row.pack(fill="x", pady=(0, 8))
        self.output_entry = ctk.CTkEntry(
            output_row, placeholder_text="Select output directory…", height=32,
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            output_row, text="Browse", width=80, height=32,
            corner_radius=8, command=self._browse_output,
        ).pack(side="right")

        # --- Languages ---
        ctk.CTkLabel(inner, text="Translation Languages", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
        lang_row = ctk.CTkFrame(inner, fg_color="transparent")
        lang_row.pack(fill="x", pady=(0, 8))

        src_frame = ctk.CTkFrame(lang_row, fg_color="transparent")
        src_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ctk.CTkLabel(src_frame, text="Source:", font=("", 10)).pack(anchor="w", pady=(0, 2))
        self.source_lang = ttk.Combobox(src_frame, values=LANG_NAMES, state="readonly", height=5)
        self.source_lang.set("English")
        self.source_lang.pack(fill="x")

        tgt_frame = ctk.CTkFrame(lang_row, fg_color="transparent")
        tgt_frame.pack(side="right", fill="both", expand=True, padx=(6, 0))
        ctk.CTkLabel(tgt_frame, text="Target:", font=("", 10)).pack(anchor="w", pady=(0, 2))
        self.target_lang = ttk.Combobox(tgt_frame, values=LANG_NAMES, state="readonly", height=5)
        self.target_lang.set("Chinese")
        self.target_lang.pack(fill="x")

        # --- Provider Profiles ---
        ctk.CTkLabel(inner, text="Provider Profiles", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
        profile_row = ctk.CTkFrame(inner, fg_color="transparent")
        profile_row.pack(fill="x", pady=(0, 8))
        self._profiles: dict[str, _LLMProfile] = load_llm_profiles()
        self.profile_combo = ttk.Combobox(
            profile_row,
            values=sorted(self._profiles.keys()),
            height=5,
        )
        self.profile_combo.set("")
        self.profile_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda e: self._on_profile_select(self.profile_combo.get()))
        ctk.CTkButton(
            profile_row, text="Save", width=70, height=32,
            corner_radius=8, command=self._save_profile,
        ).pack(side="right")

        # --- Provider + Model ---
        ctk.CTkLabel(inner, text="Translation Provider", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
        pm_row = ctk.CTkFrame(inner, fg_color="transparent")
        pm_row.pack(fill="x", pady=(0, 8))

        prov_frame = ctk.CTkFrame(pm_row, fg_color="transparent")
        prov_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ctk.CTkLabel(prov_frame, text="Provider:", font=("", 10)).pack(anchor="w", pady=(0, 2))
        self.provider = ttk.Combobox(
            prov_frame,
            values=list(PROVIDER_PRESETS.keys()),
            state="readonly",
            height=5,
        )
        self.provider.set("local")
        self.provider.bind("<<ComboboxSelected>>", lambda e: self._on_provider_change(self.provider.get()))
        self.provider.bind("<<ComboboxSelected>>", lambda e: self._auto_save_config(), add=True)
        self.provider.pack(fill="x")

        model_frame = ctk.CTkFrame(pm_row, fg_color="transparent")
        model_frame.pack(side="right", fill="both", expand=True, padx=(6, 0))
        ctk.CTkLabel(model_frame, text="Model:", font=("", 10)).pack(anchor="w", pady=(0, 2))
        self.model_entry = ctk.CTkEntry(model_frame, height=32, corner_radius=8)
        self.model_entry.insert(0, PROVIDER_PRESETS["local"][1])
        self.model_entry.pack(fill="x")
        # Bind to focus-out event to save when user finishes editing the model
        self.model_entry.bind("<FocusOut>", lambda e: self._auto_save_config())

        # --- API Key ---
        ctk.CTkLabel(inner, text="API Key (remote providers only)", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
        self.api_key_entry = ctk.CTkEntry(
            inner,
            placeholder_text="sk-xxxxxxxxxxxxxxxxxxxxxxxx",
            height=32,
            corner_radius=8,
        )
        self.api_key_entry.pack(fill="x", pady=(0, 8))
        # Bind to focus-out event to save when user finishes editing the API key
        self.api_key_entry.bind("<FocusOut>", lambda e: self._auto_save_config())

        self._on_provider_change(self.provider.get())

    def _on_profile_select(self, name: str) -> None:
        """Load a saved LLM profile into the provider/model/api_key fields."""
        profile = self._profiles.get(name)
        if not profile:
            return
        provider = profile.get("provider", "")
        if provider and provider in PROVIDER_PRESETS:
            self.provider.set(provider)
            self._on_provider_change(provider)
        model = profile.get("model", "")
        if model:
            self._set_entry_value(self.model_entry, model)
        api_key = profile.get("api_key", "")
        self._set_entry_value(self.api_key_entry, api_key)
        # Auto-save after loading a profile
        self._auto_save_config()

    def _save_profile(self) -> None:
        """Save current provider/model/api_key under the profile name in the combobox."""
        name = self.profile_combo.get().strip()
        if not name:
            return
        self._profiles[name] = {
            "provider": self.provider.get().strip(),
            "model": self.model_entry.get().strip(),
            "api_key": self.api_key_entry.get(),
        }
        save_llm_profiles(self._profiles)
        self.profile_combo.configure(values=sorted(self._profiles.keys()))
        self.profile_combo.set(name)

    def _auto_save_config(self) -> None:
        """Auto-save the current configuration whenever LLM config changes."""
        try:
            self.save_state()
        except Exception as exc:
            # Silently ignore save errors to avoid disrupting the user
            pass

    def _on_provider_change(self, provider_name: str):
        """Update default model when provider changes."""
        preset = PROVIDER_PRESETS.get(provider_name)
        if preset:
            self.model_entry.delete(0, "end")
            self.model_entry.insert(0, preset[1])
        if hasattr(self, "api_key_entry"):
            self.api_key_entry.configure(
                state="disabled" if provider_name == "local" else "normal"
            )

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
            "llm_profile": self.profile_combo.get().strip(),
            "provider": self.provider.get().strip(),
            "model": self.model_entry.get().strip(),
            "api_key": self.api_key_entry.get(),
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

        # Restore individual LLM fields from state first (fallback if no profile).
        provider = state.get("provider")
        if isinstance(provider, str) and provider in PROVIDER_PRESETS:
            self.provider.set(provider)
            self._on_provider_change(provider)

        model = state.get("model")
        if isinstance(model, str):
            self._set_entry_value(self.model_entry, model)

        api_key = state.get("api_key")
        if isinstance(api_key, str):
            self._set_entry_value(self.api_key_entry, api_key)

        # If a named profile was active, apply it last so it wins over stale state values.
        llm_profile = state.get("llm_profile")
        if isinstance(llm_profile, str) and llm_profile:
            self.profile_combo.set(llm_profile)
            self._on_profile_select(llm_profile)

    def load_state(self, path: Path = STATE_FILE_PATH) -> None:
        """Load saved form values from disk, if present."""
        self.apply_state(load_form_state(path))

    def save_state(self, path: Path = STATE_FILE_PATH) -> None:
        """Write current form values to disk."""
        save_form_state(self.get_state(), path)

    def get_config(self) -> TranslationConfig:
        """Get current configuration."""
        provider = self.provider.get()
        preset = PROVIDER_PRESETS.get(provider)
        api_key = self.api_key_entry.get().strip()
        model_value = self.model_entry.get().strip() or (preset[1] if preset else None)
        batch_value, workers_value = provider_runtime_defaults(provider)

        defaults = TranslationConfig()

        output_value = self.output_entry.get().strip()
        if output_value:
            output_dir = Path(output_value).expanduser()
            # Keep temporary work artifacts close to selected output directory.
            work_dir = output_dir / "work"
        else:
            output_dir = defaults.output_dir
            work_dir = defaults.work_dir

        return TranslationConfig(
            source_lang=self._lang_name_to_code(self.source_lang.get()),
            target_lang=self._lang_name_to_code(self.target_lang.get()),
            provider=provider if provider else None,
            model=model_value,
            api_key_env=preset[2] if preset else None,
            api_key=api_key if api_key else None,
            batch_size=batch_value,
            max_workers=workers_value,
            llm_for_tables=True,
            test_limit_texts=None,
            use_env_test_limit=False,
            game_context="",
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

        if (
            provider_requires_api_key(self.provider.get())
            and not self.api_key_entry.get().strip()
        ):
            provider = self.provider.get()
            preset = PROVIDER_PRESETS.get(provider)
            env_var = preset[2] if preset and len(preset) > 2 else None
            if not env_var or not os.environ.get(env_var):
                if env_var:
                    return False, f"Please enter your API key or set {env_var}"
                return False, "Please enter your API key"

        return True, ""
