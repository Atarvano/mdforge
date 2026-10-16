"""Granular converter plugins shipped with mdforge.

Each module exposes exactly one :class:`~mdforge.core.base.BaseConverter`
subclass.  Imports of third-party parsing libraries happen *inside* the
converter body (see :func:`mdforge.utils.deps.import_optional`), which keeps
``import mdforge`` cheap and lets users install only the extras they need.
"""

from __future__ import annotations

from ..core.base import BaseConverter

__all__ = ["default_converters"]


def default_converters() -> list[BaseConverter]:
    """Instantiate every built-in converter.

    Returns:
        A fresh list of converter instances, ordered so that the most specific
        text formats are registered first.  The engine keeps the *last*
        registration for a given extension, so ordering here is purely
        cosmetic in practice.
    """
    # Imported lazily to keep module import time low and to avoid importing
    # modules whose optional dependencies are not installed.
    from .csv import CsvConverter
    from .docx import DocxConverter
    from .eml import EmlConverter
    from .html import HtmlConverter
    from .json import JsonConverter
    from .pdf import PdfConverter
    from .pptx import PptxConverter
    from .text import TextConverter
    from .xlsx import XlsxConverter
    from .xml import XmlConverter

    converters: list[BaseConverter] = [
        PdfConverter(),
        DocxConverter(),
        PptxConverter(),
        XlsxConverter(),
        CsvConverter(),
        EmlConverter(),
        HtmlConverter(),
        JsonConverter(),
        XmlConverter(),
        TextConverter(),
    ]
    return converters
