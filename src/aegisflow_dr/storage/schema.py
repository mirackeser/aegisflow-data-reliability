# SPDX-License-Identifier: Apache-2.0
"""Explicit, additive schema evolution; no implicit migration on open."""
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import sqlite3

APPLICATION_ID = 1095124051
SCHEMA_VERSION = 2

def legacy_schema_sql() -> str:
    ddl = '''
CREATE TABLE incidents (
 id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
 manifest BLOB NOT NULL, manifest_sha256 TEXT NOT NULL
);
CREATE TABLE evidence (
 incident_id TEXT NOT NULL REFERENCES incidents(id), id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('source_csv','diagnostic_report')),
 content BLOB NOT NULL, sha256 TEXT NOT NULL,
 PRIMARY KEY(incident_id,id), UNIQUE(incident_id,kind)
);
CREATE TABLE claims (
 incident_id TEXT NOT NULL REFERENCES incidents(id), id TEXT NOT NULL,
 content BLOB NOT NULL, PRIMARY KEY(incident_id,id)
);
CREATE TABLE claim_evidence (
 incident_id TEXT NOT NULL, claim_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
 PRIMARY KEY(incident_id,claim_id,evidence_id),
 FOREIGN KEY(incident_id,claim_id) REFERENCES claims(incident_id,id),
 FOREIGN KEY(incident_id,evidence_id) REFERENCES evidence(incident_id,id)
);
CREATE TABLE events (
 incident_id TEXT NOT NULL REFERENCES incidents(id), revision INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('RECEIVED','DIAGNOSED','CLOSED')),
 content BLOB NOT NULL, previous_sha256 TEXT, sha256 TEXT NOT NULL,
 PRIMARY KEY(incident_id,revision)
);
'''
    for table in ('incidents', 'evidence', 'claims', 'claim_evidence', 'events'):
        for operation in ('UPDATE', 'DELETE'):
            ddl += (f'CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} '
                    f"ON {table} BEGIN SELECT RAISE(ABORT,'immutable record'); END;\n")
    return ddl


def run_schema_sql() -> str:
    ddl = """
CREATE TABLE investigation_runs (
 id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
 request_key TEXT NOT NULL, manifest BLOB NOT NULL, manifest_sha256 TEXT NOT NULL,
 trace BLOB NOT NULL, UNIQUE(incident_id,request_key)
);
CREATE TABLE run_artifacts (
 run_id TEXT NOT NULL REFERENCES investigation_runs(id), name TEXT NOT NULL,
 content BLOB NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(run_id,name)
);
"""
    for table in ('investigation_runs', 'run_artifacts'):
        for operation in ('UPDATE', 'DELETE'):
            ddl += (f'CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} '
                    f"ON {table} BEGIN SELECT RAISE(ABORT,'immutable record'); END;\n")
    return ddl


def schema_sql(version=SCHEMA_VERSION) -> str:
    if version not in (1, 2):
        raise ValueError('Unsupported schema version')
    return legacy_schema_sql() + (run_schema_sql() if version == 2 else '')


def signature(connection) -> tuple:
    return tuple(connection.execute("SELECT type,name,sql FROM sqlite_master "
                                    "WHERE sql IS NOT NULL ORDER BY type,name"))


@lru_cache(maxsize=2)
def expected_schema(version: int) -> tuple:
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.executescript(schema_sql(version))
        return signature(connection)


def validate_schema(connection) -> int:
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if (connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
            or version not in (1, 2) or signature(connection) != expected_schema(version)):
        raise ValueError('Unsupported store schema')
    return version


def migrate(path: Path) -> None:
    """Upgrade a verified v1 store atomically; reject unknown layouts unchanged."""
    uri = Path(path).resolve().as_uri() + '?mode=rw'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('BEGIN IMMEDIATE')
        try:
            version = validate_schema(connection)
            if version == 1:
                # executescript commits implicitly; execute complete statements
                # individually so both DDL and user_version remain atomic.
                statement = ''
                for line in run_schema_sql().splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        connection.execute(statement)
                        statement = ''
                if statement.strip():
                    raise ValueError('Incomplete migration statement')
                connection.execute('PRAGMA user_version=2')
                validate_schema(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
