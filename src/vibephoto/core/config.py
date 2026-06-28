"""Application configuration: a typed, layered settings system.

Settings are resolved from three layers, lowest precedence first:

1. **Defaults** — the dataclass field defaults in this module.
2. **User file** — ``settings.json`` in the platform config directory.
3. **Environment** — ``VIBEPHOTO_<SECTION>__<KEY>`` variables (double underscore
   separates nesting), useful for CI, headless batch nodes, and debugging.

The model is a tree of frozen-ish dataclasses. Using dataclasses (rather than a
third-party settings library) keeps the ``core`` layer dependency-free and makes
the settings tree trivially serialisable and unit-testable. Validation happens
in ``__post_init__`` so an invalid file fails fast with a clear ``ConfigError``.
"""

from __future__ import annotations

import dataclasses
import json
import os
import types
import typing
from dataclasses import dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Final, get_args, get_origin

from vibephoto.core.errors import ConfigError
from vibephoto.core.paths import AppPaths

ENV_PREFIX: Final = "VIBEPHOTO_"
ENV_NESTING_SEP: Final = "__"

_VALID_THEMES: Final = frozenset({"dark", "light", "system"})
_VALID_LOG_LEVELS: Final = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VALID_SIDECAR_MODES: Final = frozenset({"catalog", "sidecar", "hybrid"})
_VALID_GPU_BACKENDS: Final = frozenset({"auto", "cpu", "opencl", "cuda", "metal"})


@dataclass
class GeneralSettings:
    """Top-level application preferences."""

    theme: str = "dark"
    language: str = "en"
    telemetry_enabled: bool = False

    def __post_init__(self) -> None:
        if self.theme not in _VALID_THEMES:
            raise ConfigError(
                f"Invalid theme {self.theme!r}; expected one of {sorted(_VALID_THEMES)}",
                context={"field": "general.theme"},
            )


@dataclass
class LoggingSettings:
    """Logging behaviour. See :mod:`vibephoto.core.logging`."""

    level: str = "INFO"
    console_level: str = "INFO"
    file_level: str = "DEBUG"
    json_logs: bool = False
    max_bytes: int = 5 * 1024 * 1024
    backup_count: int = 5

    def __post_init__(self) -> None:
        for name in ("level", "console_level", "file_level"):
            value = getattr(self, name)
            if value not in _VALID_LOG_LEVELS:
                raise ConfigError(
                    f"Invalid log level {value!r} for logging.{name}",
                    context={"field": f"logging.{name}"},
                )
        if self.backup_count < 0:
            raise ConfigError("logging.backup_count must be >= 0")


@dataclass
class CatalogSettings:
    """Catalog persistence and safety behaviour."""

    autosave_interval_s: int = 30
    backup_on_launch: bool = True
    max_backups: int = 10

    def __post_init__(self) -> None:
        if self.autosave_interval_s < 0:
            raise ConfigError("catalog.autosave_interval_s must be >= 0")


@dataclass
class CacheSettings:
    """Preview / thumbnail cache budgets and quality."""

    max_thumbnail_cache_mb: int = 2048
    max_preview_cache_mb: int = 8192
    preview_quality: int = 85  # JPEG quality for standard previews
    smart_preview_long_edge: int = 2560

    def __post_init__(self) -> None:
        if not 1 <= self.preview_quality <= 100:
            raise ConfigError("cache.preview_quality must be within 1..100")


@dataclass
class ProcessingSettings:
    """Processing-engine concurrency and acceleration."""

    worker_threads: int = 0  # 0 => auto (os.cpu_count)
    use_gpu: bool = False
    gpu_backend: str = "auto"

    def __post_init__(self) -> None:
        if self.gpu_backend not in _VALID_GPU_BACKENDS:
            raise ConfigError(
                f"Invalid gpu_backend {self.gpu_backend!r}",
                context={"field": "processing.gpu_backend"},
            )
        if self.worker_threads < 0:
            raise ConfigError("processing.worker_threads must be >= 0")

    @property
    def resolved_worker_threads(self) -> int:
        """Concrete worker count, expanding the ``0 => auto`` sentinel."""
        if self.worker_threads > 0:
            return self.worker_threads
        return max(1, (os.cpu_count() or 4))


@dataclass
class MetadataSettings:
    """Metadata read/write behaviour and the ExifTool integration."""

    exiftool_path: str = "exiftool"
    sidecar_mode: str = "hybrid"
    write_xmp_sidecars: bool = True

    def __post_init__(self) -> None:
        if self.sidecar_mode not in _VALID_SIDECAR_MODES:
            raise ConfigError(
                f"Invalid sidecar_mode {self.sidecar_mode!r}",
                context={"field": "metadata.sidecar_mode"},
            )


@dataclass
class UISettings:
    """UI/workspace preferences."""

    restore_workspace: bool = True
    thumbnail_size: int = 160
    filmstrip_visible: bool = True


@dataclass
class AppSettings:
    """Root settings object — a tree of section dataclasses."""

    general: GeneralSettings = field(default_factory=GeneralSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    catalog: CatalogSettings = field(default_factory=CatalogSettings)
    cache: CacheSettings = field(default_factory=CacheSettings)
    processing: ProcessingSettings = field(default_factory=ProcessingSettings)
    metadata: MetadataSettings = field(default_factory=MetadataSettings)
    ui: UISettings = field(default_factory=UISettings)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain nested dict (JSON-ready)."""
        return typing.cast(dict[str, Any], _to_dict(self))


# --------------------------------------------------------------------------- #
# (De)serialisation helpers — generic over the dataclass tree.
# --------------------------------------------------------------------------- #


def _to_dict(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _coerce(value: Any, annotation: Any, *, path: str) -> Any:
    """Coerce ``value`` to the declared ``annotation`` type with clear errors."""
    origin = get_origin(annotation)

    # Optional[X] / X | None
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if value is None:
            return None
        # Single non-None member is the common Optional[...] case.
        return _coerce(value, args[0], path=path)

    if annotation is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("1", "true", "yes", "on"):
                return True
            if lowered in ("0", "false", "no", "off"):
                return False
        raise ConfigError(f"Cannot interpret {value!r} as bool", context={"field": path})

    if annotation is int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"Cannot interpret {value!r} as int", context={"field": path}
            ) from exc

    if annotation is float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"Cannot interpret {value!r} as float", context={"field": path}
            ) from exc

    if annotation is str:
        return str(value)

    if annotation is Path:
        return Path(value)

    return value


def _from_dict(cls: type, data: dict[str, Any], *, path: str = "") -> Any:
    """Build a dataclass instance from ``data``, ignoring unknown keys.

    Unknown keys are tolerated (forward-compat with newer setting files); missing
    keys fall back to field defaults.
    """
    if not isinstance(data, dict):
        raise ConfigError(
            f"Expected a mapping for {path or cls.__name__}, got {type(data).__name__}",
            context={"field": path},
        )

    kwargs: dict[str, Any] = {}
    hints = typing.get_type_hints(cls)
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        field_path = f"{path}.{f.name}" if path else f.name
        annotation = hints[f.name]
        raw = data[f.name]
        if is_dataclass(annotation) and isinstance(annotation, type):
            kwargs[f.name] = _from_dict(annotation, raw, path=field_path)
        else:
            kwargs[f.name] = _coerce(raw, annotation, path=field_path)
    return cls(**kwargs)


def _apply_env_overrides(data: dict[str, Any], environ: dict[str, str]) -> dict[str, Any]:
    """Overlay ``VIBEPHOTO_SECTION__KEY`` env vars onto a settings dict in place."""
    for env_key, env_val in environ.items():
        if not env_key.startswith(ENV_PREFIX):
            continue
        trail = env_key[len(ENV_PREFIX) :].lower()
        parts = trail.split(ENV_NESTING_SEP)
        cursor = data
        for part in parts[:-1]:
            node = cursor.get(part)
            if not isinstance(node, dict):
                node = {}
                cursor[part] = node
            cursor = node
        cursor[parts[-1]] = env_val
    return data


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def load_settings(
    paths: AppPaths,
    *,
    environ: dict[str, str] | None = None,
) -> AppSettings:
    """Load settings by merging defaults, the user file, and environment vars.

    Raises :class:`ConfigError` if the settings file exists but is malformed, so
    corruption surfaces immediately rather than silently resetting the user's
    preferences.
    """
    environ = os.environ.copy() if environ is None else environ

    file_data: dict[str, Any] = {}
    settings_file = paths.settings_file
    if settings_file.is_file():
        try:
            file_data = json.loads(settings_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(
                f"Failed to read settings file {settings_file}: {exc}",
                context={"path": str(settings_file)},
            ) from exc
        if not isinstance(file_data, dict):
            raise ConfigError(
                "Settings file must contain a JSON object",
                context={"path": str(settings_file)},
            )

    merged = _apply_env_overrides(file_data, environ)
    return typing.cast(AppSettings, _from_dict(AppSettings, merged))


def save_settings(settings: AppSettings, paths: AppPaths) -> Path:
    """Persist settings atomically to the user config file; return its path."""
    target = paths.settings_file
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(settings.to_dict(), indent=2, sort_keys=True)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)  # atomic on all target platforms
    return target
