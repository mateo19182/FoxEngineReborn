import unittest
from unittest import mock
from uuid import UUID

from foxengine.dsl.sql import CompiledLeadsQuery
from foxengine.services.job_queries import (
    attach_tag_ids,
    fetch_lead_tag_ids,
    leads_count_sql,
    leads_select_sql,
)

U1 = UUID("11111111-1111-1111-1111-111111111111")


class TestLeadsCountSql(unittest.TestCase):
    def test_tag_only_count_skips_leads_join(self) -> None:
        compiled = CompiledLeadsQuery(
            leads_where="(1 = 1)",
            parameters={},
            tag_keys_select="SELECT batch_id, row_in_batch FROM lead_tags WHERE 1 = 0",
        )
        sql = leads_count_sql(compiled)
        self.assertIn(") AS tagged\nWHERE (1 = 1)", sql)
        self.assertNotIn("INNER JOIN leads", sql)

    def test_tag_and_email_count_keeps_leads_join(self) -> None:
        compiled = CompiledLeadsQuery(
            leads_where="(email = {v_0:String})",
            parameters={},
            tag_keys_select="SELECT batch_id, row_in_batch FROM lead_tags WHERE 1 = 0",
        )
        sql = leads_count_sql(compiled)
        self.assertIn("INNER JOIN leads", sql)


class TestLeadsSelectSql(unittest.TestCase):
    def test_tag_first_select_has_no_inline_tag_aggregation(self) -> None:
        compiled = CompiledLeadsQuery(
            leads_where="1 = 1",
            parameters={},
            tag_keys_select=(
                f"SELECT batch_id, row_in_batch FROM lead_tags WHERE tag_id = toUUID('{U1}')"
            ),
        )
        sql = leads_select_sql(compiled, limit=50)
        self.assertIn("EXCEPT (batch_id, row_in_batch, extras)", sql)
        self.assertNotIn("groupUniqArray", sql)
        self.assertNotIn("LEFT ANY JOIN", sql)


class TestAttachTagIds(unittest.TestCase):
    def test_fills_empty_when_missing(self) -> None:
        rows = [{"batch_id": U1, "row_in_batch": 1}]
        attach_tag_ids(rows, {})
        self.assertEqual(rows[0]["tag_ids"], [])


class TestFetchLeadTagIds(unittest.IsolatedAsyncioTestCase):
    async def test_empty_keys_skips_query(self) -> None:
        ch = mock.AsyncMock()
        out = await fetch_lead_tag_ids(ch, [])
        self.assertEqual(out, {})
        ch.query.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
