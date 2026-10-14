"""PDF converter (pypdf by default, with an optional pdfplumber engine)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..exceptions import ConversionError
from ..utils.deps import has_dependency, import_optional

__all__ = ["PdfConverter"]

_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_SENTENCE_END_RE = re.compile(r"[.!?:;)\]}>»\"']\s*$")


class PdfConverter(BaseConverter):
    """Extract text from PDF files and reshape it into readable Markdown.

    PDF has no notion of paragraphs, so raw extraction yields a hard line
    break at every visual line.  Two clean-up passes fix the worst of it:

    * **dehyphenation** - ``informa-\\ntion`` becomes ``information``;
    * **reflow** - consecutive lines are re-joined into paragraphs unless the
      previous line ends a sentence, the next line looks like a bullet or
      heading, or either line is short (heuristic for titles and table rows).

    Supported options:

    ``pdf_engine``
        ``"auto"`` (default), ``"pypdf"`` or ``"pdfplumber"``.  ``"auto"``
        uses pypdf and only falls back to pdfplumber when pypdf extracts
        nothing.
    ``pages``
        ``"1-5,8"`` style selector or an iterable of 1-based page numbers.
    ``page_markers``
        Emit ``<!-- page: N -->`` HTML comments (default ``True``); ignored by
        the chunker but preserved as line references.
    ``password``
        Password for encrypted PDFs.
    ``reflow`` / ``dehyphenate``
        Toggle the clean-up passes (both default ``True``).
    """

    name = "pdf"
    extensions = (".pdf",)
    mime_types = ("application/pdf",)
    requires = ("pypdf",)
    extra = "pdf"
    description = "Portable Document Format"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Extract text from ``path`` into Markdown.

        Args:
            path: ``.pdf`` file to convert.
            **options: See the class docstring.

        Returns:
            A :class:`DocumentResult` with per-page text.

        Raises:
            MissingDependencyError: If no PDF engine is installed.
            ConversionError: If the PDF cannot be read.
        """
        engine = str(options.get("pdf_engine", "auto")).lower()
        pages, page_count, metadata, used_engine = self._extract(path, engine, options)

        marker_enabled = bool(options.get("page_markers", True))
        reflow = bool(options.get("reflow", True))
        dehyphenate = bool(options.get("dehyphenate", True))

        blocks: list[str] = []
        empty_pages = 0
        for number, raw in pages:
            text = _clean_page(raw, reflow=reflow, dehyphenate=dehyphenate)
            if not text:
                empty_pages += 1
                if marker_enabled:
                    blocks.append(f"<!-- page: {number} (no extractable text) -->")
                continue
            if marker_enabled:
                blocks.append(f"<!-- page: {number} -->\n\n{text}")
            else:
                blocks.append(text)

        warnings: list[str] = []
        if empty_pages == len(pages) and pages:
            warnings.append(
                "No extractable text found. The PDF is likely a scan; "
                "run OCR (e.g. ocrmypdf) before converting."
            )
        elif empty_pages:
            warnings.append(f"{empty_pages} page(s) contained no extractable text.")
        if used_engine == "pdfplumber":
            warnings.append("Extracted with the pdfplumber fallback engine.")

        metadata.update(
            {
                "page_count": page_count,
                "extracted_pages": len(pages),
                "empty_pages": empty_pages,
                "pdf_engine": used_engine,
            }
        )
        return self.build_result(path, "\n\n".join(blocks), metadata=metadata, warnings=warnings)

    # -- Internals ---------------------------------------------------------

    def _extract(
        self,
        path: PathLike,
        engine: str,
        options: dict[str, Any],
    ) -> tuple[list[tuple[int, str]], int, dict[str, Any], str]:
        """Dispatch to the requested engine and normalise its output."""
        if engine not in {"auto", "pypdf", "pdfplumber"}:
            raise ConversionError(
                str(path),
                f"unknown pdf_engine {engine!r} (use 'auto', 'pypdf' or 'pdfplumber')",
                converter=self.name,
            )

        if engine == "pdfplumber":
            return self._extract_pdfplumber(path, options)

        primary = self._extract_pypdf(path, options)
        if (
            engine == "auto"
            and not any(text.strip() for _, text in primary[0])
            and has_dependency("pdfplumber")
        ):
            fallback = self._extract_pdfplumber(path, options)
            if any(text.strip() for _, text in fallback[0]):
                return fallback
        return primary

    def _extract_pypdf(
        self, path: PathLike, options: dict[str, Any]
    ) -> tuple[list[tuple[int, str]], int, dict[str, Any], str]:
        """Extract text with pypdf."""
        pypdf = import_optional("pypdf", extra="pdf", feature="to convert PDF files")
        try:
            reader = pypdf.PdfReader(str(path))
            if reader.is_encrypted:
                password = options.get("password") or ""
                if reader.decrypt(password) == 0:
                    raise ConversionError(
                        str(path),
                        "PDF is encrypted and the supplied password was rejected",
                        converter=self.name,
                    )
            page_count = len(reader.pages)
            selected = _select_pages(options.get("pages"), page_count)
            pages = [(number, reader.pages[number - 1].extract_text() or "") for number in selected]
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(str(path), f"pypdf failed: {exc}", converter=self.name) from exc

        metadata = _pdf_metadata(getattr(reader, "metadata", None))
        return pages, page_count, metadata, "pypdf"

    def _extract_pdfplumber(
        self, path: PathLike, options: dict[str, Any]
    ) -> tuple[list[tuple[int, str]], int, dict[str, Any], str]:
        """Extract text with pdfplumber (better layout, slower)."""
        pdfplumber = import_optional(
            "pdfplumber", extra="pdf", feature="to convert PDF files with pdfplumber"
        )
        try:
            with pdfplumber.open(str(path), password=options.get("password")) as pdf:
                page_count = len(pdf.pages)
                selected = _select_pages(options.get("pages"), page_count)
                pages = [
                    (number, pdf.pages[number - 1].extract_text() or "") for number in selected
                ]
                raw_meta = getattr(pdf, "metadata", None)
        except Exception as exc:
            raise ConversionError(
                str(path), f"pdfplumber failed: {exc}", converter=self.name
            ) from exc
        return pages, page_count, _pdf_metadata(raw_meta), "pdfplumber"


def _select_pages(spec: Any, page_count: int) -> list[int]:
    """Resolve a page selector into a sorted list of 1-based page numbers.

    Args:
        spec: ``None`` (all pages), ``"1-3,7"`` or an iterable of ints.
        page_count: Total pages available, used for clamping.

    Returns:
        Sorted, de-duplicated, clamped page numbers.
    """
    if page_count <= 0:
        return []
    if spec is None:
        return list(range(1, page_count + 1))

    numbers: list[int] = []
    if isinstance(spec, str):
        for chunk in spec.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "-" in chunk:
                start_text, _, end_text = chunk.partition("-")
                start = int(start_text) if start_text.strip() else 1
                end = int(end_text) if end_text.strip() else page_count
                numbers.extend(range(start, end + 1))
            else:
                numbers.append(int(chunk))
    else:
        numbers.extend(int(value) for value in spec)
    return sorted({n for n in numbers if 1 <= n <= page_count})


def _clean_page(text: str, *, reflow: bool, dehyphenate: bool) -> str:
    """Normalise one page of extracted PDF text."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "")
    if dehyphenate:
        text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    if reflow:
        text = _reflow(text)
    text = _TRAILING_WS_RE.sub("", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def _reflow(text: str) -> str:
    """Re-join hard-wrapped lines into paragraphs using layout heuristics."""
    paragraphs: list[str] = []
    buffer = ""
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            if buffer:
                paragraphs.append(buffer)
                buffer = ""
            continue
        if not buffer:
            buffer = line
            continue
        if _starts_new_block(line) or _ends_block(buffer):
            paragraphs.append(buffer)
            buffer = line
            continue
        buffer = f"{buffer} {line}"
    if buffer:
        paragraphs.append(buffer)
    return "\n\n".join(paragraphs)


def _starts_new_block(line: str) -> bool:
    """Heuristic: does ``line`` look like the start of a new block?"""
    if re.match(r"^([-*•‣▪◦]|(\d+|[A-Za-z])[.)])\s+", line):
        return True
    if re.match(r"^(#{1,6}\s|```|---+$|\*\*\*+)", line):
        return True
    if len(line) < 40 and line.isupper() and any(ch.isalpha() for ch in line):
        return True
    return bool(re.match(r"^(\d+(\.\d+)*\s+\S)", line) and len(line) < 80)


def _ends_block(line: str) -> bool:
    """Heuristic: does ``line`` end a logical block?"""
    return bool(_SENTENCE_END_RE.search(line))


def _pdf_metadata(raw: Any) -> dict[str, Any]:
    """Normalise a PDF metadata object to a plain dictionary."""
    if raw is None:
        return {}
    metadata: dict[str, Any] = {}
    for source, target in (
        ("title", "title"),
        ("author", "author"),
        ("subject", "subject"),
        ("keywords", "keywords"),
        ("creator", "creator"),
        ("producer", "producer"),
    ):
        value = getattr(raw, source, None)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            metadata[target] = text
    created = getattr(raw, "creation_date", None)
    if created is not None:
        try:
            metadata["created"] = created.isoformat()
        except AttributeError:  # pragma: no cover - defensive
            metadata["created"] = str(created)
    return metadata


def _page_summary(pages: Sequence[tuple[int, str]]) -> str:  # pragma: no cover - convenience
    """Return a short human summary of extracted pages (debug helper)."""
    return f"{len(pages)} page(s), {sum(len(t) for _, t in pages)} characters"
