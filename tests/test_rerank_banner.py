"""The CLI must never let a dry-run rerank row pass for a measurement."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RerankBanner(unittest.TestCase):
    def run_cli(self, env_extra):
        env = dict(os.environ)
        env.pop("JEV_DRY_RUN", None)
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-m", "vaultbench", "run", "--vault", os.path.join(ROOT, "tests", "fixture_vault"),
             "--ranker", "tiered", "--rerank", "vaultbench.jev_rerank:rerank", "--split", "all"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120).stdout

    def test_default_run_is_dry_and_says_so(self):
        out = self.run_cli({})
        self.assertIn("RERANK ROWS ARE PLACEHOLDERS", out)
        self.assertIn("no model was called", out)

    def test_plain_run_prints_no_rerank_notice(self):
        env = dict(os.environ)
        out = subprocess.run(
            [sys.executable, "-m", "vaultbench", "run", "--vault", os.path.join(ROOT, "tests", "fixture_vault"),
             "--ranker", "tiered", "--split", "all"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120).stdout
        self.assertNotIn("RERANK", out)


if __name__ == "__main__":
    unittest.main()
