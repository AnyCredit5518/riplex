"""Resolve and validate directories used for riplex output."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OutputPathPreflight:
    """Result of resolving and, optionally, probing an output directory."""

    path: Path
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class RipOutputPreflight:
    """Resolved media and raw-rip roots required by a rip workflow."""

    output_root: Path | None
    rip_output: Path | None
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def resolve_output_path(value: str | Path) -> Path:
    """Expand a configured path and make relative paths unambiguous."""
    return Path(value).expanduser().absolute()


def preflight_output_directory(
    value: str | Path,
    *,
    create: bool,
) -> OutputPathPreflight:
    """Resolve *value* and prove it is writable when *create* is true."""
    raw_path = Path(value)
    try:
        path = resolve_output_path(raw_path)
    except (OSError, RuntimeError) as exc:
        return OutputPathPreflight(raw_path, _format_error(raw_path, exc))

    if not create:
        if path.exists():
            error = _validate_existing_directory(path)
            if error:
                return OutputPathPreflight(path, error)
        return OutputPathPreflight(path)

    probe = path / f".riplex-write-test-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
        error = _validate_existing_directory(path)
        if error:
            return OutputPathPreflight(path, error)
    except OSError as exc:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return OutputPathPreflight(path, _format_error(path, exc))

    return OutputPathPreflight(path)


def _validate_existing_directory(path: Path) -> str | None:
    """Return an error unless *path* is a readable directory."""
    if not path.is_dir():
        return _format_error(path, NotADirectoryError("Not a directory"))
    try:
        with os.scandir(path) as entries:
            next(entries, None)
    except OSError as exc:
        return _format_error(path, exc)
    return None


def preflight_rip_outputs(
    output_root: str | Path,
    rip_output: str | Path,
    *,
    create: bool,
) -> RipOutputPreflight:
    """Resolve and validate the two directories required for a rip workflow."""
    output_check = preflight_output_directory(output_root, create=create)
    rip_check = preflight_output_directory(rip_output, create=create)
    errors = tuple(
        error for error in (output_check.error, rip_check.error) if error
    )
    return RipOutputPreflight(
        output_root=output_check.path,
        rip_output=rip_check.path,
        errors=errors,
    )


def preflight_configured_rip_outputs(
    output_override: str | None = None,
    *,
    create: bool,
) -> RipOutputPreflight:
    """Resolve configured rip workflow roots and validate them consistently."""
    from riplex.config import get_output_root, get_rip_output

    try:
        output_root = get_output_root(output_override)
    except (OSError, RuntimeError) as exc:
        return RipOutputPreflight(
            output_root=None,
            rip_output=None,
            errors=(f"Cannot resolve output_root: {exc}",),
        )
    if not output_root:
        return RipOutputPreflight(
            output_root=None,
            rip_output=None,
            errors=("An output_root or --output value is required.",),
        )

    try:
        rip_output = get_rip_output(output_override)
    except (OSError, RuntimeError) as exc:
        return RipOutputPreflight(
            output_root=Path(output_root),
            rip_output=None,
            errors=(f"Cannot resolve rip_output: {exc}",),
        )
    if not rip_output:
        return RipOutputPreflight(
            output_root=resolve_output_path(output_root),
            rip_output=None,
            errors=("A rip_output or output_root value is required.",),
        )

    return preflight_rip_outputs(output_root, rip_output, create=create)


def preflight_configured_output_root(
    output_override: str | None = None,
    *,
    create: bool,
) -> OutputPathPreflight:
    """Resolve and validate only the configured media-library root."""
    from riplex.config import get_output_root

    try:
        output_root = get_output_root(output_override)
    except (OSError, RuntimeError) as exc:
        return OutputPathPreflight(
            Path(output_override or ""),
            f"Cannot resolve output_root: {exc}",
        )
    if not output_root:
        return OutputPathPreflight(
            Path(),
            "An output_root or --output value is required.",
        )
    return preflight_output_directory(output_root, create=create)


def _format_error(path: Path, exc: BaseException) -> str:
    detail = getattr(exc, "strerror", None) or str(exc)
    failed_path = getattr(exc, "filename", None)
    if failed_path and Path(failed_path) != path:
        detail = f"{detail}: {failed_path}"
    return f"Cannot write to output directory '{path}': {detail}"