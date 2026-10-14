<div align="center">

# mdforge

**Documents in. Retrieval-ready Markdown out.**

Convert PDF, DOCX, PPTX, XLSX/CSV, HTML, JSON, XML and plain text into clean,
structured Markdown that is *actually* optimised for LLM prompts and RAG
pipelines — with YAML frontmatter, structure-aware chunking and concurrent
batch conversion built in.

[![PyPI version](https://img.shields.io/pypi/v/mdforge.svg?color=3776AB&logo=pypi&logoColor=white)](https://pypi.org/project/mdforge/)
[![Python versions](https://img.shields.io/pypi/pyversions/mdforge.svg)](https://pypi.org/project/mdforge/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/AndrazKen/mdforge/actions/workflows/tests.yml/badge.svg)](https://github.com/AndrazKen/mdforge/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/AndrazKen/mdforge/branch/main/graph/badge.svg)](https://codecov.io/gh/AndrazKen/mdforge)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-blue.svg)](https://mypy-lang.org/)
[![PyPI downloads](https://img.shields.io/pypi/dm/mdforge.svg)](https://pypi.org/project/mdforge/)

</div>

---

## Why mdforge?

Getting *text* out of a PDF is easy. Getting **structure** out of it — headings
that survive into your chunker, tables that stay tables, metadata you can filter
on — is the hard part, and it is exactly what retrieval quality depends on.

| Capability | What it means for you |
| --- | --- |
| **YAML frontmatter by default** | Every document arrives with `title`, `source_file`, `file_type`, `converted_at`, `word_count` and any document properties the parser found. Filter, sort and cite without re-reading the body. |
| **Smart structural chunking** | `MarkdownChunker` splits on the *heading tree*, packs oversized sections with overlap, and stamps every chunk with a breadcrumb (`Report » Methods » Sampling`) so an isolated chunk still knows where it came from. |
| **Async batch conversion** | `engine.convert_batch([...])` maps over hundreds of files with bounded concurrency and per-file error isolation. One broken PDF never sinks the run. |
| **Plugin-first architecture** | Subclass `BaseConverter`, declare an extension, done. The registry, routing, metadata merge and CLI listing pick it up automatically. |
| **Lazy, optional dependencies** | Core install is three tiny packages. PDF support pulls `pypdf`, DOCX pulls `python-docx`, and nothing imports a parser you did not install. |
| **Typed and tested** | Full type hints, `py.typed` marker, strict mypy, ruff-clean, and a CI matrix across Linux/macOS/Windows and Python 3.10–3.13. |

## Installation

```bash
# Core: CLI, frontmatter, chunking, plain text / JSON / XML / CSV / HTML collectors
pip install mdforge

# Everything (PDF, DOCX, PPTX, XLSX, HTML, encoding detection)
pip install "mdforge[all]"

# Only what you need
pip install "mdforge[pdf]"     # pypdf + pdfplumber
pip install "mdforge[docx]"    # python-docx
pip install "mdforge[pptx]"    # python-pptx
pip install "mdforge[xlsx]"    # openpyxl
pip install "mdforge[html]"    # beautifulsoup4 + lxml
```

Requires **Python 3.10+**.

## Quick start

### Python API

```python
from mdforge import convert, convert_batch, MarkdownChunker

result = convert("quarterly-report.pdf")

print(result.markdown)  # Markdown + YAML frontmatter
print(result.metadata["title"])  # 'Quarterly Report'
print(result.word_count)  # 4821
print(result.warnings)  # ['2 page(s) contained no extractable text.']
```

The generated document starts like this:

```markdown
---
title: Quarterly Report
source_file: reports/q3.pdf
file_type: pdf
converter: pdf
converted_at: '2026-01-31T09:15:00+00:00'
word_count: 4821
char_count: 31240
page_count: 24
extracted_pages: 24
empty_pages: 0
pdf_engine: pypdf
---

<!-- page: 1 -->

Revenue grew by 12% year over year, driven by strong demand in Europe…
```

### Batch conversion

```python
from mdforge import convert_batch

batch = convert_batch(
    ["a.docx", "b.pptx", "c.xlsx", "broken.pdf"],
    max_workers=8,
)

print(f"{len(batch.results)} ok, {batch.failures} failed ({batch.files_per_second:.1f} files/s)")

for error in batch.errors:
    print(error.source_file, "->", error.error)
```

Inside an async application, `await engine.convert_batch(...)` is a first-class
coroutine; `convert_batch_sync` is safe to call from a running event loop too.

### RAG-ready chunking

```python
from mdforge import convert
from mdforge.utils.chunker import MarkdownChunker, chunks_to_records

markdown = convert("handbook.pdf").markdown

chunker = MarkdownChunker(max_chars=1200, overlap_chars=150)
chunks = chunker.chunk(markdown, metadata={"doc_id": "handbook"})

for chunk in chunks:
    print(chunk.breadcrumb_text)  # 'Handbook » 3. Leave policy » 3.2 Parental leave'
    print(chunk.token_estimate)  # ~285
    print(chunk.content[:80])

# Straight into a vector store
records = chunks_to_records(chunks)
# [{'id': 'handbook::0', 'text': '...', 'metadata': {...}}, ...]
```

### Command line

```bash
# One file to stdout
mdforge convert report.pdf

# One file to disk, plus chunks
mdforge convert slides.pptx -o out/slides.md --chunk --chunk-size 1200

# A whole directory, 8 workers, chunks alongside each document
mdforge batch ./documents -o ./markdown --pattern "*.pdf" -w 8 --chunk

# Inspect a Markdown file's structure before you index it
mdforge chunk out/slides.md --preview

# Which formats can I use with what's installed?
mdforge formats
```

`mdforge formats` tells you exactly what is ready and what to install:

```
                       mdforge supported formats
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Converter ┃ Extensions                   ┃ Status        ┃ Install hint           ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ pdf       │ .pdf                         │ ready         │                        │
│ docx      │ .docx                        │ ready         │                        │
│ xlsx      │ .xlsx, .xlsm                 │ needs extras  │ pip install 'mdforge…  │
└───────────┴──────────────────────────────┴───────────────┴────────────────────────┘
```

Exit codes: `0` success, `1` a conversion failed, `2` bad usage or missing file —
so `mdforge batch` drops straight into a Makefile or CI job.

`mdforge batch` is safe to re-run. Files whose extension has no registered
converter are skipped (with a count printed), and the output directory is
excluded from the scan, so a second run never re-ingests the Markdown it
produced. When two inputs share a file name, outputs are disambiguated with the
parent folder (`reports__index.md`, `docs__index.md`).

Tuning chunk boundaries: `mdforge chunk --min-chars 120` folds sections shorter
than that into their predecessor — worth doing for real corpora full of one-line
subsections. The default (`0`) keeps the heading tree exactly as written.

## Supported formats

| Converter | Extensions | Extra | Notes |
| --- | --- | --- | --- |
| `pdf` | `.pdf` | `pdf` | pypdf, with optional pdfplumber fallback; dehyphenation + paragraph reflow; page selectors |
| `docx` | `.docx` | `docx` | Headings, nested lists, tables, bold/italic/code runs, hyperlinks |
| `pptx` | `.pptx` | `pptx` | Per-slide sections, bullet levels, tables, speaker notes |
| `xlsx` | `.xlsx`, `.xlsm` | `xlsx` | One section per worksheet, formulas evaluated |
| `csv` | `.csv`, `.tsv` | — | Dialect sniffing, row/column caps with warnings |
| `html` | `.html`, `.htm`, `.xhtml` | `html` | Content selectors, nested lists, tables, code fences, relative-link absolutisation |
| `json` | `.json`, `.jsonl`, `.ndjson` | — | Raw fence mode, or `flatten` mode with a key outline + record table |
| `xml` | `.xml`, `.svg`, `.rss`, `.atom`, … | — | Pretty-printed with root tag and element count |
| `text` | `.txt`, `.md`, `.rst`, `.log` | — | reST heading promotion, encoding detection |

## Writing your own converter

The plugin surface is three declarations and one method:

```python
"""mdforge_ini/__init__.py"""

from pathlib import Path
from typing import Any

from mdforge.core.base import BaseConverter, DocumentResult
from mdforge.utils.text import fenced_code_block


class IniConverter(BaseConverter):
    name = "ini"
    extensions = (".ini", ".cfg")
    description = "INI configuration files"

    def convert(self, path: Path, **options: Any) -> DocumentResult:
        text = path.read_text(encoding=options.get("encoding", "utf-8"))
        # Turn `[section]` headers into Markdown headings.
        lines = []
        for line in text.splitlines():
            if line.startswith("[") and line.endswith("]"):
                lines.append(f"## {line[1:-1]}")
            else:
                lines.append(line)
        body = fenced_code_block("\n".join(lines), language="ini")
        # Returned metadata is merged into the frontmatter automatically.
        return self.build_result(path, body, metadata={"format": "ini"})
```

Wire it in once:

```python
from mdforge import ConversionEngine, set_default_engine
from mdforge_ini import IniConverter

engine = ConversionEngine()
engine.register(IniConverter())
set_default_engine(engine)

engine.convert("app.cfg")  # works, and `mdforge formats` lists it
```

Publishing it? Use the `mdforge.converters` entry-point group and it registers
itself — see [`docs/plugins.md`](docs/plugins.md).

## Architecture

```
src/mdforge/
├── cli.py                 # Typer CLI: convert / batch / chunk / formats
├── exceptions.py          # single error hierarchy, actionable messages
├── core/
│   ├── base.py            # BaseConverter + DocumentResult
│   ├── engine.py          # registry, routing, batch execution
│   └── metadata.py        # frontmatter assembly + YAML rendering
├── converters/            # one module per format, lazily imported deps
│   ├── pdf.py  docx.py  pptx.py  xlsx.py  csv.py
│   └── html.py  json.py  xml.py  text.py
└── utils/
    ├── chunker.py         # MarkdownChunker, Chunk, chunks_to_records
    ├── text.py            # table rendering, fence widening, encoding-safe reads
    └── deps.py            # optional-dependency import shim
```

The data flow is deliberately linear and inspectable:

```
file ──▶ ConversionEngine.get_converter()      # extension → converter
     ──▶ BaseConverter.convert()               # Markdown body + metadata
     ──▶ BaseConverter.extract_metadata()      # cheap document properties
     ──▶ build_metadata()                      # merge + derive word/char counts
     ──▶ prepend_frontmatter()                 # YAML block
     ──▶ MarkdownChunker.chunk()               # optional, RAG-ready chunks
```

## Development

```bash
git clone https://github.com/AndrazKen/mdforge.git
cd mdforge
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[all,dev]"

pytest --cov=mdforge          # tests
ruff check . && ruff format . # lint + format
mypy src/mdforge              # strict type-check
pre-commit install            # optional: run the above on every commit
```

Or simply `make dev test lint typecheck`.

## Contributing

Contributions are very welcome — especially **new converters**.

1. Fork, branch from `main` (`git checkout -b feat/rtf-converter`).
2. Add `src/mdforge/converters/rtf.py` implementing `BaseConverter`.
3. Register it in `src/mdforge/converters/__init__.py::default_converters`.
4. Add a fixture and tests in `tests/`.
5. Run `make all` (lint + mypy + tests) and open a pull request.

Please keep optional imports lazy via `utils.deps.import_optional`, keep the
public API fully type-hinted, and include a docstring on every public callable.
See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full checklist and
[`docs/`](docs/) for deeper design notes.

## License

[MIT](LICENSE) © mdforge contributors.

<div align="center">
<sub>If mdforge saved you a week of glue code, a ⭐ helps other people find it.</sub>
</div>
