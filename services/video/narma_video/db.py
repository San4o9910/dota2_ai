from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from .config import database_url

@contextmanager
def database():
    with psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=10) as connection:
        yield connection

def migrate():
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(643847204)")
        connection.execute("CREATE TABLE IF NOT EXISTS video_schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        for path in sorted((Path(__file__).parent.parent / "migrations").glob("*.sql")):
            if not connection.execute("SELECT 1 FROM video_schema_migrations WHERE name=%s", (path.name,)).fetchone():
                connection.execute(path.read_text())
                connection.execute("INSERT INTO video_schema_migrations(name) VALUES (%s)", (path.name,))

if __name__ == "__main__":
    migrate()
