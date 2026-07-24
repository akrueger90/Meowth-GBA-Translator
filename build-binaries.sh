#!/bin/bash
# Build MeowthBridge for all platforms locally
# This is useful for testing the packaging before pushing to GitHub

set -e

echo "=== Building MeowthBridge for all platforms ==="
echo ""

# Check if dotnet is installed
if ! command -v dotnet &> /dev/null; then
    echo "Error: dotnet CLI not found. Please install .NET 8.0 SDK."
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSHARP_PROJECT="$PROJECT_ROOT/src/MeowthBridge"
OUTPUT_DIR="$PROJECT_ROOT/src/meowth/binaries"

# Build for Linux
echo "Building for Linux (x64)..."
dotnet publish "$CSHARP_PROJECT" \
    -c Release \
    -r linux-x64 \
    --self-contained true \
    -p:PublishSingleFile=true \
    -p:PublishTrimmed=true \
    -p:IncludeNativeLibrariesForSelfExtract=true \
    -o "$OUTPUT_DIR/linux"

chmod +x "$OUTPUT_DIR/linux/MeowthBridge"
echo "✓ Linux binary built: $(du -h "$OUTPUT_DIR/linux/MeowthBridge" | cut -f1)"
echo ""

# Build for Windows
echo "Building for Windows (x64)..."
dotnet publish "$CSHARP_PROJECT" \
    -c Release \
    -r win-x64 \
    --self-contained true \
    -p:PublishSingleFile=true \
    -p:PublishTrimmed=true \
    -p:IncludeNativeLibrariesForSelfExtract=true \
    -o "$OUTPUT_DIR/windows"

echo "✓ Windows binary built: $(du -h "$OUTPUT_DIR/windows/MeowthBridge.exe" | cut -f1)"
echo ""

# Build complete, architecture-specific macOS bundles. A universal apphost
# cannot load native runtime libraries from only one architecture.
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Building for macOS (x64 and arm64)..."

    dotnet publish "$CSHARP_PROJECT" \
        -c Release \
        -r osx-x64 \
        --self-contained true \
        -p:PublishSingleFile=true \
        -p:PublishTrimmed=true \
        -p:IncludeNativeLibrariesForSelfExtract=true \
        -o "$OUTPUT_DIR/macos-x64"

    dotnet publish "$CSHARP_PROJECT" \
        -c Release \
        -r osx-arm64 \
        --self-contained true \
        -p:PublishSingleFile=true \
        -p:PublishTrimmed=true \
        -p:IncludeNativeLibrariesForSelfExtract=true \
        -o "$OUTPUT_DIR/macos-arm64"

    chmod +x "$OUTPUT_DIR/macos-x64/MeowthBridge"
    chmod +x "$OUTPUT_DIR/macos-arm64/MeowthBridge"
    echo "✓ macOS x64 bundle built: $(du -sh "$OUTPUT_DIR/macos-x64" | cut -f1)"
    echo "✓ macOS arm64 bundle built: $(du -sh "$OUTPUT_DIR/macos-arm64" | cut -f1)"
else
    echo "⚠ Skipping macOS build (requires macOS host for universal binary)"
    echo "  Building x64-only binary instead..."
    dotnet publish "$CSHARP_PROJECT" \
        -c Release \
        -r osx-x64 \
        --self-contained true \
        -p:PublishSingleFile=true \
        -p:PublishTrimmed=true \
        -p:IncludeNativeLibrariesForSelfExtract=true \
        -o "$OUTPUT_DIR/macos-x64"

    chmod +x "$OUTPUT_DIR/macos-x64/MeowthBridge"
    echo "✓ macOS x64 bundle built: $(du -sh "$OUTPUT_DIR/macos-x64" | cut -f1)"
fi

echo ""
echo "=== Build complete ==="
echo "Binaries are in: $OUTPUT_DIR"
echo ""
echo "Total size:"
du -sh "$OUTPUT_DIR"
echo ""
echo "Individual sizes:"
du -h "$OUTPUT_DIR"/*/* 2>/dev/null || true
