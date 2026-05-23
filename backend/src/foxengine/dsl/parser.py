from typing import cast

from lark import Lark, Token, Transformer, v_args

from foxengine.dsl.ast_nodes import And, Expr, Not, Or, Pred

_MATCH_ALL = And([])

GRAMMAR = r"""
?start: expr | match_all

?match_all:

?expr: orexpr

?orexpr: andexpr (OR andexpr)*
?andexpr: notexpr (AND notexpr)*
?notexpr: NOT notexpr -> not_
        | atom

atom: "(" expr ")"
    | predicate

predicate: PRED_FIELD ":" PRED_VALUE

OR: "OR"
AND: "AND"
NOT: "NOT"

PRED_FIELD: /[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*/i
PRED_VALUE: /[^\s()]+/

%import common.WS
%ignore WS
"""


class Tree(Transformer[Token, Expr]):
    def match_all(self, _items: list) -> Expr:
        return _MATCH_ALL

    def orexpr(self, items: list) -> Expr:
        parts = [items[i] for i in range(0, len(items), 2)]
        if len(parts) == 1:
            return parts[0]  # type: ignore[return-value]
        return Or(parts)  # type: ignore[arg-type]

    def andexpr(self, items: list) -> Expr:
        parts = [items[i] for i in range(0, len(items), 2)]
        if len(parts) == 1:
            return parts[0]  # type: ignore[return-value]
        return And(parts)  # type: ignore[arg-type]

    @v_args(inline=True)
    def not_(self, _not: Token, inner: Expr) -> Expr:
        return Not(inner)

    def atom(self, items: list) -> Expr:
        if len(items) == 1:
            return cast(Expr, items[0])
        _, inner, _ = items
        return cast(Expr, inner)

    @v_args(inline=True)
    def predicate(self, field: Token, val: Token) -> Expr:
        return Pred(str(field).lower(), str(val))


_parser = Lark(GRAMMAR, parser="lalr", transformer=Tree())


def parse_dsl(text: str) -> Expr:
    if not text.strip():
        return _MATCH_ALL
    return cast(Expr, _parser.parse(text.strip()))
