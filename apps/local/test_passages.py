# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from random import Random
import unittest
from unittest import mock

from knowledge import Document, Knowledge
import passage_eval as pe
from reference_documents import REFERENCE_DOCUMENTS

ALL = frozenset({"long", "other", "short"})


def paragraph(word, n=30):
    return " ".join([word] * 3 + [f"filler{i}" for i in range(n)]) + "."


LONG = "\n\n".join(paragraph(w) for w in ("zebra", "quokka", "narwhal", "axolotl"))


def loaded(*docs):
    knowledge = Knowledge()
    knowledge.replace(tuple(docs))
    return knowledge


class PassageRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.doc = Document("local", "long", "v1", LONG)
        self.knowledge = loaded(self.doc, Document("local", "short", "v1", "A short note about quokka care."))

    def test_returns_the_matching_passage_with_exact_span_and_own_citation(self):
        found = self.knowledge.retrieve_passages("local", "narwhal", allowed_sources=ALL)
        self.assertEqual(found[0]["source"], "long")
        self.assertEqual(self.doc.text[found[0]["start"]:found[0]["end"]], found[0]["text"])
        self.assertIn("narwhal", found[0]["text"])
        self.assertNotIn("zebra", found[0]["text"])
        self.assertNotEqual(found[0]["citation_sha256"], found[0]["document_citation_sha256"])
        self.assertEqual(found[0]["document_citation_sha256"], self.doc.citation)
        self.assertTrue(self.knowledge.verify_passage("local", found[0]["citation_sha256"], allowed_sources=ALL))

    def test_limits_ordering_and_per_document_cap(self):
        many = "\n\n".join(paragraph("quokka", n) for n in (30, 31, 32, 33))
        knowledge = loaded(Document("local", "long", "v1", many), Document("local", "short", "v1", "quokka"))
        found = knowledge.retrieve_passages("local", "quokka", allowed_sources=ALL, limit=10)
        self.assertEqual(sorted(r["source"] for r in found), ["long", "long", "short"])  # two per document at most
        self.assertEqual(len(knowledge.retrieve_passages("local", "quokka", allowed_sources=ALL, limit=1)), 1)
        self.assertEqual(self.knowledge.retrieve_passages("local", "nothing matches here", allowed_sources=ALL), [])

    def test_grants_and_tenants_are_enforced(self):
        self.assertEqual(self.knowledge.retrieve_passages("local", "zebra", allowed_sources=frozenset({"short"})), [])
        self.assertEqual(self.knowledge.retrieve_passages("other", "zebra", allowed_sources=ALL), [])
        found = self.knowledge.retrieve_passages("local", "zebra", allowed_sources=ALL)[0]
        self.assertFalse(self.knowledge.verify_passage("local", found["citation_sha256"], allowed_sources=frozenset({"short"})))
        self.assertFalse(self.knowledge.verify_passage("other", found["citation_sha256"], allowed_sources=ALL))
        self.assertFalse(self.knowledge.verify_passage("local", "0" * 64, allowed_sources=ALL))

    def test_an_edit_invalidates_old_passage_citations(self):
        old = self.knowledge.retrieve_passages("local", "zebra", allowed_sources=ALL)[0]["citation_sha256"]
        self.knowledge.replace((Document("local", "long", "v2", LONG), Document("local", "short", "v1", "x")))
        self.assertFalse(self.knowledge.verify_passage("local", old, allowed_sources=ALL))
        self.assertNotEqual(self.knowledge.retrieve_passages("local", "zebra", allowed_sources=ALL)[0]["citation_sha256"], old)

    def test_invalid_requests_are_rejected(self):
        for tenant, query, sources, limit in (("Bad", "q", ALL, 3), ("local", "", ALL, 3), ("local", "q", {"long"}, 3), ("local", "q", ALL, 0), ("local", "q", ALL, 11)):
            with self.assertRaises(ValueError):
                self.knowledge.retrieve_passages(tenant, query, allowed_sources=sources, limit=limit)

    def test_built_in_documents_are_single_passages_so_nothing_changes_for_them(self):
        knowledge = loaded(*REFERENCE_DOCUMENTS)
        allowed = frozenset(d.source for d in REFERENCE_DOCUMENTS)
        for d in REFERENCE_DOCUMENTS:
            self.assertEqual(len(knowledge.passages[("local", d.source)]), 1)
            self.assertEqual(knowledge.passages[("local", d.source)][0]["text"], d.text)
        by_doc = knowledge.retrieve("local", "blank identifier prevents matching", allowed_sources=allowed, limit=1)[0]
        by_passage = knowledge.retrieve_passages("local", "blank identifier prevents matching", allowed_sources=allowed, limit=1)[0]
        self.assertEqual((by_doc["source"], by_doc["text"]), (by_passage["source"], by_passage["text"]))

    def test_random_documents_every_passage_verifies_and_matches_its_span(self):
        rng = Random(3)
        words = [f"term{n}" for n in range(60)]
        docs = []
        for index in range(12):
            body = "\n\n".join(" ".join(rng.choice(words) for _ in range(rng.randrange(5, 140))) + "." for _ in range(rng.randrange(1, 9)))
            docs.append(Document("local", f"doc-{index}", "v1", body))
        knowledge = loaded(*docs)
        allowed = frozenset(d.source for d in docs)
        by_source = {d.source: d for d in docs}
        for _ in range(150):
            query = " ".join(rng.sample(words, 3))
            for result in knowledge.retrieve_passages("local", query, allowed_sources=allowed, limit=5):
                self.assertEqual(by_source[result["source"]].text[result["start"]:result["end"]], result["text"])
                self.assertTrue(knowledge.verify_passage("local", result["citation_sha256"], allowed_sources=allowed))


class PassageEvaluationTests(unittest.TestCase):
    """Exact, deterministic figures for the seeded synthetic corpus."""

    def test_corpus_is_well_formed_and_deterministic(self):
        documents, gold = pe.corpus()
        self.assertEqual(pe.corpus()[1], gold)
        self.assertEqual((len(documents), len(gold)), (12, 96))
        self.assertTrue(all(len(g["unique"]) >= 4 for g in gold))
        domains = [set(v.split()) for v in pe.DOMAINS.values()]
        self.assertEqual(sum(len(d) for d in domains), len(set().union(*domains)))  # topic vocabularies are disjoint

    def test_paragraphs_without_enough_distinctive_words_are_skipped(self):
        with mock.patch.object(pe, "PREFIXES", ()):  # a narrow vocabulary leaves too few words unique to one paragraph
            self.assertLess(len(pe.corpus()[1]), 96)

    def test_pinned_results(self):
        report = pe.evaluate()
        self.assertEqual((report["documents"], report["queries_per_group"], report["synthetic"], report["mean_document_bytes"]), (12, 96, True, 2018))
        four, two = report["groups"]["4_distinctive_words"], report["groups"]["2_distinctive_words"]
        self.assertEqual([four["document_level"]["right_document_first"]["numerator"], four["passage_level"]["right_passage_first"]["numerator"]], [96, 96])
        self.assertEqual((two["document_level"]["right_document_first"]["numerator"], two["passage_level"]["right_document_first"]["numerator"],
                          two["passage_level"]["right_passage_first"]["numerator"]), (90, 94, 94))
        self.assertEqual((four["document_level"]["mean_returned_bytes"], four["passage_level"]["mean_returned_bytes"]), (2018, 250))
        self.assertLess(four["passage_level"]["mean_returned_bytes"] * 7, four["document_level"]["mean_returned_bytes"])

    def test_measurement_reacts_to_a_broken_passage_retriever(self):
        with mock.patch.object(Knowledge, "retrieve_passages", return_value=[]):
            report = pe.evaluate()
        self.assertEqual(report["groups"]["4_distinctive_words"]["passage_level"]["right_passage_first"]["numerator"], 0)
        wrong = [{"source": "synthetic-99", "start": 0, "end": 1, "text": "x"}]
        with mock.patch.object(Knowledge, "retrieve_passages", return_value=wrong):
            report = pe.evaluate()
        self.assertEqual(report["groups"]["4_distinctive_words"]["passage_level"]["right_passage_first"]["numerator"], 0)
        with mock.patch.object(Knowledge, "retrieve", return_value=[]):
            self.assertEqual(pe.evaluate()["groups"]["2_distinctive_words"]["document_level"]["right_document_first"]["numerator"], 0)

    def test_published_report_matches_the_code_and_states_the_limits(self):
        published = (Path(__file__).resolve().parents[2] / "docs" / "evaluation" / "passages.md").read_text("utf-8")
        text = pe.render_markdown(pe.evaluate())
        self.assertEqual(published, text + "\n")
        for phrase in ("Synthetic and seeded", "not real prose", "it is not shown to be better", "intervals overlap"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
