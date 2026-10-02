import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: Path, *, read_only: bool = True) -> sqlite3.Connection:
    """Open a connection with row access by column name.

    The API only reads, so request connections are opened read-only: a bug in
    a handler can't corrupt the data, and SQLite allows any number of readers.
    """
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
