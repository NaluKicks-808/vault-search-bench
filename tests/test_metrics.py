import unittest

from helpers import notes_vault

from vaultbench import evaluate, rank_of, score, table
from vaultbench.metrics import pct


class TestRankOf(unittest.TestCase):

    def test_first_right_answer_wins(self):
        self.assertEqual(rank_of(["b.md", "c.md"], ["a.md", "b.md", "c.md"]), 2)

    def test_a_miss_is_none(self):
        self.assertIsNone(rank_of(["z.md"], ["a.md", "b.md"]))

    def test_an_empty_ranking_is_a_miss(self):
        self.assertIsNone(rank_of(["a.md"], []))


class TestScore(unittest.TestCase):

    def test_the_arithmetic(self):
        s = score([1, 2, 4, None], ks=(1, 3, 10))
        self.assertEqual(s["n"], 4)
        self.assertEqual(s["found"], 3)
        self.assertEqual(s["top1"], 1)
        self.assertEqual(s["top3"], 2)
        self.assertEqual(s["top10"], 3)
        self.assertAlmostEqual(s["top1_rate"], 0.25)
        self.assertAlmostEqual(s["top3_rate"], 0.5)
        self.assertAlmostEqual(s["mrr"], (1.0 + 0.5 + 0.25) / 4)

    def test_a_miss_counts_in_the_denominator(self):
        self.assertAlmostEqual(score([None, None])["mrr"], 0.0)
        self.assertEqual(score([None, None])["n"], 2)

    def test_empty_is_all_zero_and_not_an_error(self):
        s = score([])
        self.assertEqual(s["n"], 0)
        self.assertEqual(s["mrr"], 0.0)
        self.assertIsNone(s["median_rank"])

    def test_perfect(self):
        s = score([1, 1, 1])
        self.assertEqual(s["top1"], 3)
        self.assertAlmostEqual(s["mrr"], 1.0)


class TestEvaluate(unittest.TestCase):

    def test_cases_and_rankings_line_up(self):
        cases = [{"answers": ["a.md"]}, {"answers": ["b.md"]}]
        rankings = [["a.md", "b.md"], ["c.md", "d.md", "b.md"]]
        result = evaluate(cases, rankings)
        self.assertEqual(result["ranks"], [1, 3])
        self.assertEqual(result["top1"], 1)
        self.assertEqual(result["top3"], 2)


class TestPresentation(unittest.TestCase):

    def test_percentages_carry_their_count(self):
        text = table([("titles", "tiered", score([1, 1, 2, None]))])
        self.assertIn("titles", text)
        self.assertIn("tiered", text)
        self.assertIn("2 ", text)
        self.assertIn("50.0%", text)

    def test_pct_of_nothing_does_not_divide_by_zero(self):
        self.assertIn("n/a", pct(0, 0))


class TestEndToEndOnTheFixture(unittest.TestCase):

    def test_a_title_search_finds_its_own_note(self):
        from vaultbench import Index, TieredRanker, build_titles
        vault = notes_vault()
        ts = build_titles(vault)
        index = Index(vault, ts.corpus)
        ranker = TieredRanker()
        rankings = [ranker.rank(c["query"], index) for c in ts.cases]
        result = evaluate(ts.cases, rankings)
        self.assertEqual(result["n"], 4)
        self.assertEqual(result["top1"], 4)


if __name__ == "__main__":
    unittest.main()
