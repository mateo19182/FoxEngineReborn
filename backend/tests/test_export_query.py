import unittest
from datetime import UTC, datetime
from uuid import UUID

from foxengine.dsl.sql import CompiledLeadsQuery
from foxengine.services.export_query import (
    ExportCursor,
    export_s3_url,
    leads_export_batch_sql,
    leads_export_s3_insert_sql,
    normalize_export_columns,
)


class TestExportQuery(unittest.TestCase):
    def test_keyset_clause_omitted_without_cursor(self) -> None:
        compiled = CompiledLeadsQuery(
            leads_where="email = {v:String}",
            parameters={"v": "a@b.c"},
        )
        sql = leads_export_batch_sql(compiled, limit=100, cursor=None)
        self.assertNotIn("cursor_ts", sql)
        self.assertIn("ORDER BY l.ingest_ts DESC", sql)
        self.assertIn("LIMIT 100", sql)

    def test_batch_sql_uses_selected_columns(self) -> None:
        compiled = CompiledLeadsQuery(leads_where="1 = 1", parameters={})
        sql = leads_export_batch_sql(
            compiled,
            limit=100,
            columns=["email", "username"],
        )
        self.assertIn("SELECT l.email, l.username", sql)
        self.assertNotIn("l.password", sql)

    def test_keyset_clause_with_cursor(self) -> None:
        compiled = CompiledLeadsQuery(leads_where="1 = 1", parameters={})
        cur = ExportCursor(
            ingest_ts=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
            batch_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            row_in_batch=7,
        )
        sql = leads_export_batch_sql(compiled, limit=50, cursor=cur)
        self.assertIn("{cursor_ts:DateTime}", sql)
        self.assertIn("{cursor_bid:UUID}", sql)
        self.assertIn("{cursor_rib:UInt32}", sql)

    def test_s3_insert_sql(self) -> None:
        compiled = CompiledLeadsQuery(leads_where="1 = 1", parameters={})
        sql = leads_export_s3_insert_sql(
            compiled,
            s3_url="http://rustfs:9000/exports/job/result.csv",
            access_key="ak",
            secret_key="sk",
            ch_format="CSVWithNames",
            row_cap=1000,
        )
        self.assertIn("INSERT INTO FUNCTION s3(", sql)
        self.assertIn("CSVWithNames", sql)
        self.assertIn("LIMIT 1000", sql)
        self.assertNotIn("tag_ids", sql)

    def test_s3_insert_sql_uses_selected_columns(self) -> None:
        compiled = CompiledLeadsQuery(leads_where="1 = 1", parameters={})
        sql = leads_export_s3_insert_sql(
            compiled,
            s3_url="http://rustfs:9000/exports/job/result.csv",
            access_key="ak",
            secret_key="sk",
            ch_format="CSVWithNames",
            row_cap=1000,
            columns=["email", "username"],
        )
        self.assertIn("SELECT l.email, l.username", sql)
        self.assertNotIn("l.password", sql)

    def test_normalize_export_columns_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            normalize_export_columns(["email", "not_a_column"])

    def test_export_s3_url(self) -> None:
        self.assertEqual(
            export_s3_url("http://localhost:9000/", "exports", "exports/uuid/result.csv"),
            "http://localhost:9000/exports/exports/uuid/result.csv",
        )

    def test_cursor_checkpoint_roundtrip(self) -> None:
        cur = ExportCursor(
            ingest_ts=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            batch_id=UUID("11111111-1111-1111-1111-111111111111"),
            row_in_batch=42,
        )
        restored = ExportCursor.from_checkpoint(cur.to_checkpoint())
        assert restored is not None
        self.assertEqual(restored.batch_id, cur.batch_id)
        self.assertEqual(restored.row_in_batch, cur.row_in_batch)


if __name__ == "__main__":
    unittest.main()
