import zipfile
from pathlib import Path

import pytest

from meowth.binaries import loader


def test_get_architecture_name_normalizes_x86_64(monkeypatch):
    monkeypatch.setattr(loader.platform, "machine", lambda: "x86_64")

    assert loader.get_architecture_name() == "x64"


def test_validate_bundle_checks_native_runtime_libraries(tmp_path, monkeypatch):
    exe = tmp_path / "MeowthBridge"
    exe.touch()
    incompatible_runtime = tmp_path / "libhostfxr.dylib"
    incompatible_runtime.touch()

    monkeypatch.setattr(loader.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(loader, "get_architecture_name", lambda: "x64")
    monkeypatch.setattr(
        loader,
        "_looks_like_arch_mismatch",
        lambda path: path == incompatible_runtime,
    )

    with pytest.raises(RuntimeError, match="libhostfxr.dylib"):
        loader._validate_binary_bundle(exe)


def test_download_uses_versioned_architecture_specific_cache(tmp_path, monkeypatch):
    home = tmp_path / "home"
    captured_url = ""

    def fake_download(url: str, destination: Path):
        nonlocal captured_url
        captured_url = url
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("MeowthBridge", b"bridge")

    monkeypatch.setattr(loader.Path, "home", lambda: home)
    monkeypatch.setattr(loader, "get_platform_name", lambda: "macos")
    monkeypatch.setattr(loader, "get_architecture_name", lambda: "x64")
    monkeypatch.setattr(loader, "get_meowth_version", lambda: "1.2.3")
    monkeypatch.setattr(loader, "_download_with_progress_and_retry", fake_download)
    monkeypatch.setattr(loader, "_validate_binary_bundle", lambda path: None)

    executable = loader._download_meowth_bridge()

    assert captured_url == (
        "https://github.com/akrueger90/Meowth-GBA-Translator/"
        "releases/download/v1.2.3/MeowthBridge-macos-x64.zip"
    )
    assert executable == (
        home
        / ".meowth"
        / "binaries"
        / "macos-x64"
        / "v1.2.3"
        / "MeowthBridge"
    )
