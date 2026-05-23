import unittest

from foxengine.dsl.parser import parse_dsl
from foxengine.dsl.sql import CompileError, compile_expr


class TestDslExtras(unittest.TestCase):
    def _compile(self, dsl: str):
        return compile_expr(parse_dsl(dsl), {})

    def test_extras_exact_any_value(self):
        cw = self._compile("extras:foo")
        self.assertIn("mapValues(extras)", cw.sql)
        self.assertIn("arrayExists", cw.sql)
        self.assertEqual(cw.parameters["ev_0"], "foo")
        self.assertIn("v = {ev_0:String}", cw.sql)

    def test_extras_substring_wildcard(self):
        cw = self._compile("extras:*bar*")
        self.assertIn("mapValues(extras)", cw.sql)
        self.assertEqual(cw.parameters["ev_0"], "bar")
        self.assertIn("position(v, {ev_0:String}) > 0", cw.sql)

    def test_extras_keyed_case_insensitive(self):
        cw = self._compile("extras.my_col:baz")
        self.assertIn("mapKeys(extras)", cw.sql)
        self.assertIn("mapValues(extras)", cw.sql)
        self.assertIn("lowerUTF8(k)", cw.sql)
        self.assertEqual(cw.parameters["ek_0"], "my_col")
        self.assertEqual(cw.parameters["ev_0"], "baz")

    def test_unknown_field_raises(self):
        with self.assertRaises(CompileError) as ctx:
            self._compile("unknown_field:foo")
        self.assertIn("unknown field", str(ctx.exception))

    def test_identity_key_field_rejected(self):
        with self.assertRaises(CompileError) as ctx:
            self._compile("identity_key:foo")
        self.assertIn("unknown field", str(ctx.exception))

    def test_phone_uses_lead_identities(self):
        cw = self._compile("phone:+34123456789")
        self.assertIn("lead_identities", cw.sql)
        self.assertIn("identity_kind = 'phone'", cw.sql)
        self.assertEqual(cw.parameters["iv_0"], "+34123456789")


if __name__ == "__main__":
    unittest.main()
