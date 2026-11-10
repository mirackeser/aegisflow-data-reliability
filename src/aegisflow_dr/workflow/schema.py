# SPDX-License-Identifier: Apache-2.0
"""Separate queue database; never adopt or migrate an evidence database."""
from contextlib import closing
from functools import lru_cache
import os
from pathlib import Path
import sqlite3

from .model import QueueError

APPLICATION_ID = 1095124052
VERSION = 1


def ddl():
    sql = '''
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
 manifest BLOB NOT NULL, sha256 TEXT NOT NULL
);
CREATE TABLE projections (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), status TEXT NOT NULL,
 content BLOB NOT NULL, sha256 TEXT NOT NULL
);
CREATE INDEX active_jobs ON projections(status,job_id);
CREATE TABLE events (
 job_id TEXT NOT NULL REFERENCES jobs(id), revision INTEGER NOT NULL,
 content BLOB NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(job_id,revision)
);
'''
    for table in ('jobs', 'events'):
        for operation in ('UPDATE', 'DELETE'):
            sql += (f'CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} '
                    "BEGIN SELECT RAISE(ABORT,'immutable queue record'); END;\n")
    return sql


def signature(connection):
    return tuple(connection.execute('SELECT type,name,sql FROM sqlite_master '
                                    'WHERE sql IS NOT NULL ORDER BY type,name'))


@lru_cache(maxsize=1)
def expected_schema():
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.executescript(ddl())
        return signature(connection)


def validate(connection):
    if (connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
            or connection.execute('PRAGMA user_version').fetchone()[0] != VERSION
            or signature(connection) != expected_schema()):
        raise QueueError('Unsupported queue schema')


def initialize(path: Path):
    path = Path(path)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('PRAGMA synchronous=FULL')
        connection.executescript('BEGIN IMMEDIATE;\n' + ddl()
                                 + f'PRAGMA application_id={APPLICATION_ID};\n'
                                 + f'PRAGMA user_version={VERSION};\nCOMMIT;')
