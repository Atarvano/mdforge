"""HTML converter (powered by BeautifulSoup).

Implements a bespoke HTML -> Markdown renderer rather than pulling in an extra
dependency, so we control exactly how tables, nested lists, code blocks and
relative links are emitted - the parts that matter most for RAG quality.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..exceptions import ConversionError
from ..utils.deps import import_optional
from ..utils.text import fenced_code_block, markdown_table, read_text_safely

__all__ = ["HtmlConverter"]

_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_SKIP_TAGS = {"script", "style", "noscript", "template", "head", "meta", "link"}
_CONTAINER_TAGS = {
    "div",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "aside",
    "nav",
    "figure",
    "body",
    "html",
    "form",
    "details",
    "summary",
    "dl",
    "dd",
    "dt",
}
_BLOCK_TAGS = (
    set(_HEADINGS)
    | _CONTAINER_TAGS
    | {"p", "ul", "ol", "li", "table", "thead", "tbody", "tr", "blockquote", "pre", "hr", "br"}
)
_WHITESPACE_RE = re.compile(r"[ \t\r\n\f\v]+")


class HtmlConverter(BaseConverter):
    """Convert HTML documents and fragments into clean Markdown.

    Supported options (passed as keyword arguments to :meth:`convert`):

    ``content_selector``
        A single CSS selector (e.g. ``"article"`` or ``"#main"``) restricting
        conversion to that subtree.  Ideal for stripping cookie banners and
        site chrome.
    ``strip_selectors``
        Iterable of extra CSS selectors to delete before rendering.
    ``keep_links`` / ``keep_images``
        Toggle link and image rendering (defaults: ``True``).
    ``base_url``
        Base used to absolutise relative ``href``/``src`` attributes.
    """

    name = "html"
    extensions = (".html", ".htm", ".xhtml")
    mime_types = ("text/html", "application/xhtml+xml")
    requires = ("bs4",)
    extra = "html"
    description = "HTML pages and fragments"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Render ``path`` as Markdown.

        Args:
            path: HTML file to convert.
            **options: See the class docstring.

        Returns:
            A :class:`DocumentResult` with the rendered Markdown.

        Raises:
            MissingDependencyError: If ``beautifulsoup4`` is not installed.
            ConversionError: If the document cannot be parsed.
        """
        bs4 = import_optional(
            "bs4", extra="html", feature="to convert HTML documents", package="beautifulsoup4"
        )
        text, encoding = read_text_safely(path, encoding=options.get("encoding"))

        parser = _pick_parser()
        try:
            soup = bs4.BeautifulSoup(text, parser)
        except Exception as exc:
            raise ConversionError(
                str(path), f"cannot parse HTML: {exc}", converter=self.name
            ) from exc

        title = _document_title(soup)
        description = _meta_content(soup, "description")

        for tag_name in _SKIP_TAGS:
            for element in soup.find_all(tag_name):
                element.decompose()
        for selector in options.get("strip_selectors") or ():
            for element in soup.select(selector):
                element.decompose()

        root = soup
        selector = options.get("content_selector")
        if selector:
            selected = soup.select_one(selector)
            if selected is None:
                warning = (
                    f"content_selector {selector!r} matched nothing; using the whole document."
                )
            else:
                root = selected
                warning = None
        else:
            warning = None

        renderer = _HtmlRenderer(
            base_url=options.get("base_url"),
            keep_links=bool(options.get("keep_links", True)),
            keep_images=bool(options.get("keep_images", True)),
        )
        body = renderer.render(root)
        if not body.strip():
            body = (
                f"# {title}\n\n_No extractable text content._"
                if title
                else "_No extractable text content._"
            )

        warnings: list[str] = []
        if warning:
            warnings.append(warning)
        if encoding not in {"utf-8", "utf-8-sig", "ascii"}:
            warnings.append(f"Decoded as {encoding}; verify non-ASCII characters.")

        metadata: dict[str, Any] = {
            "encoding": encoding,
            "link_count": len(root.find_all("a")),
            "image_count": len(root.find_all("img")),
            "heading_count": len(root.find_all(list(_HEADINGS))),
        }
        if description:
            metadata["description"] = description
        language = (soup.find("html") or {}).get("lang") if soup.find("html") else None
        if language:
            metadata["language"] = str(language)
        if title:
            metadata["title"] = title
        return self.build_result(path, body, metadata=metadata, warnings=warnings)


def _pick_parser() -> str:
    """Prefer ``lxml`` when installed, else fall back to the stdlib parser."""
    from ..utils.deps import has_dependency

    return "lxml" if has_dependency("lxml") else "html.parser"


def _document_title(soup: Any) -> str:
    """Return the ``<title>`` text, or the first ``<h1>`` as a fallback."""
    if soup.title and soup.title.string:
        return str(soup.title.string).strip()
    heading = soup.find("h1")
    if heading is not None:
        return str(heading.get_text(strip=True))
    return ""


def _meta_content(soup: Any, name: str) -> str | None:
    """Return the ``content`` of ``<meta name="...">`` when present."""
    meta = soup.find("meta", attrs={"name": name})
    if meta is not None and meta.get("content"):
        return str(meta["content"]).strip()
    return None


class _HtmlRenderer:
    """Stateful HTML -> Markdown renderer."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        keep_links: bool = True,
        keep_images: bool = True,
    ) -> None:
        self.base_url = base_url
        self.keep_links = keep_links
        self.keep_images = keep_images

    # -- Entry point -------------------------------------------------------

    def render(self, node: Any) -> str:
        """Render ``node``'s children as a block-level Markdown document."""
        blocks = self._blocks(node)
        text = "\n\n".join(block for block in blocks if block and block.strip())
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # -- Block level -------------------------------------------------------

    def _blocks(self, node: Any) -> list[str]:
        """Render direct children into a list of block strings."""
        from bs4.element import NavigableString

        blocks: list[str] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                text = _clean("".join(buffer))
                if text:
                    blocks.append(text)
                buffer.clear()

        for child in node.children:
            if isinstance(child, NavigableString):
                buffer.append(str(child))
                continue
            name = (child.name or "").lower()
            if name in _SKIP_TAGS:
                continue
            if name in _BLOCK_TAGS:
                flush()
                blocks.extend(self._block(child, name))
            else:
                buffer.append(self._inline(child))
        flush()
        return blocks

    def _block(self, node: Any, name: str) -> list[str]:
        """Render a single block-level element into zero or more blocks."""
        if name in _HEADINGS:
            text = self._inline_children(node).strip()
            return [f"{'#' * _HEADINGS[name]} {text}".rstrip()] if text else []
        if name == "p":
            text = self._inline_children(node).strip()
            return [text] if text else []
        if name in ("ul", "ol"):
            rendered = self._list(node, ordered=name == "ol", depth=0)
            return [rendered] if rendered.strip() else []
        if name == "table":
            rendered = self._table(node)
            return [rendered] if rendered else []
        if name == "pre":
            return [self._code_block(node)]
        if name == "blockquote":
            inner = self.render(node)
            if not inner.strip():
                return []
            quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in inner.split("\n"))
            return [quoted]
        if name == "hr":
            return ["---"]
        if name in ("dl",):
            return [self._definition_list(node)]
        if name in _CONTAINER_TAGS:
            return self._blocks(node)
        # Unknown block-ish element: fall back to its inline rendering.
        text = self._inline_children(node).strip()
        return [text] if text else []

    def _list(self, node: Any, *, ordered: bool, depth: int) -> str:
        """Render ``<ul>``/``<ol>`` recursively, preserving nesting."""
        lines: list[str] = []
        index = 1
        for item in node.find_all("li", recursive=False):
            inline_parts: list[str] = []
            nested: list[str] = []
            for child in item.children:
                child_name = (getattr(child, "name", None) or "").lower()
                if child_name in ("ul", "ol"):
                    nested.append(self._list(child, ordered=child_name == "ol", depth=depth + 1))
                elif child_name in _BLOCK_TAGS:
                    nested.extend(b for b in self._block(child, child_name) if b)
                else:
                    inline_parts.append(self._inline(child))
            marker = f"{index}." if ordered else "-"
            indent = "  " * depth
            text = _clean("".join(inline_parts))
            lines.append(f"{indent}{marker} {text}".rstrip())
            for block in nested:
                lines.extend(block.split("\n"))
            index += 1
        return "\n".join(lines)

    def _definition_list(self, node: Any) -> str:
        """Render ``<dl>`` as bold terms followed by their definitions."""
        lines: list[str] = []
        for child in node.find_all(["dt", "dd"], recursive=False):
            text = self._inline_children(child).strip()
            if not text:
                continue
            lines.append(f"**{text}**" if child.name == "dt" else text)
        return "\n\n".join(lines)

    def _table(self, node: Any) -> str:
        """Render an HTML table as a Markdown table."""
        rows: list[list[str]] = []
        header: list[str] | None = None
        for row in node.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            values = [self._inline_children(cell).strip() for cell in cells]
            if header is None and any(cell.name == "th" for cell in cells):
                header = values
            else:
                rows.append(values)
        if header is None and rows:
            header, rows = rows[0], rows[1:]
        if header is None:
            return ""
        return markdown_table(rows, header)

    def _code_block(self, node: Any) -> str:
        """Render ``<pre>`` (optionally wrapping ``<code>``) as a fence."""
        language = ""
        code = node.find("code")
        target = code if code is not None else node
        classes = target.get("class") or []
        for cls in classes:
            if cls.startswith("language-"):
                language = cls[len("language-") :]
                break
            if cls.startswith("lang-"):
                language = cls[len("lang-") :]
                break
        return fenced_code_block(target.get_text(), language=language)

    # -- Inline level ------------------------------------------------------

    def _inline_children(self, node: Any) -> str:
        from bs4.element import NavigableString

        parts: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            else:
                parts.append(self._inline(child))
        return "".join(parts)

    def _inline(self, node: Any) -> str:
        """Render an inline-level element (or string) to Markdown."""
        from bs4.element import NavigableString

        if isinstance(node, NavigableString):
            return str(node)

        name = (node.name or "").lower()
        if name in _SKIP_TAGS:
            return ""
        if name == "br":
            return "\n"
        if name == "hr":
            return "\n\n---\n\n"

        if name in _BLOCK_TAGS:
            # A block nested inside inline context: render as its own paragraph.
            return "\n\n" + "\n\n".join(self._block(node, name)) + "\n\n"

        if name in ("strong", "b"):
            return self._wrap(node, "**")
        if name in ("em", "i"):
            return self._wrap(node, "*")
        if name in ("del", "s", "strike"):
            return self._wrap(node, "~~")
        if name == "code":
            text = node.get_text()
            return f"`{text}`" if text else ""
        if name == "kbd":
            return f"`{node.get_text()}`"
        if name == "mark":
            return f"=={self._inline_children(node).strip()}=="
        if name == "sub":
            return f"~{self._inline_children(node).strip()}~"
        if name == "sup":
            return f"^{self._inline_children(node).strip()}^"
        if name == "a":
            return self._link(node)
        if name == "img":
            return self._image(node)

        return self._inline_children(node)

    def _wrap(self, node: Any, marker: str) -> str:
        inner = self._inline_children(node).strip()
        return f"{marker}{inner}{marker}" if inner else ""

    def _link(self, node: Any) -> str:
        text = _clean(self._inline_children(node))
        href = node.get("href")
        if not self.keep_links or not href or str(href).startswith(("javascript:", "#")):
            return text
        return f"[{text or href}]({self._absolute(href)})"

    def _image(self, node: Any) -> str:
        if not self.keep_images:
            return ""
        src = node.get("src")
        if not src:
            return ""
        alt = _clean(str(node.get("alt") or ""))
        return f"![{alt}]({self._absolute(src)})"

    def _absolute(self, url: Any) -> str:
        url_str = str(url).strip()
        if self.base_url and not url_str.startswith(("http://", "https://", "data:", "mailto:")):
            return urljoin(self.base_url, url_str)
        return url_str


def _clean(text: str) -> str:
    """Collapse HTML whitespace runs into single spaces."""
    return _WHITESPACE_RE.sub(" ", text).strip()
