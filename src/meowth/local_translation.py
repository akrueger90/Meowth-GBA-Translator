"""Offline machine translation using Argos/OpenNMT model packages."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Callable

import httpx


MODEL_INDEX_URL = (
    "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
)
DEFAULT_MODEL_ROOT = Path.home() / ".meowth" / "models" / "argos"
MAX_MODEL_DOWNLOAD_BYTES = 1_000_000_000
MAX_MODEL_EXTRACTED_BYTES = 1_500_000_000

_PLACEHOLDER_RE = re.compile(r"\{([CG])(\d+)\}")
_LOOSE_PLACEHOLDER_RE = re.compile(r"\{\s*([CG])\s*(\d+)\s*\}")
_LANGUAGE_CODES = {"zh-Hans": "zh"}


class LocalTranslationError(RuntimeError):
    """Raised when the local translation runtime or model is unavailable."""


class LocalTranslationBackend:
    """Download, load, and run one local machine-translation language pair."""

    def __init__(
        self,
        source_lang: str,
        target_lang: str,
        model_root: Path = DEFAULT_MODEL_ROOT,
        stop_event: threading.Event | None = None,
        status_callback: Callable[[str], None] | None = None,
        runtime_factory: Callable[[Path], tuple[object, object]] | None = None,
    ):
        self.source_lang = _LANGUAGE_CODES.get(source_lang, source_lang)
        self.target_lang = _LANGUAGE_CODES.get(target_lang, target_lang)
        self.model_root = Path(model_root)
        self.stop_event = stop_event
        self.status_callback = status_callback
        self._runtime_factory = runtime_factory or self._create_runtime
        self._runtime: tuple[object, object] | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def pair_name(self) -> str:
        return f"{self.source_lang}_{self.target_lang}"

    def _status(self, message: str) -> None:
        if self.status_callback:
            self.status_callback(message)
        else:
            print(message)

    def _check_stop(self) -> None:
        if self.stop_event and self.stop_event.is_set():
            from .translator import TranslationStoppedError

            raise TranslationStoppedError("Translation stopped by user")

    def translate_batch(
        self, texts: list[str], glossary_context: str = ""
    ) -> list[str]:
        """Translate texts locally while preserving control and glossary markers."""
        if not texts:
            return []
        self._check_stop()
        translator, tokenizer = self._ensure_runtime()
        glossary = self._parse_glossary_context(glossary_context)

        prepared: list[str] = []
        restorations: list[dict[str, str]] = []
        for text in texts:
            protected, restoration = self._protect_glossary_terms(text, glossary)
            for marker in _PLACEHOLDER_RE.findall(protected):
                token = f"{{{marker[0]}{marker[1]}}}"
                restoration.setdefault(token, token)
            prepared.append(protected)
            restorations.append(restoration)

        model_inputs = [self._pad_placeholders(text) for text in prepared]
        translated = self._translate_raw(model_inputs, translator, tokenizer)
        results: list[str] = []
        for source, result, restoration in zip(prepared, translated, restorations):
            normalized = _LOOSE_PLACEHOLDER_RE.sub(r"{\1\2}", result)
            normalized = self._restore_placeholder_spacing(source, normalized)
            if self._placeholders_match(source, normalized):
                results.append(self._restore_placeholders(normalized, restoration))
                continue

            # Some models occasionally alter unknown marker tokens. Translating
            # around markers is less fluent, but guarantees ROM control-code safety.
            results.append(
                self._translate_around_placeholders(
                    source, restoration, translator, tokenizer
                )
            )
        return results

    def _ensure_runtime(self) -> tuple[object, object]:
        if self._runtime is not None:
            return self._runtime
        with self._load_lock:
            if self._runtime is None:
                model_path = self._ensure_model()
                self._status(
                    f"Loading offline translation model {self.source_lang} -> "
                    f"{self.target_lang} from {model_path}"
                )
                self._runtime = self._runtime_factory(model_path)
        return self._runtime

    def _create_runtime(self, model_path: Path) -> tuple[object, object]:
        try:
            import ctranslate2
            import sentencepiece
        except ImportError as exc:
            raise LocalTranslationError(
                "The local translation runtime is not installed. Run "
                "`pip install -e '.[local]'` or rerun scripts/setup-dev-macos.sh."
            ) from exc

        tokenizer = sentencepiece.SentencePieceProcessor(
            model_file=str(model_path / "sentencepiece.model")
        )
        translator = ctranslate2.Translator(
            str(model_path / "model"),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
        )
        return translator, tokenizer

    def _ensure_model(self) -> Path:
        pair_dir = self.model_root / self.pair_name
        if self._is_valid_model_dir(pair_dir):
            self._validate_model_metadata(pair_dir)
            return pair_dir

        self.model_root.mkdir(parents=True, exist_ok=True)
        self._check_stop()
        package = self._find_available_package()
        links = [
            link
            for link in package.get("links", [])
            if isinstance(link, str) and link.startswith("https://")
        ]
        if not links:
            raise LocalTranslationError(
                f"No secure model download is available for "
                f"{self.source_lang} -> {self.target_lang}."
            )

        with tempfile.TemporaryDirectory(
            prefix=f".{self.pair_name}-", dir=self.model_root
        ) as temp_name:
            temp_dir = Path(temp_name)
            archive_path = temp_dir / "model.argosmodel"
            self._status(
                f"Downloading free offline translation model "
                f"{self.source_lang} -> {self.target_lang} (first run only)..."
            )
            self._download_file(links[0], archive_path)
            extracted_dir = temp_dir / "extracted"
            model_source = self._extract_model_archive(
                archive_path, extracted_dir
            )
            self._validate_model_metadata(model_source)

            if pair_dir.exists():
                if self._is_valid_model_dir(pair_dir):
                    return pair_dir
                raise LocalTranslationError(
                    f"Local model directory is incomplete: {pair_dir}. "
                    "Remove it and retry the model download."
                )
            shutil.move(str(model_source), str(pair_dir))

        self._status(f"Offline translation model installed at {pair_dir}")
        return pair_dir

    def _find_available_package(self) -> dict:
        try:
            response = httpx.get(
                MODEL_INDEX_URL,
                follow_redirects=True,
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise LocalTranslationError(
                "Unable to retrieve the offline model index. Check the internet "
                "connection and retry; internet is only needed for the first download."
            ) from exc

        if not isinstance(payload, list):
            raise LocalTranslationError("The offline model index has an invalid format.")

        matches = [
            item
            for item in payload
            if isinstance(item, dict)
            and item.get("from_code") == self.source_lang
            and item.get("to_code") == self.target_lang
        ]
        if not matches:
            raise LocalTranslationError(
                f"No direct offline model exists for "
                f"{self.source_lang} -> {self.target_lang}."
            )
        return max(
            matches,
            key=lambda item: self._version_key(str(item.get("package_version", ""))),
        )

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        parts = re.findall(r"\d+", version)
        return tuple(int(part) for part in parts) or (0,)

    def _download_file(self, url: str, destination: Path) -> None:
        try:
            with httpx.stream(
                "GET",
                url,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, read=120.0),
            ) as response:
                response.raise_for_status()
                declared_size = int(response.headers.get("content-length", "0") or 0)
                if declared_size > MAX_MODEL_DOWNLOAD_BYTES:
                    raise LocalTranslationError(
                        "The offline model download exceeds the safety size limit."
                    )
                downloaded = 0
                with destination.open("wb") as model_file:
                    for chunk in response.iter_bytes():
                        self._check_stop()
                        downloaded += len(chunk)
                        if downloaded > MAX_MODEL_DOWNLOAD_BYTES:
                            raise LocalTranslationError(
                                "The offline model download exceeds the safety size limit."
                            )
                        model_file.write(chunk)
        except httpx.HTTPError as exc:
            raise LocalTranslationError(
                f"Failed to download the offline model from {url}."
            ) from exc

    def _extract_model_archive(self, archive_path: Path, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                total_size = 0
                destination_root = destination.resolve()
                for member in archive.infolist():
                    total_size += member.file_size
                    if total_size > MAX_MODEL_EXTRACTED_BYTES:
                        raise LocalTranslationError(
                            "The offline model archive exceeds the extraction size limit."
                        )
                    member_path = (destination / member.filename).resolve()
                    try:
                        safe_root = os.path.commonpath(
                            (destination_root, member_path)
                        )
                    except ValueError:
                        safe_root = ""
                    if safe_root != str(destination_root):
                        raise LocalTranslationError(
                            "The offline model archive contains an unsafe path."
                        )
                    mode = member.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise LocalTranslationError(
                            "The offline model archive contains an unsupported symlink."
                        )
                archive.extractall(destination)
        except zipfile.BadZipFile as exc:
            raise LocalTranslationError(
                "The downloaded offline model is not a valid archive."
            ) from exc

        candidates = [
            metadata.parent
            for metadata in destination.rglob("metadata.json")
            if self._is_valid_model_dir(metadata.parent)
        ]
        if len(candidates) != 1:
            raise LocalTranslationError(
                "The offline model archive does not contain one valid model."
            )
        return candidates[0]

    def _validate_model_metadata(self, model_dir: Path) -> None:
        try:
            metadata = json.loads(
                (model_dir / "metadata.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise LocalTranslationError(
                "The offline model metadata cannot be read."
            ) from exc
        if (
            metadata.get("from_code") != self.source_lang
            or metadata.get("to_code") != self.target_lang
        ):
            raise LocalTranslationError(
                "The downloaded offline model does not match the requested languages."
            )

    @staticmethod
    def _is_valid_model_dir(path: Path) -> bool:
        return all(
            required.exists()
            for required in (
                path / "metadata.json",
                path / "sentencepiece.model",
                path / "model" / "config.json",
                path / "model" / "model.bin",
            )
        )

    @staticmethod
    def _parse_glossary_context(context: str) -> list[tuple[str, str]]:
        terms: list[tuple[str, str]] = []
        for line in context.splitlines():
            source, separator, target = line.strip().partition("=")
            source = source.strip()
            target = target.strip()
            if separator and source and target:
                terms.append((source, target))
        return sorted(terms, key=lambda item: len(item[0]), reverse=True)

    @staticmethod
    def _protect_glossary_terms(
        text: str, glossary: list[tuple[str, str]]
    ) -> tuple[str, dict[str, str]]:
        restoration: dict[str, str] = {}
        protected = text
        next_index = 0
        for source, target in glossary:
            pattern = re.compile(
                r"(?<![\w])" + re.escape(source) + r"(?![\w])",
                re.IGNORECASE,
            )
            if not pattern.search(protected):
                continue

            def replace_match(_: re.Match[str]) -> str:
                nonlocal next_index
                marker = f"{{G{next_index}}}"
                next_index += 1
                restoration[marker] = target
                return marker

            protected = pattern.sub(replace_match, protected)
        return protected, restoration

    @staticmethod
    def _placeholders_match(source: str, translated: str) -> bool:
        source_markers = _PLACEHOLDER_RE.findall(source)
        translated_markers = _PLACEHOLDER_RE.findall(translated)
        source_controls = [marker for marker in source_markers if marker[0] == "C"]
        translated_controls = [
            marker for marker in translated_markers if marker[0] == "C"
        ]
        source_glossary = sorted(
            marker for marker in source_markers if marker[0] == "G"
        )
        translated_glossary = sorted(
            marker for marker in translated_markers if marker[0] == "G"
        )
        return (
            source_controls == translated_controls
            and source_glossary == translated_glossary
        )

    @staticmethod
    def _pad_placeholders(text: str) -> str:
        """Give marker tokens boundaries that SentencePiece models preserve."""
        return re.sub(
            r"\s*(\{[CG]\d+\})\s*",
            r" \1 ",
            text,
        )

    @staticmethod
    def _restore_placeholder_spacing(source: str, translated: str) -> str:
        """Restore each marker's original adjacent whitespace after inference."""
        for match in _PLACEHOLDER_RE.finditer(source):
            marker = match.group(0)
            before = (
                " "
                if match.start() > 0 and source[match.start() - 1].isspace()
                else ""
            )
            after = (
                " "
                if match.end() < len(source) and source[match.end()].isspace()
                else ""
            )
            translated = re.sub(
                r"\s*" + re.escape(marker) + r"\s*",
                before + marker + after,
                translated,
            )
        return translated

    @staticmethod
    def _restore_placeholders(text: str, restoration: dict[str, str]) -> str:
        for marker, value in restoration.items():
            text = text.replace(marker, value)
        return text

    def _translate_around_placeholders(
        self,
        text: str,
        restoration: dict[str, str],
        translator: object,
        tokenizer: object,
    ) -> str:
        parts = _PLACEHOLDER_RE.split(text)
        # re.split() with capturing groups returns text, marker type, marker index.
        plain: list[str] = []
        for index in range(0, len(parts), 3):
            segment = parts[index]
            if segment.strip():
                plain.append(segment)

        translated_plain = iter(self._translate_raw(plain, translator, tokenizer))
        result: list[str] = []
        segment_index = 0
        while segment_index < len(parts):
            segment = parts[segment_index]
            result.append(next(translated_plain) if segment.strip() else segment)
            if segment_index + 2 < len(parts):
                marker = f"{{{parts[segment_index + 1]}{parts[segment_index + 2]}}}"
                result.append(restoration.get(marker, marker))
            segment_index += 3
        return "".join(result)

    def _translate_raw(
        self, texts: list[str], translator: object, tokenizer: object
    ) -> list[str]:
        if not texts:
            return []
        self._check_stop()
        source_tokens = [
            tokenizer.encode(text, out_type=str)
            for text in texts
        ]
        with self._inference_lock:
            translated = translator.translate_batch(source_tokens, beam_size=4)
        self._check_stop()
        return [
            tokenizer.decode(result.hypotheses[0])
            for result in translated
        ]
