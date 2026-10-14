"""The conversion engine: registry, routing, frontmatter and batch execution."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import (
    Any,
    cast,
)

from ..exceptions import ConversionError, UnsupportedFormatError
from ..utils.text import normalise_markdown
from .base import BaseConverter, DocumentResult, PathLike
from .metadata import build_metadata, prepend_frontmatter

logger = logging.getLogger("mdforge")

__all__ = [
    "ENTRY_POINT_GROUP",
    "BatchError",
    "BatchResult",
    "ConversionEngine",
    "ProgressCallback",
    "load_entry_point_converters",
]

ProgressCallback = Callable[[str, int, int], None]

#: Entry-point group third-party packages publish their converters under.
ENTRY_POINT_GROUP = "mdforge.converters"


@dataclass
class BatchError:
    """A single failed conversion inside a batch run.

    Attributes:
        source_file: Path that failed.
        error: The exception instance that was raised.
        error_type: ``type(error).__name__`` for cheap filtering.
    """

    source_file: str
    error: BaseException
    error_type: str

    def to_dict(self) -> dict[str, str]:
        """Serialise to a JSON-friendly dictionary."""
        return {
            "source_file": self.source_file,
            "error_type": self.error_type,
            "error": str(self.error),
        }


@dataclass
class BatchResult:
    """Aggregated outcome of :meth:`ConversionEngine.convert_batch`.

    Results and errors preserve input order, which makes it trivial to zip the
    output back against the original file list.
    """

    results: list[DocumentResult] = field(default_factory=list)
    errors: list[BatchError] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def successes(self) -> list[DocumentResult]:
        """Successfully converted :class:`~mdforge.core.base.DocumentResult`\\ s."""
        return self.results

    @property
    def failures(self) -> int:
        """Number of files that raised during conversion."""
        return len(self.errors)

    @property
    def total(self) -> int:
        """Total number of files attempted."""
        return len(self.results) + len(self.errors)

    @property
    def files_per_second(self) -> float:
        """Throughput of the batch run, or ``0.0`` for a zero-duration run."""
        return self.total / self.elapsed_seconds if self.elapsed_seconds else 0.0

    def to_dict(self, *, include_markdown: bool = True) -> dict[str, Any]:
        """Serialise the whole batch to a JSON-friendly dictionary."""
        return {
            "total": self.total,
            "succeeded": len(self.results),
            "failed": len(self.errors),
            "elapsed_seconds": round(self.elapsed_seconds, 4),
            "files_per_second": round(self.files_per_second, 3),
            "results": [r.to_dict(include_markdown=include_markdown) for r in self.results],
            "errors": [e.to_dict() for e in self.errors],
        }

    def __iter__(self) -> Iterable[DocumentResult]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)


class ConversionEngine:
    """Registry + router + frontmatter factory + async batch runner.

    The engine is the single entry point most users need::

        from mdforge import ConversionEngine

        engine = ConversionEngine()
        result = engine.convert("report.pdf")
        print(result.markdown)

    It is intentionally free of global state, so multiple engines with
    different registries can coexist (handy in tests and in multi-tenant
    services).

    Args:
        converters: Initial converters to register.  Defaults to every
            built-in converter (plus any converters installed as entry
            points, unless ``load_plugins=False``).
        include_frontmatter: Prepend YAML metadata to every result.
        max_workers: Default concurrency for :meth:`convert_batch`.
        raise_on_error: When ``True`` batch runs re-raise the first error
            instead of collecting it into :attr:`BatchResult.errors`.
        load_plugins: When ``True`` and ``converters`` is not given, also
            register converters discovered via the ``mdforge.converters``
            entry-point group (see :func:`load_entry_point_converters`).
    """

    def __init__(
        self,
        converters: Sequence[BaseConverter] | None = None,
        *,
        include_frontmatter: bool = True,
        max_workers: int | None = None,
        raise_on_error: bool = False,
        load_plugins: bool = True,
    ) -> None:
        self.include_frontmatter = include_frontmatter
        self.max_workers = max_workers or _default_workers()
        self.raise_on_error = raise_on_error

        # extension (lower-case, with dot) -> converter
        self._registry: dict[str, BaseConverter] = {}
        if converters is None:
            from ..converters import default_converters

            converters = default_converters()
            if load_plugins:
                converters = [*converters, *load_entry_point_converters()]
        for converter in converters:
            self.register(converter)

    # -- Registry ----------------------------------------------------------

    def register(self, converter: BaseConverter, *, overwrite: bool = True) -> None:
        """Register ``converter`` for all of its extensions.

        Args:
            converter: The converter instance to add.
            overwrite: When ``False``, an existing binding for an extension is
                kept and a warning is logged instead of being replaced.

        Raises:
            ValueError: If the converter declares no extensions, or declares an
                extension that is already taken while ``overwrite`` is ``False``.
        """
        if not converter.extensions:
            raise ValueError(f"Converter {type(converter).__name__!r} declares no extensions.")
        for extension in converter.extensions:
            key = extension.lower()
            if not key.startswith("."):
                key = f".{key}"
            existing = self._registry.get(key)
            if existing is not None and not overwrite:
                logger.warning(
                    "Extension %s already handled by %s; keeping it and ignoring %s.",
                    key,
                    existing.name,
                    converter.name,
                )
                raise ValueError(f"Extension {key!r} is already registered to {existing.name!r}.")
            self._registry[key] = converter

    def unregister(self, extension: str) -> BaseConverter | None:
        """Remove the converter bound to ``extension`` and return it."""
        key = extension.lower()
        if not key.startswith("."):
            key = f".{key}"
        return self._registry.pop(key, None)

    @property
    def registry(self) -> Mapping[str, BaseConverter]:
        """Read-only view of the extension -> converter mapping."""
        return dict(self._registry)

    @property
    def supported_extensions(self) -> list[str]:
        """Sorted list of every extension the engine can route."""
        return sorted(self._registry)

    def get_converter(self, path: PathLike) -> BaseConverter:
        """Return the converter responsible for ``path``.

        Raises:
            UnsupportedFormatError: If no converter claims the extension.
        """
        extension = Path(path).suffix.lower()
        converter = self._registry.get(extension)
        if converter is None:
            raise UnsupportedFormatError(extension, self.supported_extensions)
        return converter

    # -- Single file -------------------------------------------------------

    def convert(
        self,
        path: PathLike,
        *,
        frontmatter: bool | None = None,
        metadata: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> DocumentResult:
        """Convert one file to Markdown.

        Args:
            path: File to convert.
            frontmatter: Override the engine default for this call.
            metadata: Extra key/values merged into the frontmatter with the
                highest precedence.
            **options: Forwarded verbatim to the converter (e.g.
                ``max_rows=100`` for spreadsheets).

        Returns:
            A :class:`~mdforge.core.base.DocumentResult` whose ``markdown``
            already contains the frontmatter when enabled.

        Raises:
            UnsupportedFormatError: No converter claims the extension.
            ConversionError: The converter failed to parse the file.
        """
        source = Path(path)
        converter = self.get_converter(source)
        if not source.exists():
            raise ConversionError(str(source), "file does not exist", converter=converter.name)

        try:
            extracted = converter.convert(source, **options)
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(
                str(source),
                f"{type(exc).__name__}: {exc}",
                converter=converter.name,
            ) from exc

        extracted.markdown = normalise_markdown(extracted.markdown)
        extracted.converter = extracted.converter or converter.name

        converter_metadata = dict(converter.extract_metadata(source))
        converter_metadata.update(extracted.metadata)
        full_metadata = build_metadata(
            markdown=extracted.markdown,
            source_file=str(source),
            file_type=extracted.file_type,
            converter=extracted.converter,
            converter_metadata=converter_metadata,
            extra=metadata,
        )
        extracted.metadata = full_metadata

        use_frontmatter = self.include_frontmatter if frontmatter is None else frontmatter
        if use_frontmatter:
            extracted.markdown = prepend_frontmatter(
                extracted.markdown, full_metadata, include=True
            )
        return extracted

    def convert_to_markdown(self, path: PathLike, **options: Any) -> str:
        """Convenience wrapper returning only the Markdown string."""
        return str(self.convert(path, **options).markdown)

    # -- Batch -------------------------------------------------------------

    async def convert_batch(
        self,
        file_paths: Sequence[PathLike],
        *,
        max_workers: int | None = None,
        frontmatter: bool | None = None,
        metadata: Mapping[str, Any] | None = None,
        on_progress: ProgressCallback | None = None,
        **options: Any,
    ) -> BatchResult:
        """Convert many files concurrently.

        Concurrency is provided by a bounded ``asyncio`` semaphore driving
        ``asyncio.to_thread``.  Conversion is dominated by parsing and disk
        I/O, which releases the GIL inside the C extensions of the underlying
        parsers, so threads give most of the win of processes without the
        pickling overhead or Windows spawn cost.

        Args:
            file_paths: Files to convert, in the order results should follow.
            max_workers: Concurrency cap; defaults to the engine's setting.
            frontmatter: Per-call frontmatter override.
            metadata: Extra metadata merged into every result's frontmatter.
            on_progress: Callable ``(path, done, total)`` invoked as each file
                finishes; handy for CLI progress bars.
            **options: Forwarded to each converter.

        Returns:
            A :class:`BatchResult`.  Errors are collected rather than raised
            unless ``raise_on_error=True`` was set on the engine.
        """
        paths = list(file_paths)
        total = len(paths)
        started = time.perf_counter()
        result = BatchResult()
        if total == 0:
            return result

        workers = max(1, min(max_workers or self.max_workers, total))
        semaphore = asyncio.Semaphore(workers)
        lock = asyncio.Lock()
        done = 0

        async def _run_one(index: int, path: PathLike) -> tuple[int, Any, BaseException | None]:
            async with semaphore:
                try:
                    outcome = await asyncio.to_thread(
                        self.convert, path, frontmatter=frontmatter, metadata=metadata, **options
                    )
                    return index, outcome, None
                except BaseException as exc:  # noqa: BLE001 - collected, not swallowed
                    return index, None, exc

        tasks = [asyncio.ensure_future(_run_one(i, p)) for i, p in enumerate(paths)]
        gathered: list[tuple[int, Any, BaseException | None]] = []
        try:
            for coro in asyncio.as_completed(tasks):
                outcome = await coro
                gathered.append(outcome)
                async with lock:
                    done += 1
                    if on_progress is not None:
                        try:
                            on_progress(str(paths[outcome[0]]), done, total)
                        except Exception:
                            logger.debug("progress callback raised", exc_info=True)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

        gathered.sort(key=lambda item: item[0])
        for index, outcome, error in gathered:
            if error is None:
                result.results.append(outcome)
            else:
                if self.raise_on_error:
                    raise error
                result.errors.append(
                    BatchError(
                        source_file=str(paths[index]),
                        error=error,
                        error_type=type(error).__name__,
                    )
                )

        result.elapsed_seconds = time.perf_counter() - started
        return result

    def convert_batch_sync(
        self,
        file_paths: Sequence[PathLike],
        *,
        max_workers: int | None = None,
        on_progress: ProgressCallback | None = None,
        **options: Any,
    ) -> BatchResult:
        """Synchronous wrapper around :meth:`convert_batch`.

        Safe to call from inside an already-running event loop: the coroutine
        is executed on a dedicated thread with its own loop, avoiding the
        classic ``RuntimeError: asyncio.run() cannot be called from a running
        event loop``.
        """
        coro = self.convert_batch(
            file_paths, max_workers=max_workers, on_progress=on_progress, **options
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        # We are inside a running loop; run the coroutine on a worker thread.
        import threading

        box: dict[str, Any] = {}

        def _runner() -> None:
            try:
                box["result"] = asyncio.run(coro)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the caller thread
                box["error"] = exc

        thread = threading.Thread(target=_runner, name="mdforge-batch", daemon=True)
        thread.start()
        thread.join()
        if "error" in box:
            raise box["error"]
        return cast("BatchResult", box["result"])


def _default_workers() -> int:
    """Pick a sensible default concurrency for I/O-bound conversion."""
    cpu = os.cpu_count() or 4
    return max(4, min(32, cpu * 4))


def load_entry_point_converters(group: str = ENTRY_POINT_GROUP) -> list[BaseConverter]:
    """Discover third-party converters published as entry points.

    A plugin package advertises its converter under the
    ``mdforge.converters`` group in ``pyproject.toml``::

        [project.entry-points."mdforge.converters"]
        ini = "mdforge_ini:IniConverter"

    The referenced object may be a :class:`~mdforge.core.base.BaseConverter`
    subclass (it is instantiated with no arguments) or an already-built
    instance.  Anything that fails to import or does not resolve to a
    converter is logged and skipped, so a single broken plugin can never stop
    ``import mdforge`` from working.

    Args:
        group: Entry-point group to read (overridable for testing).

    Returns:
        Instances of every loadable converter, in entry-point order.
    """
    discovered: list[BaseConverter] = []
    for entry_point in _iter_entry_points(group):
        try:
            target = entry_point.load()
            converter = target() if isinstance(target, type) else target
        except Exception:  # pragma: no cover - defensive, exercised via mocking
            logger.warning("Failed to load mdforge converter %r", entry_point.name, exc_info=True)
            continue
        if not isinstance(converter, BaseConverter):  # pragma: no cover - defensive
            logger.warning(
                "Entry point %r did not provide a BaseConverter (got %s); skipping.",
                entry_point.name,
                type(converter).__name__,
            )
            continue
        discovered.append(converter)
    return discovered


def _iter_entry_points(group: str) -> Iterable[Any]:
    """Return the entry points registered for ``group``.

    Wrapped so tests can monkeypatch a single seam and so the call site stays
    independent of the ``importlib.metadata`` signature across versions.
    """
    return entry_points(group=group)
