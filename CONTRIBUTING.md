# Contributing to mdforge

Thanks for taking the time to help. This document covers everything you need to
go from a fresh clone to a merged pull request. If something here is wrong or
missing, that is itself a bug — please open an issue or fix it in the same PR.

By participating you agree to keep the discussion respectful and constructive.
Be kind, assume good faith, and critique the code rather than the coder.

## Ways to contribute

* **New converters** — the most valuable contribution. RTF, EPUB, ODT, EML,
  LaTeX, notebooks, Parquet, images with OCR… see [`docs/plugins.md`](docs/plugins.md).
* **Better structure extraction** — headings, tables, lists and footnotes
  recovered more faithfully from an existing format.
* **Chunking quality** — new strategies, better boundaries, tokenizer adapters.
* **Bug reports** with a minimal reproduction (the file, the command, the
  output you expected).
* **Docs** — typos, unclear passages, missing examples.

If you are planning something large, open an issue first so we can agree on the
approach before you write a lot of code.

## Development setup

```bash
git clone https://github.com/AndrazKen/mdforge.git
cd mdforge

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[all,dev]"        # editable install + every extra + tooling
pre-commit install                 # optional but recommended
```

Verify the setup:

```bash
pytest -q
ruff check .
mypy src/mdforge
```

All three must pass. The [`Makefile`](Makefile) wraps the common commands:

| Command | Does |
| --- | --- |
| `make dev` | `pip install -e ".[all,dev]"` |
| `make test` | `pytest --cov=mdforge --cov-report=term-missing` |
| `make lint` | `ruff check .` |
| `make format` | `ruff check --fix . && ruff format .` |
| `make typecheck` | `mypy src/mdforge` |
| `make build` | `python -m build` |
| `make clean` | Remove caches and build artefacts |
| `make all` | `lint` + `typecheck` + `test` |

## House rules

These are enforced in CI, and review will ask for them:

1. **Type everything.** The package ships `py.typed` and is checked under
   `mypy --strict`. Public functions need full annotations; no bare `Any` in
   signatures unless a third-party boundary forces it.
2. **Document every public callable.** Google-style docstrings with `Args:`,
   `Returns:` and `Raises:` sections where they apply.
3. **`from __future__ import annotations`** at the top of every module, and
   modern syntax throughout (PEP 585 `list[str]`, PEP 604 `str | None`).
4. **Lazy optional imports.** A converter must import its third-party parser
   *inside* `convert()` via `mdforge.utils.deps.import_optional`, never at module
   scope. `import mdforge` must never fail because an extra is missing.
5. **One error hierarchy.** Raise `MdForgeError` subclasses
   (`ConversionError`, `UnsupportedFormatError`, `MissingDependencyError`) — do
   not leak parser-specific exceptions.
6. **Line length 100**, ruff-clean under the configured rule set (see
   `[tool.ruff]` in [`pyproject.toml`](pyproject.toml)).
7. **Tests come with the change.** New behaviour needs a test; new formats need
   a fixture in `tests/conftest.py`.

## Adding a converter

The short version (full guide: [`docs/plugins.md`](docs/plugins.md)):

1. Create `src/mdforge/converters/<format>.py` with a `BaseConverter` subclass.
   Declare `name`, `extensions`, and `description`; set `requires` / `extra`
   if it needs an optional dependency.
2. Implement `convert()` and return `self.build_result(path, body, metadata=...)`.
3. Register it in `default_converters()` in
   `src/mdforge/converters/__init__.py`.
4. Add a fixture to `tests/conftest.py` (generate the sample in-memory where
   possible — see `tmp_docx`) and assertions to `tests/test_converters.py`.
5. Add a row to the **Supported formats** table in the README, and an extra to
   `[project.optional-dependencies]` in `pyproject.toml` if applicable.
6. Run `make all`.

Guidelines for converters specifically:

* Assert on **structure** in tests (headings, nesting, tables), not on exact
  whitespace, so formatting tweaks do not churn the suite.
* Surface lossy conversions as `warnings=[...]` on the result rather than
  failing — e.g. "truncated after 1000 rows".
* Keep `extract_metadata()` cheap and never duplicate the work of `convert()`.

## Commit and PR conventions

* Branch from `main`: `git checkout -b feat/rtf-converter`.
* Write [Conventional Commit](https://www.conventionalcommits.org/) subjects:
  `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`. Add `!` for breaking
  changes (`feat!: drop Python 3.9`).
* Keep pull requests focused. One feature or fix per PR is much easier to review
  than five.
* Update [`CHANGELOG.md`](CHANGELOG.md) under the `Unreleased` heading for any
  user-visible change.
* Make sure `make all` is green locally before pushing. CI runs the same checks
  on Linux, macOS and Windows across Python 3.10–3.13.

In the PR description, include:

* **What** changed and **why**.
* **How** you verified it (the command you ran, the output you saw).
* Anything you are unsure about, so reviewers can focus there.

## Reporting bugs

A good report includes:

```
mdforge version:   (mdforge --version)
Python version:    (python --version)
OS:
Input format & how it was produced:
Command or code that reproduces it:
Expected output:
Actual output (or traceback):
```

If you can attach or describe a minimal sample document, that is the single
most helpful thing you can do.

## Security

Please do not open a public issue for a security problem. Instead, use GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on the repository. We will acknowledge receipt within a few days.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE), the same terms as the project.
</content>
