# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Entry-point plugin discovery: third-party packages can register converters
  under the `mdforge.converters` group and they are loaded automatically by
  `ConversionEngine()`. New public helper `load_entry_point_converters()`, and a
  `load_plugins` flag to opt out. See [`docs/plugins.md`](docs/plugins.md).
- Design notes in [`docs/`](docs/): `architecture.md`, `chunking.md`,
  `plugins.md`.

### Changed

- Requires Python 3.10+ (was 3.9). Python 3.9 is end-of-life and the modern
  type-checking and linting toolchain no longer supports it.

## [0.1.0] - Unreleased

Initial release.

### Added

- **Converters** for PDF, DOCX, PPTX, XLSX/`xlsm`, CSV/TSV, HTML/XHTML, JSON /
  JSONL / NDJSON, XML / SVG / RSS / Atom, and plain text (including reST heading
  promotion and encoding detection).
- **YAML frontmatter** generated for every document with `title`,
  `source_file`, `file_type`, `converter`, `converted_at`, `word_count` and
  `char_count`, merged with converter-extracted document properties.
- **Structure-aware chunking** (`MarkdownChunker`): splits on the heading tree,
  packs oversized sections with configurable overlap, and stamps each chunk with
  a breadcrumb. `chunks_to_records()` emits vector-database-ready payloads.
- **Concurrent batch conversion** via `ConversionEngine.convert_batch()` (async)
  and `convert_batch_sync()`, with bounded concurrency and per-file error
  isolation. Results preserve input order.
- **Extensible converter contract** (`BaseConverter` + `DocumentResult`) with a
  programmatic registry and an entry-point plugin system.
- **Typer + Rich CLI** with `convert`, `batch`, `chunk` and `formats` commands,
  progress reporting, JSON output, and meaningful exit codes.
- **Optional, lazily imported dependencies** grouped into extras (`pdf`,
  `docx`, `pptx`, `xlsx`, `html`, `text`, `all`); a missing extra raises an
  actionable `MissingDependencyError` instead of an `ImportError`.
- Full type hints with a `py.typed` marker, checked under `mypy --strict`.

[Unreleased]: https://github.com/AndrazKen/mdforge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AndrazKen/mdforge/releases/tag/v0.1.0
</content>
