import unittest
from uuid import UUID

from foxengine.dsl.parser import parse_dsl
from foxengine.dsl.sql import CompiledLeadsQuery, compile_leads_query
from foxengine.services.job_queries import leads_count_sql

U1 = UUID("11111111-1111-1111-1111-111111111111")
U2 = UUID("22222222-2222-2222-2222-222222222222")
U3 = UUID("33333333-3333-3333-3333-333333333333")


class TestDslTagFirst(unittest.TestCase):
    def _compile(self, dsl: str, tag_map: dict | None = None):
        return compile_leads_query(parse_dsl(dsl), tag_map or {})

    def test_single_tag_uses_tag_first(self):
        cw = self._compile("tag:Foo", {("tag", "Foo"): [U1]})
        self.assertIsNotNone(cw.tag_keys_select)
        self.assertIn("SELECT DISTINCT batch_id, row_in_batch", cw.tag_keys_select)
        self.assertIn("FROM lead_tags", cw.tag_keys_select)
        self.assertIn("tag_id", cw.tag_keys_select)
        self.assertNotIn("IN (SELECT", cw.tag_keys_select or "")
        self.assertEqual(cw.leads_where, "1 = 1")

    def test_tag_or_merged_into_one_in(self):
        cw = self._compile("tag:Foo OR tag:Bar", {("tag", "Foo"): [U1], ("tag", "Bar"): [U2]})
        self.assertIsNotNone(cw.tag_keys_select)
        self.assertIn("tag_id IN", cw.tag_keys_select)
        self.assertEqual(cw.parameters["tu_0"], str(U1))
        self.assertEqual(cw.parameters["tu_1"], str(U2))

    def test_tag_and_uses_group_by_having(self):
        cw = self._compile("tag:Foo AND tag:Bar", {("tag", "Foo"): [U1], ("tag", "Bar"): [U2]})
        self.assertIsNotNone(cw.tag_keys_select)
        self.assertIn("GROUP BY batch_id, row_in_batch", cw.tag_keys_select)
        self.assertIn("HAVING", cw.tag_keys_select)
        self.assertIn("countIf", cw.tag_keys_select)

    def test_tag_and_non_tag_splits_plan(self):
        cw = self._compile(
            "tag:Foo AND email:john@example.com",
            {("tag", "Foo"): [U1]},
        )
        self.assertIsNotNone(cw.tag_keys_select)
        self.assertIn("lead_identities", cw.leads_where)
        self.assertNotIn("lead_tags", cw.leads_where)

    def test_mixed_tag_or_falls_back(self):
        cw = self._compile(
            "tag:Foo OR email:john@example.com",
            {("tag", "Foo"): [U1]},
        )
        self.assertIsNone(cw.tag_keys_select)
        self.assertIn("IN (SELECT", cw.leads_where)

    def test_tag_family_multi_uuid_in(self):
        cw = self._compile("tag.family:LEAK", {("tag.family", "LEAK"): [U1, U2, U3]})
        self.assertIsNotNone(cw.tag_keys_select)
        self.assertIn("tag_id IN", cw.tag_keys_select)

    def test_unknown_tag_empty_keys(self):
        cw = self._compile("tag:Missing", {})
        self.assertIsNotNone(cw.tag_keys_select)
        self.assertIn("1 = 0", cw.tag_keys_select)

    def test_not_tag_with_other_pred_falls_back(self):
        cw = self._compile("NOT tag:Foo AND email:a@b.com", {("tag", "Foo"): [U1]})
        self.assertIsNone(cw.tag_keys_select)
        self.assertIn("NOT", cw.leads_where)
        self.assertIn("lead_tags", cw.leads_where)

    def test_tag_and_not_other_tag_uses_tag_first(self):
        cw = self._compile(
            "tag:Foo AND NOT tag:Bar",
            {("tag", "Foo"): [U1], ("tag", "Bar"): [U2]},
        )
        self.assertIsNotNone(cw.tag_keys_select)
        self.assertIn("NOT", cw.leads_where)

    def test_tag_count_keeps_visibility_clause_parentheses_balanced(self):
        compiled = CompiledLeadsQuery(
            leads_where="""(1 = 1) AND batch_id NOT IN (
    SELECT batch_id
    FROM batch_visibility
    GROUP BY batch_id
    HAVING argMax(visible, version) = 0
)""",
            parameters={},
            tag_keys_select="SELECT DISTINCT batch_id, row_in_batch FROM lead_tags WHERE tag_id = toUUID({tu_0:String})",
        )
        sql = leads_count_sql(compiled)
        self.assertIn("WHERE (1 = 1) AND batch_id NOT IN", sql)
        self.assertNotIn("WHERE 1 = 1) AND", sql)


if __name__ == "__main__":
    unittest.main()
