"""Plain-text / Markdown passthrough converter."""

from __future__ import annotations

import re
from typing import Any

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..utils.text import read_text_safely

__all__ = ["TextConverter"]

_MARKDOWN_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd")
_ATX_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_BLANK_LINE_RE = re.compile(r"\n{3,}")


class TextConverter(BaseConverter):
    """Handle ``.txt``, ``.log``, ``.rst`` and Markdown files.

    Markdown input is returned verbatim (the engine still normalises it and
    adds frontmatter).  Everything else is treated as prose: blank lines are
    preserved so the structural chunker can still partition the document, and
    a leading ``Title``/``=====`` reST heading is promoted to ``# Title``.
    """

    name = "text"
    extensions = (".txt", ".text", ".log", ".rst", ".md", ".markdown", ".mdown", ".mkd")
    mime_types = ("text/plain", "text/markdown")
    description = "Plain text and Markdown files"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Read ``path`` as text, preserving its paragraph structure.

        Args:
            path: Text file to read.
            **options: Supports ``encoding`` (str) and ``max_bytes`` (int).

        Returns:
            A :class:`DocumentResult` containing the file's contents.
        """
        encoding: str | None = options.get("encoding")
        max_bytes: int | None = options.get("max_bytes")
        text, used_encoding = read_text_safely(path, encoding=encoding, max_bytes=max_bytes)

        warnings: list[str] = []
        if used_encoding not in {"utf-8", "utf-8-sig", "ascii"}:
            warnings.append(
                f"Decoded '{path}' as {used_encoding}; "
                "verify that accented characters rendered correctly."
            )

        if str(path).lower().endswith(_MARKDOWN_EXTENSIONS):
            body = text
            title = _first_atx_heading(text)
        else:
            body = _promote_rst_heading(text)
            title = _first_atx_heading(body)

        metadata: dict[str, Any] = {
            "encoding": used_encoding,
            "line_count": text.count("\n") + 1,
        }
        if title:
            metadata["title"] = title
        return self.build_result(path, body, metadata=metadata, warnings=warnings)


def _first_atx_heading(text: str) -> str | None:
    """Return the text of the first ATX heading in ``text``, if any."""
    match = _ATX_HEADING_RE.search(text)
    return match.group(1).strip() if match else None


def _promote_rst_heading(text: str) -> str:
    """Turn a leading reST/underline heading into an ATX ``#`` heading."""
    lines = text.split("\n")
    for index in range(len(lines) - 1):
        title = lines[index].strip()
        underline = lines[index + 1].strip()
        if not title or len(underline) < 3:
            continue
        if set(underline) <= {"="} and len(underline) >= len(title):
            lines[index] = f"# {title}"
            del lines[index + 1]
            break
        if set(underline) <= {"-"} and len(underline) >= len(title):
            lines[index] = f"## {title}"
            del lines[index + 1]
            break
    return _BLANK_LINE_RE.sub("\n\n", "\n".join(lines))
