# SPDX-License-Identifier: Apache-2.0
"""Explicit pager recovery without changing the evidence store's read-only API."""
from contextlib import closing
from pathlib import Path
import sqlite3

from .schema import validate_schema


def recover(path: Path) -> None:
    """Roll back a hot SQLite journal, verify layout/pages, never create a file.

    This repairs interrupted SQLite transactions, not corrupted application data.
    Readers continue to validate retained evidence with the existing store API.
    """
    uri = Path(path).resolve().as_uri() + '?mode=rw'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('BEGIN IMMEDIATE')
        try:
            validate_schema(connection)
            if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('Evidence database integrity check failed')
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
