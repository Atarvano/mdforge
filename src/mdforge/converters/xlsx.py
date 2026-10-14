"""XLSX / XLSM workbook converter (powered by openpyxl)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..exceptions import ConversionError
from ..utils.deps import import_optional
from ..utils.text import markdown_table

__all__ = ["XlsxConverter"]


class XlsxConverter(BaseConverter):
    """Convert every worksheet of an Excel workbook into a Markdown section.

    Each sheet becomes a ``## Sheet name`` section containing a Markdown table
    (the first non-empty row is the header).  Formulas are read as their last
    computed value thanks to ``data_only=True``.
    """

    name = "xlsx"
    extensions = (".xlsx", ".xlsm")
    mime_types = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel.sheet.macroEnabled.12",
    )
    requires = ("openpyxl",)
    extra = "xlsx"
    description = "Excel workbooks (.xlsx / .xlsm)"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Convert all sheets in the workbook.

        Args:
            path: Workbook to read.
            **options: Supports ``max_rows`` (int, per sheet, default 500)
                and ``max_columns`` (int, default 50).

        Returns:
            A :class:`DocumentResult` with one section per sheet.

        Raises:
            MissingDependencyError: If ``openpyxl`` is not installed.
            ConversionError: If the workbook cannot be opened.
        """
        openpyxl = import_optional("openpyxl", extra="xlsx", feature="to convert Excel workbooks")
        max_rows = int(options.get("max_rows", 500))
        max_columns = int(options.get("max_columns", 50))
        warnings: list[str] = []

        try:
            workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        except Exception as exc:
            raise ConversionError(
                str(path), f"cannot open workbook: {exc}", converter=self.name
            ) from exc

        sections: list[str] = []
        sheet_names: list[str] = []
        try:
            for worksheet in workbook.worksheets:
                sheet_names.append(worksheet.title)
                rows, truncated = _sheet_rows(worksheet, max_rows=max_rows, max_columns=max_columns)
                if truncated:
                    warnings.append(f"Sheet '{worksheet.title}' truncated to {max_rows} rows.")
                heading = f"## {worksheet.title}"
                if not rows:
                    sections.append(f"{heading}\n\n_No data._")
                    continue
                sections.append(f"{heading}\n\n{markdown_table(rows)}")
        finally:
            close = getattr(workbook, "close", None)
            if callable(close):
                close()

        metadata: dict[str, Any] = {
            "sheet_count": len(sheet_names),
            "sheets": sheet_names,
        }
        return self.build_result(path, "\n\n".join(sections), metadata=metadata, warnings=warnings)


def _sheet_rows(worksheet: Any, *, max_rows: int, max_columns: int) -> tuple[list[list[str]], bool]:
    """Extract rows of strings from a worksheet.

    Returns:
        ``(rows, truncated)`` where ``rows`` holds at most ``max_rows``
        non-empty data rows and ``truncated`` reports whether more data existed.
    """
    rows: list[list[str]] = []
    truncated = False
    for index, row in enumerate(worksheet.iter_rows(values_only=True)):
        if index >= max_rows:
            truncated = True
            break
        cells = [_cell_to_text(value) for value in row[:max_columns]]
        if any(cells):
            rows.append(cells)
    return rows, truncated


def _cell_to_text(value: Any) -> str:
    """Render a spreadsheet cell value as a compact string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # Avoid 0.30000000000000004 style noise.
        return f"{value:g}"
    return str(value).strip()
