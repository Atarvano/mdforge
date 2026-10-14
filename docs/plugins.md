# Writing a converter plugin

mdforge ships nine converters, but the interesting formats are the ones **you**
care about. The plugin surface is deliberately small: subclass `BaseConverter`,
declare an extension, implement `convert()`. The engine handles routing,
frontmatter, metadata merging, batch execution and CLI listing for you.

There are two ways to plug a converter in:

| Approach | When to use it |
| --- | --- |
| [Register an instance](#registering-programmatically) | A private script, an application, or tests. No packaging required. |
| [Publish an entry point](#publishing-as-a-package) | A reusable, `pip install`-able package that other people can use. |

Both end up at the same place: `ConversionEngine.register()`. The difference is
*who* calls it.

---

## The converter contract

`BaseConverter` (in `mdforge.core.base`) is an abstract base class with a few
class attributes and one method you must implement.

```python
class BaseConverter(abc.ABC):
    name: ClassVar[str] = "base"  # lower-case id used in CLI + errors
    extensions: ClassVar[Sequence[str]] = ()  # e.g. (".ini", ".cfg")
    mime_types: ClassVar[Sequence[str]] = ()  # informational
    requires: ClassVar[Sequence[str]] = ()  # import names, for `mdforge formats`
    extra: ClassVar[str | None] = None  # extra that installs `requires`
    description: ClassVar[str] = ""  # one-liner shown by the CLI

    @abc.abstractmethod
    def convert(self, path: PathLike, **options: Any) -> DocumentResult: ...

    def extract_metadata(self, path: PathLike) -> dict[str, Any]:  # optional
        return {}
```

Rules of the road:

1. **`name`** must be stable and lower-case — it shows up in frontmatter
   (`converter: ini`), CLI tables and error messages.
2. **`extensions`** must include the leading dot and be lower-case. The engine
   normalises them anyway, but consistency keeps `supported_formats()` tidy.
3. **`convert()`** must return a `DocumentResult`. Build it with
   `self.build_result(path, markdown, metadata=..., warnings=...)` so the body
   is stripped and the file type is derived consistently.
4. Raise `ConversionError` (or let the engine wrap it) for parse failures —
   never leak a parser-specific exception to the caller.
5. Optional dependencies must be imported **inside** `convert()` via
   `mdforge.utils.deps.import_optional`, so `import mdforge` never fails for a
   format the user has not installed.

### What gets merged into the frontmatter

When you call `engine.convert(path)`, the engine assembles metadata from three
sources, in increasing precedence:

1. `build_metadata()` core fields — `title`, `source_file`, `file_type`,
   `converter`, `converted_at`, `word_count`, `char_count`.
2. Your converter's `extract_metadata()` result, **then** the `metadata=` you
   passed to `build_result()` (the latter wins).
3. Any `metadata={...}` you pass to `engine.convert(path, metadata=...)`.

So a converter can contribute cheap document properties (author, page count,
sheet names) that callers can filter on without re-reading the body.

---

## Registering programmatically

The smallest possible plugin — a converter for INI files that promotes
`[section]` headers to Markdown headings:

```python
"""mdforge_ini/__init__.py"""

from pathlib import Path
from typing import Any

from mdforge.core.base import BaseConverter, DocumentResult
from mdforge.utils.text import fenced_code_block


class IniConverter(BaseConverter):
    """Convert INI/CFG files into Markdown."""

    name = "ini"
    extensions = (".ini", ".cfg")
    description = "INI configuration files"

    def convert(self, path: Path, **options: Any) -> DocumentResult:
        text = Path(path).read_text(encoding=options.get("encoding", "utf-8"))
        lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("[") and line.endswith("]"):
                lines.append(f"## {line[1:-1]}")
            else:
                lines.append(line)
        body = fenced_code_block("\n".join(lines), language="ini")
        return self.build_result(path, body, metadata={"format": "ini"})
```

Wire it into an engine:

```python
from mdforge import ConversionEngine, set_default_engine
from mdforge_ini import IniConverter

engine = ConversionEngine()
engine.register(IniConverter())

# Option A: use this engine directly
result = engine.convert("app.cfg")
print(result.markdown)

# Option B: make it the process-wide default used by mdforge.convert()
set_default_engine(engine)
```

`mdforge formats` will now list the `ini` converter next to the built-ins, as
long as `set_default_engine()` has been called (the CLI builds its own engine,
so for the CLI you want the [entry-point route](#publishing-as-a-package)).

### Registering without a class

Any object with the right shape works — the tests use a tiny double. But a
`BaseConverter` subclass buys you `build_result()`, `supports()` and
`ensure_supported()` for free, so prefer it.

### `overwrite`

`register()` replaces an existing binding for an extension by default. Pass
`overwrite=False` to be strict — it logs a warning and raises `ValueError` when
an extension is already taken, which is useful when you want to *extend* a
format without silently clobbering a built-in:

```python
engine.register(MarkdownWithCallouts(), overwrite=False)  # raises if .md is taken
```

---

## Publishing as a package

`ConversionEngine()` calls
[`load_entry_point_converters()`](../src/mdforge/core/engine.py) on startup,
which reads the **`mdforge.converters`** entry-point group. A published package
therefore registers itself the moment it is installed — no `set_default_engine()`
boilerplate for your users, and the converter appears in the `mdforge formats`
table.

### 1. The package layout

```
mdforge-ini/
├── pyproject.toml
└── src/
    └── mdforge_ini/
        ├── __init__.py      # exports IniConverter
        └── converter.py     # the BaseConverter subclass
```

### 2. Declare the entry point

In `pyproject.toml` (PEP 621 metadata; works with hatchling, setuptools,
poetry, flit — whichever you use):

```toml
[project]
name = "mdforge-ini"
version = "0.1.0"
dependencies = ["mdforge>=0.1"]

[project.entry-points."mdforge.converters"]
# entry-point-name = "module:Attribute"
ini = "mdforge_ini:IniConverter"
```

The entry-point name (`ini`) is cosmetic; what matters is the target. The target
may be either:

* a `BaseConverter` **subclass** — mdforge instantiates it with no arguments, or
* an already-constructed **instance** — handy when your converter needs
  configuration.

### 3. Publish

```bash
python -m build
twine upload dist/*
```

### 4. Consume

```bash
pip install mdforge-ini
mdforge formats          # the `ini` row now appears, marked ready
mdforge convert app.cfg
```

```python
from mdforge import convert

convert("app.cfg").markdown
```

No changes to mdforge, no plugin registry to remember.

### Failure handling

Discovery is intentionally forgiving. If your plugin raises during import, or
resolves to something that is not a `BaseConverter`, mdforge logs a warning and
carries on with the remaining plugins — a broken third-party package can never
prevent `import mdforge`. Opt out entirely with:

```python
ConversionEngine(load_plugins=False)
```

---

## Declaring optional dependencies

Most real converters wrap a third-party parser. Declare the dependency as an
optional extra and import it lazily:

```python
from mdforge.utils.deps import import_optional


class RtfConverter(BaseConverter):
    name = "rtf"
    extensions = (".rtf",)
    requires = ("striprtf",)  # import names, shown by `mdforge formats`
    extra = "rtf"  # -> `pip install mdforge[rtf]`
    description = "Rich Text Format"

    def convert(self, path: Path, **options: Any) -> DocumentResult:
        rtf = import_optional(
            "striprtf",
            extra=self.extra or "all",
            feature="to convert RTF files",
            package="striprtf",
        )
        ...
```

When the package is missing, `import_optional` raises
`MissingDependencyError` whose message tells the user exactly which
`pip install` to run. `mdforge formats` derives its *"needs extras"* column
from `requires` by calling `has_dependency()` on each import name.

If you ship your plugin as a **separate** distribution, you cannot extend
mdforge's own extras. `requires` should still list the **import** names (that is
what the CLI probes to decide whether the format is *ready*), and your README
should tell users which `pip install` pulls those packages in.

---

## Checklist before you publish

- [ ] `name`, `extensions`, `description` set; extensions lower-case with dots.
- [ ] `convert()` returns `self.build_result(...)` and raises `ConversionError`
      (not parser exceptions) on failure.
- [ ] Optional imports go through `import_optional` with a helpful `feature`.
- [ ] Metadata is JSON-serialisable (no dataclasses, dates, or file handles).
- [ ] `extract_metadata()` is cheap — it must not duplicate the work of
      `convert()`.
- [ ] A round-trip test exists (`tests/` has room for a fixture per format).
- [ ] If published: entry point declared and the package installs cleanly in a
      fresh venv.

## Working examples in this repo

* `src/mdforge/converters/text.py` — no dependencies, encoding detection.
* `src/mdforge/converters/csv.py` — dialect sniffing, row caps, warnings.
* `src/mdforge/converters/docx.py` — nested lists and tables.
* `src/mdforge/converters/pdf.py` — one parser with a fallback, plus options.
</content>
