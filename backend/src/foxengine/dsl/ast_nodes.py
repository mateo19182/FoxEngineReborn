from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Pred:
    field: str
    value: str


@dataclass
class And:
    parts: list[Expr]


@dataclass
class Or:
    parts: list[Expr]


@dataclass
class Not:
    inner: Expr


Expr = Pred | And | Or | Not
