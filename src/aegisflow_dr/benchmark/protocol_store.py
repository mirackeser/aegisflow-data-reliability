# SPDX-License-Identifier: Apache-2.0
"""Local immutable evaluation registration and append-only result history."""
from contextlib import closing, contextmanager
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from uuid import UUID

from .core import BenchmarkError, canonical, parse
from .quality import validate_protocol, evaluate_quality


@contextmanager
def database(path):
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw',uri=True,timeout=5)) as connection:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                yield connection
    except BenchmarkError:
        raise
    except (sqlite3.Error,OSError,ValueError,TypeError):
        raise BenchmarkError('Evaluation registry unavailable') from None


def register_protocol(path, protocol):
    """Create exclusively; the trusted host approves provenance and candidate thresholds."""
    value=validate_protocol(protocol)
    normalized=canonical(value)
    try:
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(descriptor)
    except (OSError,TypeError,ValueError):
        raise BenchmarkError('New evaluation registry required') from None
    with database(path) as connection:
        connection.execute('CREATE TABLE registration (id INTEGER PRIMARY KEY CHECK(id=1), protocol BLOB NOT NULL)')
        connection.execute('CREATE TABLE evaluations (sequence INTEGER PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, predictions_sha256 TEXT NOT NULL, result BLOB NOT NULL)')
        connection.execute('INSERT INTO registration VALUES (1,?)',(normalized,))
        for table in ('registration','evaluations'):
            for action in ('UPDATE','DELETE'):
                connection.execute(f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable evaluation history'); END")
    return sha256(normalized).hexdigest()


class EvaluationRegistry:
    def __init__(self,path,*,expected_protocol_sha256):
        self.path=Path(path)
        self.expected=expected_protocol_sha256
        with database(self.path) as connection:
            self._protocol(connection)

    def _protocol(self,connection):
        rows=connection.execute('SELECT protocol FROM registration').fetchall()
        if len(rows)!=1 or sha256(rows[0][0]).hexdigest()!=self.expected:
            raise BenchmarkError('Evaluation registration mismatch')
        protocol=rows[0][0]
        validate_protocol(protocol)
        return protocol

    def evaluate(self,cases,predictions,*,run_id,model_revision_sha256):
        """Retain PASS and BLOCK; exact replay returns history, never replaces it."""
        try:
            if type(run_id) is not str or str(UUID(run_id))!=run_id:
                raise ValueError()
        except (ValueError,AttributeError):
            raise BenchmarkError('Canonical evaluation run ID required') from None
        with database(self.path) as connection:
            protocol=self._protocol(connection)
            # Revalidate all inputs even for a repeated run ID.
            result=evaluate_quality(protocol,cases,predictions,model_revision_sha256=model_revision_sha256)
            payload=canonical(result)
            previous=connection.execute('SELECT result FROM evaluations WHERE run_id=?',(run_id,)).fetchone()
            if previous is not None:
                if previous[0]!=payload:
                    raise BenchmarkError('Evaluation run conflict')
                return parse(previous[0])
            connection.execute('INSERT INTO evaluations (run_id,predictions_sha256,result) VALUES (?,?,?)',
                               (run_id,result['predictions_sha256'],payload))
            return result

    def history(self):
        with database(self.path) as connection:
            self._protocol(connection)
            rows=connection.execute('SELECT sequence,run_id,result FROM evaluations ORDER BY sequence').fetchall()
            return [{'sequence':row[0],'run_id':row[1],'result':parse(row[2])} for row in rows]
