"""Email message (RFC 822 / ``.eml``) converter built on the stdlib ``email`` package."""

from __future__ import annotations

import html
import re
from email import policy
from email.message import EmailMessage, MIMEPart
from email.parser import BytesHeaderParser, BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..exceptions import ConversionError
from ..utils.deps import has_dependency
from ..utils.text import markdown_table

__all__ = ["EmlConverter"]

_ADDRESS_HEADERS = ("From", "To", "Cc", "Reply-To")
_TAG_RE = re.compile(r"<[^>]+>")
_SKIP_BLOCK_RE = re.compile(r"<(script|style|head)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_BREAK_RE = re.compile(r"<\s*(br|/p|/div|/li|/tr|/h[1-6])\b[^>]*>", re.IGNORECASE)


class EmlConverter(BaseConverter):
    """Convert a saved email into Markdown: headers, body, then attachment list.

    The ``text/plain`` part is preferred because it is what the sender wrote.
    HTML-only messages go through the HTML renderer when ``beautifulsoup4`` is
    installed, and a tag-stripping fallback otherwise. Attachments are listed,
    not converted.

    Supported options (passed as keyword arguments to :meth:`convert`):

    ``prefer_html``
        Use the ``text/html`` part even when a ``text/plain`` part exists
        (default: ``False``).
    """

    name = "eml"
    extensions = (".eml",)
    mime_types = ("message/rfc822",)
    description = "Email messages (RFC 822)"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Render ``path`` as Markdown.

        Args:
            path: ``.eml`` file to convert.
            **options: See the class docstring.

        Returns:
            A :class:`DocumentResult` with headers, body and attachment list.

        Raises:
            ConversionError: If the file cannot be read or parsed as an email.
        """
        message = self._parse(path)
        warnings: list[str] = []

        subject = _header(message, "Subject")
        body, body_format = _body(message, prefer_html=bool(options.get("prefer_html")))
        if body_format == "html-stripped":
            warnings.append(
                "HTML-only email rendered without beautifulsoup4; "
                "install mdforge[html] to keep tables and lists."
            )
        attachments = _attachments(message)

        sections = [f"# {subject}" if subject else "# (no subject)"]
        header_rows = [
            [name, value]
            for name in (*_ADDRESS_HEADERS, "Date")
            if (value := _header(message, name))
        ]
        if header_rows:
            sections.append(markdown_table(header_rows, ["Field", "Value"]))
        sections.append(body.strip() if body.strip() else "_No text body._")
        if attachments:
            rows = [
                [name, content_type, f"{size:,} bytes"] for name, content_type, size in attachments
            ]
            sections.append("## Attachments\n\n" + markdown_table(rows, ["File", "Type", "Size"]))

        metadata = _header_metadata(message)
        metadata["body_format"] = body_format
        metadata["attachment_count"] = len(attachments)
        return self.build_result(path, "\n\n".join(sections), metadata=metadata, warnings=warnings)

    def extract_metadata(self, path: PathLike) -> dict[str, Any]:
        """Read headers only, skipping the body and attachments.

        Args:
            path: ``.eml`` file to inspect.

        Returns:
            Subject, addresses, date and message ID when present.
        """
        try:
            with Path(path).open("rb") as handle:
                headers = BytesHeaderParser(policy=policy.default).parse(handle)
        except OSError:
            return {}
        return _header_metadata(headers)

    def _parse(self, path: PathLike) -> EmailMessage:
        try:
            with Path(path).open("rb") as handle:
                message = BytesParser(policy=policy.default).parse(handle)
        except OSError as exc:
            raise ConversionError(
                str(path), f"cannot read email: {exc}", converter=self.name
            ) from exc
        if not isinstance(message, EmailMessage) or not message.keys():
            raise ConversionError(str(path), "no email headers found", converter=self.name)
        return message


def _header(message: Any, name: str) -> str:
    """Return a decoded, single-line header value, or ``""`` when absent or malformed."""
    try:
        value = message.get(name)
    except (TypeError, ValueError):
        return ""
    return " ".join(str(value).split()) if value is not None else ""


def _header_metadata(message: Any) -> dict[str, Any]:
    """Collect frontmatter fields from the message headers."""
    metadata: dict[str, Any] = {}
    subject = _header(message, "Subject")
    if subject:
        metadata["title"] = subject
    for name in ("From", "To", "Cc"):
        raw = message.get_all(name) or []
        addresses = [addr for _, addr in getaddresses([str(value) for value in raw]) if addr]
        if addresses:
            metadata[name.lower()] = addresses[0] if name == "From" else addresses
    date = _header(message, "Date")
    if date:
        try:
            metadata["date"] = parsedate_to_datetime(date).isoformat()
        except (TypeError, ValueError):
            metadata["date"] = date
    message_id = _header(message, "Message-ID")
    if message_id:
        metadata["message_id"] = message_id
    return metadata


def _body(message: EmailMessage, *, prefer_html: bool) -> tuple[str, str]:
    """Return the body text and which part produced it."""
    preference = ("html", "plain") if prefer_html else ("plain", "html")
    part = message.get_body(preferencelist=preference)
    if part is None:
        return "", "none"
    content = _part_text(part)
    if part.get_content_subtype() != "html":
        return content, "plain"
    if has_dependency("bs4"):
        return _render_html(content), "html"
    return _strip_html(content), "html-stripped"


def _part_text(part: MIMEPart) -> str:
    # get_content() raises LookupError on unknown charsets that mail clients still send.
    try:
        return str(part.get_content())
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""


def _render_html(markup: str) -> str:
    """Render HTML with the same renderer the HTML converter uses."""
    import bs4

    from .html import _SKIP_TAGS, _HtmlRenderer, _pick_parser

    soup = bs4.BeautifulSoup(markup, _pick_parser())
    for tag_name in _SKIP_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()
    return _HtmlRenderer().render(soup)


def _strip_html(markup: str) -> str:
    """Reduce HTML to paragraphs of plain text."""
    text = _SKIP_BLOCK_RE.sub("", markup)
    text = _BREAK_RE.sub("\n", text)
    text = html.unescape(_TAG_RE.sub("", text))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _attachments(message: EmailMessage) -> list[tuple[str, str, int]]:
    """List ``(filename, content type, decoded size)`` for every attachment."""
    found: list[tuple[str, str, int]] = []
    for part in message.iter_attachments():
        payload = part.get_payload(decode=True)
        size = len(payload) if isinstance(payload, bytes) else 0
        found.append((part.get_filename() or "(unnamed)", part.get_content_type(), size))
    return found
