import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from helpers import FIXTURE

from vaultbench.cli import main

COMMON = ["--vault", FIXTURE, "--corpus-folders", "notes", "--answer-folders", "notes",
          "--index-note", "notes/_catalogue.md"]


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    return code, out.getvalue()


class TestCommandLine(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vaultbench-cli-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sets_prints_a_count_per_set_and_split(self):
        code, text = run(["sets"] + COMMON)
        self.assertEqual(code, 0)
        for name in ("titles", "names", "descriptions", "linked_sentences"):
            self.assertIn(name, text)
        self.assertIn("dev", text)
        self.assertIn("held", text)

    def test_sets_writes_one_file_per_set(self):
        run(["sets"] + COMMON + ["--out", self.tmp])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "titles.json")))
        with open(os.path.join(self.tmp, "titles.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["set"], "titles")
        self.assertEqual(data["counts"]["all"], len(data["cases"]))

    def test_run_scores_every_named_ranker(self):
        code, text = run(["run"] + COMMON + ["--sets", "titles", "--ranker", "count,tiered",
                                             "--split", "all"])
        self.assertEqual(code, 0)
        self.assertIn("count", text)
        self.assertIn("tiered", text)
        self.assertIn("100.0%", text)

    def test_run_writes_json_with_the_counts_behind_the_rates(self):
        path = os.path.join(self.tmp, "result.json")
        run(["run"] + COMMON + ["--sets", "titles", "--split", "all", "--json", path])
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        block = data["sets"]["titles"]["rankers"]["tiered"]
        self.assertEqual(block["n"], 4)
        self.assertEqual(block["top1"], 4)

    def test_sample_and_seed_are_repeatable(self):
        args = ["run"] + COMMON + ["--sets", "names", "--split", "all", "--sample", "2",
                                   "--seed", "11"]
        self.assertEqual(run(args)[1], run(args)[1])

    def test_split_choices_are_enforced(self):
        self.assertRaises(SystemExit, run, ["run"] + COMMON + ["--split", "nonsense"])


if __name__ == "__main__":
    unittest.main()
