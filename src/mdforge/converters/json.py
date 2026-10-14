"""JSON and JSON-Lines converter."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ..core.base import BaseConverter, DocumentResult, PathLike
from ..utils.text import fenced_code_block, read_text_safely

__all__ = ["JsonConverter"]


class JsonConverter(BaseConverter):
    """Convert JSON / JSONL into fenced, syntax-highlighted Markdown.

    Two modes are available via the ``json_mode`` option:

    ``code`` (default)
        Emit the pretty-printed JSON inside a ```json fence.  Best fidelity;
        ideal when an LLM needs to reason over the raw structure.
    ``flatten``
        Additionally emit a ``## Keys`` outline of the top-level structure and,
        for arrays of objects, a Markdown table of scalar fields.  Best for
        embedding in RAG pipelines.
    """

    name = "json"
    extensions = (".json", ".jsonl", ".ndjson")
    mime_types = ("application/json", "application/x-ndjson")
    description = "JSON and JSON Lines documents"

    def convert(self, path: PathLike, **options: Any) -> DocumentResult:
        """Parse ``path`` and render it as Markdown.

        Args:
            path: JSON or JSONL file.
            **options: Supports ``json_mode`` (``"code"``/``"flatten"``),
                ``encoding`` and ``max_rows`` (int, flatten mode).

        Returns:
            A :class:`DocumentResult` with the rendered JSON.

        Raises:
            ConversionError: If the file is not valid JSON/JSONL.
        """
        text, encoding = read_text_safely(path, encoding=options.get("encoding"))
        mode = str(options.get("json_mode", "code")).lower()
        is_lines = str(path).lower().endswith((".jsonl", ".ndjson"))

        if is_lines:
            records: list[Any] = []
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise _invalid(path, f"invalid JSON on line {number}: {exc}") from exc
            data: Any = records
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise _invalid(path, f"invalid JSON: {exc}") from exc

        pretty = json.dumps(_jsonable(data), indent=2, ensure_ascii=False)
        parts: list[str] = []
        if mode == "flatten":
            outline = _outline(data, max_rows=int(options.get("max_rows", 50)))
            if outline:
                parts.append(outline)
        parts.append(fenced_code_block(pretty, language="json"))
        body = "\n\n".join(parts)

        metadata: dict[str, Any] = {
            "encoding": encoding,
            "json_mode": mode,
            "root_type": _root_type(data),
        }
        if isinstance(data, list):
            metadata["record_count"] = len(data)
        if isinstance(data, dict):
            metadata["key_count"] = len(data)
            for candidate in ("title", "name", "id"):
                value = data.get(candidate)
                if isinstance(value, (str, int)):
                    metadata["title"] = str(value)
                    break
        return self.build_result(path, body, metadata=metadata)


def _invalid(path: PathLike, reason: str) -> Exception:
    """Build a :class:`ConversionError` for malformed JSON input."""
    from ..exceptions import ConversionError

    return ConversionError(str(path), reason, converter="json")


def _root_type(data: Any) -> str:
    """Return a friendly name for the JSON root value's type."""
    if isinstance(data, dict):
        return "object"
    if isinstance(data, list):
        return "array"
    return type(data).__name__


def _jsonable(value: Any) -> Any:
    """Recursively coerce non-JSON values (dates) into serialisable forms."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _outline(data: Any, *, max_rows: int) -> str | None:
    """Render a structural outline of ``data`` for the ``flatten`` mode."""
    from ..utils.text import markdown_table

    sections: list[str] = []
    if isinstance(data, dict):
        keys = [f"- `{key}` -> {_describe(value)}" for key, value in data.items()]
        sections.append("## Keys\n\n" + "\n".join(keys))
        table_source = _first_object_array(data)
        if table_source is not None:
            rows, header = table_source
            sections.append("## Records\n\n" + markdown_table(rows[:max_rows], header))
    elif isinstance(data, list):
        rows, header = _object_rows(data)
        if header:
            sections.append("## Records\n\n" + markdown_table(rows[:max_rows], header))
    return "\n\n".join(s for s in sections if s) or None


def _describe(value: Any) -> str:
    """One-phrase description of a JSON value for the key outline."""
    if isinstance(value, dict):
        return f"object ({len(value)} keys)"
    if isinstance(value, list):
        return f"array ({len(value)} items)"
    if isinstance(value, str):
        preview = value if len(value) <= 60 else value[:57] + "..."
        return f"string {preview!r}"
    return f"{type(value).__name__} {value!r}"


def _first_object_array(data: dict[str, Any]) -> tuple[list[list[Any]], list[str]] | None:
    """Find the first top-level key holding an array of objects."""
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return _object_rows(value)
    return None


def _object_rows(items: list[Any]) -> tuple[list[list[Any]], list[str]]:
    """Turn a list of flat objects into ``(rows, header)`` for a table."""
    if not items or not all(isinstance(item, dict) for item in items):
        return [], []
    header: list[str] = []
    for item in items:
        for key in item:
            if key not in header:
                header.append(key)
    rows = [[item.get(column, "") for column in header] for item in items if isinstance(item, dict)]
    return rows, header
