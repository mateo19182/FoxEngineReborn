import unittest

from foxengine.services.identity import identity_facet_tuples
from foxengine.services.related_rows import identity_facets


class IdentityFacetTuplesTests(unittest.TestCase):
    def test_all_present(self) -> None:
        facets = identity_facet_tuples("+34123456789", "a@b.com", "Alice", "ID1")
        self.assertEqual(
            facets,
            [
                ("email", "a@b.com"),
                ("phone", "+34123456789"),
                ("username", "alice"),
                ("id_card", "ID1"),
            ],
        )

    def test_skips_empty(self) -> None:
        self.assertEqual(identity_facet_tuples("", "", "  ", ""), [])

    def test_related_row_facet_keys_match_identities(self) -> None:
        row = {
            "phone_norm": "+34123456789",
            "email_norm": "a@b.com",
            "username": "Alice",
            "id_card": "ID1",
        }
        self.assertEqual(
            identity_facets(row),
            ["email:a@b.com", "phone:+34123456789", "username:alice", "id_card:ID1"],
        )


if __name__ == "__main__":
    unittest.main()
