# TODO

- **SQLAlchemy 2.1+**: When stable, check default `postgresql://` → psycopg3 ([sqlalchemy#13010](https://github.com/sqlalchemy/sqlalchemy/issues/13010)); then drop Alembic `postgresql://` → `postgresql+psycopg://` rewrite in `backend/alembic/env.py` if redundant. Async URL stays `postgresql+asyncpg://`.

- more encryption?

- integrate ultimateparser...

- test data 
    - /mnt/data/stuff
    - /mnt/data/hmm/ultimateparser
