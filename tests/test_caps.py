"""Unit tests for resource caps, the cost estimate, and env resolution (ADR-010)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from common_file_generator.web.caps import Caps, estimate_cost  # noqa: E402


def test_defaults_are_generous() -> None:
    caps = Caps()
    assert caps.max_slides == 200
    assert caps.max_cost == 2_000_000
    assert caps.gen_timeout_s == 30
    assert caps.max_output_bytes == 50 * 1024 * 1024
    # ADR-013 concurrency cap.
    assert caps.max_concurrent == 8
    assert caps.acquire_timeout_s == 5


def test_from_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("COMMON_FILE_GEN_MAX_SLIDES", "7")
    monkeypatch.setenv("COMMON_FILE_GEN_GEN_TIMEOUT_S", "3")
    monkeypatch.setenv("COMMON_FILE_GEN_MAX_OUTPUT_MB", "2")
    monkeypatch.setenv("COMMON_FILE_GEN_MAX_CONCURRENT", "2")
    monkeypatch.setenv("COMMON_FILE_GEN_ACQUIRE_TIMEOUT_S", "1")
    caps = Caps.from_env()
    assert caps.max_slides == 7
    assert caps.gen_timeout_s == 3
    assert caps.max_output_bytes == 2 * 1024 * 1024
    assert caps.max_concurrent == 2
    assert caps.acquire_timeout_s == 1
    # An untouched var keeps its default.
    assert caps.max_sections == 200


def test_from_env_ignores_invalid_and_non_positive(monkeypatch) -> None:
    monkeypatch.setenv("COMMON_FILE_GEN_MAX_SLIDES", "not-a-number")
    monkeypatch.setenv("COMMON_FILE_GEN_MAX_SECTIONS", "0")
    monkeypatch.setenv("COMMON_FILE_GEN_MAX_SHEETS", "-5")
    caps = Caps.from_env()
    assert caps.max_slides == 200
    assert caps.max_sections == 200
    assert caps.max_sheets == 100


def test_cost_deck_is_slides() -> None:
    assert estimate_cost("deck", {"slides": 12}) == 12


def test_cost_doc_multiplies_sections_by_blocks() -> None:
    assert estimate_cost("doc", {"sections": 4, "blocks_per_section": 6}) == 24


def test_cost_doc_uses_complexity_default_when_blocks_omitted() -> None:
    # standard -> 3 blocks/section default.
    assert estimate_cost("doc", {"sections": 5, "complexity": "standard"}) == 15
    # maximum -> 5 blocks/section default.
    assert estimate_cost("doc", {"sections": 5, "complexity": "maximum"}) == 25


def test_cost_sheet_multiplies_sheets_tables_rows_cols() -> None:
    # complex -> 2 tables/sheet default; explicit rows/cols.
    cost = estimate_cost(
        "sheet", {"sheets": 2, "rows": 100, "cols": 10, "complexity": "complex"}
    )
    assert cost == 2 * 2 * 100 * 10


def test_cost_sheet_uses_defaults_when_rows_cols_omitted() -> None:
    # standard -> 1 table/sheet, 10 rows default, 5 cols worst-case default.
    cost = estimate_cost("sheet", {"sheets": 3, "complexity": "standard"})
    assert cost == 3 * 1 * 10 * 5


def test_cost_unknown_kind_is_zero() -> None:
    assert estimate_cost("mystery", {"slides": 99}) == 0


# --- Drift guards: the cost estimate mirrors generator/complexity internals.
# These fail if a generator changes its per-complexity density without updating
# caps.py, which would silently desync the composite-cost budget.


def test_default_blocks_match_generator_sources() -> None:
    from common_file_generator.core import Complexity
    from common_file_generator.generators import docx, markdown, pdf
    from common_file_generator.web import caps

    for module in (docx, pdf, markdown):
        assert module._BLOCKS_PER_SECTION == caps._DEFAULT_BLOCKS, module.__name__
    # Sanity: every complexity level is covered.
    assert set(caps._DEFAULT_BLOCKS) == set(Complexity)


def test_default_sheet_dims_match_complexity_source() -> None:
    from common_file_generator.core import Complexity
    from common_file_generator.core.complexity import sheet_feature_pool
    from common_file_generator.web import caps

    for level in Complexity:
        features = sheet_feature_pool(level)
        assert caps._DEFAULT_SHEET_ROWS[level] == features.rows_per_table, level
        assert caps._TABLES_PER_SHEET[level] == features.tables_per_sheet, level
