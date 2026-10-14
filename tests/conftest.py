"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mdforge.core.base import BaseConverter, DocumentResult
from mdforge.core.engine import ConversionEngine


@pytest.fixture()
def engine() -> ConversionEngine:
    """A fresh engine with the built-in converter registry."""
    return ConversionEngine()


@pytest.fixture()
def tmp_text(tmp_path: Path) -> Path:
    path = tmp_path / "notes.txt"
    path.write_text(
        "Release Notes\n=============\n\n"
        "This release focuses on retrieval quality.\n\n"
        "Second paragraph with more detail about chunking behaviour.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def tmp_markdown(tmp_path: Path) -> Path:
    path = tmp_path / "guide.md"
    path.write_text(
        "---\n"
        "title: Retrieval Guide\n"
        "---\n"
        "\n"
        "# Retrieval Guide\n\n"
        "Intro paragraph.\n\n"
        "## Indexing\n\n"
        "Indexing details here.\n\n"
        "### Chunk sizes\n\n"
        "Prefer 300-800 tokens per chunk.\n\n"
        "## Querying\n\n"
        "Query rewriting helps.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def tmp_csv(tmp_path: Path) -> Path:
    path = tmp_path / "people.csv"
    path.write_text(
        "name,role,city\nAda Lovelace,Engineer,London\n"
        "Grace Hopper,Admiral,New York\nAlan Turing,Mathematician,London\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def tmp_json(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "title": "Service Config",
                "retries": 3,
                "features": ["rag", "chunking"],
                "endpoints": [
                    {"name": "search", "method": "GET"},
                    {"name": "index", "method": "POST"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def tmp_jsonl(tmp_path: Path) -> Path:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"id": 1, "event": "convert"}\n{"id": 2, "event": "chunk"}\n',
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def tmp_html(tmp_path: Path) -> Path:
    path = tmp_path / "page.html"
    path.write_text(
        """<!doctype html>
<html lang="en">
  <head>
    <title>Widget Docs</title>
    <meta name="description" content="How the widget works">
    <style>.x { color: red }</style>
    <script>console.log("ignored")</script>
  </head>
  <body>
    <nav><a href="/home">Home</a></nav>
    <h1>Widget</h1>
    <p>A <strong>widget</strong> with <em>style</em> and <code>code</code>.</p>
    <h2>Usage</h2>
    <ul>
      <li>Install it</li>
      <li>Configure it
        <ul><li>Set the key</li></ul>
      </li>
    </ul>
    <table>
      <tr><th>Flag</th><th>Meaning</th></tr>
      <tr><td>--fast</td><td>Skip validation</td></tr>
    </table>
    <pre><code class="language-python">print("hi")</code></pre>
    <p>See <a href="/docs">the docs</a>.</p>
  </body>
</html>
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def tmp_xml(tmp_path: Path) -> Path:
    path = tmp_path / "feed.xml"
    path.write_text(
        '<?xml version="1.0"?><feed><title>News</title><item id="1">First</item></feed>',
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def tmp_docx(tmp_path: Path) -> Path:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Quarterly Report", level=1)
    document.add_paragraph("Revenue grew by 12% year over year.")
    document.add_heading("Details", level=2)
    document.add_paragraph("Europe led the growth.", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Region"
    table.cell(0, 1).text = "Growth"
    table.cell(1, 0).text = "Europe"
    table.cell(1, 1).text = "18%"
    path = tmp_path / "report.docx"
    document.save(str(path))
    return path


class UpperCaseConverter(BaseConverter):
    """Test double: echoes the file contents in upper case."""

    name = "upper"
    extensions = (".up",)
    description = "Uppercase echo"

    def convert(self, path: Any, **options: Any) -> DocumentResult:
        text = Path(path).read_text(encoding="utf-8").upper()
        return self.build_result(path, text, metadata={"echoed": True})

    def extract_metadata(self, path: Any) -> dict[str, Any]:
        return {"byte_size": Path(path).stat().st_size}


@pytest.fixture()
def upper_converter() -> UpperCaseConverter:
    return UpperCaseConverter()
