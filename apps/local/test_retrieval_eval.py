# SPDX-License-Identifier: Apache-2.0
from random import Random
import unittest

from knowledge import STOPWORDS, Document, Knowledge, terms
import retrieval_eval as ev
from reference_documents import REFERENCE_DOCUMENTS

SOURCES = frozenset(d.source for d in REFERENCE_DOCUMENTS)


def loaded():
    knowledge = Knowledge()
    knowledge.replace(REFERENCE_DOCUMENTS)
    return knowledge


class StopwordTests(unittest.TestCase):
    def test_function_words_are_not_evidence(self):
        self.assertEqual(terms("The weather IS in Istanbul"), {"weather", "istanbul"})
        self.assertTrue({"the", "is", "of"} <= STOPWORDS)
        self.assertEqual(loaded().retrieve("local", "the and of to a", allowed_sources=SOURCES), [])

    def test_content_words_still_match(self):
        found = loaded().retrieve("local", "blank order_total understates revenue", allowed_sources=SOURCES)
        self.assertEqual(found[0]["source"], "missing-value-guidance")


class CorpusTests(unittest.TestCase):
    def test_query_set_is_well_formed(self):
        queries = [q for _, q, _ in ev.QUERIES]
        self.assertEqual(len(queries), len(set(queries)))
        for group, _, gold in ev.QUERIES:
            self.assertIn(group, ev.GROUPS)
            self.assertTrue(gold <= SOURCES)
            self.assertEqual(bool(gold), group != "out_of_scope")
        self.assertEqual({g: sum(1 for x, _, _ in ev.QUERIES if x == g) for g in ev.GROUPS},
                         {"keyword": 18, "paraphrase": 8, "out_of_scope": 6})


class MeasuredQualityTests(unittest.TestCase):
    """Exact, deterministic figures. Change them only on purpose and update docs/evaluation/retrieval.md."""

    def test_pinned_results(self):
        report = ev.evaluate()
        self.assertEqual((report["documents"], report["queries"], report["authored_with_corpus_in_view"]), (6, 32, True))
        keyword, paraphrase, scope = (report["groups"][g] for g in ev.GROUPS)
        self.assertEqual((keyword["recall_at_1"]["value"], keyword["recall_at_3"]["value"], keyword["mrr"]), (1.0, 1.0, 1.0))
        self.assertEqual((paraphrase["recall_at_1"]["numerator"], paraphrase["recall_at_3"]["numerator"], paraphrase["mrr"]), (3, 4, 0.4375))
        self.assertEqual((scope["false_retrieval"]["numerator"], scope["correctly_empty"]["numerator"]), (0, 6))
        self.assertEqual(paraphrase["recall_at_3"]["wilson95"], [0.2152, 0.7848])

    def test_measurement_reacts_to_a_broken_retriever(self):
        report = ev.evaluate(Knowledge())  # empty corpus: nothing can be found
        keyword = report["groups"]["keyword"]
        self.assertEqual((keyword["recall_at_1"]["numerator"], keyword["mrr"]), (0, 0.0))
        self.assertEqual(report["groups"]["out_of_scope"]["correctly_empty"]["numerator"], 6)

    def test_a_retriever_that_returns_everything_fails_out_of_scope(self):
        class Everything(Knowledge):
            def retrieve(self, tenant, query, *, allowed_sources, limit=3):
                return [{"source": s} for s in sorted(allowed_sources)][:limit]
        report = ev.evaluate(Everything())
        self.assertEqual(report["groups"]["out_of_scope"]["false_retrieval"]["numerator"], 6)


class DocumentTests(unittest.TestCase):
    def test_published_report_matches_the_code(self):
        from pathlib import Path
        published = (Path(__file__).resolve().parents[2] / "docs" / "evaluation" / "retrieval.md").read_text("utf-8")
        self.assertEqual(published, ev.render_markdown(ev.evaluate()) + "\n")

    def test_markdown_states_the_limits(self):
        text = ev.render_markdown(ev.evaluate())
        for phrase in ("not an independent benchmark", "no model is involved", "Paraphrase queries are the realistic case"):
            self.assertIn(phrase, text)


class IsolationTests(unittest.TestCase):
    def test_results_never_leave_the_granted_sources_or_tenant(self):
        knowledge = Knowledge()
        foreign = Document("other", "secret-runbook", "v1", "order_total revenue secret export column duplicate")
        knowledge.replace((*REFERENCE_DOCUMENTS, foreign))
        rng = Random(7)
        for _, query, _ in ev.QUERIES:
            granted = frozenset(rng.sample(sorted(SOURCES), rng.randrange(0, len(SOURCES) + 1)))
            for result in knowledge.retrieve("local", query, allowed_sources=granted):
                self.assertIn(result["source"], granted)
                self.assertNotEqual(result["source"], "secret-runbook")
        self.assertEqual(knowledge.retrieve("local", "secret", allowed_sources=frozenset({"secret-runbook"})), [])

    def test_every_returned_citation_verifies_and_a_changed_document_does_not(self):
        knowledge = loaded()
        for _, query, _ in ev.QUERIES:
            for result in knowledge.retrieve("local", query, allowed_sources=SOURCES):
                self.assertTrue(knowledge.verify("local", result["citation_sha256"], allowed_sources=SOURCES))
        before = knowledge.retrieve("local", "blank identifier prevents matching", allowed_sources=SOURCES)[0]["citation_sha256"]
        changed = tuple(Document(d.tenant, d.source, "v2", d.text) if d.source == "missing-value-guidance" else d for d in REFERENCE_DOCUMENTS)
        knowledge.replace(changed)
        self.assertFalse(knowledge.verify("local", before, allowed_sources=SOURCES))


if __name__ == "__main__":
    unittest.main()
