"""PPTX converter (powered by python-pptx)."""

from __future__ import annotations

from typing import Any

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..exceptions import ConversionError
from ..utils.deps import import_optional
from ..utils.text import markdown_table

__all__ = ["PptxConverter"]


class PptxConverter(BaseConverter):
    """Convert each slide into a ``## Slide N`` Markdown section.

    Titles, bullet lists (with nesting), tables, speaker notes and picture
    counts all survive the conversion, which makes decks directly usable as
    retrieval sources instead of an unreadable blob.
    """

    name = "pptx"
    extensions = (".pptx",)
    mime_types = ("application/vnd.openxmlformats-officedocument.presentationml.presentation",)
    requires = ("pptx",)
    extra = "pptx"
    description = "PowerPoint presentations (.pptx)"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Convert ``path`` to Markdown.

        Args:
            path: ``.pptx`` file to convert.
            **options: Supports ``include_notes`` (bool, default ``True``) and
                ``max_table_rows`` (int, default ``50``).

        Returns:
            A :class:`DocumentResult` with one section per slide.

        Raises:
            MissingDependencyError: If ``python-pptx`` is not installed.
            ConversionError: If the presentation cannot be opened.
        """
        pptx = import_optional("pptx", extra="pptx", feature="to convert PowerPoint presentations")

        try:
            presentation = pptx.Presentation(str(path))
        except Exception as exc:
            raise ConversionError(
                str(path), f"cannot open presentation: {exc}", converter=self.name
            ) from exc

        include_notes = bool(options.get("include_notes", True))
        max_table_rows = int(options.get("max_table_rows", 50))

        sections: list[str] = []
        warnings: list[str] = []
        tables = 0
        pictures = 0
        notes_count = 0
        deck_title: str | None = None

        for number, slide in enumerate(presentation.slides, start=1):
            title = _slide_title(slide)
            if deck_title is None and title:
                deck_title = title
            heading = f"## {number}. {title}" if title else f"## Slide {number}"
            body: list[str] = []
            title_shape = slide.shapes.title
            title_id = getattr(title_shape, "shape_id", None) if title_shape is not None else None

            for shape in slide.shapes:
                if getattr(shape, "has_table", False):
                    tables += 1
                    rows = _table_rows(shape.table, max_rows=max_table_rows)
                    if rows:
                        body.append(markdown_table(rows))
                    continue
                if (
                    getattr(shape, "shape_type", None) is not None
                    and str(shape.shape_type) == "PICTURE (13)"
                ):
                    pictures += 1
                if title_id is not None and getattr(shape, "shape_id", None) == title_id:
                    continue
                if not getattr(shape, "has_text_frame", False):
                    continue
                text = _text_frame_markdown(shape.text_frame)
                if text.strip():
                    body.append(text)

            if include_notes and slide.has_notes_slide:
                notes = _text_frame_markdown(slide.notes_slide.notes_text_frame, notes=True)
                if notes.strip():
                    notes_count += 1
                    body.append(f"> **Speaker notes:** {notes.strip()}")

            sections.append(f"{heading}\n\n" + "\n\n".join(body) if body else heading)

        if pictures:
            warnings.append(
                f"Presentation contains {pictures} picture(s); image content is not transcribed."
            )

        body_text = "\n\n".join(sections)
        metadata: dict[str, Any] = {
            "slide_count": len(presentation.slides),
            "table_count": tables,
            "picture_count": pictures,
            "notes_count": notes_count,
        }
        metadata.update(_core_properties(presentation))
        if deck_title:
            metadata["title"] = deck_title
        return self.build_result(path, body_text, metadata=metadata, warnings=warnings)


def _slide_title(slide: Any) -> str:
    """Return the text of a slide's title placeholder, if any."""
    try:
        title_shape = slide.shapes.title
    except (KeyError, ValueError):  # pragma: no cover - malformed deck
        title_shape = None
    if title_shape is None or not getattr(title_shape, "has_text_frame", False):
        return ""
    return str(title_shape.text_frame.text).strip().replace("\n", " ")


def _text_frame_markdown(text_frame: Any, *, notes: bool = False) -> str:
    """Render a text frame as Markdown bullet list lines."""
    lines: list[str] = []
    for paragraph in text_frame.paragraphs:
        text = "".join(run.text for run in paragraph.runs).strip()
        if not text:
            continue
        level = int(getattr(paragraph, "level", 0) or 0)
        indent = "  " * level
        if notes:
            lines.append(f"{indent}{text}")
        else:
            lines.append(f"{indent}- {text}")
    return "\n".join(lines)


def _table_rows(table: Any, *, max_rows: int) -> list[list[str]]:
    """Extract a PowerPoint table as rows of cell text."""
    rows: list[list[str]] = []
    for index, row in enumerate(table.rows):
        if index > max_rows:
            break
        cells = [" ".join(cell.text.split()) if cell.text else "" for cell in row.cells]
        if any(cells):
            rows.append(cells)
    return rows


def _core_properties(presentation: Any) -> dict[str, Any]:
    """Extract presentation core properties such as author and title."""
    props = getattr(presentation, "core_properties", None)
    if props is None:  # pragma: no cover - defensive
        return {}
    metadata: dict[str, Any] = {}
    for attribute in ("author", "category", "comments", "keywords", "subject"):
        value = getattr(props, attribute, None)
        if value:
            key = "description" if attribute == "comments" else attribute
            metadata[key] = str(value).strip()
    for attribute in ("created", "modified"):
        value = getattr(props, attribute, None)
        if value is not None:
            metadata[attribute] = value.isoformat()
    return metadata
