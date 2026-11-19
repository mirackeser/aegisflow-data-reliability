# SPDX-License-Identifier: Apache-2.0
from random import Random
import unittest

import chunking
from chunking import MAX_CHUNK_BYTES, MIN_CHUNK_BYTES, chunk


def invariants(test, text, chunks):
    previous_end = 0
    covered = set()
    for index, c in enumerate(chunks):
        test.assertEqual(c["index"], index)
        test.assertEqual(c["text"], text[c["start"]:c["end"]])
        test.assertTrue(c["text"] and c["text"] == c["text"].strip())
        test.assertLessEqual(len(c["text"].encode("utf-8")), MAX_CHUNK_BYTES)
        test.assertGreaterEqual(c["start"], previous_end)
        previous_end = c["end"]
        covered.update(range(c["start"], c["end"]))
    test.assertEqual({i for i, ch in enumerate(text) if not ch.isspace()} - covered, set())


class ChunkRuleTests(unittest.TestCase):
    def test_empty_and_blank_text_have_no_chunks(self):
        self.assertEqual(chunk(""), [])
        self.assertEqual(chunk(" \n\n \t "), [])

    def test_short_document_is_one_chunk_with_exact_span(self):
        text = "  A single short paragraph.\n"
        self.assertEqual(chunk(text), [{"index": 0, "start": 2, "end": 27, "text": "A single short paragraph."}])

    def test_paragraphs_stay_separate_when_large_enough(self):
        a, b = "A " * 80, "B " * 80  # 160 bytes each, above the minimum
        chunks = chunk(a.strip() + "\n\n" + b.strip())
        self.assertEqual([c["text"][0] for c in chunks], ["A", "B"])

    def test_short_heading_joins_the_next_paragraph_only_while_it_fits(self):
        joined = chunk("Title\n\n" + "word " * 40)
        self.assertEqual(len(joined), 1)
        body = ("word " * 160).strip()  # 799 bytes: heading plus body would not fit
        separate = chunk("Title\n\n" + body)
        self.assertEqual([c["text"] for c in separate], ["Title", body])

    def test_long_paragraph_is_cut_at_a_sentence_end_when_possible(self):
        text = " ".join(f"Sentence {i} is moderately long and ends here." for i in range(40))
        chunks = chunk(text)
        invariants(self, text, chunks)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c["text"].endswith(".") for c in chunks))

    def test_no_sentence_end_cuts_at_a_word_boundary(self):
        text = " ".join(f"word{i}" for i in range(400))
        chunks = chunk(text)
        invariants(self, text, chunks)
        self.assertEqual(" ".join(c["text"] for c in chunks), text)

    def test_one_enormous_word_is_cut_on_character_boundaries(self):
        text = "start " + "é" * 2000 + " end"
        chunks = chunk(text)
        invariants(self, text, chunks)
        self.assertEqual("".join(c["text"] for c in chunks).replace(" ", ""), text.replace(" ", ""))
        self.assertTrue(any(c["text"] == "end" or c["text"].endswith(" end") for c in chunks))

    def test_a_long_sentence_followed_by_a_long_word_still_fits(self):
        text = "Opening. " + "x" * 700 + ". " + "y" * 150
        chunks = chunk(text)
        invariants(self, text, chunks)
        self.assertGreaterEqual(len(chunks), 2)

    def test_constants_are_sane(self):
        self.assertLess(MIN_CHUNK_BYTES, MAX_CHUNK_BYTES)
        self.assertIs(chunking.chunk, chunk)


class PropertyTests(unittest.TestCase):
    def test_random_documents_satisfy_every_invariant_and_are_deterministic(self):
        rng = Random(2026)
        alphabet = ["alpha", "beta", "gamma.", "delta!", "épsilon", "zeta?", "ηθ", "x" * 300, "y" * 900, "z"]
        for case in range(250):
            parts = []
            for _ in range(rng.randrange(1, 90)):
                parts.append(rng.choice(alphabet))
                parts.append(rng.choice([" ", " ", " ", "\n", "\n\n", "\n \n", "  ", "\t"]))
            text = "".join(parts)
            first = chunk(text)
            with self.subTest(case=case):
                invariants(self, text, first)
                self.assertEqual(first, chunk(text))


if __name__ == "__main__":
    unittest.main()
