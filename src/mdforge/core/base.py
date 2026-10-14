"""The converter contract.

Two primitives live here:

* :class:`DocumentResult` - the immutable-ish value object every conversion
  returns.  It carries the Markdown body *and* structured metadata so callers
  never have to re-parse the frontmatter to get at the title or page count.
* :class:`BaseConverter` - the abstract base class that plugin authors
  subclass.  It is deliberately tiny: declare which extensions you handle,
  declare which optional packages you need, implement :meth:`convert`.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from ..exceptions import UnsupportedFormatError

__all__ = ["BaseConverter", "DocumentResult", "PathLike"]

PathLike = str | Path


@dataclass
class DocumentResult:
    """The outcome of converting a single file.

    Attributes:
        markdown: Converted Markdown body, *without* the YAML frontmatter
            (the engine prepends that when requested).
        source_file: Original path as a string, kept verbatim for provenance.
        file_type: Normalised extension without a dot, e.g. ``"pdf"``.
        metadata: Converter-extracted metadata (author, page count, ...).
            Merged into the frontmatter by the engine.
        warnings: Non-fatal, human-readable notes about lossy conversion.
        converter: Name of the converter that produced this result.
    """

    markdown: str
    source_file: str
    file_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    converter: str = ""

    @property
    def word_count(self) -> int:
        """Number of whitespace-delimited words in :attr:`markdown`."""
        return len(self.markdown.split())

    @property
    def char_count(self) -> int:
        """Number of characters in :attr:`markdown`."""
        return len(self.markdown)

    def to_dict(self, *, include_markdown: bool = True) -> dict[str, Any]:
        """Serialise the result to a JSON-friendly dictionary."""
        payload: dict[str, Any] = {
            "source_file": self.source_file,
            "file_type": self.file_type,
            "converter": self.converter,
            "word_count": self.word_count,
            "char_count": self.char_count,
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
        }
        if include_markdown:
            payload["markdown"] = self.markdown
        return payload

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.markdown


class BaseConverter(abc.ABC):
    """Abstract base class for every mdforge converter.

    Subclasses must define :attr:`name`, :attr:`extensions` and implement
    :meth:`convert`.  Optional dependencies are declared via :attr:`requires`
    purely for introspection/documentation; the actual import is performed by
    the subclass using :func:`mdforge.utils.deps.import_optional`.

    Example:
        >>> from pathlib import Path
        >>> from mdforge.core.base import BaseConverter, DocumentResult
        >>> class IniConverter(BaseConverter):
        ...     name = "ini"
        ...     extensions = (".ini",)
        ...     def convert(self, path, **options):
        ...         text = Path(path).read_text(encoding="utf-8")
        ...         body = "\\n".join(f"- {line}" for line in text.splitlines())
        ...         return self.build_result(path, body)
    """

    #: Stable, lower-case identifier used in CLI output and error messages.
    name: ClassVar[str] = "base"

    #: File extensions (with leading dot, lower-case) this converter claims.
    extensions: ClassVar[Sequence[str]] = ()

    #: Optional MIME types this converter can handle (informational).
    mime_types: ClassVar[Sequence[str]] = ()

    #: Import names of optional third-party packages, for `mdforge formats`.
    requires: ClassVar[Sequence[str]] = ()

    #: Name of the ``pip install mdforge[...]`` extra that provides `requires`.
    extra: ClassVar[str | None] = None

    #: One-line description shown by the CLI.
    description: ClassVar[str] = ""

    # -- Introspection -----------------------------------------------------

    @property
    def supported_extensions(self) -> frozenset[str]:
        """Extensions this converter handles, normalised to lower case."""
        return frozenset(ext.lower() for ext in self.extensions)

    def supports(self, path: PathLike) -> bool:
        """Return ``True`` when this converter can handle ``path``."""
        return _normalise_extension(path) in self.supported_extensions

    # -- Extension points --------------------------------------------------

    @abc.abstractmethod
    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Convert ``path`` into a :class:`DocumentResult`.

        Implementations must raise :class:`~mdforge.exceptions.ConversionError`
        (or let it propagate from the engine) rather than leaking parser
        specific exceptions to the caller.
        """
        raise NotImplementedError

    def extract_metadata(self, path: PathLike) -> dict[str, Any]:  # noqa: ARG002 - API symmetry
        """Cheaply extract metadata *without* a full conversion.

        The default implementation returns an empty mapping.  Converters that
        can read document properties cheaply should override this; the engine
        merges the result into the frontmatter.

        Args:
            path: File to inspect.

        Returns:
            Arbitrary JSON-serialisable metadata.
        """
        return {}

    # -- Helpers for subclasses -------------------------------------------

    def build_result(
        self,
        path: PathLike,
        markdown: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        warnings: Sequence[str] | None = None,
    ) -> DocumentResult:
        """Assemble a :class:`DocumentResult` with consistent defaults.

        Args:
            path: Source file the Markdown came from.
            markdown: Converted Markdown body.
            metadata: Extra metadata to attach.
            warnings: Non-fatal conversion notes.
        """
        return DocumentResult(
            markdown=markdown.strip() + "\n" if markdown.strip() else "",
            source_file=str(path),
            file_type=_normalise_extension(path).lstrip("."),
            metadata=dict(metadata or {}),
            warnings=list(warnings or []),
            converter=self.name,
        )

    def ensure_supported(self, path: PathLike) -> None:
        """Raise :class:`UnsupportedFormatError` if ``path`` is not claimable."""
        extension = _normalise_extension(path)
        if extension not in self.supported_extensions:
            raise UnsupportedFormatError(extension, sorted(self.supported_extensions))

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{type(self).__name__} name={self.name!r} extensions={tuple(self.extensions)!r}>"


def _normalise_extension(path: PathLike) -> str:
    """Return a lower-case, dot-prefixed extension for ``path``.

    Handles multi-dot extensions such as ``.tar.gz`` *and* compressed compound
    suffixes like ``.docx.bak`` by simply returning the last suffix.  Returns
    ``""`` for paths without a suffix.
    """
    return Path(path).suffix.lower()
