"""CSV / TSV converter."""

from __future__ import annotations

import csv
import io
from typing import Any

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..utils.text import markdown_table, read_text_safely

__all__ = ["CsvConverter"]

_DELIMITERS = (",", ";", "\t", "|")


class CsvConverter(BaseConverter):
    """Convert delimited text into a Markdown table.

    The dialect is auto-detected with :class:`csv.Sniffer` and falls back to
    comma.  Wide spreadsheets are truncated (with a warning) so a 500-column
    export does not blow up an LLM context window.
    """

    name = "csv"
    extensions = (".csv", ".tsv")
    mime_types = ("text/csv", "text/tab-separated-values")
    description = "Comma/tab separated values"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Parse ``path`` and render it as a Markdown table.

        Args:
            path: CSV/TSV file.
            **options: Supports ``delimiter`` (str), ``max_rows`` (int,
                default ``1000``), ``max_columns`` (int, default ``50``) and
                ``encoding``.

        Returns:
            A :class:`DocumentResult` with the table.
        """
        text, encoding = read_text_safely(path, encoding=options.get("encoding"))
        delimiter = options.get("delimiter") or _sniff_delimiter(text, path)

        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        all_rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not all_rows:
            return self.build_result(
                path, "_Empty delimited file._", metadata={"encoding": encoding, "row_count": 0}
            )

        max_rows = int(options.get("max_rows", 1000))
        max_columns = int(options.get("max_columns", 50))
        warnings: list[str] = []

        total_rows = len(all_rows)
        total_columns = max(len(row) for row in all_rows)

        rows = all_rows[: max_rows + 1]  # +1 reserves the header row
        if total_rows > len(rows):
            warnings.append(
                f"Truncated {total_rows - len(rows)} rows; pass max_rows=<n> to widen the limit."
            )

        if total_columns > max_columns:
            rows = [row[:max_columns] for row in rows]
            warnings.append(
                f"Truncated {total_columns - max_columns} columns; "
                "pass max_columns=<n> to widen the limit."
            )

        table = markdown_table(rows)
        metadata: dict[str, Any] = {
            "encoding": encoding,
            "delimiter": delimiter,
            "row_count": total_rows,
            "column_count": total_columns,
            "truncated": bool(warnings),
        }
        header = rows[0] if rows else []
        if header:
            metadata["columns"] = [str(c) for c in header[:max_columns]]
        return self.build_result(path, table, metadata=metadata, warnings=warnings)


def _sniff_delimiter(text: str, path: PathLike) -> str:
    """Detect the delimiter, defaulting sensibly for ``.tsv`` and on failure."""
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS)).delimiter
    except csv.Error:
        if str(path).lower().endswith(".tsv"):
            return "\t"
        # Fall back to the delimiter that yields the most consistent columns.
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        best, best_count = ",", 0
        for candidate in _DELIMITERS:
            count = first_line.count(candidate)
            if count > best_count:
                best, best_count = candidate, count
        return best
