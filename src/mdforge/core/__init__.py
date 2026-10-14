"""Core building blocks: the converter contract, the engine and metadata.

Nothing in this subpackage imports a third-party *format* library at module
level, so ``from mdforge.core import ConversionEngine`` is always safe.
"""

from __future__ import annotations

from .base import BaseConverter, DocumentResult
from .engine import BatchError, BatchResult, ConversionEngine, load_entry_point_converters
from .metadata import (
    build_metadata,
    prepend_frontmatter,
    render_frontmatter,
    utc_now_iso,
)

__all__ = [
    "BaseConverter",
    "BatchError",
    "BatchResult",
    "ConversionEngine",
    "DocumentResult",
    "build_metadata",
    "load_entry_point_converters",
    "prepend_frontmatter",
    "render_frontmatter",
    "utc_now_iso",
]
