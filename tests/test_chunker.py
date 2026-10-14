"""Tests for the structure-aware Markdown chunker."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdforge.utils.chunker import MarkdownChunker, chunk_file, chunks_to_records, estimate_tokens


def structural_chunker(**kwargs: object) -> MarkdownChunker:
    """A chunker for exact structural assertions.

    Small-section merging is off by default in the library, but this helper
    makes that explicit so the tests keep documenting the intent.
    """
    kwargs.setdefault("min_chars", 0)
    return MarkdownChunker(**kwargs)  # type: ignore[arg-type]


DOCUMENT = """---
title: Retrieval Guide
---

# Retrieval Guide

Preamble paragraph that belongs to the document root.

## Indexing

Indexing overview text.

### Chunk sizes

Prefer small chunks.

### Overlap

Overlap keeps facts retrievable.

## Querying

Rewrite the query first.
"""


def test_breadcrumbs_follow_heading_tree() -> None:
    chunks = structural_chunker().chunk(DOCUMENT)
    breadcrumbs = [c.breadcrumb for c in chunks]
    assert ["Retrieval Guide"] in breadcrumbs
    assert ["Retrieval Guide", "Indexing"] in breadcrumbs
    assert ["Retrieval Guide", "Indexing", "Chunk sizes"] in breadcrumbs
    assert ["Retrieval Guide", "Querying"] in breadcrumbs


def test_frontmatter_title_becomes_root_breadcrumb() -> None:
    chunks = structural_chunker().chunk(DOCUMENT)
    assert all(c.breadcrumb[0] == "Retrieval Guide" for c in chunks)
    assert all("title" not in c.content for c in chunks)


def test_frontmatter_context_can_be_disabled() -> None:
    chunker = structural_chunker(use_frontmatter_context=False)
    chunks = chunker.chunk(DOCUMENT)
    assert all("Retrieval Guide" in c.breadcrumb for c in chunks)
    assert chunks[0].breadcrumb == ["Retrieval Guide"]


def test_preamble_chunk_has_no_heading() -> None:
    markdown = "Just a paragraph with no headings at all.\n\nSecond paragraph."
    chunks = structural_chunker().chunk(markdown)
    assert len(chunks) == 1
    assert chunks[0].heading is None
    assert chunks[0].breadcrumb == []
    assert chunks[0].breadcrumb_text == ""


def test_heading_is_included_in_content() -> None:
    chunks = structural_chunker().chunk(DOCUMENT)
    indexing = next(c for c in chunks if c.heading == "Indexing")
    assert indexing.content.startswith("## Indexing")
    assert "Indexing overview text." in indexing.content


def test_large_section_is_packed_with_overlap() -> None:
    paragraph = "Sentence about retrieval. " * 60
    markdown = f"# Doc\n\n## Big\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}\n"
    chunker = MarkdownChunker(max_chars=800, overlap_chars=100)
    chunks = chunker.chunk(markdown)
    big = [c for c in chunks if c.heading == "Big"]
    assert len(big) > 1
    assert all(c.char_count <= 800 + len("## Big\n\n") for c in big)


def test_oversized_paragraph_is_split() -> None:
    single = "word " * 2000
    chunks = MarkdownChunker(max_chars=500, overlap_chars=0).chunk(f"# T\n\n{single}")
    assert len(chunks) > 1


def test_headings_inside_code_fences_are_ignored() -> None:
    markdown = "# Doc\n\n```markdown\n# Not a heading\n## Also not\n```\n\n## Real\n\nBody.\n"
    chunks = structural_chunker().chunk(markdown)
    headings = [c.heading for c in chunks]
    assert "Not a heading" not in headings
    assert "Real" in headings


def test_small_sections_are_merged() -> None:
    markdown = "## A\n\n" + "long body " * 40 + "\n\n## B\n\ntiny\n"
    chunks = MarkdownChunker(min_chars=200).chunk(markdown)
    assert len(chunks) == 1
    assert "tiny" in chunks[0].content


def test_token_estimate_is_positive_and_monotonic() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("a" * 800) > estimate_tokens("a" * 400)


def test_chunk_to_dict_and_record() -> None:
    chunks = structural_chunker().chunk(DOCUMENT, metadata={"doc_id": "guide"})
    record = chunks[0].to_record()
    assert record["id"].startswith("guide::")
    assert record["metadata"]["doc_id"] == "guide"
    assert record["metadata"]["chunk_index"] == 0
    assert record["text"]

    payload = chunks[0].to_dict()
    assert payload["char_count"] == chunks[0].char_count
    assert "content" in payload
    assert "content" not in chunks[0].to_dict(include_content=False)


def test_chunks_to_records_helper() -> None:
    chunks = structural_chunker().chunk(DOCUMENT)
    records = chunks_to_records(chunks)
    assert len(records) == len(chunks)
    assert all({"id", "text", "metadata"} <= set(r) for r in records)
    without_text = chunks_to_records(chunks, embed_text=False)
    assert all("text" not in r for r in without_text)


def test_chunk_index_is_sequential() -> None:
    chunks = structural_chunker().chunk(DOCUMENT)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_empty_document_yields_no_chunks() -> None:
    assert MarkdownChunker().chunk("") == []
    assert MarkdownChunker().chunk("   \n\n  ") == []


def test_invalid_options_raise() -> None:
    with pytest.raises(ValueError):
        MarkdownChunker(max_chars=0)
    with pytest.raises(ValueError):
        MarkdownChunker(max_chars=100, overlap_chars=100)


def test_chunk_file_reads_and_tags_source(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(DOCUMENT, encoding="utf-8")
    chunks = chunk_file(path, max_chars=1000)
    assert chunks
    assert all(c.metadata["source_file"] == str(path) for c in chunks)


def test_line_numbers_are_recorded() -> None:
    chunks = structural_chunker().chunk(DOCUMENT)
    querying = next(c for c in chunks if c.heading == "Querying")
    assert querying.start_line > 1
    assert querying.end_line >= querying.start_line


def test_deep_headings_stay_inline_by_default() -> None:
    markdown = "# Doc\n\n## Section\n\n#### Deep heading\n\nDeep body.\n"
    chunks = structural_chunker().chunk(markdown)
    assert [c.heading for c in chunks] == ["Doc", "Section"]
    assert "#### Deep heading" in chunks[-1].content
