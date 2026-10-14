"""Small, dependency-light text helpers shared by the converters.

Everything here is pure Python / stdlib so it can be imported unconditionally.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path

__all__ = [
    "collapse_blank_lines",
    "escape_table_cell",
    "fenced_code_block",
    "markdown_table",
    "normalise_markdown",
    "read_text_safely",
    "slugify",
]

PathLike = str | Path

_BLANK_LINES_RE = re.compile(r"\n{3,}")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

#: Candidate encodings tried, in order, when the caller does not specify one.
_FALLBACK_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


def normalise_markdown(text: str) -> str:
    """Tidy converter output without touching its semantics.

    * Normalises line endings to ``\\n``.
    * Strips trailing whitespace on every line (except inside fenced code
      blocks, where trailing spaces are occasionally meaningful).
    * Collapses runs of three or more newlines into exactly two.
    * Ensures the document ends with a single newline.

    Args:
        text: Raw Markdown produced by a converter.

    Returns:
        Cleaned Markdown.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    in_fence = False
    fence = ""
    cleaned: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = "```" if stripped.startswith("```") else "~~~"
            if not in_fence:
                in_fence, fence = True, marker
            elif stripped.startswith(fence):
                in_fence = False
            cleaned.append(line.rstrip())
            continue
        cleaned.append(line if in_fence else line.rstrip())
    text = "\n".join(cleaned)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip("\n") + "\n" if text.strip() else ""


def collapse_blank_lines(text: str, *, max_blank: int = 2) -> str:
    """Collapse consecutive blank lines to at most ``max_blank`` newlines."""
    pattern = re.compile(r"\n{" + str(max_blank + 1) + r",}")
    return pattern.sub("\n" * max_blank, text)


def escape_table_cell(value: object) -> str:
    """Escape a value for safe inclusion in a Markdown table cell."""
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("|", "\\|")
    text = _TRAILING_SPACE_RE.sub("", text)
    text = text.replace("\n", "<br>")
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def markdown_table(
    rows: Sequence[Sequence[object]],
    header: Sequence[object] | None = None,
    *,
    align: Sequence[str] | None = None,
) -> str:
    """Render ``rows`` as a GitHub-flavoured Markdown table.

    Args:
        rows: Data rows.  When ``header`` is ``None`` the first row is promoted
            to the header.
        header: Explicit header row.  Columns beyond its length are dropped;
            shorter rows are padded with empty cells.
        align: Optional per-column alignment: ``"left"``, ``"right"`` or
            ``"center"``.  Missing entries default to ``"left"``.

    Returns:
        Markdown table text, or ``""`` when there is nothing to render.
    """
    data = [list(row) for row in rows]
    if header is None:
        if not data:
            return ""
        head, data = data[0], data[1:]
    else:
        head = list(header)

    if not head:
        return ""

    ncols = len(head)

    def _fit(row: Sequence[object]) -> list[str]:
        cells = [escape_table_cell(c) for c in row][:ncols]
        cells.extend([""] * (ncols - len(cells)))
        return cells

    alignment = list(align or [])
    if len(alignment) < ncols:
        alignment.extend(["left"] * (ncols - len(alignment)))
    markers = {"left": ":---", "right": "---:", "center": ":---:"}
    separator = [markers.get(a, ":---") for a in alignment[:ncols]]

    lines = [
        "| " + " | ".join(_fit(head)) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(_fit(row)) + " |" for row in data)
    return "\n".join(lines)


def fenced_code_block(text: str, *, language: str = "") -> str:
    """Wrap ``text`` in a fenced code block, widening the fence if needed.

    A naive ``"```"`` fence breaks whenever the payload itself contains three
    backticks (common in embedded Markdown).  This helper picks the shortest
    fence that is strictly longer than any run of backticks in the payload.
    """
    longest = 0
    for run in re.findall(r"`+", text):
        longest = max(longest, len(run))
    fence = "`" * max(3, longest + 1)
    language = language.strip()
    return f"{fence}{language}\n{text.rstrip()}\n{fence}"


def slugify(text: str, *, max_length: int = 80) -> str:
    """Convert arbitrary text into a URL/anchor friendly slug."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_RE.sub("-", ascii_text).strip("-")
    return slug[:max_length].strip("-")


def read_text_safely(
    path: PathLike,
    *,
    encoding: str | None = None,
    max_bytes: int | None = None,
) -> tuple[str, str]:
    """Read a text file, detecting its encoding instead of crashing.

    Strategy:

    1. If ``encoding`` is given, honour it.
    2. Otherwise try :mod:`charset_normalizer` when installed.
    3. Otherwise fall back through :data:`_FALLBACK_ENCODINGS`.

    Args:
        path: File to read.
        encoding: Explicit encoding, bypassing detection.
        max_bytes: Read at most this many bytes from the start of the file.

    Returns:
        ``(text, encoding_used)``.

    Raises:
        FileNotFoundError: If the file does not exist.
        UnicodeDecodeError: If every candidate encoding fails.
    """
    source = Path(path)
    raw = source.read_bytes()
    if max_bytes is not None:
        raw = raw[:max_bytes]
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    candidates: list[str] = []
    if encoding:
        candidates.append(encoding)
    else:
        detected = _detect_encoding(raw)
        if detected:
            candidates.append(detected)
        candidates.extend(_FALLBACK_ENCODINGS)

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return raw.decode(candidate), candidate
        except (UnicodeDecodeError, LookupError):
            continue

    # Last resort: never fail, replace undecodable bytes.
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _detect_encoding(raw: bytes) -> str | None:
    """Best-effort encoding detection using charset-normalizer if present."""
    try:
        from charset_normalizer import from_bytes
    except ImportError:
        return None
    try:
        match = from_bytes(raw[:65536]).best()
    except Exception:  # noqa: BLE001 - detection must never break a conversion
        return None
    return match.encoding if match is not None else None


def iter_lines(text: str) -> Iterable[str]:
    """Yield lines without their terminators (thin ``splitlines`` wrapper)."""
    return text.splitlines()
