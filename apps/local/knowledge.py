# SPDX-License-Identifier: Apache-2.0
"""Bounded local lexical retrieval with revision-bound citations and isolated caching."""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from threading import RLock
from time import monotonic

from chunking import chunk


STOPWORDS = frozenset('a an and are as at be but by for from how i if in into is it its me my of on or that the their then there these this to was were what when where which who why will with you your do does not no can'.split())


def terms(text):
    """Lower-cased word set without function words, so that 'the' or 'is' never counts as evidence."""
    return set(re.findall(r'\w+', text.casefold())) - STOPWORDS


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class Document:
    tenant: str
    source: str
    revision: str
    text: str

    def __post_init__(self):
        if any(type(v) is not str or not re.fullmatch('[a-z0-9-]{1,64}', v)
               for v in (self.tenant, self.source, self.revision)):
            raise ValueError('Invalid document identity')
        if type(self.text) is not str or not 1 <= len(self.text.encode()) <= 16384:
            raise ValueError('Invalid document size')

    @property
    def citation(self):
        return digest([self.tenant, self.source, self.revision, self.text])


class Knowledge:
    """Trusted host grants are required on every query, including cache hits.

    Documents are untrusted reference text, never instructions or tool grants.
    This lexical baseline does not claim embedding retrieval or semantic accuracy.
    """
    def __init__(self, *, clock=monotonic, ttl=60, capacity=128):
        if type(ttl) is not int or not 1 <= ttl <= 3600 or type(capacity) is not int or not 1 <= capacity <= 1024:
            raise ValueError('Invalid cache limits')
        self.clock, self.ttl, self.capacity = clock, ttl, capacity
        self.documents, self.cache, self.lock = {}, {}, RLock()
        self.passages = {}

    def replace(self, documents):
        if type(documents) is not tuple or len(documents) > 256 or any(type(d) is not Document for d in documents):
            raise ValueError('Invalid knowledge collection')
        values = {(d.tenant, d.source): d for d in documents}
        if len(values) != len(documents):
            raise ValueError('Duplicate source')
        passages = {key: [{**c, 'terms': terms(c['text']),
                           'citation': digest([d.tenant, d.source, d.revision, c['index'], c['start'], c['end'], c['text']])}
                          for c in chunk(d.text)] for key, d in values.items()}
        with self.lock:
            self.documents = values
            self.passages = passages
            self.cache.clear()

    @staticmethod
    def _check(tenant, query, allowed_sources, limit):
        if (type(tenant) is not str or not re.fullmatch('[a-z0-9-]{1,64}', tenant)
                or type(query) is not str or not 1 <= len(query.encode()) <= 1024
                or type(allowed_sources) is not frozenset or len(allowed_sources) > 256
                or any(type(s) is not str or not re.fullmatch('[a-z0-9-]{1,64}', s) for s in allowed_sources)
                or type(limit) is not int or not 1 <= limit <= 10):
            raise ValueError('Invalid retrieval request')

    def retrieve(self, tenant, query, *, allowed_sources, limit=3):
        self._check(tenant, query, allowed_sources, limit)
        with self.lock:
            selected = [d for (t, s), d in self.documents.items() if t == tenant and s in allowed_sources]
            key = digest([tenant, query, sorted(allowed_sources), limit, sorted(d.citation for d in selected)])
            now = self.clock()
            if type(now) not in (int, float) or not 0 <= now < float('inf'):
                raise ValueError('Invalid cache clock')
            cached = self.cache.get(key)
            if cached is not None and cached[0] <= now < cached[0] + self.ttl:
                return json.loads(cached[1])
            tokens = terms(query)
            ranked = []
            for d in selected:
                score = len(tokens & terms(d.text))
                if score:
                    ranked.append((score, d))
            ranked.sort(key=lambda item: (-item[0], item[1].source))
            result = [{'source': d.source, 'revision': d.revision, 'citation_sha256': d.citation,
                       'text': d.text, 'matching_terms': score} for score, d in ranked[:limit]]
            if len(self.cache) >= self.capacity:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = (now, json.dumps(result))
            return result

    def verify(self, tenant, citation, *, allowed_sources):
        with self.lock:
            return any(d.tenant == tenant and d.source in allowed_sources and d.citation == citation
                       for d in self.documents.values())

    def retrieve_passages(self, tenant, query, *, allowed_sources, limit=3, per_document=2):
        """Best passages (not whole documents), each with its exact span and its own verifiable citation."""
        self._check(tenant, query, allowed_sources, limit)
        tokens = terms(query)
        with self.lock:
            ranked = []
            for (t, source), d in self.documents.items():
                if t != tenant or source not in allowed_sources:
                    continue
                scored = [(len(tokens & p['terms']), p) for p in self.passages[(t, source)]]
                scored = sorted((item for item in scored if item[0]), key=lambda item: (-item[0], item[1]['index']))[:per_document]
                ranked += [(score, d, p) for score, p in scored]
            ranked.sort(key=lambda item: (-item[0], item[1].source, item[2]['index']))
            return [{'source': d.source, 'revision': d.revision, 'chunk': p['index'], 'start': p['start'], 'end': p['end'],
                     'text': p['text'], 'matching_terms': score, 'citation_sha256': p['citation'],
                     'document_citation_sha256': d.citation} for score, d, p in ranked[:limit]]

    def verify_passage(self, tenant, citation, *, allowed_sources):
        with self.lock:
            return any(t == tenant and s in allowed_sources and p['citation'] == citation
                       for (t, s), passages in self.passages.items() for p in passages)
