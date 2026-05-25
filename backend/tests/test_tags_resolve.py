import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from foxengine.dsl.parser import parse_dsl
from foxengine.services.tags_resolve import (
    TagResolveError,
    validate_tag_references,
    walk_positive_tag_preds,
)

U1 = UUID("11111111-1111-1111-1111-111111111111")


class TestWalkPositiveTagPreds(unittest.TestCase):
    def test_not_tag_excluded(self) -> None:
        ast = parse_dsl("NOT tag:Foo")
        self.assertEqual(walk_positive_tag_preds(ast), [])

    def test_positive_tag_included(self) -> None:
        ast = parse_dsl("tag:Foo AND email:a@b.com")
        preds = walk_positive_tag_preds(ast)
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0].field, "tag")
        self.assertEqual(preds[0].value, "Foo")


class TestValidateTagReferences(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_tag_raises(self) -> None:
        session = AsyncMock()
        ast = parse_dsl("tag:Missing")
        with self.assertRaises(TagResolveError) as ctx:
            await validate_tag_references(session, ast, {("tag", "Missing"): []})
        self.assertEqual(str(ctx.exception), "tag does not exist: Missing")
        session.execute.assert_not_awaited()

    async def test_known_tag_ok(self) -> None:
        session = AsyncMock()
        ast = parse_dsl("tag:Foo")
        await validate_tag_references(session, ast, {("tag", "Foo"): [U1]})
        session.execute.assert_not_awaited()

    async def test_not_unknown_tag_ok(self) -> None:
        session = AsyncMock()
        ast = parse_dsl("NOT tag:Missing")
        await validate_tag_references(session, ast, {("tag", "Missing"): []})

    async def test_unknown_family_raises(self) -> None:
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result)
        ast = parse_dsl("tag.family:LEAK")
        with self.assertRaises(TagResolveError) as ctx:
            await validate_tag_references(session, ast, {("tag.family", "LEAK"): []})
        self.assertEqual(str(ctx.exception), "tag family does not exist: LEAK")

    async def test_existing_family_without_tags_ok(self) -> None:
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = ["LEAK"]
        session.execute = AsyncMock(return_value=result)
        ast = parse_dsl("tag.family:LEAK")
        await validate_tag_references(session, ast, {("tag.family", "LEAK"): []})


if __name__ == "__main__":
    unittest.main()
