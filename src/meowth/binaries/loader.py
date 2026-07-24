"""Smart loader for MeowthBridge executable across platforms."""

import os
import platform
import sys
import urllib.request
import urllib.error
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path


def _read_repo_version() -> str | None:
    """Read the package version from pyproject.toml when available."""
    project_root = Path(__file__).resolve().parents[3]
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    for line in pyproject_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def get_meowth_version() -> str:
    """Get the current meowth package version."""
    # Prefer the source checkout version when running from the repository,
    # even if an older meowth package is installed globally.
    repo_version = _read_repo_version()
    if repo_version:
        return repo_version

    try:
        import importlib.metadata
        return importlib.metadata.version("meowth")
    except Exception:
        return "0.0.0"


def get_platform_name() -> str:
    """Get the normalized platform name for binary selection."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    else:
        return "linux"


def get_architecture_name() -> str:
    """Get the release architecture name for the current process."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    raise RuntimeError(f"Unsupported CPU architecture: {platform.machine()}")


def get_executable_name() -> str:
    """Get the executable name for the current platform."""
    return "MeowthBridge.exe" if platform.system() == "Windows" else "MeowthBridge"


def _ensure_unix_executable(path: Path):
    """Ensure Unix binaries are executable for direct subprocess calls."""
    if platform.system() == "Windows":
        return
    if path.exists() and path.is_file():
        path.chmod(0o755)


def _configure_dotnet_runtime_env():
    """Make local dotnet installs discoverable when launching framework-dependent apphosts."""
    if platform.system() != "Darwin":
        return

    if "DOTNET_ROOT" in os.environ:
        return

    candidate_root = None

    # Common user-local install path.
    home_root = Path.home() / ".dotnet"
    if (home_root / "dotnet").exists():
        candidate_root = home_root
    else:
        dotnet_path = shutil.which("dotnet")
        if dotnet_path:
            resolved = Path(dotnet_path).resolve()
            candidate_root = resolved.parent

    if candidate_root and (candidate_root / "dotnet").exists():
        os.environ["DOTNET_ROOT"] = str(candidate_root)
        path_parts = os.environ.get("PATH", "").split(os.pathsep)
        if str(candidate_root) not in path_parts:
            os.environ["PATH"] = (
                f"{candidate_root}{os.pathsep}{os.environ.get('PATH', '')}"
            ).strip(os.pathsep)


def _looks_like_arch_mismatch(path: Path) -> bool:
    """Check a native file for a CPU architecture mismatch on macOS."""
    if platform.system() != "Darwin" or not path.exists():
        return False

    arch = platform.machine().lower()
    try:
        info = subprocess.check_output(["file", str(path)], text=True, stderr=subprocess.STDOUT)
    except Exception:
        return False

    lowered = info.lower()
    if arch in ("arm64", "aarch64"):
        return "x86_64" in lowered and "arm64" not in lowered
    if arch in ("x86_64", "amd64"):
        return "arm64" in lowered and "x86_64" not in lowered
    return False


def _validate_binary_bundle(exe_path: Path) -> None:
    """Validate the apphost and its native runtime libraries."""
    if not exe_path.exists():
        raise FileNotFoundError(f"MeowthBridge executable not found: {exe_path}")
    if platform.system() != "Darwin":
        return

    native_files = [exe_path, *sorted(exe_path.parent.glob("*.dylib"))]
    createdump = exe_path.parent / "createdump"
    if createdump.exists():
        native_files.append(createdump)

    mismatches = [path for path in native_files if _looks_like_arch_mismatch(path)]
    if mismatches:
        listed = "\n".join(f"  - {path.name}" for path in mismatches[:10])
        raise RuntimeError(
            "MeowthBridge contains native files for the wrong CPU architecture.\n"
            f"Required architecture: {get_architecture_name()}\n"
            f"Incompatible files:\n{listed}"
        )


def find_meowth_bridge() -> Path:
    """Locate the MeowthBridge executable using multiple search strategies.

    Search order:
    1. Environment variable MEOWTH_BRIDGE_PATH (if set)
    2. Development build (src/MeowthBridge/bin/Release or Debug)
    3. Bundled binary in package (src/meowth/binaries/{platform}/)
    4. Cached download (~/.meowth/binaries/{platform}/)
    5. Download from GitHub releases
    """
    exe_name = get_executable_name()
    _configure_dotnet_runtime_env()

    # Strategy 1: Check environment variable
    env_path = os.environ.get("MEOWTH_BRIDGE_PATH")
    if env_path:
        env_exe = Path(env_path)
        if env_exe.exists() and env_exe.is_file():
            _validate_binary_bundle(env_exe)
            return env_exe
        if env_exe.is_dir():
            env_exe = env_exe / exe_name
            if env_exe.exists():
                _validate_binary_bundle(env_exe)
                return env_exe

    # Strategy 2: Check development build
    project_root = Path(__file__).parent.parent.parent.parent
    meowth_bridge_dir = project_root / "src" / "MeowthBridge"

    for build_config in ("Release", "Debug"):
        dev_exe = meowth_bridge_dir / "bin" / build_config / "net8.0" / exe_name
        if dev_exe.exists():
            _ensure_unix_executable(dev_exe)
            _validate_binary_bundle(dev_exe)
            return dev_exe

    # Strategy 3: Check bundled binary in package
    package_dir = Path(__file__).parent
    platform_name = get_platform_name()
    platform_arch = f"{platform_name}-{get_architecture_name()}"
    bundled_candidates = [
        package_dir / platform_arch / exe_name,
        package_dir / platform_name / exe_name,
    ]

    for bundled_exe in bundled_candidates:
        if bundled_exe.exists():
            _ensure_unix_executable(bundled_exe)
            try:
                _validate_binary_bundle(bundled_exe)
                return bundled_exe
            except RuntimeError as error:
                print(f"⚠️  Ignoring incompatible bundled bridge: {error}")

    # Strategy 4: Check old location (backward compatibility)
    old_location = project_root / "MeowthBridge" / "bin"
    for build_config in ("Release", "Debug"):
        old_exe = old_location / build_config / "net8.0" / exe_name
        if old_exe.exists():
            _ensure_unix_executable(old_exe)
            _validate_binary_bundle(old_exe)
            return old_exe

    # Strategy 5: Download from GitHub
    try:
        return _download_meowth_bridge()
    except Exception as download_error:
        raise FileNotFoundError(
            f"MeowthBridge executable not found. Tried:\n"
            f"  1. Environment variable MEOWTH_BRIDGE_PATH: {env_path or '(not set)'}\n"
            f"  2. Bundled binaries: {', '.join(map(str, bundled_candidates))}\n"
            f"  3. Development build: {meowth_bridge_dir / 'bin'}\n"
            f"  4. Download from GitHub: {download_error}\n"
            f"\n"
            f"To fix this:\n"
            f"  - Set MEOWTH_BRIDGE_PATH environment variable to the executable path\n"
            f"  - Or check your internet connection for auto-download"
        ) from download_error


def _download_meowth_bridge() -> Path:
    """Download MeowthBridge ZIP from GitHub release and extract it."""
    exe_name = get_executable_name()
    platform_name = get_platform_name()
    architecture = get_architecture_name()
    platform_arch = f"{platform_name}-{architecture}"
    version = get_meowth_version()

    asset_name = f"MeowthBridge-{platform_arch}.zip"
    download_url = (
        "https://github.com/akrueger90/Meowth-GBA-Translator/"
        f"releases/download/v{version}/{asset_name}"
    )

    # Versioned, architecture-specific caches prevent stale native libraries
    # from being mixed with a newly downloaded apphost.
    cache_dir = (
        Path.home() / ".meowth" / "binaries" / platform_arch / f"v{version}"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)

    exe_path = cache_dir / exe_name

    # If already cached, return it
    if exe_path.exists():
        _ensure_unix_executable(exe_path)
        try:
            _validate_binary_bundle(exe_path)
            return exe_path
        except RuntimeError as error:
            print(f"⚠️  Replacing incompatible cached bridge: {error}")
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)

    # Download the ZIP file
    print(f"🔽 First-time setup: Downloading MeowthBridge for {platform_name}...")
    print(f"   Source: {download_url}")

    tmp_zip_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
            tmp_zip_path = Path(tmp_file.name)

        _download_with_progress_and_retry(download_url, tmp_zip_path)

        # Extract into a temporary sibling, then replace the cache atomically.
        print(f"📦 Extracting files...")
        extract_dir = Path(tempfile.mkdtemp(prefix="meowth-bridge-", dir=cache_dir.parent))
        try:
            with zipfile.ZipFile(tmp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            extracted_exe = extract_dir / exe_name
            _ensure_unix_executable(extracted_exe)
            _validate_binary_bundle(extracted_exe)
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            extract_dir.replace(cache_dir)
        except Exception:
            shutil.rmtree(extract_dir, ignore_errors=True)
            raise

        # Clean up temporary ZIP file
        tmp_zip_path.unlink()

        # Make executable on Unix
        _ensure_unix_executable(exe_path)
        _validate_binary_bundle(exe_path)

        print(f"✅ Downloaded and cached to {cache_dir}")
        print(f"   (Subsequent runs will use the cached version)")
        return exe_path

    except urllib.error.HTTPError as e:
        if tmp_zip_path and tmp_zip_path.exists():
            tmp_zip_path.unlink()
        if e.code == 404:
            raise FileNotFoundError(
                f"MeowthBridge binary not found in release v{version}.\n"
                f"URL: {download_url}\n\n"
                f"This usually means:\n"
                f"  1. The release hasn't been published yet\n"
                f"  2. The binary wasn't uploaded to the release\n\n"
                f"Workaround:\n"
                f"  export MEOWTH_BRIDGE_PATH=/path/to/MeowthBridge"
            )
        else:
            raise FileNotFoundError(f"HTTP error {e.code} downloading from {download_url}: {e}")
    except Exception as e:
        if tmp_zip_path and tmp_zip_path.exists():
            tmp_zip_path.unlink()
        raise FileNotFoundError(f"Failed to download MeowthBridge: {e}")


def _download_with_progress_and_retry(url: str, dest: Path, max_retries: int = 3):
    """Download file with progress display and retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            _download_with_progress(url, dest)
            return
        except Exception as e:
            if attempt < max_retries:
                print(f"   ⚠️  Download failed (attempt {attempt}/{max_retries}): {e}")
                print(f"   🔄 Retrying in 2 seconds...")
                time.sleep(2)
            else:
                raise


def _download_with_progress(url: str, dest: Path):
    """Download file with progress display."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

        response = urllib.request.urlopen(url, timeout=60)
        total_size = int(response.headers.get('content-length', 0))

        downloaded = 0
        chunk_size = 65536
        last_percent = -1

        with open(tmp_path, 'wb') as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                if total_size > 0:
                    percent = int((downloaded / total_size) * 100)
                    if percent != last_percent and percent % 10 == 0:
                        mb_downloaded = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        print(f"   [{percent:3d}%] {mb_downloaded:.1f} MB / {mb_total:.1f} MB")
                        last_percent = percent

        shutil.move(str(tmp_path), str(dest))

    except Exception:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
        raise


def get_binary_info() -> dict:
    """Get information about the MeowthBridge binary."""
    try:
        exe_path = find_meowth_bridge()
        if os.environ.get("MEOWTH_BRIDGE_PATH"):
            source = "environment"
        elif ".meowth" in str(exe_path):
            source = "downloaded"
        elif "binaries" in str(exe_path):
            source = "bundled"
        else:
            source = "development"

        return {
            "path": str(exe_path),
            "platform": get_platform_name(),
            "source": source,
            "exists": True,
        }
    except FileNotFoundError:
        return {
            "path": None,
            "platform": get_platform_name(),
            "source": None,
            "exists": False,
        }
