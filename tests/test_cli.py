"""Tests for the Typer command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mdforge import __version__
from mdforge.cli import app

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_flag() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Convert documents" in result.stdout


def test_convert_single_to_stdout(tmp_markdown: Path) -> None:
    result = runner.invoke(app, ["convert", str(tmp_markdown)])
    assert result.exit_code == 0
    assert "title: Retrieval Guide" in result.stdout


def test_convert_single_to_file(tmp_markdown: Path, tmp_path: Path) -> None:
    target = tmp_path / "out" / "result.md"
    result = runner.invoke(app, ["convert", str(tmp_markdown), "-o", str(target)])
    assert result.exit_code == 0
    assert target.exists()
    assert "Retrieval Guide" in target.read_text(encoding="utf-8")


def test_convert_no_frontmatter(tmp_text: Path) -> None:
    result = runner.invoke(app, ["convert", str(tmp_text), "--no-frontmatter"])
    assert result.exit_code == 0
    assert not result.stdout.lstrip().startswith("---")


def test_convert_json_output(tmp_text: Path) -> None:
    result = runner.invoke(app, ["convert", str(tmp_text), "--json"])
    assert result.exit_code == 0
    assert '"file_type": "txt"' in result.stdout
    assert '"converter": "text"' in result.stdout


def test_convert_extra_metadata(tmp_text: Path) -> None:
    result = runner.invoke(
        app, ["convert", str(tmp_text), "--meta", "team=rag", "--meta", "env=prod"]
    )
    assert result.exit_code == 0
    assert "team: rag" in result.stdout
    assert "env: prod" in result.stdout


def test_convert_invalid_meta(tmp_text: Path) -> None:
    result = runner.invoke(app, ["convert", str(tmp_text), "--meta", "broken"])
    assert result.exit_code == 2


def test_convert_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["convert", str(tmp_path / "nope.txt")])
    assert result.exit_code == 2


def test_convert_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "thing.zzz"
    path.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(path)])
    assert result.exit_code == 1


def test_convert_multiple_files_writes_directory(tmp_path: Path) -> None:
    files = []
    for index in range(3):
        path = tmp_path / f"doc{index}.txt"
        path.write_text(f"Body {index}", encoding="utf-8")
        files.append(str(path))
    out = tmp_path / "out"

    result = runner.invoke(app, ["convert", *files, "-o", str(out), "--quiet"])

    assert result.exit_code == 0
    assert sorted(p.name for p in out.glob("*.md")) == ["doc0.md", "doc1.md", "doc2.md"]


def test_convert_with_chunk_emits_jsonl(tmp_text: Path, tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    result = runner.invoke(
        app,
        ["convert", str(tmp_text), "-o", str(target), "--chunk", "--chunk-size", "400"],
    )
    assert result.exit_code == 0
    chunk_file = tmp_path / "out.chunks.jsonl"
    assert chunk_file.exists()
    first = json.loads(chunk_file.read_text(encoding="utf-8").splitlines()[0])
    assert "breadcrumb" in first and "content" in first


def test_batch_command(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir()
    for index in range(2):
        (source / f"note{index}.txt").write_text(f"Note {index}", encoding="utf-8")
    (source / "ignored.bin").write_bytes(b"\x00\x01")

    out = tmp_path / "markdown"
    result = runner.invoke(
        app, ["batch", str(source), "-o", str(out), "--pattern", "*.txt", "--quiet"]
    )

    assert result.exit_code == 0
    assert sorted(p.name for p in out.glob("*.md")) == ["note0.md", "note1.md"]


def test_batch_command_no_match(tmp_path: Path) -> None:
    result = runner.invoke(app, ["batch", str(tmp_path), "--pattern", "*.pdf"])
    assert result.exit_code == 1


def test_batch_skips_unsupported_and_reports(tmp_path: Path) -> None:
    source = tmp_path / "mixed"
    source.mkdir()
    (source / "keep.txt").write_text("keep me", encoding="utf-8")
    (source / "skip.bin").write_bytes(b"\x00\x01\x02")

    out = tmp_path / "out"
    result = runner.invoke(app, ["batch", str(source), "-o", str(out)])

    assert result.exit_code == 0
    assert "Skipped 1 file(s)" in result.stdout
    assert [p.name for p in out.glob("*.md")] == ["keep.md"]


def test_batch_does_not_rescan_its_own_output(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir()
    (source / "note.txt").write_text("hello", encoding="utf-8")
    out = source / "markdown"

    first = runner.invoke(app, ["batch", str(source), "-o", str(out), "--quiet"])
    second = runner.invoke(app, ["batch", str(source), "-o", str(out), "--quiet"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert sorted(p.name for p in out.glob("*.md")) == ["note.md"]


def test_batch_disambiguates_duplicate_stems(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    (source / "a").mkdir(parents=True)
    (source / "b").mkdir(parents=True)
    (source / "a" / "note.txt").write_text("alpha", encoding="utf-8")
    (source / "b" / "note.txt").write_text("beta", encoding="utf-8")

    out = tmp_path / "out"
    result = runner.invoke(app, ["batch", str(source), "-o", str(out), "--quiet"])

    assert result.exit_code == 0
    assert sorted(p.name for p in out.glob("*.md")) == ["a__note.md", "b__note.md"]


def test_batch_command_bad_directory(tmp_path: Path) -> None:
    result = runner.invoke(app, ["batch", str(tmp_path / "missing")])
    assert result.exit_code == 2


def test_chunk_command_preview(tmp_markdown: Path) -> None:
    result = runner.invoke(app, ["chunk", str(tmp_markdown), "--preview"])
    assert result.exit_code == 0
    assert "Breadcrumb" in result.stdout


def test_chunk_command_jsonl_to_file(tmp_markdown: Path, tmp_path: Path) -> None:
    target = tmp_path / "chunks.jsonl"
    result = runner.invoke(app, ["chunk", str(tmp_markdown), "-o", str(target)])
    assert result.exit_code == 0
    assert target.exists()
    records = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert records
    assert records[0]["breadcrumb"][0] == "Retrieval Guide"


def test_formats_command() -> None:
    result = runner.invoke(app, ["formats"])
    assert result.exit_code == 0
    assert "pdf" in result.stdout
    assert "docx" in result.stdout


def test_formats_command_json() -> None:
    result = runner.invoke(app, ["formats", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    names = {row["name"] for row in payload}
    assert {"pdf", "docx", "csv", "html", "json", "xml", "text"} <= names


@pytest.mark.parametrize("command", ["convert", "batch", "chunk", "formats"])
def test_subcommands_have_help(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
