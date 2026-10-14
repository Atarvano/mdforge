"""Metadata assembly and YAML frontmatter rendering.

The frontmatter contract is intentionally stable - downstream RAG pipelines
index it verbatim, so key names and ordering matter:

.. code-block:: yaml

    ---
    title: Quarterly Report
    source_file: reports/q3.pdf
    file_type: pdf
    converter: pdf
    converted_at: '2026-01-31T09:15:00+00:00'
    word_count: 4821
    char_count: 31240
    ---
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import yaml

__all__ = [
    "build_metadata",
    "count_words",
    "prepend_frontmatter",
    "render_frontmatter",
    "split_frontmatter",
    "utc_now_iso",
]

#: Canonical key order for the frontmatter block.
CORE_KEY_ORDER = (
    "title",
    "source_file",
    "file_type",
    "converter",
    "converted_at",
    "word_count",
    "char_count",
)


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string.

    Seconds precision keeps diffs of generated collections stable and avoids
    needlessly invalidating caches keyed on the frontmatter.
    """
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def count_words(text: str) -> int:
    """Count whitespace-delimited words in ``text``."""
    return len(text.split())


def build_metadata(
    *,
    markdown: str,
    source_file: str,
    file_type: str,
    converter: str,
    converter_metadata: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge derived, converter-supplied and user-supplied metadata.

    Precedence (lowest to highest): derived values < converter metadata <
    ``extra``.  That ordering means a PDF's embedded ``title`` beats the
    filename-derived fallback, and a caller can always override anything.

    Args:
        markdown: Converted body used to compute word/char counts.
        source_file: Original file path.
        file_type: Normalised extension without a dot.
        converter: Converter name.
        converter_metadata: Metadata produced by the converter.
        extra: Caller overrides (e.g. from the CLI's ``--meta`` flag).

    Returns:
        An ordered-by-:data:`CORE_KEY_ORDER` dictionary ready for YAML output.
    """
    derived: dict[str, Any] = {
        "title": _fallback_title(source_file),
        "source_file": source_file,
        "file_type": file_type,
        "converter": converter,
        "converted_at": utc_now_iso(),
        "word_count": count_words(markdown),
        "char_count": len(markdown),
    }

    merged: dict[str, Any] = dict(derived)
    for key, value in (converter_metadata or {}).items():
        if value is not None and value != "":
            merged[key] = value
    for key, value in (extra or {}).items():
        if value is not None:
            merged[key] = value

    # Deterministic ordering: canonical keys first, then the rest alphabetically.
    ordered: dict[str, Any] = {}
    for key in CORE_KEY_ORDER:
        if key in merged:
            ordered[key] = merged[key]
    for key in sorted(k for k in merged if k not in ordered):
        ordered[key] = merged[key]
    return ordered


def render_frontmatter(metadata: Mapping[str, Any], *, delimiter: str = "---") -> str:
    """Render ``metadata`` as a YAML frontmatter block.

    Args:
        metadata: Mapping to serialise.  Values must be JSON/YAML-safe.
        delimiter: Fence marker; defaults to ``---``.

    Returns:
        A string of the form ``---\\n<yaml>\\n---`` (no trailing newline).
    """
    body = yaml.safe_dump(
        dict(metadata),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    ).rstrip("\n")
    return f"{delimiter}\n{body}\n{delimiter}"


def prepend_frontmatter(
    markdown: str,
    metadata: Mapping[str, Any],
    *,
    include: bool = True,
) -> str:
    """Return ``markdown`` preceded by its frontmatter block.

    Any frontmatter already present in ``markdown`` is stripped first so that
    repeated conversions are idempotent.
    """
    if not include:
        return markdown
    _, body = split_frontmatter(markdown)
    block = render_frontmatter(metadata)
    body = body.lstrip("\n")
    return f"{block}\n\n{body}".rstrip() + "\n"


def split_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Split leading YAML frontmatter from a Markdown document.

    Args:
        markdown: Markdown text, optionally starting with a ``---`` fence.

    Returns:
        ``(metadata, body)``.  ``metadata`` is empty when no valid
        frontmatter is present, and ``body`` is always the remainder.
    """
    if not markdown.startswith("---"):
        return {}, markdown
    lines = markdown.splitlines()
    if len(lines) < 2 or lines[0].strip() != "---":
        return {}, markdown
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            raw = "\n".join(lines[1:index])
            try:
                parsed = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                return {}, markdown
            if not isinstance(parsed, dict):
                return {}, markdown
            body = "\n".join(lines[index + 1 :]).lstrip("\n")
            return dict(parsed), body
    return {}, markdown


def _fallback_title(source_file: str) -> str:
    """Derive a human-readable title from a path, e.g. ``q3-report.pdf``."""
    from pathlib import Path

    stem = Path(source_file).stem or source_file
    return stem.replace("_", " ").replace("-", " ").strip().title()
