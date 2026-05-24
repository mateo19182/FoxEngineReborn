"""SQL shape tests for ClickHouse lead queries."""

from foxengine.services.job_queries import (
    CompiledLeadsQuery,
    KeysetCursor,
    leads_bounded_count_sql,
    leads_count_sql,
    leads_select_sql,
)


def test_tag_query_counts_on_lead_tags() -> None:
    tag_rows_sql = (
        "SELECT batch_id, row_in_batch, max(ingest_ts) AS ingest_ts "
        "FROM lead_tags WHERE tag_id = toUUID({tu_0:String}) "
        "GROUP BY batch_id, row_in_batch"
    )
    query = CompiledLeadsQuery(
        leads_where_sql="(1 = 1)",
        parameters={"tu_0": "00000000-0000-0000-0000-000000000001"},
        tag_keys_rows_sql=tag_rows_sql,
    )
    count_sql = leads_count_sql(query)
    assert "FROM lead_tags" in count_sql
    assert "FROM leads" not in count_sql


def test_bounded_count_caps_scan() -> None:
    query = CompiledLeadsQuery(
        leads_where_sql="(country = {v_0:String})",
        parameters={"v_0": "US"},
    )
    sql = leads_bounded_count_sql(query, cap=10_000)
    assert "LIMIT 10001" in sql


def test_tag_query_limits_on_lead_tags_before_wide_read() -> None:
    tag_rows_sql = (
        "SELECT batch_id, row_in_batch, max(ingest_ts) AS ingest_ts "
        "FROM lead_tags WHERE tag_id = toUUID({tu_0:String}) "
        "GROUP BY batch_id, row_in_batch"
    )
    sql = leads_select_sql(
        "(1 = 1)",
        limit=50,
        tag_keys_rows_sql=tag_rows_sql,
    )
    assert "EXCEPT (batch_id, row_in_batch, extras)" in sql
    assert "FROM lead_tags" in sql
    assert "ORDER BY ingest_ts DESC" in sql
    assert "LIMIT 50" in sql


def test_export_keyset_uses_cursor_not_offset() -> None:
    tag_rows_sql = (
        "SELECT batch_id, row_in_batch, max(ingest_ts) AS ingest_ts "
        "FROM lead_tags WHERE tag_id = toUUID({tu_0:String}) "
        "GROUP BY batch_id, row_in_batch"
    )
    cursor = KeysetCursor(
        ingest_ts="2024-06-01 12:00:00",
        batch_id="00000000-0000-0000-0000-000000000001",
        row_in_batch=42,
    )
    sql = leads_select_sql(
        "(1 = 1)",
        limit=50_000,
        tag_keys_rows_sql=tag_rows_sql,
        cursor=cursor,
    )
    assert "cur_ts" in sql
    assert "cur_bid" in sql
    assert "cur_rib" in sql
    assert "OFFSET" not in sql


def test_plain_query_excludes_extras() -> None:
    sql = leads_select_sql("email_norm = {v_0:String}", limit=10)
    assert "EXCEPT (batch_id, row_in_batch, extras)" in sql
