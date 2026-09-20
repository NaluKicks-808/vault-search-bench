"""The plug for an outside search tool, exercised with a fake one."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import notes_vault, write_vault

from vaultbench import ExternalRanker, Index, Vault

FAKE = """import sys
query = " ".join(sys.argv[1:])
if query == "silent":
    raise SystemExit(0)
print("notes/lens-polish.md")
print("  notes/foghorn-repair.md  ")
print("")
print("notes/not-a-real-note.md")
print("notes/lens-polish.md")
"""


class TestExternalRanker(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="vaultbench-cmd-")
        cls.script = os.path.join(cls.tmp, "fake_search.py")
        with open(cls.script, "w", encoding="utf-8") as fh:
            fh.write(FAKE)
        cls.vault = notes_vault()
        cls.index = Index(cls.vault)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ranker(self, extra=""):
        template = "%s %s %s{query}" % (sys.executable, self.script, extra)
        return ExternalRanker(template, cwd=self.vault.root)

    def test_the_query_stays_one_argument(self):
        argv = self.ranker().argv("two words here")
        self.assertEqual(argv[-1], "two words here")
        self.assertEqual(len(argv), 3)

    def test_a_template_with_no_placeholder_gets_the_query_appended(self):
        ranker = ExternalRanker("mysearch --json")
        self.assertEqual(ranker.argv("beacon"), ["mysearch", "--json", "beacon"])

    def test_it_reads_one_path_a_line(self):
        order = self.ranker().rank("anything", self.index)
        self.assertEqual(order, ["notes/lens-polish.md", "notes/foghorn-repair.md"])

    def test_unknown_paths_and_repeats_are_ignored(self):
        order = self.ranker().rank("anything", self.index)
        self.assertNotIn("notes/not-a-real-note.md", order)
        self.assertEqual(len(order), len(set(order)))

    def test_absolute_paths_are_understood(self):
        absolute = os.path.join(self.vault.root, "notes/harbour-picnic.md")
        parsed = self.ranker().parse(absolute + "\n", self.index)
        self.assertEqual(parsed, ["notes/harbour-picnic.md"])

    def test_printing_nothing_is_an_empty_ranking(self):
        self.assertEqual(self.ranker().rank("silent", self.index), [])

    def test_a_command_that_does_not_exist_is_counted_not_raised(self):
        ranker = ExternalRanker("definitely-not-a-real-command-xyz {query}")
        self.assertEqual(ranker.rank("beacon", self.index), [])
        self.assertEqual(ranker.errors, 1)

    def test_no_shell_is_involved(self):
        argv = ExternalRanker("mysearch {query}").argv("a; rm -rf b")
        self.assertEqual(argv, ["mysearch", "a; rm -rf b"])


if __name__ == "__main__":
    unittest.main()
