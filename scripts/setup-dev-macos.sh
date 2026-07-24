#!/bin/bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

export PATH="$HOME/.local/bin:$HOME/.dotnet:$PATH"
export DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.dotnet}"

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required. Install it from https://docs.astral.sh/uv/." >&2
    exit 1
fi

if ! command -v dotnet >/dev/null 2>&1; then
    echo "Error: .NET 8 SDK is required. Install it in ~/.dotnet or add it to PATH." >&2
    exit 1
fi

git submodule update --init HexManiacAdvance pokeapi
if [[ ! -x .venv/bin/python ]]; then
    uv venv --python 3.12
fi
uv pip install --python .venv/bin/python -e ".[gui,dev]"
dotnet build src/MeowthBridge/MeowthBridge.csproj -c Debug
