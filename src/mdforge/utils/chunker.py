"""Structure-aware Markdown chunking for RAG pipelines.

The default "split every N characters" approach shreds documents at arbitrary
boundaries, which is why naive RAG retrieves half a table or a dangling
sentence.  :class:`MarkdownChunker` instead:

1. Parses the Markdown heading tree (``#``/``##``/``###``), ignoring ``#``
   characters that appear inside fenced code blocks.
2. Emits one chunk per leaf section that fits, and *packs paragraphs* for
   sections that do not, with a configurable character overlap so facts split
   across a boundary are still retrievable from both sides.
3. Attaches a **context breadcrumb** (``Report > 2. Methods > 2.1 Sampling``)
   plus the frontmatter ``title`` to every chunk, so an isolated chunk still
   carries its position in the document.

Every chunk is a :class:`Chunk` with ``to_dict()`` / ``to_record()`` helpers so
you can dump straight into a vector database payload.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core.metadata import split_frontmatter

__all__ = [
    "Chunk",
    "MarkdownChunker",
    "chunk_file",
    "chunks_to_records",
]

PathLike = str | Path

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    """A single retrievable unit of a Markdown document.

    Attributes:
        index: Zero-based position of the chunk in the document.
        content: Chunk body (Markdown, heading included when configured).
        heading: Text of the heading that owns this chunk, if any.
        level: Heading level (1-6) of :attr:`heading`, or ``0`` for preamble.
        breadcrumb: Ancestor heading path *including* :attr:`heading`.
        start_line: 1-based line where the owning section starts.
        end_line: 1-based line where the owning section ends (inclusive).
        char_count: ``len(content)``.
        token_estimate: Rough LLM token count (``chars / 4``).
        metadata: Free-form metadata copied from the parent document.
    """

    index: int
    content: str
    heading: str | None = None
    level: int = 0
    breadcrumb: list[str] = field(default_factory=list)
    start_line: int = 1
    end_line: int = 1
    char_count: int = 0
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.char_count = len(self.content)
        self.token_estimate = estimate_tokens(self.content)

    @property
    def breadcrumb_text(self) -> str:
        """Human-readable breadcrumb joined with `` » ``."""
        return " » ".join(self.breadcrumb)

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        """Serialise to a JSON-friendly dictionary."""
        payload: dict[str, Any] = {
            "index": self.index,
            "heading": self.heading,
            "level": self.level,
            "breadcrumb": list(self.breadcrumb),
            "breadcrumb_text": self.breadcrumb_text,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "char_count": self.char_count,
            "token_estimate": self.token_estimate,
            "metadata": dict(self.metadata),
        }
        if include_content:
            payload["content"] = self.content
        return payload

    def to_record(self, *, embed_text: str | None = None) -> dict[str, Any]:
        """Build a vector-database ready record.

        The returned mapping has the shape most store APIs want:
        ``{"id": ..., "text": ..., "metadata": {...}}`` where ``text`` is the
        string to embed (breadcrumb + content by default) and ``metadata``
        holds everything filterable.

        Args:
            embed_text: Override the string that downstream systems should
                embed.  Defaults to ``breadcrumb + "\\n\\n" + content``.

        Returns:
            A dict with ``id``, ``text`` and ``metadata`` keys.
        """
        breadcrumb = self.breadcrumb_text
        text = (
            embed_text
            if embed_text is not None
            else (f"{breadcrumb}\n\n{self.content}" if breadcrumb else self.content)
        )
        meta = {
            "chunk_index": self.index,
            "heading": self.heading,
            "level": self.level,
            "breadcrumb": breadcrumb,
        }
        meta.update(self.metadata)
        return {"id": f"{meta.get('doc_id', 'doc')}::{self.index}", "text": text, "metadata": meta}

    def __len__(self) -> int:
        return self.char_count


def _dedupe_adjacent(parts: list[str]) -> list[str]:
    """Collapse consecutive duplicate breadcrumb entries.

    Frontmatter ``title`` and the document's ``# H1`` are frequently identical
    (``title: Retrieval Guide`` over ``# Retrieval Guide``); without this the
    breadcrumb would read ``Retrieval Guide » Retrieval Guide``.
    """
    deduped: list[str] = []
    for part in parts:
        if not deduped or deduped[-1] != part:
            deduped.append(part)
    return deduped


def estimate_tokens(text: str) -> int:
    """Estimate LLM tokens for ``text``.

    Uses the widely cited ``~4 characters per token`` heuristic.  It is
    deliberately dependency-free; swap in ``tiktoken`` downstream if you need
    exact counts.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass
class _Section:
    """Internal intermediate: a heading and the raw lines beneath it."""

    level: int
    title: str | None
    breadcrumb: list[str]
    lines: list[str]
    start_line: int
    end_line: int = 0

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip()


class MarkdownChunker:
    """Split Markdown into RAG-ready, structure-aware chunks.

    Args:
        max_chars: Soft upper bound on chunk size.  Sections larger than this
            are packed paragraph-by-paragraph.
        overlap_chars: Number of trailing characters carried from one packed
            chunk into the next, so boundary-spanning facts stay retrievable.
        min_chars: When greater than ``0``, sections smaller than this are
            folded into their predecessor to avoid a swarm of one-line chunks.
            Defaults to ``0`` (no merging) so the heading tree is preserved
            exactly; set it to ~120-200 when indexing a real-world corpus.
        heading_levels: Heading levels that start a new chunk.  Levels outside
            this set stay inline as content.
        include_heading_in_content: Prepend the owning heading to each chunk
            body so chunks read standalone.
        use_frontmatter_context: When the document starts with YAML
            frontmatter, use its ``title`` as the root of every breadcrumb.
        merge_small_sections: Fold sub-``min_chars`` sections forward.

    Example:
        >>> chunker = MarkdownChunker(max_chars=1200)
        >>> chunks = chunker.chunk(open("report.md", encoding="utf-8").read())
        >>> chunks[0].breadcrumb_text
        'Quarterly Report » 1. Executive Summary'
    """

    def __init__(
        self,
        *,
        max_chars: int = 1800,
        overlap_chars: int = 200,
        min_chars: int = 0,
        heading_levels: Sequence[int] = (1, 2, 3),
        include_heading_in_content: bool = True,
        use_frontmatter_context: bool = True,
        merge_small_sections: bool = True,
    ) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if overlap_chars < 0:
            raise ValueError("overlap_chars must not be negative")
        if overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self.min_chars = max(0, min_chars)
        self.heading_levels = frozenset(int(level) for level in heading_levels)
        self.include_heading_in_content = include_heading_in_content
        self.use_frontmatter_context = use_frontmatter_context
        self.merge_small_sections = merge_small_sections

    # -- Public API --------------------------------------------------------

    def chunk(
        self,
        markdown: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Split ``markdown`` into a list of :class:`Chunk` objects.

        Args:
            markdown: The Markdown document, optionally with frontmatter.
            metadata: Extra metadata copied onto every chunk (e.g. a
                ``doc_id`` or ``source_file``).

        Returns:
            Chunks in document order.  An empty or whitespace-only document
            yields an empty list.
        """
        if not markdown or not markdown.strip():
            return []

        front, body = split_frontmatter(markdown)
        root: list[str] = []
        if self.use_frontmatter_context and isinstance(front.get("title"), str):
            title = front["title"].strip()
            if title:
                root = [title]
        if not self.use_frontmatter_context:
            front = {}

        base_metadata: dict[str, Any] = dict(metadata or {})
        for key in ("title", "source_file", "file_type"):
            if key in front and key not in base_metadata:
                base_metadata[key] = front[key]

        sections = self._split_sections(body or markdown)
        if self.merge_small_sections and self.min_chars:
            sections = self._merge_small(sections)

        chunks: list[Chunk] = []
        for section in sections:
            text = section.body
            if self.include_heading_in_content and section.title:
                text = f"{'#' * section.level} {section.title}\n\n{text}".strip()
            if not text:
                continue
            breadcrumb = _dedupe_adjacent(root + section.breadcrumb)
            for piece in self._pack(text):
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        content=piece,
                        heading=section.title,
                        level=section.level,
                        breadcrumb=list(breadcrumb),
                        start_line=section.start_line,
                        end_line=section.end_line or section.start_line,
                        metadata=dict(base_metadata),
                    )
                )
        return chunks

    def chunk_many(
        self,
        documents: dict[str, str],
    ) -> dict[str, list[Chunk]]:
        """Chunk several documents keyed by an identifier (usually a path)."""
        return {
            doc_id: self.chunk(text, metadata={"doc_id": doc_id})
            for doc_id, text in documents.items()
        }

    # -- Parsing -----------------------------------------------------------

    def _split_sections(self, markdown: str) -> list[_Section]:
        """Parse the heading tree into a flat, ordered list of sections."""
        lines = markdown.splitlines()
        sections: list[_Section] = []
        stack: list[tuple[int, str]] = []
        current = _Section(level=0, title=None, breadcrumb=[], lines=[], start_line=1)
        in_fence = False
        fence_char = ""
        fence_len = 0

        for number, line in enumerate(lines, start=1):
            fence_match = _FENCE_RE.match(line)
            if fence_match:
                token = fence_match.group(1)
                if not in_fence:
                    in_fence = True
                    fence_char = token[0]
                    fence_len = len(token)
                elif token[0] == fence_char and len(token) >= fence_len:
                    in_fence = False
                current.lines.append(line)
                continue

            if in_fence:
                current.lines.append(line)
                continue

            heading = _HEADING_RE.match(line)
            if heading is None or len(heading.group(1)) not in self.heading_levels:
                current.lines.append(line)
                continue

            level = len(heading.group(1))
            title = heading.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            current.end_line = number - 1
            if current.body or current.title:
                sections.append(current)
            stack.append((level, title))
            current = _Section(
                level=level,
                title=title,
                breadcrumb=[t for _, t in stack],
                lines=[],
                start_line=number,
            )

        current.end_line = len(lines)
        if current.body or current.title:
            sections.append(current)
        return [s for s in sections if s.body or s.title]

    def _merge_small(self, sections: list[_Section]) -> list[_Section]:
        """Fold tiny sections into their predecessor to avoid chunk spam."""
        merged: list[_Section] = []
        for section in sections:
            if (
                merged
                and len(section.body) < self.min_chars
                # Never fold a parent section into a deeper child: the child's
                # breadcrumb would then mislabel the parent's content.
                and section.level >= merged[-1].level
                and len(merged[-1].body) + len(section.body) <= self.max_chars
            ):
                previous = merged[-1]
                if section.title:
                    previous.lines.append("")
                    previous.lines.append(f"{'#' * section.level} {section.title}")
                previous.lines.extend(section.lines)
                previous.end_line = section.end_line
                continue
            merged.append(section)
        return merged

    # -- Packing -----------------------------------------------------------

    def _pack(self, text: str) -> list[str]:
        """Split one section's text into <= ``max_chars`` pieces with overlap."""
        text = text.strip()
        if not text:
            return []
        if len(text) <= self.max_chars:
            return [text]

        pieces: list[str] = []
        for paragraph in _PARAGRAPH_SPLIT_RE.split(text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if len(paragraph) <= self.max_chars:
                pieces.append(paragraph)
            else:
                pieces.extend(self._split_oversized(paragraph))

        packed: list[str] = []
        buffer = ""
        for piece in pieces:
            if not buffer:
                buffer = piece
                continue
            if len(buffer) + len(piece) + 2 <= self.max_chars:
                buffer = f"{buffer}\n\n{piece}"
                continue
            packed.append(buffer)
            tail = self._overlap_tail(buffer)
            candidate = f"{tail}\n\n{piece}" if tail else piece
            buffer = candidate if len(candidate) <= self.max_chars else piece
        if buffer:
            packed.append(buffer)
        return packed

    def _split_oversized(self, paragraph: str) -> list[str]:
        """Break a single oversized paragraph into sentence-ish fragments."""
        sentences = _SENTENCE_SPLIT_RE.split(paragraph)
        fragments: list[str] = []
        buffer = ""
        for sentence in sentences:
            if len(sentence) > self.max_chars:
                if buffer:
                    fragments.append(buffer)
                    buffer = ""
                fragments.extend(
                    sentence[i : i + self.max_chars]
                    for i in range(0, len(sentence), self.max_chars)
                )
                continue
            if not buffer:
                buffer = sentence
            elif len(buffer) + len(sentence) + 1 <= self.max_chars:
                buffer = f"{buffer} {sentence}"
            else:
                fragments.append(buffer)
                buffer = sentence
        if buffer:
            fragments.append(buffer)
        return fragments

    def _overlap_tail(self, text: str) -> str:
        """Return up to ``overlap_chars`` of ``text``'s tail, on a word boundary."""
        if self.overlap_chars <= 0:
            return ""
        tail = text[-self.overlap_chars :]
        for separator in ("\n", ". ", "! ", "? ", " "):
            index = tail.find(separator)
            if 0 <= index < len(tail) - 1:
                return tail[index + len(separator) :].strip()
        return tail.strip()


def chunk_file(
    path: PathLike,
    *,
    chunker: MarkdownChunker | None = None,
    encoding: str = "utf-8",
    **chunker_options: Any,
) -> list[Chunk]:
    """Read a Markdown file and chunk it.

    Args:
        path: Markdown file to read.
        chunker: Reuse an existing chunker; otherwise one is built from
            ``chunker_options``.
        encoding: Text encoding for reading the file.
        **chunker_options: Forwarded to :class:`MarkdownChunker` when
            ``chunker`` is ``None``.

    Returns:
        The document's chunks.
    """
    source = Path(path)
    text = source.read_text(encoding=encoding)
    active = chunker or MarkdownChunker(**chunker_options)
    return active.chunk(text, metadata={"source_file": str(source)})


def chunks_to_records(
    chunks: Iterable[Chunk],
    *,
    embed_text: bool = True,
) -> list[dict[str, Any]]:
    """Convert an iterable of chunks into vector-database records.

    Args:
        chunks: Chunks to convert.
        embed_text: Kept for API symmetry; when ``False`` the ``text`` field is
            omitted from each record.

    Returns:
        A list of ``{"id", "text", "metadata"}`` mappings.
    """
    records: list[dict[str, Any]] = []
    for chunk in chunks:
        record = chunk.to_record()
        if not embed_text:
            record.pop("text", None)
        records.append(record)
    return records


def asdict_public(chunk: Chunk) -> dict[str, Any]:  # pragma: no cover - convenience
    """Return the raw dataclass fields of ``chunk`` (includes ``breadcrumb_text``)."""
    return asdict(chunk)


def dump_frontmatter(markdown: str) -> dict[str, Any]:  # pragma: no cover - convenience
    """Parse and return only the frontmatter mapping of ``markdown``."""
    metadata, _ = split_frontmatter(markdown)
    return metadata
