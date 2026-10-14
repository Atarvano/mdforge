"""mdforge - turn documents into LLM-ready Markdown.

Quick start::

    from mdforge import convert, convert_batch, MarkdownChunker

    result = convert("report.pdf")
    print(result.markdown)          # Markdown + YAML frontmatter
    print(result.metadata["title"])

    batch = convert_batch(["a.docx", "b.html"])
    for chunk in MarkdownChunker().chunk(result.markdown):
        print(chunk.breadcrumb, chunk.token_estimate)
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from typing import Any

from .core.base import BaseConverter, DocumentResult, PathLike
from .core.engine import (
    BatchError,
    BatchResult,
    ConversionEngine,
    load_entry_point_converters,
)
from .core.metadata import split_frontmatter
from .exceptions import (
    ConversionError,
    ConversionWarning,
    MdForgeError,
    MissingDependencyError,
    UnsupportedFormatError,
)
from .utils.chunker import Chunk, MarkdownChunker, chunk_file, chunks_to_records

try:  # pragma: no cover - depends on installation mode
    __version__ = _version("mdforge")
except PackageNotFoundError:  # pragma: no cover - editable/dev checkout
    __version__ = "0.0.0.dev0"

__all__ = [
    # core
    "BaseConverter",
    "BatchError",
    "BatchResult",
    # chunking
    "Chunk",
    "ConversionEngine",
    "ConversionError",
    "ConversionWarning",
    "DocumentResult",
    "MarkdownChunker",
    # errors
    "MdForgeError",
    "MissingDependencyError",
    "UnsupportedFormatError",
    "__version__",
    "chunk_file",
    "chunks_to_records",
    "convert",
    "convert_batch",
    "get_default_engine",
    "load_entry_point_converters",
    "set_default_engine",
    "split_frontmatter",
    # convenience
    "supported_formats",
]

_DEFAULT_ENGINE: ConversionEngine | None = None


def get_default_engine() -> ConversionEngine:
    """Return the lazily created process-wide :class:`ConversionEngine`.

    The engine is cached so repeated :func:`convert` calls do not rebuild the
    converter registry.  Use :func:`set_default_engine` to swap it (useful in
    tests or when registering custom converters globally).
    """
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = ConversionEngine()
    return _DEFAULT_ENGINE


def set_default_engine(engine: ConversionEngine | None) -> None:
    """Replace the cached default engine; pass ``None`` to force a rebuild."""
    global _DEFAULT_ENGINE
    _DEFAULT_ENGINE = engine


def convert(path: PathLike, **options: Any) -> DocumentResult:
    """Convert one file using the default engine.

    Args:
        path: File to convert.
        **options: Forwarded to :meth:`ConversionEngine.convert`.

    Returns:
        The conversion result.
    """
    return get_default_engine().convert(path, **options)


def convert_batch(
    file_paths: Sequence[PathLike],
    *,
    max_workers: int | None = None,
    on_progress: Any | None = None,
    **options: Any,
) -> BatchResult:
    """Convert many files concurrently using the default engine.

    Args:
        file_paths: Files to convert.
        max_workers: Concurrency cap.
        on_progress: Optional ``(path, done, total)`` callback.
        **options: Forwarded to :meth:`ConversionEngine.convert_batch`.

    Returns:
        The aggregated :class:`BatchResult`.
    """
    return get_default_engine().convert_batch_sync(
        file_paths, max_workers=max_workers, on_progress=on_progress, **options
    )


def supported_formats() -> dict[str, str]:
    """Map every registered extension to the converter name handling it."""
    return {
        extension: converter.name for extension, converter in get_default_engine().registry.items()
    }
