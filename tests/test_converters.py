"""Tests for the individual converters."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdforge.core.engine import ConversionEngine
from mdforge.core.metadata import split_frontmatter

# --------------------------------------------------------------------------- #
# Plain text
# --------------------------------------------------------------------------- #


def test_text_converter_promotes_rst_heading(engine: ConversionEngine, tmp_text: Path) -> None:
    result = engine.convert(tmp_text)
    assert result.markdown.split("---")[-1].lstrip().startswith("# Release Notes")
    assert result.metadata["line_count"] > 0
    assert result.metadata["encoding"] in {"utf-8", "utf-8-sig", "ascii"}


def test_markdown_passthrough(engine: ConversionEngine, tmp_markdown: Path) -> None:
    result = engine.convert(tmp_markdown)
    _, body = split_frontmatter(result.markdown)
    assert body.count("# Retrieval Guide") >= 1
    assert "### Chunk sizes" in body
    assert result.metadata["title"] == "Retrieval Guide"


def test_latin1_fallback_does_not_crash(engine: ConversionEngine, tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes("Caf\xe9 cr\xe8me".encode("latin-1"))
    result = engine.convert(path)
    assert "Caf" in result.markdown


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #


def test_csv_converter_table(engine: ConversionEngine, tmp_csv: Path) -> None:
    result = engine.convert(tmp_csv)
    _, body = split_frontmatter(result.markdown)
    assert "| name | role | city |" in body
    assert "| Ada Lovelace | Engineer | London |" in body
    assert result.metadata["row_count"] == 4  # header + 3 data rows
    assert result.metadata["column_count"] == 3
    assert result.metadata["delimiter"] == ","


def test_csv_truncation_warns(engine: ConversionEngine, tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    lines = ["value"] + [str(i) for i in range(50)]
    path.write_text("\n".join(lines), encoding="utf-8")
    result = engine.convert(path, max_rows=10)
    assert any("Truncated" in warning for warning in result.warnings)
    assert result.metadata["truncated"] is True


def test_tsv_semicolon_detection(engine: ConversionEngine, tmp_path: Path) -> None:
    path = tmp_path / "semi.csv"
    path.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    result = engine.convert(path)
    assert result.metadata["delimiter"] == ";"
    assert "| a | b | c |" in result.markdown


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #


def test_json_code_mode(engine: ConversionEngine, tmp_json: Path) -> None:
    result = engine.convert(tmp_json)
    assert "```json" in result.markdown
    assert result.metadata["root_type"] == "object"
    assert result.metadata["title"] == "Service Config"


def test_json_flatten_mode(engine: ConversionEngine, tmp_json: Path) -> None:
    result = engine.convert(tmp_json, json_mode="flatten")
    assert "## Keys" in result.markdown
    assert "## Records" in result.markdown
    assert "| name" in result.markdown and "method" in result.markdown


def test_jsonl_is_parsed(engine: ConversionEngine, tmp_jsonl: Path) -> None:
    result = engine.convert(tmp_jsonl)
    assert result.metadata["root_type"] == "array"
    assert result.metadata["record_count"] == 2


def test_invalid_json_reports_line(engine: ConversionEngine, tmp_path: Path) -> None:
    from mdforge.exceptions import ConversionError

    path = tmp_path / "broken.jsonl"
    path.write_text('{"ok": 1}\n{not json}\n', encoding="utf-8")
    with pytest.raises(ConversionError) as excinfo:
        engine.convert(path)
    assert "line 2" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# XML
# --------------------------------------------------------------------------- #


def test_xml_converter(engine: ConversionEngine, tmp_xml: Path) -> None:
    result = engine.convert(tmp_xml)
    assert "```xml" in result.markdown
    assert "<title>News</title>" in result.markdown
    assert result.metadata["root_tag"] == "feed"
    assert result.metadata["element_count"] == 3


def test_invalid_xml_raises(engine: ConversionEngine, tmp_path: Path) -> None:
    from mdforge.exceptions import ConversionError

    path = tmp_path / "bad.xml"
    path.write_text("<a><b></a>", encoding="utf-8")
    with pytest.raises(ConversionError):
        engine.convert(path)


# --------------------------------------------------------------------------- #
# EML
# --------------------------------------------------------------------------- #


def test_eml_converter_structure(engine: ConversionEngine, tmp_eml: Path) -> None:
    body = engine.convert(tmp_eml).markdown
    assert "# Q3 shipping schedule" in body
    assert "| From | Ada Lovelace <ada@example.com> |" in body
    assert "The vessel leaves Batu Ampar on Friday." in body
    assert "> Old thread line" in body
    assert "HTML" not in body.split("## Attachments")[0]
    assert "## Attachments" in body
    assert "| manifest.csv | text/csv |" in body


def test_eml_metadata(engine: ConversionEngine, tmp_eml: Path) -> None:
    result = engine.convert(tmp_eml)
    assert result.metadata["title"] == "Q3 shipping schedule"
    assert result.metadata["from"] == "ada@example.com"
    assert result.metadata["to"] == ["ops@example.com", "grace@example.com"]
    assert result.metadata["date"] == "2025-10-14T09:30:00+07:00"
    assert result.metadata["message_id"] == "<q3-schedule@example.com>"
    assert result.metadata["body_format"] == "plain"
    assert result.metadata["attachment_count"] == 1


def test_eml_prefer_html(engine: ConversionEngine, tmp_eml: Path) -> None:
    result = engine.convert(tmp_eml, prefer_html=True)
    assert result.metadata["body_format"] == "html"
    assert "**version**" in result.markdown


def test_eml_html_only_uses_renderer(engine: ConversionEngine, tmp_eml_html_only: Path) -> None:
    pytest.importorskip("bs4")
    result = engine.convert(tmp_eml_html_only)
    assert "# Weekly" in result.markdown
    assert "- First item" in result.markdown
    assert "color:red" not in result.markdown
    assert result.warnings == []


def test_eml_html_only_without_bs4_warns(
    engine: ConversionEngine, tmp_eml_html_only: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mdforge.converters import eml

    monkeypatch.setattr(eml, "has_dependency", lambda _module: False)
    result = engine.convert(tmp_eml_html_only)
    assert result.metadata["body_format"] == "html-stripped"
    assert "First item\nSecond item" in result.markdown
    assert "Fish & chips" in result.markdown
    assert "<p>" not in result.markdown
    assert any("mdforge[html]" in warning for warning in result.warnings)


def test_eml_extract_metadata_reads_headers(tmp_eml: Path) -> None:
    from mdforge.converters.eml import EmlConverter

    metadata = EmlConverter().extract_metadata(tmp_eml)
    assert metadata["title"] == "Q3 shipping schedule"
    assert "body_format" not in metadata


def test_eml_without_headers_raises(engine: ConversionEngine, tmp_path: Path) -> None:
    from mdforge.exceptions import ConversionError

    path = tmp_path / "not-mail.eml"
    path.write_bytes(b"just some text without headers\n")
    with pytest.raises(ConversionError):
        engine.convert(path)


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #


def test_html_converter_structure(engine: ConversionEngine, tmp_html: Path) -> None:
    result = engine.convert(tmp_html)
    body = result.markdown
    assert "# Widget" in body
    assert "## Usage" in body
    assert "**widget**" in body
    assert "*style*" in body
    assert "`code`" in body
    assert "- Install it" in body
    assert "  - Set the key" in body  # nested list indentation
    assert "| Flag | Meaning |" in body
    assert "```python" in body
    assert "[the docs](/docs)" in body
    assert "console.log" not in body
    assert "color: red" not in body


def test_html_metadata(engine: ConversionEngine, tmp_html: Path) -> None:
    result = engine.convert(tmp_html)
    assert result.metadata["title"] == "Widget Docs"
    assert result.metadata["description"] == "How the widget works"
    assert result.metadata["language"] == "en"
    assert result.metadata["heading_count"] == 2


def test_html_selector_and_link_options(engine: ConversionEngine, tmp_html: Path) -> None:
    result = engine.convert(tmp_html, content_selector="h2", keep_links=False)
    assert result.metadata["heading_count"] == 0
    assert "Home" not in result.markdown


def test_html_missing_selector_warns(engine: ConversionEngine, tmp_html: Path) -> None:
    result = engine.convert(tmp_html, content_selector="#does-not-exist")
    assert any("matched nothing" in warning for warning in result.warnings)


def test_html_base_url_absolutises_links(engine: ConversionEngine, tmp_path: Path) -> None:
    path = tmp_path / "rel.html"
    path.write_text('<p><a href="/docs">Docs</a></p>', encoding="utf-8")
    result = engine.convert(path, base_url="https://example.com")
    assert "https://example.com/docs" in result.markdown


# --------------------------------------------------------------------------- #
# DOCX (optional dependency)
# --------------------------------------------------------------------------- #


def test_docx_converter(engine: ConversionEngine, tmp_docx: Path) -> None:
    result = engine.convert(tmp_docx)
    body = result.markdown
    assert "# Quarterly Report" in body
    assert "## Details" in body
    assert "Revenue grew by 12%" in body
    assert "- Europe led the growth." in body
    assert "| Region | Growth |" in body
    assert "| Europe | 18% |" in body
    assert result.metadata["heading_count"] == 2
    assert result.metadata["table_count"] == 1


def test_docx_unsupported_file_raises(engine: ConversionEngine, tmp_path: Path) -> None:
    from mdforge.exceptions import ConversionError

    path = tmp_path / "fake.docx"
    path.write_bytes(b"this is definitely not a docx file")
    with pytest.raises(ConversionError):
        engine.convert(path)


# --------------------------------------------------------------------------- #
# PDF (optional dependency)
# --------------------------------------------------------------------------- #


def test_pdf_converter_roundtrip(engine: ConversionEngine, tmp_path: Path) -> None:
    """Build a tiny PDF with pypdf-free means (raw PDF bytes) and convert it."""
    pytest.importorskip("pypdf")
    path = tmp_path / "simple.pdf"
    path.write_bytes(_minimal_pdf("Hello PDF world"))

    result = engine.convert(path)
    assert result.metadata["page_count"] == 1
    assert "Hello PDF world" in result.markdown


def test_pdf_page_selector(engine: ConversionEngine, tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    path = tmp_path / "two.pdf"
    path.write_bytes(_minimal_pdf("First page", pages=2))
    result = engine.convert(path, pages="2")
    assert result.metadata["extracted_pages"] == 1
    assert "<!-- page: 2 -->" in result.markdown


def _minimal_pdf(text: str, *, pages: int = 1) -> bytes:
    """Craft a minimal, valid single-page-per-object PDF for testing."""
    objects: list[bytes] = []
    content = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET"

    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for page_index in range(pages):
        content_id = 5 + 2 * page_index
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        stream = content.encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)
