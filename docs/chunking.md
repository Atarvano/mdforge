# Chunking for RAG

`MarkdownChunker` turns one Markdown document into a list of `Chunk` objects
that are *safe to embed*. It is structure-aware: it respects the heading tree,
keeps tables intact where it can, and stamps every chunk with enough context to
stand alone.

The problem it solves is real. Fixed-size splitting cuts a table in half, splits
a list from its lead-in sentence, and produces chunks whose text gives the
embedding model no idea what *part* of the document it is looking at. A query
for "sampling method" then fails to match a chunk that says only "…the second
batch was processed at 4 °C."

## What a chunk looks like

```python
@dataclass
class Chunk:
    index: int  # position in the document
    content: str  # Markdown body (heading included by default)
    heading: str | None  # owning heading
    level: int  # heading level (0 for preamble)
    breadcrumb: list[str]  # ancestor titles, root first
    start_line: int  # 1-based
    end_line: int
    char_count: int  # len(content)
    token_estimate: int  # chars / 4 (or 1 for non-empty tiny chunks)
    metadata: dict[str, Any]  # copied from the parent document
```

`chunk.breadcrumb_text` joins the breadcrumb with `»`:

```
Handbook » 3. Leave policy » 3.2 Parental leave
```

## The algorithm

1. **Parse the heading tree.** `_split_sections()` walks the document line by
   line, tracking `#`/`##`/`###` headings (configurable via `heading_levels`).
   Heading markers inside fenced code blocks are ignored, so a `# comment` in a
   Python example never becomes a section.
2. **One chunk per leaf section** when it fits inside `max_chars`.
3. **Pack paragraphs** when a section is too big. Paragraphs are accumulated up
   to `max_chars`; a section with no paragraph breaks is split on sentences, and
   a single oversized sentence is hard-sliced as a last resort.
4. **Overlap** the tail of each packed chunk into the next (`overlap_chars`,
   snapped to a word/sentence boundary) so a fact spanning the cut is
   retrievable from both sides.
5. **Breadcrumb everything.** The ancestor path becomes the chunk's
   `breadcrumb`, and (with `use_frontmatter_context=True`) the frontmatter
   `title` is prepended as the root — deduplicated when it equals the `# H1`.

## Parameters

| Option | Default | Effect |
| --- | --- | --- |
| `max_chars` | `1800` | Soft ceiling per chunk. ~450 tokens at the 4-chars-per-token heuristic. |
| `overlap_chars` | `200` | Trailing context carried into the next packed chunk. Must be `< max_chars`. |
| `min_chars` | `0` | Fold sections shorter than this into their predecessor. `0` keeps the heading tree exactly. |
| `heading_levels` | `(1, 2, 3)` | Which levels start a new chunk. Deeper levels stay inline. |
| `include_heading_in_content` | `True` | Prepend the owning heading to the body so chunks read standalone. |
| `use_frontmatter_context` | `True` | Use frontmatter `title` as the breadcrumb root. |
| `merge_small_sections` | `True` | Master switch for folding small sections. |

### Choosing values

* **Small models / tight context** — `max_chars=1200`, `overlap_chars=150`.
* **Long legal or medical prose** — `max_chars=2400`, `min_chars=200` so a wall
  of one-sentence subsections becomes a few substantial chunks.
* **Slides and config tables** — `min_chars=0` (the default) keeps each section
  as its own chunk, which matches how those documents are read.

`min_chars` merging is deliberately conservative: a section is only folded if
the previous section is at most its own heading level. A parent heading is never
absorbed into a deeper child, because the child's breadcrumb would then mislabel
the parent's content.

## Usage

### Library

```python
from mdforge import convert
from mdforge.utils.chunker import MarkdownChunker, chunks_to_records

markdown = convert("handbook.pdf").markdown

chunker = MarkdownChunker(max_chars=1200, overlap_chars=150, min_chars=120)
chunks = chunker.chunk(markdown, metadata={"doc_id": "handbook"})

for chunk in chunks:
    print(chunk.breadcrumb_text)  # 'Handbook » 3. Leave policy » 3.2 Parental leave'
    print(chunk.token_estimate)  # ~285
    print(chunk.content[:80])
```

### Straight into a vector store

`chunks_to_records()` produces the `{"id", "text", "metadata"}` shape most
stores expect, where `text` is the breadcrumb **plus** the content (embed the
breadcrumb — it materially improves retrieval) and `metadata` holds everything
filterable:

```python
records = chunks_to_records(chunks)
# [{'id': 'handbook::0', 'text': 'Handbook » …\n\n…', 'metadata': {...}}, ...]

collection.add(
    ids=[r["id"] for r in records],
    documents=[r["text"] for r in records],
    metadatas=[r["metadata"] for r in records],
)
```

You can override what gets embedded with `chunk.to_record(embed_text=...)`, or
drop the text field with `chunks_to_records(chunks, embed_text=False)` when your
store embeds server-side.

### From a file

```python
from mdforge.utils.chunker import chunk_file

chunks = chunk_file("out/handbook.md", max_chars=1200)
```

### Command line

```bash
# JSONL, one chunk per line (pipe it anywhere)
mdforge chunk out/handbook.md -o handbook.chunks.jsonl

# Or inspect the structure before you index it
mdforge chunk out/handbook.md --preview
```

`mdforge convert ... --chunk` and `mdforge batch ... --chunk` write a
`.chunks.jsonl` file next to each `.md`.

## Token counts

`token_estimate` is `ceil(chars / 4)`, clamped to at least 1 for non-empty
content. It is a heuristic, not a tokenizer: it is dependency-free and good
enough for sizing, but if you need exact counts, tokenise
`chunk.to_record()["text"]` with `tiktoken` downstream. Nothing in mdforge
depends on the estimate being exact.
</content>
