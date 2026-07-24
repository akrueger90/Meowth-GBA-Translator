# Meowth GBA Translator

[![Tests](https://github.com/akrueger90/Meowth-GBA-Translator/actions/workflows/test.yml/badge.svg)](https://github.com/akrueger90/Meowth-GBA-Translator/actions/workflows/test.yml)
[![Desktop builds](https://github.com/akrueger90/Meowth-GBA-Translator/actions/workflows/build-gui.yml/badge.svg)](https://github.com/akrueger90/Meowth-GBA-Translator/actions/workflows/build-gui.yml)
[![Version](https://img.shields.io/badge/version-0.3.6-green.svg)](https://github.com/akrueger90/Meowth-GBA-Translator/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Meowth translates text in Pokémon Game Boy Advance ROMs and writes it back
without limiting translated labels to the original string length. It combines
official PokeAPI terminology with a free local translation model and provides
both a desktop GUI and CLI.

> Use only ROMs that you are legally allowed to modify. ROM files are never
> included in this repository or its releases.

## Highlights

- Free offline translation through CTranslate2 and Argos/OpenNMT models
- Official Pokémon, move, ability, item and location names from PokeAPI
- Editable Pokémon terminology without rebuilding the application
- Safe relocation of texts that are longer than their original ROM slots
- Preservation of ROM control codes, page breaks and placeholders
- Integrated review, manual correction, retry and resumable runs
- Optional OpenAI-compatible cloud providers
- Desktop builds for Windows x64, Linux x64, macOS Intel and Apple Silicon

## Download

Download a packaged desktop application from
[GitHub Releases](https://github.com/akrueger90/Meowth-GBA-Translator/releases):

| Platform | Release asset |
| --- | --- |
| Windows x64 | `Meowth-Translator-Windows-x64.zip` |
| Linux x64 | `Meowth-Translator-Linux-x64.tar.gz` |
| macOS Intel | `Meowth-Translator-macOS-x64.dmg` |
| macOS Apple Silicon | `Meowth-Translator-macOS-arm64.dmg` |

The applications are currently unsigned. Windows SmartScreen or macOS
Gatekeeper can therefore show a warning on first launch.

## GUI guide

Start the application, select a ROM and work from left to right.

### Configuration

| Field | Meaning |
| --- | --- |
| **ROM File** | Source `.gba` ROM. The source file is never overwritten. |
| **Output Directory** | Final ROMs, work files and resumable runs. |
| **Source / Target** | Languages used for PokeAPI and model translation. |
| **Provider Profiles** | Optional saved provider/model/API-key combinations. |
| **Provider** | Use `local` for free offline translation or select a cloud provider. |
| **Model** | Local model identifier or remote model name. |
| **API Key** | Required only for remote providers; disabled for `local`. |

Batch sizes, worker counts, table fallback and other internal settings are
selected automatically for the provider. The old Game Context, Advanced and
Category Settings panels are intentionally no longer needed.

### Translation workflow

1. **Prepare** copies the ROM into a resumable run, refreshes PokeAPI data and
   extracts all supported text.
2. **Start** translates PokeAPI matches first and sends only unresolved text to
   the selected provider. With an active category filter, only that category is
   processed.
3. **Stop** requests a safe cancellation. Completed work remains on disk.
4. Inspect the **Review** table. Red entries are suspected to be untranslated.
5. Use **LLM Selected** to retry selected rows or edit a row and choose
   **Save Manual**.
6. **Build Rom** creates a ROM from the current translations without closing
   the run.
7. **Finalize** builds the ROM, archives the run and removes it from the active
   work list.

Additional review controls:

- **Refresh** reloads the current translation file.
- **Select Suspects** selects all suspicious rows.
- **Next Untranslated** jumps to the next empty translation.
- Category buttons filter the review list.

## Translation behavior

The translation pipeline uses this fixed order:

1. Match official PokeAPI names and descriptions.
2. Apply user terminology and known ROM variants.
3. Protect matched Pokémon names and ROM control codes.
4. Translate unresolved table entries and dialogue with the configured
   provider.
5. Wrap and encode text for the target ROM.

Official Pokémon, region and location names are protected case-insensitively in
dialogue. Ambiguous move and item names are protected when the ROM uses their
uppercase name, such as `CUT` or `DOME FOSSIL`, avoiding false matches with
ordinary English words.

### Free local model

Select the `local` provider to translate without an API key or usage limit. The
language-pair model is downloaded once to:

```text
~/.meowth/models/argos
```

The first run requires internet access. Later translations work offline.

### Editable terminology

Meowth creates this file on first use:

```text
~/.meowth/terminology.toml
```

It contains language-specific terms and complete phrase overrides:

```toml
["en"."de"]
"HM" = "VM"
"HP" = "KP"
"LOST WOODS" = "Verlorener Wald"
"Deposit in which BOX?" = "In welcher Box ablegen?"
```

Edit the file and restart Meowth. No rebuild is necessary. Longer phrase
matches take priority, and changed terms automatically produce new translation
cache keys.

## Install from source

### Requirements

- Python 3.12 recommended
- .NET 8 SDK
- CMake and a C/C++ compiler for armips
- Git with submodule support

### macOS

```bash
git clone --recurse-submodules https://github.com/akrueger90/Meowth-GBA-Translator.git
cd Meowth-GBA-Translator
bash scripts/setup-dev-macos.sh
./.venv/bin/meowth-gui
```

VS Code also provides the `dev: setup mac` task and the
`Meowth GUI (Python)` launch configuration.

### Other platforms

```bash
git clone --recurse-submodules https://github.com/akrueger90/Meowth-GBA-Translator.git
cd Meowth-GBA-Translator
python3.12 -m venv .venv

# Linux/macOS
./.venv/bin/python -m pip install -e ".[gui,dev,local]"
./.venv/bin/meowth-gui

# Windows PowerShell
.\.venv\Scripts\python.exe -m pip install -e ".[gui,dev,local]"
.\.venv\Scripts\meowth-gui.exe
```

Build the bridge if no matching packaged binary is present:

```bash
dotnet build src/MeowthBridge/MeowthBridge.csproj -c Debug
```

## CLI

Run the complete local pipeline:

```bash
meowth full pokemon.gba \
  --provider local \
  --source en \
  --target de \
  --output-dir outputs
```

Or execute individual stages:

```bash
meowth extract pokemon.gba -o work/texts.json
meowth translate work/texts.json --provider local --target de -o work/translated.json
meowth build pokemon.gba --translations work/translated.json -o outputs/pokemon_de.gba
```

Run `meowth COMMAND --help` for all options.

## Configuration

`meowth.toml` provides CLI defaults:

```toml
[translation]
provider = "local"
model = "argos-opus"
source_language = "en"
target_language = "de"
terminology_file = "~/.meowth/terminology.toml"
llm_for_tables = true

[output]
dir = "outputs"
cache_dir = "work/cache"
```

Remote providers can define an API endpoint and environment variable:

```toml
[translation]
provider = "groq"
model = "llama-3.3-70b-versatile"

[translation.api]
key_env = "GROQ_API_KEY"
base_url = "https://api.groq.com/openai/v1"
```

Supported providers include local, DeepSeek, OpenAI, Anthropic, Google, Groq,
Mistral, OpenRouter, SiliconFlow, Zhipu, Moonshot and Qwen.

## Development

Run the existing validation suite:

```bash
python -m pytest -q tests
dotnet build src/MeowthBridge/MeowthBridge.csproj -c Debug
```

### CI and releases

GitHub Actions runs tests and creates downloadable build artifacts after every
push to `main`. Standard GitHub-hosted runners are free for public repositories.

A version tag creates one GitHub Release containing all desktop applications
and standalone MeowthBridge bundles:

```bash
git tag v0.3.6
git push origin v0.3.6
```

The tag should match the version in `pyproject.toml`. Release artifacts are
unsigned and do not contain ROMs or local model weights.

## Supported languages

- English (`en`)
- German (`de`)
- Spanish (`es`)
- French (`fr`)
- Italian (`it`)
- Simplified Chinese (`zh-Hans`)

Support depends on both PokeAPI language data and availability of a direct
local model or configured cloud provider.

## Troubleshooting

### Local model download fails

The first local translation needs internet access. Check the connection and
retry. Models already installed under `~/.meowth/models/argos` are reused.

### MeowthBridge cannot be found

Reinstall the packaged application, build the bridge with .NET 8, or set
`MEOWTH_BRIDGE_PATH` to a matching executable directory.

### macOS blocks the application

Open **System Settings → Privacy & Security** and choose **Open Anyway**, or
right-click the application and choose **Open**. Published builds are not yet
code-signed or notarized.

### Translation terminology is wrong

Add the source and desired target phrase to
`~/.meowth/terminology.toml`, restart Meowth and retry the affected rows.

## Credits

- [HexManiacAdvance](https://github.com/entropyus/HexManiacAdvance)
- [PokéAPI](https://pokeapi.co/)
- [Argos Translate](https://www.argosopentech.com/)
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)
- [Pokemon GBA Font Patch](https://github.com/Wokann/Pokemon_GBA_Font_Patch)
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)

## License

[MIT](LICENSE)
