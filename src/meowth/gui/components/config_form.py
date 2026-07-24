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
        elif key == "category_policies" and isinstance(value, dict):
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
        self._category_policies = {
            category: policy.copy()
            for category, policy in TranslationConfig().category_policies.items()
        }

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

        # --- LLM Profiles ---
        ctk.CTkLabel(inner, text="LLM Profiles", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
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
        ctk.CTkLabel(inner, text="LLM Provider", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
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
        self.provider.set("deepseek")
        self.provider.bind("<<ComboboxSelected>>", lambda e: self._on_provider_change(self.provider.get()))
        self.provider.bind("<<ComboboxSelected>>", lambda e: self._auto_save_config(), add=True)
        self.provider.pack(fill="x")

        model_frame = ctk.CTkFrame(pm_row, fg_color="transparent")
        model_frame.pack(side="right", fill="both", expand=True, padx=(6, 0))
        ctk.CTkLabel(model_frame, text="Model:", font=("", 10)).pack(anchor="w", pady=(0, 2))
        self.model_entry = ctk.CTkEntry(model_frame, height=32, corner_radius=8)
        self.model_entry.insert(0, PROVIDER_PRESETS["deepseek"][1])
        self.model_entry.pack(fill="x")
        # Bind to focus-out event to save when user finishes editing the model
        self.model_entry.bind("<FocusOut>", lambda e: self._auto_save_config())

        # --- API Key ---
        ctk.CTkLabel(inner, text="API Key", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
        self.api_key_entry = ctk.CTkEntry(
            inner,
            placeholder_text="sk-xxxxxxxxxxxxxxxxxxxxxxxx",
            height=32,
            corner_radius=8,
        )
        self.api_key_entry.pack(fill="x", pady=(0, 8))
        # Bind to focus-out event to save when user finishes editing the API key
        self.api_key_entry.bind("<FocusOut>", lambda e: self._auto_save_config())

        # --- Game Context ---
        ctk.CTkLabel(inner, text="Game Context (optional)", font=("", 11, "bold")).pack(anchor="w", pady=(8, 4))
        ctk.CTkLabel(
            inner,
            text="Describe the game so the LLM can translate more accurately (setting, tone, character names, etc.)",
            font=("", 10),
            text_color=("gray45", "gray55"),
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))
        self.game_context_entry = ctk.CTkTextbox(
            inner, height=72, corner_radius=8, wrap="word",
        )
        self.game_context_entry.pack(fill="x", pady=(0, 8))
        self.game_context_entry.bind("<FocusOut>", lambda e: self._auto_save_config())

        # --- Advanced (collapsible) ---
        self.advanced_visible = False
        self.advanced_button = ctk.CTkButton(
            inner, text="+ Advanced Settings", command=self._toggle_advanced,
            fg_color="transparent", text_color=("gray45", "gray55"),
            hover_color=("gray85", "gray25"), height=26, font=("", 11),
            anchor="w",
        )
        self.advanced_button.pack(anchor="w", pady=(4, 0))

        self.advanced_frame = ctk.CTkFrame(inner, fg_color="transparent")
        # All three advanced fields in one compact row
        adv_row_compact = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        adv_row_compact.pack(fill="x", pady=(6, 0))

        bf_compact = ctk.CTkFrame(adv_row_compact, fg_color="transparent")
        bf_compact.pack(side="left", fill="both", expand=True, padx=(0, 4))
        ctk.CTkLabel(bf_compact, text="Batch:", font=("", 9)).pack(anchor="w", pady=(0, 2))
        self.batch_size = ctk.CTkEntry(bf_compact, height=28, corner_radius=6)
        self.batch_size.insert(0, "30")
        self.batch_size.pack(fill="x")

        wf_compact = ctk.CTkFrame(adv_row_compact, fg_color="transparent")
        wf_compact.pack(side="left", fill="both", expand=True, padx=(4, 4))
        ctk.CTkLabel(wf_compact, text="Workers:", font=("", 9)).pack(anchor="w", pady=(0, 2))
        self.max_workers = ctk.CTkEntry(wf_compact, height=28, corner_radius=6)
        self.max_workers.insert(0, "10")
        self.max_workers.pack(fill="x")

        tlf_compact = ctk.CTkFrame(adv_row_compact, fg_color="transparent")
        tlf_compact.pack(side="left", fill="both", expand=True, padx=(4, 0))
        ctk.CTkLabel(tlf_compact, text="Test:", font=("", 9)).pack(anchor="w", pady=(0, 2))
        self.test_limit_texts = ctk.CTkEntry(tlf_compact, height=28, corner_radius=6)
        self.test_limit_texts.insert(0, "")
        self.test_limit_texts.pack(fill="x")
        ctk.CTkLabel(
            tlf_compact, text="0=all",
            font=("", 8), text_color=("gray55", "gray50"),
        ).pack(anchor="w", pady=(2, 0))

    def _on_profile_select(self, name: str) -> None:
        """Load a saved LLM profile into the provider/model/api_key fields."""
        profile = self._profiles.get(name)
        if not profile:
            return
        provider = profile.get("provider", "")
        if provider and provider in PROVIDER_PRESETS:
            self.provider.set(provider)
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
        if provider_name == "groq":
            # Free Groq accounts are heavily TPM-limited.
            # Safer defaults reduce rate-limit failures.
            self._set_entry_value(self.batch_size, "6")
            self._set_entry_value(self.max_workers, "2")
        elif provider_name == "openrouter":
            # OpenRouter free-tier keys can also be easily throttled.
            # Conservative defaults avoid immediate 429 storms.
            self._set_entry_value(self.batch_size, "4")
            self._set_entry_value(self.max_workers, "1")

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
            self.advanced_button.configure(text="+ Advanced Settings")
            self.advanced_visible = False
        else:
            self.advanced_frame.pack(fill="x", pady=(4, 0))
            self.advanced_button.configure(text="− Advanced Settings")
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
            "llm_profile": self.profile_combo.get().strip(),
            "provider": self.provider.get().strip(),
            "model": self.model_entry.get().strip(),
            "api_key": self.api_key_entry.get(),
            "batch_size": self.batch_size.get().strip(),
            "max_workers": self.max_workers.get().strip(),
            "test_limit_texts": self.test_limit_texts.get().strip(),
            "game_context": self.game_context_entry.get("1.0", "end-1c"),
            "advanced_visible": self.advanced_visible,
            "category_policies": self.get_category_policies(),
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

        batch_size = state.get("batch_size")
        if isinstance(batch_size, str):
            self._set_entry_value(self.batch_size, batch_size)

        max_workers = state.get("max_workers")
        if isinstance(max_workers, str):
            self._set_entry_value(self.max_workers, max_workers)

        test_limit_texts = state.get("test_limit_texts")
        if isinstance(test_limit_texts, str):
            self._set_entry_value(self.test_limit_texts, test_limit_texts)

        game_context = state.get("game_context")
        if isinstance(game_context, str):
            self.game_context_entry.delete("1.0", "end")
            self.game_context_entry.insert("1.0", game_context)

        advanced_visible = state.get("advanced_visible")
        if isinstance(advanced_visible, bool) and advanced_visible != self.advanced_visible:
            self._toggle_advanced()

        category_policies = state.get("category_policies")
        if isinstance(category_policies, dict):
            self.set_category_policies(category_policies)

    def load_state(self, path: Path = STATE_FILE_PATH) -> None:
        """Load saved form values from disk, if present."""
        self.apply_state(load_form_state(path))

    def save_state(self, path: Path = STATE_FILE_PATH) -> None:
        """Write current form values to disk."""
        save_form_state(self.get_state(), path)

    def set_category_policies(self, policies: dict[str, object]) -> None:
        """Store a validated copy of category translation policies."""
        normalized: dict[str, dict[str, bool]] = {}
        for category, policy in policies.items():
            if not isinstance(category, str) or not isinstance(policy, dict):
                continue
            use_glossary = policy.get("use_glossary")
            use_llm = policy.get("use_llm")
            if isinstance(use_glossary, bool) and isinstance(use_llm, bool):
                normalized[category] = {
                    "use_glossary": use_glossary,
                    "use_llm": use_llm,
                }
        if normalized:
            self._category_policies = normalized

    def get_category_policies(self) -> dict[str, dict[str, bool]]:
        """Return an independent copy of category translation policies."""
        return {
            category: policy.copy()
            for category, policy in self._category_policies.items()
        }

    def requires_llm(self) -> bool:
        """Return whether any configured category can call the LLM."""
        return any(
            policy.get("use_llm", True)
            for policy in self._category_policies.values()
        )

    def get_config(self) -> TranslationConfig:
        """Get current configuration."""
        provider = self.provider.get()
        preset = PROVIDER_PRESETS.get(provider)
        api_key = self.api_key_entry.get().strip()
        model_value = self.model_entry.get().strip() or (preset[1] if preset else None)
        batch_value = int(self.batch_size.get()) if self.batch_size.get().isdigit() else 30
        workers_value = int(self.max_workers.get()) if self.max_workers.get().isdigit() else 10

        # Safety guard for stale saved profiles/state: OpenRouter free-tier keys
        # are easily throttled when old high-concurrency values are restored.
        if provider == "openrouter":
            workers_value = min(workers_value, 1)
            batch_value = min(batch_value, 4)

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
            model=model_value,
            api_key_env=preset[2] if preset else None,
            api_key=api_key if api_key else None,
            batch_size=batch_value,
            max_workers=workers_value,
            test_limit_texts=test_limit,
            use_env_test_limit=False,
            game_context=self.game_context_entry.get("1.0", "end-1c").strip(),
            rom_path=Path(self.rom_entry.get()) if self.rom_entry.get() else None,
            output_dir=output_dir,
            work_dir=work_dir,
            category_policies=self.get_category_policies(),
        )

    def validate(self) -> tuple[bool, str]:
        """Validate configuration."""
        if not self.rom_entry.get():
            return False, "Please select a ROM file"
        rom_path = Path(self.rom_entry.get())
        if not rom_path.exists():
            return False, f"ROM file not found: {rom_path}"

        if self.requires_llm() and not self.api_key_entry.get().strip():
            provider = self.provider.get()
            preset = PROVIDER_PRESETS.get(provider)
            env_var = preset[2] if preset and len(preset) > 2 else None
            if not env_var or not os.environ.get(env_var):
                if env_var:
                    return False, f"Please enter your API key or set {env_var}"
                return False, "Please enter your API key"

        return True, ""
