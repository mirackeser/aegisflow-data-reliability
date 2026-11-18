# SPDX-License-Identifier: Apache-2.0
from hashlib import sha256
from random import Random
from threading import Thread
import unittest

from aegisflow_dr.advisory.context_cache import CacheIdentity, ContextCache
from aegisflow_dr.advisory.contracts import AdvisoryError

H1, H2 = sha256(b"1").hexdigest(), sha256(b"2").hexdigest()


def ident(tenant="alpha", kind="evidence", version="v1", evidence=H1, scope=()):
    return CacheIdentity(tenant, kind, version, evidence, scope)


class Counter:
    def __init__(self, value=b"payload"):
        self.calls, self.value = 0, value

    def __call__(self):
        self.calls += 1
        return self.value


class IdentityTests(unittest.TestCase):
    def test_valid_identity(self):
        self.assertEqual(ident(scope=("a", "b")).scope, ("a", "b"))

    def test_invalid_identities_are_rejected(self):
        bad = [dict(tenant="Alpha"), dict(tenant=""), dict(kind="x y"), dict(version=3), dict(evidence="abc"), dict(evidence=H1.upper()),
               dict(scope=["a"]), dict(scope=("b", "a")), dict(scope=("a", "a")), dict(scope=(1,)), dict(scope=tuple(f"s{i:02d}" for i in range(65)))]
        for kwargs in bad:
            with self.assertRaises(AdvisoryError, msg=str(kwargs)):
                ident(**kwargs)

    def test_invalid_limits_are_rejected(self):
        for kwargs in (dict(ttl=0), dict(ttl=True), dict(ttl=3601), dict(capacity=0), dict(capacity=1025), dict(max_entry_bytes=0),
                       dict(max_total_bytes=10, max_entry_bytes=20), dict(max_total_bytes=64_000_001)):
            with self.assertRaises(AdvisoryError, msg=str(kwargs)):
                ContextCache(**kwargs)

    def test_only_identities_are_accepted(self):
        with self.assertRaises(AdvisoryError):
            ContextCache().get_or_build(("alpha",), Counter())


class HitMissTests(unittest.TestCase):
    def test_second_request_is_a_hit_and_builder_runs_once(self):
        cache, build = ContextCache(), Counter()
        self.assertEqual(cache.get_or_build(ident(), build), b"payload")
        self.assertEqual(cache.get_or_build(ident(), build), b"payload")
        self.assertEqual(build.calls, 1)
        self.assertEqual((cache.stats()["hits"], cache.stats()["misses"], cache.stats()["entries"], cache.stats()["bytes"]), (1, 1, 1, 7))

    def test_every_identity_field_isolates_entries(self):
        cache = ContextCache()
        variants = [ident(), ident(tenant="beta"), ident(kind="other"), ident(version="v2"), ident(evidence=H2), ident(scope=("s",))]
        for index, identity in enumerate(variants):
            self.assertEqual(cache.get_or_build(identity, Counter(f"value-{index}".encode())), f"value-{index}".encode())
        for index, identity in enumerate(variants):  # each still returns only its own bytes
            self.assertEqual(cache.get_or_build(identity, Counter(b"WRONG")), f"value-{index}".encode())
        self.assertEqual((cache.stats()["hits"], cache.stats()["misses"]), (6, 6))

    def test_builder_failures_and_bad_values_cache_nothing(self):
        cache = ContextCache(max_entry_bytes=4)

        def boom():
            raise RuntimeError("build failed")
        with self.assertRaises(RuntimeError):
            cache.get_or_build(ident(), boom)
        for value in ("text", b"", b"12345", None):
            with self.assertRaises(AdvisoryError):
                cache.get_or_build(ident(), lambda value=value: value)
        self.assertEqual(cache.stats()["entries"], 0)

    def test_bad_clock_is_rejected(self):
        for value in ("1", -1, float("inf"), None):
            with self.assertRaises(AdvisoryError):
                ContextCache(clock=lambda value=value: value).get_or_build(ident(), Counter())


class ExpiryAndEvictionTests(unittest.TestCase):
    def test_entries_expire_at_exactly_ttl(self):
        now = [10]
        cache, build = ContextCache(clock=lambda: now[0], ttl=5), Counter()
        cache.get_or_build(ident(), build)
        now[0] = 14
        cache.get_or_build(ident(), build)
        self.assertEqual(build.calls, 1)
        now[0] = 15
        cache.get_or_build(ident(), build)
        self.assertEqual((build.calls, cache.stats()["expirations"]), (2, 1))

    def test_least_recently_used_entry_is_evicted_first(self):
        cache = ContextCache(capacity=2)
        a, b, c = ident(evidence=H1), ident(evidence=H2), ident(tenant="gamma")
        cache.get_or_build(a, Counter(b"a"))
        cache.get_or_build(b, Counter(b"b"))
        cache.get_or_build(a, Counter(b"a"))  # a is now most recent
        cache.get_or_build(c, Counter(b"c"))  # evicts b
        build = Counter(b"b2")
        self.assertEqual(cache.get_or_build(b, build), b"b2")
        self.assertEqual((build.calls, cache.stats()["evictions"]), (1, 2))

    def test_total_bytes_are_bounded(self):
        cache = ContextCache(capacity=10, max_entry_bytes=6, max_total_bytes=10)
        for index in range(4):
            cache.get_or_build(ident(tenant=f"t{index}"), Counter(b"123456"))
        self.assertLessEqual(cache.stats()["bytes"], 10)
        self.assertEqual((cache.stats()["entries"], cache.stats()["evictions"]), (1, 3))


class IntegrityAndInvalidationTests(unittest.TestCase):
    def test_tampered_entry_is_detected_and_rebuilt(self):
        cache, build = ContextCache(), Counter(b"good")
        cache.get_or_build(ident(), build)
        stored_at, _, digest = cache._entries[ident()]
        cache._entries[ident()] = (stored_at, b"evil", digest)
        self.assertEqual(cache.get_or_build(ident(), build), b"good")
        self.assertEqual((build.calls, cache.stats()["corrupt"]), (2, 1))

    def test_invalidate_by_each_filter_and_combinations(self):
        cache = ContextCache()
        for identity in (ident(), ident(tenant="beta"), ident(version="v2"), ident(kind="other"), ident(evidence=H2)):
            cache.get_or_build(identity, Counter())
        self.assertEqual(cache.invalidate(tenant="beta"), 1)
        self.assertEqual(cache.invalidate(version="v2"), 1)
        self.assertEqual(cache.invalidate(kind="other", tenant="alpha"), 1)
        self.assertEqual(cache.invalidate(evidence_sha256=H2), 1)
        self.assertEqual(cache.invalidate(tenant="nobody"), 0)
        self.assertEqual((cache.stats()["entries"], cache.stats()["invalidations"]), (1, 4))

    def test_invalidation_requires_a_filter(self):
        with self.assertRaises(AdvisoryError):
            ContextCache().invalidate()


class ConcurrencyAndPropertyTests(unittest.TestCase):
    def test_concurrent_callers_build_once(self):
        cache, build, results = ContextCache(), Counter(), []
        threads = [Thread(target=lambda: results.append(cache.get_or_build(ident(), build))) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((build.calls, results), (1, [b"payload"] * 16))

    def test_random_workload_never_returns_another_identitys_bytes(self):
        rng = Random(11)
        now = [0]
        cache = ContextCache(clock=lambda: now[0], ttl=7, capacity=5, max_entry_bytes=32, max_total_bytes=64)
        pool = [ident(tenant=t, version=v, scope=s) for t in ("a", "b", "c") for v in ("v1", "v2") for s in ((), ("x",))]
        expected = lambda identity: f"{identity.tenant}|{identity.version}|{identity.scope}".encode()
        for _ in range(600):
            action = rng.random()
            if action < 0.8:
                identity = rng.choice(pool)
                self.assertEqual(cache.get_or_build(identity, lambda identity=identity: expected(identity)), expected(identity))
            elif action < 0.9:
                now[0] += rng.randrange(0, 5)
            else:
                cache.invalidate(tenant=rng.choice(("a", "b", "c")))
            stats = cache.stats()
            self.assertLessEqual(stats["entries"], 5)
            self.assertLessEqual(stats["bytes"], 64)


if __name__ == "__main__":
    unittest.main()
