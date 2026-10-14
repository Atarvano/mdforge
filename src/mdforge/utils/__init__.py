"""Utilities: text normalisation, table rendering, dependency shims, chunking."""

from __future__ import annotations

from .chunker import Chunk, MarkdownChunker, chunk_file, chunks_to_records
from .text import (
    escape_table_cell,
    fenced_code_block,
    markdown_table,
    normalise_markdown,
    read_text_safely,
    slugify,
)

__all__ = [
    "Chunk",
    "MarkdownChunker",
    "chunk_file",
    "chunks_to_records",
    "escape_table_cell",
    "fenced_code_block",
    "markdown_table",
    "normalise_markdown",
    "read_text_safely",
    "slugify",
]
