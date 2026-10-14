"""XML converter."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..utils.text import fenced_code_block, read_text_safely

__all__ = ["XmlConverter"]


class XmlConverter(BaseConverter):
    """Convert XML into pretty-printed, fenced Markdown.

    Useful for configuration files, RSS/Atom feeds, SOAP payloads and OOXML
    fragments: the LLM gets the structure, while the frontmatter carries the
    root element name and a count of elements.
    """

    name = "xml"
    extensions = (".xml", ".xsd", ".xsl", ".svg", ".rss", ".atom", ".plist")
    mime_types = ("application/xml", "text/xml", "image/svg+xml")
    description = "XML and XML-based formats"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Parse ``path`` and render it as a fenced XML block.

        Args:
            path: XML file to read.
            **options: Supports ``encoding`` and ``max_bytes`` (int, truncates
                the rendered document to keep prompts small).

        Returns:
            A :class:`DocumentResult` containing the pretty-printed XML.

        Raises:
            ConversionError: If the XML is malformed.
        """
        from ..exceptions import ConversionError

        text, encoding = read_text_safely(path, encoding=options.get("encoding"))
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ConversionError(str(path), f"invalid XML: {exc}", converter=self.name) from exc

        indent_tree(root)
        pretty = ET.tostring(root, encoding="unicode")
        warnings: list[str] = []

        max_bytes = options.get("max_bytes")
        if isinstance(max_bytes, int) and len(pretty.encode("utf-8")) > max_bytes:
            pretty = pretty.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
            warnings.append(f"XML truncated to {max_bytes} bytes for prompt size control.")

        body = fenced_code_block(pretty, language="xml")
        metadata: dict[str, Any] = {
            "encoding": encoding,
            "root_tag": _local_name(root.tag),
            "element_count": sum(1 for _ in root.iter()),
        }
        return self.build_result(path, body, metadata=metadata, warnings=warnings)


def indent_tree(element: ET.Element, *, level: int = 0, space: str = "  ") -> None:
    """In-place pretty-print of an :mod:`xml.etree` tree.

    A local reimplementation of ``ElementTree.indent`` so the minimum
    supported Python stays at 3.9 (that helper landed in 3.9, but behaves
    slightly differently for mixed content, and we want deterministic output).

    Args:
        element: Root element to indent.
        level: Current indentation depth.
        space: One indentation unit.
    """
    indentation = "\n" + space * level
    child_indentation = "\n" + space * (level + 1)
    if len(element):
        if not element.text or not element.text.strip():
            element.text = child_indentation
        for index, child in enumerate(element):
            indent_tree(child, level=level + 1, space=space)
            if not child.tail or not child.tail.strip():
                child.tail = child_indentation if index < len(element) - 1 else indentation
        if not element[-1].tail or not element[-1].tail.strip():
            element[-1].tail = indentation
    elif level and (not element.tail or not element.tail.strip()):
        element.tail = indentation


def _local_name(tag: str) -> str:
    """Strip an XML namespace from a tag, e.g. ``{ns}item`` -> ``item``."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag
