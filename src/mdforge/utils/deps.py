"""Helpers for optional third-party dependencies.

Importers of optional libraries must never crash on ``import mdforge``.  All
optional imports therefore funnel through :func:`import_optional`, which turns
a bare :class:`ImportError` into a :class:`~mdforge.exceptions.MissingDependencyError`
carrying an actionable install hint.
"""

from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from ..exceptions import MissingDependencyError

__all__ = ["has_dependency", "import_optional", "require_dependency"]


def import_optional(
    module: str,
    *,
    extra: str,
    feature: str,
    package: str | None = None,
) -> ModuleType:
    """Import ``module`` or raise a helpful :class:`MissingDependencyError`.

    Args:
        module: Dotted import path, e.g. ``"pypdf"`` or ``"bs4"``.
        extra: Optional-dependency group that installs it, e.g. ``"pdf"``.
        feature: Description used in the error message, e.g.
            ``"to convert PDF files"``.
        package: Distribution name to suggest when it differs from the import
            name (e.g. import ``"bs4"`` -> package ``"beautifulsoup4"``).

    Returns:
        The imported module object.

    Raises:
        MissingDependencyError: If the module is not importable.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - exercised via mocking
        raise MissingDependencyError(package or module, extra, feature) from exc


def has_dependency(module: str) -> bool:
    """Return ``True`` if ``module`` can be imported in the current interpreter."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # pragma: no cover - namespace edge cases
        return False


def require_dependency(module: str, *, extra: str, feature: str) -> ModuleType:
    """Alias of :func:`import_optional` kept for readability at call sites."""
    return import_optional(module, extra=extra, feature=feature)
