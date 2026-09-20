"""Ranker orderings on a corpus small enough to work out by hand.

Three notes, no frontmatter and no headings, so the word counts in the test are the whole
of each file:

    alpha.md          beacon beacon beacon
    beacon-notes.md   beacon lantern
    gamma.md          lantern lantern lantern lantern

Query: "beacon lantern".

count   alpha 3, beacon-notes 2, gamma 4                      gamma, alpha, beacon-notes
tiered  alpha 10 + 0 + 1 = 11
        beacon-notes 20 + 2 (the word is in the path) + 1 = 23
        gamma 10 + 0 + 1 = 11                                 beacon-notes, then the tie
        and the tie keeps path order, so alpha before gamma.
"""

import os
import shutil
import tempfile
import unittest

from helpers import notes_vault, write_vault

from vaultbench import (BM25Ranker, CountRanker, Index, TieredRanker, Vault, build_ranker,
                        terms_of)

CORPUS = {
    "alpha.md": "beacon beacon beacon\n",
    "beacon-notes.md": "beacon lantern\n",
    "gamma.md": "lantern lantern lantern lantern\n",
}


class TestTerms(unittest.TestCase):

    def test_words_are_lowercased_deduplicated_and_filtered(self):
        self.assertEqual(terms_of("The Lamp Room rota, the ROTA"), ["lamp", "room", "rota"])

    def test_short_words_and_stopwords_go(self):
        self.assertEqual(terms_of("it is on a pier"), ["pier"])


class TestBuiltinRankers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="vaultbench-")
        write_vault(cls.tmp, CORPUS)
        cls.index = Index(Vault(cls.tmp))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_count_sorts_by_raw_occurrences(self):
        order = CountRanker().rank("beacon lantern", self.index)
        self.assertEqual(order, ["gamma.md", "alpha.md", "beacon-notes.md"])

    def test_tiered_pays_for_distinct_words_and_the_path(self):
        order = TieredRanker().rank("beacon lantern", self.index)
        self.assertEqual(order, ["beacon-notes.md", "alpha.md", "gamma.md"])

    def test_a_tie_keeps_path_order(self):
        order = TieredRanker().rank("beacon lantern", self.index)
        self.assertEqual(order[1:], sorted(order[1:]))

    def test_bm25_discounts_repeats_and_length(self):
        order = BM25Ranker().rank("beacon lantern", self.index)
        self.assertEqual(order[0], "beacon-notes.md")
        self.assertEqual(sorted(order), ["alpha.md", "beacon-notes.md", "gamma.md"])

    def test_title_boost_lifts_a_note_whose_name_carries_the_word(self):
        plain = BM25Ranker().rank("beacon", self.index)
        boosted = BM25Ranker(title_boost=5.0).rank("beacon", self.index)
        self.assertEqual(plain, ["alpha.md", "beacon-notes.md"])
        self.assertEqual(boosted, ["beacon-notes.md", "alpha.md"])

    def test_a_note_with_no_match_is_not_ranked(self):
        for ranker in (CountRanker(), TieredRanker(), BM25Ranker()):
            self.assertEqual(ranker.rank("beacon", self.index),
                             [p for p in ranker.rank("beacon", self.index)])
            self.assertNotIn("gamma.md", ranker.rank("beacon", self.index))

    def test_a_query_with_no_usable_word_ranks_nothing(self):
        self.assertEqual(TieredRanker().rank("to be or not", self.index), [])

    def test_the_same_query_ranks_the_same_way_twice(self):
        first = TieredRanker().rank("beacon lantern", self.index)
        second = TieredRanker().rank("beacon lantern", self.index)
        self.assertEqual(first, second)


class TestIndexAndSpec(unittest.TestCase):

    def test_index_only_holds_the_corpus_it_was_given(self):
        vault = notes_vault()
        index = Index(vault, ["notes/lens-polish.md"])
        self.assertEqual(index.paths, ["notes/lens-polish.md"])
        self.assertEqual(TieredRanker().rank("compressor", index), [])

    def test_matching_lines_are_capped(self):
        index = Index(notes_vault())
        lines = index.matching_lines("notes/lens-polish.md", ["cloth"], limit=1)
        self.assertEqual(len(lines), 1)

    def test_build_ranker_by_name_and_with_options(self):
        self.assertIsInstance(build_ranker("count"), CountRanker)
        self.assertEqual(build_ranker("bm25:title_boost=1.5").title_boost, 1.5)
        self.assertRaises(ValueError, build_ranker, "nope")

    def test_build_ranker_makes_an_external_one(self):
        ranker = build_ranker("cmd:mysearch {query}", vault_root=os.getcwd())
        self.assertEqual(ranker.argv("two words"), ["mysearch", "two words"])


if __name__ == "__main__":
    unittest.main()
