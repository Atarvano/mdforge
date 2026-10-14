"""Exception hierarchy for :mod:`mdforge`.

Every error raised by the library derives from :class:`MdForgeError`, so callers
can catch a single base class instead of guessing which subsystem failed.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "ConversionError",
    "ConversionWarning",
    "MdForgeError",
    "MissingDependencyError",
    "UnsupportedFormatError",
]


class MdForgeError(Exception):
    """Base class for all errors raised by mdforge."""


class UnsupportedFormatError(MdForgeError):
    """Raised when no registered converter can handle a file extension.

    Attributes:
        extension: The normalised extension (including the leading dot) that
            could not be routed, or ``""`` when the path had no suffix.
        supported: The extensions that *are* currently registered.
    """

    def __init__(self, extension: str, supported: Sequence[str] = ()) -> None:
        self.extension = extension
        self.supported = tuple(sorted(supported))
        hint = ""
        if self.supported:
            hint = " Supported extensions: " + ", ".join(self.supported) + "."
        super().__init__(f"No converter registered for '{extension or '<none>'}'.{hint}")


class MissingDependencyError(MdForgeError):
    """Raised when a converter needs an optional third-party package.

    The message always tells the user exactly how to fix the problem, which is
    the difference between a bug report and a five-second ``pip install``.

    Attributes:
        package: Import name of the missing distribution (e.g. ``"pypdf"``).
        extra: Name of the ``pip install mdforge[...]`` extra that provides it.
        feature: Human readable description of what needed the dependency.
    """

    def __init__(self, package: str, extra: str, feature: str) -> None:
        self.package = package
        self.extra = extra
        self.feature = feature
        super().__init__(
            f"The optional dependency '{package}' is required {feature}.\n"
            f"Install it with:\n\n    pip install 'mdforge[{extra}]'\n\n"
            f"or install everything at once:\n\n    pip install 'mdforge[all]'"
        )


class ConversionError(MdForgeError):
    """Raised when a converter fails to parse a file it claimed to support.

    Attributes:
        source_file: Path of the offending file.
        converter: Name of the converter that raised the error.
        reason: Short, user-facing explanation.
    """

    def __init__(
        self,
        source_file: str,
        reason: str,
        *,
        converter: str | None = None,
    ) -> None:
        self.source_file = source_file
        self.converter = converter
        self.reason = reason
        prefix = f"[{converter}] " if converter else ""
        super().__init__(f"{prefix}Failed to convert '{source_file}': {reason}")


class ConversionWarning(UserWarning):
    """Warning category emitted for recoverable, lossy conversions."""
