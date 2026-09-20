import unittest

from helpers import notes_vault, whole_vault

from vaultbench import testsets as T


class TestTitles(unittest.TestCase):

    def test_one_case_per_note_with_a_long_enough_title(self):
        ts = T.build_titles(notes_vault())
        self.assertEqual(ts.counts()["all"], 4)
        self.assertEqual(ts.stats["titles_too_short"], 1)
        queries = [c["query"] for c in ts.cases]
        self.assertIn("Lamp room rota", queries)
        self.assertNotIn("Catalogue", queries)

    def test_the_answer_is_the_note_itself(self):
        ts = T.build_titles(notes_vault())
        case = [c for c in ts.cases if c["query"] == "Foghorn repair"][0]
        self.assertEqual(case["answers"], ["notes/foghorn-repair.md"])

    def test_answer_exclude_removes_a_note(self):
        ts = T.build_titles(notes_vault(), answer_exclude=(r"^notes/lens",))
        self.assertEqual(ts.counts()["all"], 3)


class TestNames(unittest.TestCase):

    def setUp(self):
        self.ts = T.build_names(notes_vault())

    def test_aliases_from_links_and_frontmatter(self):
        self.assertEqual(sorted(c["query"] for c in self.ts.cases),
                         ["glass cleaning", "horn work", "night watch order",
                          "the horn job", "the picnic", "the rota"])
        self.assertEqual(self.ts.stats["links"], 2)
        self.assertEqual(self.ts.stats["frontmatter"], 4)

    def test_an_alias_that_repeats_the_name_is_dropped(self):
        self.assertEqual(self.ts.stats["same_as_name"], 2)

    def test_a_link_out_of_the_answer_space_is_not_a_case(self):
        self.assertEqual(self.ts.stats["out_of_scope"], 3)

    def test_stoplist(self):
        ts = T.build_names(notes_vault(), stoplist=("the rota", "the picnic"))
        self.assertEqual(ts.stats["stoplisted"], 2)
        self.assertNotIn("the rota", [c["query"] for c in ts.cases])

    def test_short_aliases_go(self):
        ts = T.build_names(notes_vault(), min_alias_len=12)
        self.assertNotIn("horn work", [c["query"] for c in ts.cases])
        self.assertIn("night watch order", [c["query"] for c in ts.cases])

    def test_the_notes_that_use_an_alias_stay_in_the_corpus(self):
        self.assertIn("notes/_catalogue.md", self.ts.corpus)


class TestDescriptions(unittest.TestCase):

    def setUp(self):
        self.ts = T.build_descriptions(notes_vault(), "notes/_catalogue.md")

    def test_one_case_per_line_that_names_one_note(self):
        self.assertEqual(self.ts.counts()["all"], 3)
        self.assertEqual(self.ts.stats["matched"], 3)

    def test_the_line_with_no_single_leading_link_is_skipped(self):
        self.assertNotIn("notes/harbour-picnic.md",
                         [a for c in self.ts.cases for a in c["answers"]])

    def test_the_index_note_leaves_the_corpus(self):
        self.assertNotIn("notes/_catalogue.md", self.ts.corpus)
        self.assertEqual(len(self.ts.corpus), 4)

    def test_the_query_is_the_summary(self):
        case = [c for c in self.ts.cases if c["answers"] == ["notes/foghorn-repair.md"]][0]
        self.assertEqual(case["query"],
                         "three weekends of work on the horn, and a borrowed compressor")

    def test_a_missing_index_note_is_an_empty_set(self):
        ts = T.build_descriptions(notes_vault(), "notes/nope.md")
        self.assertEqual(ts.counts()["all"], 0)
        self.assertEqual(ts.stats.get("missing_index"), 1)


class TestLinkedSentences(unittest.TestCase):

    def setUp(self):
        self.vault = whole_vault(answer_folders=("sources",), corpus_folders=("sources",))

    def build(self, **kwargs):
        return T.build_linked_sentences(self.vault, anchored_only=True,
                                        target_folders=("sources",), **kwargs)

    def test_one_case_per_citing_sentence(self):
        ts = self.build()
        self.assertEqual(ts.counts()["all"], 2)
        self.assertEqual(ts.stats["with_links"], 2)

    def test_the_citation_is_gone_and_other_links_are_plain_words(self):
        ts = self.build()
        query = [c["query"] for c in ts.cases if c["query"].startswith("The order")][0]
        self.assertIn("horn work", query)
        self.assertNotIn("[[", query)
        self.assertNotIn("the workshop notes", query)

    def test_a_table_row_is_skipped_unless_you_ask_for_it(self):
        self.assertEqual(self.build().counts()["all"], 2)
        self.assertEqual(self.build(skip_tables=False).counts()["all"], 3)

    def test_a_link_with_no_anchor_does_not_qualify(self):
        ts = T.build_linked_sentences(notes_vault(), anchored_only=True,
                                      target_folders=("notes",))
        self.assertEqual(ts.counts()["all"], 0)
        ts = T.build_linked_sentences(notes_vault(), anchored_only=False,
                                      target_folders=("notes",))
        self.assertTrue(ts.counts()["all"] >= 2)

    def test_short_queries_are_dropped(self):
        ts = self.build(min_terms=200)
        self.assertEqual(ts.counts()["all"], 0)
        self.assertEqual(ts.stats["too_short"], 2)


class TestSplitAndDedupe(unittest.TestCase):

    def test_split_is_a_function_of_the_query_text(self):
        self.assertEqual(T.split_of("lamp room rota"), T.split_of("lamp room rota"))
        self.assertIn(T.split_of("lamp room rota"), ("dev", "held"))

    def test_split_survives_a_rebuild(self):
        first = {c["query"]: c["split"] for c in T.build_names(notes_vault()).cases}
        second = {c["query"]: c["split"] for c in T.build_names(notes_vault()).cases}
        self.assertEqual(first, second)

    def test_both_sides_are_used(self):
        cases = T.build_titles(notes_vault()).cases + T.build_names(notes_vault()).cases
        sides = set(c["split"] for c in cases)
        self.assertEqual(sides, {"dev", "held"})

    def test_dedupe_drops_repeats_and_sorts(self):
        cases = [T.make_case("s", "b query", ["x.md"]),
                 T.make_case("s", "a query", ["x.md"]),
                 T.make_case("s", "b query", ["x.md"]),
                 T.make_case("s", "c query", [])]
        kept = T.dedupe(cases)
        self.assertEqual([c["query"] for c in kept], ["a query", "b query"])

    def test_whitespace_is_normalised_before_hashing(self):
        one = T.make_case("s", "a   query\nhere", ["x.md"])
        two = T.make_case("s", "a query here", ["x.md"])
        self.assertEqual(one["query"], two["query"])
        self.assertEqual(one["split"], two["split"])


if __name__ == "__main__":
    unittest.main()
