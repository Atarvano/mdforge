"""Tests for the conversion engine, frontmatter assembly and batch execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mdforge.core.base import BaseConverter, DocumentResult
from mdforge.core.engine import ConversionEngine
from mdforge.core.metadata import split_frontmatter
from mdforge.exceptions import ConversionError, MissingDependencyError, UnsupportedFormatError


def test_registry_contains_expected_extensions(engine: ConversionEngine) -> None:
    extensions = set(engine.supported_extensions)
    assert {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".csv",
        ".html",
        ".json",
        ".xml",
        ".txt",
    } <= extensions


def test_convert_text_adds_frontmatter(engine: ConversionEngine, tmp_text: Path) -> None:
    result = engine.convert(tmp_text)
    assert result.markdown.startswith("---")
    metadata, body = split_frontmatter(result.markdown)
    assert metadata["file_type"] == "txt"
    assert metadata["converter"] == "text"
    assert metadata["title"] == "Release Notes"
    assert metadata["word_count"] > 0
    assert "retrieval quality" in body
    assert metadata["converted_at"].endswith("+00:00")


def test_frontmatter_can_be_disabled(engine: ConversionEngine, tmp_text: Path) -> None:
    result = engine.convert(tmp_text, frontmatter=False)
    assert not result.markdown.startswith("---")
    assert result.metadata["file_type"] == "txt"


def test_result_metadata_and_counts(engine: ConversionEngine, tmp_text: Path) -> None:
    result = engine.convert(tmp_text)
    assert result.word_count == len(result.markdown.split())
    assert result.char_count == len(result.markdown)
    payload = result.to_dict()
    assert payload["word_count"] == result.word_count
    assert "markdown" in payload


def test_unknown_extension_raises(engine: ConversionEngine, tmp_path: Path) -> None:
    bogus = tmp_path / "archive.zzz"
    bogus.write_text("data", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError) as excinfo:
        engine.convert(bogus)
    assert ".zzz" in str(excinfo.value)
    assert excinfo.value.supported


def test_missing_file_raises_conversion_error(engine: ConversionEngine, tmp_path: Path) -> None:
    with pytest.raises(ConversionError):
        engine.convert(tmp_path / "does-not-exist.txt")


def test_custom_converter_registration(
    engine: ConversionEngine, upper_converter: object, tmp_path: Path
) -> None:
    file = tmp_path / "sample.up"
    file.write_text("hello world", encoding="utf-8")
    engine.register(upper_converter)  # type: ignore[arg-type]

    assert ".up" in engine.supported_extensions
    result = engine.convert(file)
    metadata, body = split_frontmatter(result.markdown)
    assert "HELLO WORLD" in body
    assert metadata["converter"] == "upper"
    assert metadata["echoed"] is True
    assert metadata["byte_size"] == len("hello world")


def test_extra_metadata_overrides(engine: ConversionEngine, tmp_text: Path) -> None:
    result = engine.convert(tmp_text, metadata={"title": "Custom", "team": "rag"})
    metadata, _ = split_frontmatter(result.markdown)
    assert metadata["title"] == "Custom"
    assert metadata["team"] == "rag"


def test_duplicate_registration_without_overwrite(
    engine: ConversionEngine, upper_converter: object
) -> None:
    engine.register(upper_converter)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        engine.register(upper_converter, overwrite=False)  # type: ignore[arg-type]


def test_unregister(engine: ConversionEngine) -> None:
    removed = engine.unregister(".txt")
    assert removed is not None
    assert removed.name == "text"
    assert ".txt" not in engine.supported_extensions


def test_batch_collects_results_in_order(engine: ConversionEngine, tmp_path: Path) -> None:
    paths = []
    for index in range(6):
        path = tmp_path / f"doc{index}.txt"
        path.write_text(f"Document {index}\n\nBody number {index}.", encoding="utf-8")
        paths.append(path)
    paths.append(tmp_path / "unsupported.zzz")
    (tmp_path / "unsupported.zzz").write_text("x", encoding="utf-8")

    result = engine.convert_batch_sync(paths, max_workers=4)

    assert len(result.results) == 6
    assert result.failures == 1
    assert result.total == 7
    assert result.errors[0].error_type == "UnsupportedFormatError"
    assert result.elapsed_seconds >= 0
    assert [Path(r.source_file).name for r in result.results] == [
        f"doc{index}.txt" for index in range(6)
    ]
    # files_per_second is a float and to_dict round-trips.
    payload = result.to_dict(include_markdown=False)
    assert payload["succeeded"] == 6
    assert "markdown" not in payload["results"][0]


def test_batch_raise_on_error(engine: ConversionEngine, tmp_path: Path) -> None:
    bad = tmp_path / "bad.zzz"
    bad.write_text("x", encoding="utf-8")
    strict = ConversionEngine(raise_on_error=True)
    with pytest.raises(UnsupportedFormatError):
        strict.convert_batch_sync([bad])


def test_batch_progress_callback(engine: ConversionEngine, tmp_path: Path) -> None:
    paths = [tmp_path / f"{i}.txt" for i in range(3)]
    for path in paths:
        path.write_text("hello", encoding="utf-8")
    seen: list[int] = []
    engine.convert_batch_sync(paths, on_progress=lambda _p, done, _t: seen.append(done))
    assert sorted(seen) == [1, 2, 3]


async def test_convert_batch_async(engine: ConversionEngine, tmp_path: Path) -> None:
    paths = [tmp_path / f"{i}.txt" for i in range(4)]
    for path in paths:
        path.write_text("async body", encoding="utf-8")
    result = await engine.convert_batch(paths, max_workers=2)
    assert len(result.results) == 4


def test_batch_empty_input(engine: ConversionEngine) -> None:
    result = engine.convert_batch_sync([])
    assert result.total == 0
    assert result.files_per_second == 0.0


def test_missing_dependency_message_is_actionable(tmp_path: Path) -> None:
    from mdforge.utils.deps import import_optional

    with pytest.raises(MissingDependencyError) as excinfo:
        import_optional("definitely_not_installed_pkg", extra="pdf", feature="to test")
    message = str(excinfo.value)
    assert "mdforge[pdf]" in message
    assert "mdforge[all]" in message


# -- Entry-point plugin discovery -------------------------------------------


class _PluginConverter(BaseConverter):
    """A converter that stands in for a third-party plugin."""

    name = "upper"
    extensions = (".up",)
    description = "Uppercase echo plugin"

    def convert(self, path: Any, **options: Any) -> DocumentResult:
        text = Path(path).read_text(encoding="utf-8").upper()
        return self.build_result(path, text)


class _FakeEntryPoint:
    """Minimal stand-in for :class:`importlib.metadata.EntryPoint`."""

    def __init__(self, name: str, target: object, *, explodes: bool = False) -> None:
        self.name = name
        self._target = target
        self._explodes = explodes

    def load(self) -> object:
        if self._explodes:
            raise ImportError("plugin dependency missing")
        return self._target


def test_load_entry_point_converters_instantiates_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    from mdforge.core import engine as engine_module

    monkeypatch.setattr(
        engine_module,
        "_iter_entry_points",
        lambda _group: [_FakeEntryPoint("upper", _PluginConverter)],
    )
    loaded = engine_module.load_entry_point_converters()
    assert [converter.name for converter in loaded] == ["upper"]
    assert isinstance(loaded[0], _PluginConverter)


def test_load_entry_point_converters_accepts_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    from mdforge.core import engine as engine_module

    instance = _PluginConverter()
    monkeypatch.setattr(
        engine_module,
        "_iter_entry_points",
        lambda _group: [_FakeEntryPoint("upper", instance)],
    )
    assert engine_module.load_entry_point_converters()[0] is instance


def test_engine_registers_discovered_plugins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mdforge.core import engine as engine_module

    monkeypatch.setattr(
        engine_module,
        "_iter_entry_points",
        lambda _group: [_FakeEntryPoint("upper", _PluginConverter)],
    )
    plugin_engine = ConversionEngine()
    assert ".up" in plugin_engine.supported_extensions

    file = tmp_path / "sample.up"
    file.write_text("plugged in", encoding="utf-8")
    assert "PLUGGED IN" in plugin_engine.convert(file).markdown


def test_engine_can_skip_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    from mdforge.core import engine as engine_module

    def _fail(_group: str) -> list[_FakeEntryPoint]:
        raise AssertionError("plugin discovery should not run when load_plugins=False")

    monkeypatch.setattr(engine_module, "_iter_entry_points", _fail)
    plugin_engine = ConversionEngine(load_plugins=False)
    assert ".txt" in plugin_engine.supported_extensions


def test_broken_or_invalid_entry_points_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    from mdforge.core import engine as engine_module

    monkeypatch.setattr(
        engine_module,
        "_iter_entry_points",
        lambda _group: [
            _FakeEntryPoint("broken", object, explodes=True),
            _FakeEntryPoint("not-a-converter", "just a string"),
            _FakeEntryPoint("upper", _PluginConverter),
        ],
    )
    loaded = engine_module.load_entry_point_converters()
    assert [converter.name for converter in loaded] == ["upper"]
