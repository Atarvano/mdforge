"""Command line interface for mdforge.

mdforge convert report.pdf -o report.md
mdforge convert slides.pptx --chunk --chunk-size 1200
mdforge batch ./documents --output-dir ./markdown --workers 8
mdforge formats
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from . import __version__
from .core.engine import BatchResult, ConversionEngine
from .exceptions import MdForgeError
from .utils.chunker import Chunk, MarkdownChunker
from .utils.deps import has_dependency

app = typer.Typer(
    name="mdforge",
    help="Convert documents into LLM-ready Markdown with YAML metadata and RAG chunking.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"mdforge [bold cyan]{__version__}[/]")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """mdforge: documents in, retrieval-ready Markdown out."""


@app.command()
def convert(
    files: list[Path] = typer.Argument(..., help="One or more files to convert."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output file (single input) or directory (many inputs)."
    ),
    frontmatter: bool = typer.Option(
        True, "--frontmatter/--no-frontmatter", help="Prepend a YAML metadata block."
    ),
    chunk: bool = typer.Option(False, "--chunk", help="Also emit RAG chunks as JSONL."),
    chunk_size: int = typer.Option(1800, "--chunk-size", help="Max characters per chunk."),
    overlap: int = typer.Option(200, "--overlap", help="Overlap characters between chunks."),
    workers: int | None = typer.Option(
        None, "--workers", "-w", help="Concurrency for multiple inputs."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print results as JSON instead of Markdown."
    ),
    meta: list[str] = typer.Option(
        None, "--meta", help="Extra frontmatter as key=value (repeatable)."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress output."),
) -> None:
    """Convert files to Markdown."""
    _ensure_existing(files)
    extra_metadata = _parse_meta(meta)
    engine = ConversionEngine(include_frontmatter=frontmatter)

    if len(files) == 1:
        _convert_single(
            engine,
            files[0],
            output=output,
            chunk=chunk,
            chunk_size=chunk_size,
            overlap=overlap,
            as_json=as_json,
            metadata=extra_metadata,
            quiet=quiet,
        )
        return

    result = _run_batch(engine, files, workers=workers, metadata=extra_metadata, quiet=quiet)
    directory = _ensure_output_dir(output)
    _write_batch(
        result,
        directory,
        chunk=chunk,
        chunk_size=chunk_size,
        overlap=overlap,
        sources=files,
        quiet=quiet,
    )
    _report(result, quiet=quiet)
    _exit_if_failed(result)


@app.command()
def batch(
    directory: Path = typer.Argument(..., help="Directory containing files to convert."),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Where to write the Markdown files."
    ),
    pattern: str = typer.Option(
        "*", "--pattern", "-p", help="Glob applied to file names, e.g. '*.pdf'."
    ),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", "-r"),
    chunk: bool = typer.Option(False, "--chunk", help="Also emit RAG chunks as JSONL."),
    chunk_size: int = typer.Option(1800, "--chunk-size"),
    overlap: int = typer.Option(200, "--overlap"),
    workers: int | None = typer.Option(None, "--workers", "-w"),
    frontmatter: bool = typer.Option(True, "--frontmatter/--no-frontmatter"),
    meta: list[str] = typer.Option(None, "--meta", help="Extra frontmatter key=value pairs."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Convert every matching file in a directory.

    Files whose extension has no registered converter are skipped, and the
    output directory is excluded from the scan so repeated runs stay stable.
    """
    if not directory.is_dir():
        error_console.print(f"[red]Not a directory:[/] {directory}")
        raise typer.Exit(code=2)

    engine = ConversionEngine(include_frontmatter=frontmatter)
    target = output_dir or directory / "markdown"
    files, skipped = _discover(
        directory, pattern=pattern, recursive=recursive, engine=engine, exclude=target
    )
    if skipped and not quiet:
        console.print(f"[dim]Skipped {skipped} file(s) with unsupported extensions.[/]")
    if not files:
        error_console.print(f"[yellow]No supported files matched[/] {pattern!r} in {directory}")
        error_console.print(f"[dim]Supported: {', '.join(engine.supported_extensions)}[/]")
        raise typer.Exit(code=1)

    result = _run_batch(engine, files, workers=workers, metadata=_parse_meta(meta), quiet=quiet)
    target.mkdir(parents=True, exist_ok=True)
    _write_batch(
        result,
        target,
        chunk=chunk,
        chunk_size=chunk_size,
        overlap=overlap,
        sources=files,
        quiet=quiet,
    )
    _report(result, quiet=quiet)
    _exit_if_failed(result)


@app.command()
def chunk(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Markdown file to split."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write JSONL here."),
    chunk_size: int = typer.Option(1800, "--chunk-size"),
    overlap: int = typer.Option(200, "--overlap"),
    min_chars: int = typer.Option(
        0, "--min-chars", help="Merge sections shorter than this (0 = keep all)."
    ),
    as_json: bool = typer.Option(
        True, "--json/--preview", help="JSONL output or a readable preview."
    ),
) -> None:
    """Split Markdown into structure-aware, RAG-ready chunks."""
    splitter = MarkdownChunker(max_chars=chunk_size, overlap_chars=overlap, min_chars=min_chars)
    try:
        chunks = splitter.chunk(
            file.read_text(encoding="utf-8"), metadata={"source_file": str(file)}
        )
    except OSError as exc:
        error_console.print(f"[red]Cannot read[/] {file}: {exc}")
        raise typer.Exit(code=1) from exc

    if not chunks:
        error_console.print("[yellow]No content to chunk.[/]")
        raise typer.Exit(code=1)

    if as_json:
        lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in chunks]
        payload = "\n".join(lines) + "\n"
        if output:
            output.write_text(payload, encoding="utf-8")
            console.print(f"[green]Wrote[/] {len(chunks)} chunks -> {output}")
        else:
            console.print_json(json.dumps([c.to_dict() for c in chunks], ensure_ascii=False))
    else:
        _preview_chunks(chunks, file)

    if not output:
        console.print(
            f"[dim]{len(chunks)} chunks · ~{sum(c.token_estimate for c in chunks)} tokens total[/]"
        )


@app.command()
def formats(as_json: bool = typer.Option(False, "--json")) -> None:
    """List supported formats and whether their dependencies are installed."""
    engine = ConversionEngine()
    seen: dict[str, Any] = {}
    for extension, converter in engine.registry.items():
        seen.setdefault(converter.name, {"converter": converter, "extensions": []})
        seen[converter.name]["extensions"].append(extension)

    rows: list[dict[str, Any]] = []
    for name in sorted(seen):
        converter = seen[name]["converter"]
        extensions = sorted(seen[name]["extensions"])
        dependencies = list(getattr(converter, "requires", ()) or ())
        missing = [dep for dep in dependencies if not has_dependency(dep)]
        rows.append(
            {
                "name": name,
                "extensions": extensions,
                "dependencies": dependencies,
                "missing": missing,
                "extra": getattr(converter, "extra", None),
                "ready": not missing,
                "description": getattr(converter, "description", ""),
            }
        )

    if as_json:
        console.print_json(json.dumps(rows, ensure_ascii=False))
        return

    table = Table(title="mdforge supported formats", show_lines=False)
    table.add_column("Converter", style="cyan", no_wrap=True)
    table.add_column("Extensions", style="white")
    table.add_column("Status")
    table.add_column("Install hint", style="dim")
    for row in rows:
        status = "[green]ready[/]" if row["ready"] else "[yellow]needs extras[/]"
        hint = ""
        if not row["ready"]:
            extra = row["extra"] or "all"
            hint = f"pip install 'mdforge[{extra}]'"
        table.add_row(row["name"], ", ".join(row["extensions"]), status, hint)
    console.print(table)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_existing(files: Sequence[Path]) -> None:
    """Validate that every input path exists, exiting with code 2 otherwise."""
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        for path in missing:
            error_console.print(f"[red]File not found:[/] {path}")
        raise typer.Exit(code=2)


def _ensure_output_dir(output: Path | None) -> Path:
    """Return ``output`` as a directory, creating it when necessary."""
    target = output or Path("markdown")
    if target.exists() and target.is_file():
        error_console.print(
            f"[red]--output must be a directory when converting several files[/] ({target})"
        )
        raise typer.Exit(code=2)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _parse_meta(pairs: Sequence[str] | None) -> dict[str, Any]:
    """Turn repeated ``--meta key=value`` flags into a dictionary."""
    metadata: dict[str, Any] = {}
    for pair in pairs or ():
        key, separator, value = pair.partition("=")
        if not separator or not key.strip():
            error_console.print(f"[red]Invalid --meta value:[/] {pair!r} (expected key=value)")
            raise typer.Exit(code=2)
        metadata[key.strip()] = value.strip()
    return metadata


def _convert_single(
    engine: ConversionEngine,
    path: Path,
    *,
    output: Path | None,
    chunk: bool,
    chunk_size: int,
    overlap: int,
    as_json: bool,
    metadata: dict[str, Any],
    quiet: bool,
) -> None:
    """Convert exactly one file, writing Markdown/chunks to disk or stdout."""
    try:
        result = engine.convert(path, metadata=metadata)
    except MdForgeError as exc:
        error_console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        destination = _file_destination(output, path)
        if destination is None:
            console.print(result.markdown, markup=False, highlight=False, end="")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(result.markdown, encoding="utf-8")
            if not quiet:
                console.print(f"[green]Wrote[/] {destination}")

    if chunk:
        splitter = MarkdownChunker(max_chars=chunk_size, overlap_chars=overlap)
        chunks = splitter.chunk(result.markdown, metadata={"source_file": str(path)})
        chunk_target = _file_destination(output, path, suffix=".chunks.jsonl") or Path(
            f"{path.stem}.chunks.jsonl"
        )
        payload = "\n".join(json.dumps(c.to_dict(), ensure_ascii=False) for c in chunks) + "\n"
        chunk_target.write_text(payload, encoding="utf-8")
        if not quiet:
            console.print(f"[green]Wrote[/] {len(chunks)} chunks -> {chunk_target}")

    for warning in result.warnings:
        if not quiet:
            error_console.print(f"[yellow]warning:[/] {warning}")


def _file_destination(output: Path | None, source: Path, *, suffix: str = ".md") -> Path | None:
    """Resolve where a single input should be written.

    ``None`` means "print to stdout" (no ``--output`` given).  A ``--output``
    that is an existing directory receives ``<stem><suffix>``; anything else is
    treated as an explicit file path.
    """
    if output is None:
        return None
    if output.is_dir():
        return output / f"{source.stem}{suffix}"
    if output.suffix:
        if suffix == ".md":
            return output
        return output.with_suffix(suffix)
    return output.with_suffix(suffix)


def _discover(
    directory: Path,
    *,
    pattern: str,
    recursive: bool,
    engine: ConversionEngine,
    exclude: Path | None = None,
) -> tuple[list[Path], int]:
    """Find convertible files below ``directory``.

    Files whose extension has no registered converter are skipped, and the
    output directory is excluded so a second ``mdforge batch`` run cannot pick
    up the Markdown it generated the first time.

    Args:
        directory: Root to scan.
        pattern: Glob applied to file names, e.g. ``"*.pdf"``.
        recursive: Recurse into sub-directories.
        engine: Engine supplying the set of supported extensions.
        exclude: Optional directory to ignore (typically ``--output-dir``).

    Returns:
        ``(files, skipped_count)`` sorted by path.
    """
    iterator = directory.rglob(pattern) if recursive else directory.glob(pattern)
    supported = set(engine.supported_extensions)
    excluded = exclude.resolve() if exclude is not None else None
    found: list[Path] = []
    skipped = 0

    for path in iterator:
        if not path.is_file():
            continue
        resolved = path.resolve()
        if excluded is not None and resolved.is_relative_to(excluded):
            continue
        if resolved.suffix.lower() not in supported:
            skipped += 1
            continue
        found.append(path)
    return sorted(found), skipped


def _run_batch(
    engine: ConversionEngine,
    files: Sequence[Path],
    *,
    workers: int | None,
    metadata: dict[str, Any],
    quiet: bool,
) -> BatchResult:
    """Execute a batch conversion with an optional rich progress bar."""
    if quiet:
        return engine.convert_batch_sync(
            files, max_workers=workers, metadata=metadata, raise_on_error=False
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Converting", total=len(files))

        def _on_progress(path: str, done: int, _total: int) -> None:
            progress.update(task, completed=done, description=f"Converting {Path(path).name}")

        return engine.convert_batch_sync(
            files, max_workers=workers, metadata=metadata, on_progress=_on_progress
        )


def _write_batch(
    result: BatchResult,
    directory: Path,
    *,
    chunk: bool,
    chunk_size: int,
    overlap: int,
    sources: Sequence[Path],
    quiet: bool,
) -> None:
    """Write every converted document (and optional chunks) into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    splitter = MarkdownChunker(max_chars=chunk_size, overlap_chars=overlap) if chunk else None

    for document in result.results:
        source = Path(document.source_file)
        target = directory / f"{_unique_stem(source, sources)}{'.md'}"
        target.write_text(document.markdown, encoding="utf-8")
        if splitter is None:
            continue
        chunks = splitter.chunk(document.markdown, metadata={"source_file": document.source_file})
        payload = "\n".join(json.dumps(c.to_dict(), ensure_ascii=False) for c in chunks) + "\n"
        target.with_suffix(".chunks.jsonl").write_text(payload, encoding="utf-8")

    if not quiet:
        console.print(f"[green]Wrote[/] {len(result.results)} file(s) -> {directory}")


def _unique_stem(source: Path, sources: Sequence[Path]) -> str:
    """Return a collision-free output stem for ``source``."""
    stems = [s.stem for s in sources]
    if stems.count(source.stem) > 1:
        parent = source.parent.name or "root"
        return f"{parent}__{source.stem}"
    return source.stem


def _report(result: BatchResult, *, quiet: bool) -> None:
    """Print the batch summary."""
    if quiet:
        return
    for error in result.errors:
        error_console.print(f"[red]failed[/] {error.source_file}: {error.error}")
    console.print(
        f"[bold]{len(result.results)}[/] converted · "
        f"[bold]{result.failures}[/] failed · "
        f"{result.elapsed_seconds:.2f}s "
        f"({result.files_per_second:.1f} files/s)"
    )


def _exit_if_failed(result: BatchResult) -> None:
    """Exit with code 1 when at least one file failed."""
    if result.failures:
        raise typer.Exit(code=1)


def _preview_chunks(chunks: Sequence[Chunk], source: Path) -> None:
    """Print a human-readable preview of the produced chunks."""
    table = Table(title=f"Chunks of {source.name}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Breadcrumb", style="cyan", overflow="fold")
    table.add_column("Chars", justify="right")
    table.add_column("~Tokens", justify="right")
    for item in chunks[:50]:
        table.add_row(
            str(item.index),
            item.breadcrumb_text or "(preamble)",
            str(item.char_count),
            str(item.token_estimate),
        )
    console.print(table)


def main() -> None:
    """Console-script entry point."""
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        error_console.print("\n[yellow]Aborted.[/]")
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover - module execution
    main()
