# Architecture

mdforge is small on purpose. Every file does one job, and the data flow is
linear enough to hold in your head. This document explains the *why* behind the
pieces so you can extend or debug them confidently.

```
src/mdforge/
├── cli.py                 # Typer CLI: convert / batch / chunk / formats
├── exceptions.py          # one error hierarchy, actionable messages
├── core/
│   ├── base.py            # BaseConverter + DocumentResult (the contract)
│   ├── engine.py          # registry, routing, frontmatter, batch execution
│   └── metadata.py        # frontmatter assembly + YAML rendering
├── converters/            # one module per format, lazily imported deps
│   ├── pdf.py  docx.py  pptx.py  xlsx.py  csv.py
│   └── html.py  json.py  xml.py  text.py
└── utils/
    ├── chunker.py         # MarkdownChunker, Chunk, chunks_to_records
    ├── text.py            # table rendering, fence widening, encoding-safe reads
    └── deps.py            # optional-dependency import shim
```

## The conversion pipeline

```
file
 │
 ├─▶ ConversionEngine.get_converter()      # extension -> converter (or raise)
 │
 ├─▶ BaseConverter.convert()               # parse -> Markdown body + metadata
 │
 ├─▶ BaseConverter.extract_metadata()      # cheap document properties (optional)
 │
 ├─▶ build_metadata()                      # merge + derive word/char counts
 │
 ├─▶ prepend_frontmatter()                 # YAML block (when enabled)
 │
 └─▶ MarkdownChunker.chunk()               # optional, RAG-ready chunks
```

The engine is the only place that *composes* these steps. Converters never
prepend frontmatter themselves — they return a body plus a metadata mapping, and
the engine decides whether to render the YAML block. That split is what lets you
call `convert(path, frontmatter=False)`, merge extra metadata from the CLI, and
run a batch with a single frontmatter policy, all without touching converters.

## Design decisions

### One engine instance, no global state

`ConversionEngine` holds the registry as an ordinary instance attribute. The
package-level `convert()` / `convert_batch()` / `supported_formats()` helpers use
a lazily created **default** engine (`get_default_engine`), which you can swap
with `set_default_engine`. This means:

* Libraries can build their own engines without fighting a global.
* Tests get a fresh registry per fixture.
* Multi-tenant services can keep isolated converter sets.

### Optional dependencies are truly optional

The core install is `typer`, `rich` and `PyYAML`. Nothing else is imported at
module load. A converter that needs `pypdf` imports it **inside** `convert()`
through `utils.deps.import_optional`, which converts a bare `ImportError` into a
`MissingDependencyError` that names the exact `pip install` to run.

Consequence: `import mdforge` and `mdforge formats` work even with zero format
libraries installed, and the CLI can tell users precisely what is missing.

### Extension routing, not content sniffing

Routing is by file extension: a lower-case `dict[str, BaseConverter]`. It is
predictable, fast and debuggable. `register(..., overwrite=False)` refuses to
shadow an existing binding, which protects built-ins from accidental takeover.

### Errors are a single hierarchy

```
MdForgeError
├── UnsupportedFormatError   # no converter claims the extension
├── MissingDependencyError   # an extra is not installed
└── ConversionError          # the converter failed to parse the file
```

`ConversionWarning` (a `UserWarning`) is separate — it marks a *successful* but
lossy conversion (e.g. truncated spreadsheet rows) and is surfaced through
`DocumentResult.warnings`.

The engine wraps any unexpected parser exception in `ConversionError`, so
callers catch one type instead of learning every parser's exception classes.
In batch mode errors are collected into `BatchResult.errors` (unless
`raise_on_error=True`) so one broken file cannot sink the run.

### Concurrency: threads, not processes

`convert_batch()` is `async`. It bounds concurrency with an
`asyncio.Semaphore` and farms the blocking `convert()` calls onto a thread pool
via `asyncio.to_thread`.

Why threads rather than `multiprocessing`? Document conversion is dominated by
I/O and by C extensions (`pypdf`, `lxml`, `openpyxl`) that release the GIL. You
get most of the parallelism of processes without pickling results back across a
boundary or paying Windows' spawn cost. It also keeps the API trivially
awaitable from an existing event loop.

`convert_batch_sync()` is the escape hatch for synchronous callers. It is safe
to call from inside a running event loop: rather than crashing with
`asyncio.run() cannot be called from a running event loop`, it runs the
coroutine on a short-lived worker thread with its own loop.

Results and errors preserve **input order**, so you can zip them back against the
original file list.

### Frontmatter is data first, YAML second

`core/metadata.py` keeps the metadata a `dict` and only renders YAML at the
last moment (`render_frontmatter`). `DocumentResult.metadata` therefore stays
inspectable and JSON-serialisable. `split_frontmatter()` is the inverse and is
used by the chunker to recover the document title for breadcrumbs.

Core keys are emitted in a stable order (`CORE_KEY_ORDER`) so diffs between two
conversions stay readable.

## Testing strategy

* `tests/conftest.py` builds fixtures per format (including a `.docx` generated
  on the fly) plus a tiny `UpperCaseConverter` double.
* Converter tests assert on structure (headings, list nesting, tables) rather
  than exact whitespace, so formatting tweaks do not churn the suite.
* Engine tests cover routing, frontmatter merging, batch ordering, error
  isolation, progress callbacks and entry-point discovery.
* Optional-format tests use `pytest.importorskip`, so the suite still runs on a
  core-only install.

See [`plugins.md`](plugins.md) for the extension guide and
[`chunking.md`](chunking.md) for how chunk boundaries are chosen.
</content>
