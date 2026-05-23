from alembic import op
from sqlalchemy import inspect


def table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table(table):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def index_exists(table: str, index: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table(table):
        return False
    return index in {i["name"] for i in insp.get_indexes(table)}


def foreign_key_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table(table):
        return False
    return name in {fk.get("name") for fk in insp.get_foreign_keys(table) if fk.get("name")}
