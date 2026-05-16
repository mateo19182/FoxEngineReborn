import psycopg
from procrastinate import App
from procrastinate.schema import SchemaManager
from procrastinate.sync_psycopg_connector import SyncPsycopgConnector

from foxengine.config import get_settings


def ensure_procrastinate_schema() -> None:
    ci = get_settings().database_url_sync
    with psycopg.connect(ci) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'procrastinate_jobs'"
            )
            if cur.fetchone():
                return
    app = App(connector=SyncPsycopgConnector(conninfo=ci))
    with app.open():
        SchemaManager(app.connector).apply_schema()
