"""Tests for tag-only DSL compilation."""

from uuid import UUID

from foxengine.dsl.parser import parse_dsl
from foxengine.dsl.sql import compile_tag_keys_rows_sql, is_tag_only_expr


def test_is_tag_only_single_tag() -> None:
    assert is_tag_only_expr(parse_dsl("tag:testbig"))


def test_is_tag_only_rejects_not() -> None:
    assert not is_tag_only_expr(parse_dsl("NOT tag:testbig"))


def test_is_tag_only_rejects_mixed() -> None:
    assert not is_tag_only_expr(parse_dsl("tag:testbig AND country:US"))


def test_compile_single_tag_rows_sql() -> None:
    tag_id = UUID("00000000-0000-0000-0000-0000000000aa")
    ast = parse_dsl("tag:testbig")
    compiled = compile_tag_keys_rows_sql(ast, {("tag", "testbig"): [tag_id]})
    assert compiled is not None
    assert "FROM lead_tags" in compiled.sql
    assert "GROUP BY batch_id, row_in_batch" in compiled.sql
    assert compiled.parameters["tu_0"] == str(tag_id)
