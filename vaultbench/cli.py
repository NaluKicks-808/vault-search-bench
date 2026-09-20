"""The command line: build the sets, run the rankers, print the table.

    python3 -m vaultbench sets --vault ~/my-vault
    python3 -m vaultbench run  --vault ~/my-vault --ranker count,tiered,bm25 --split held
    python3 -m vaultbench run  --vault ~/my-vault --ranker-cmd 'mysearch --paths {query}'
"""

import argparse
import json
import os
import random
import sys
import time

from . import metrics, rankers, rerank as rerankmod, testsets
from .vault import Vault

ALL_SETS = ("titles", "names", "descriptions", "linked_sentences")


def comma(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def open_vault(args):
    return Vault(args.vault,
                 include=tuple(comma(args.include)) or ("**/*.md",),
                 exclude=tuple(comma(args.exclude)),
                 answer_folders=tuple(comma(args.answer_folders)),
                 corpus_folders=tuple(comma(args.corpus_folders)))


def build_sets(vault, args):
    wanted = comma(args.sets) or list(ALL_SETS)
    exclude = tuple(comma(args.answer_exclude))
    out = []
    for name in wanted:
        if name == "titles":
            out.append(testsets.build_titles(vault, min_terms=args.min_title_terms,
                                             answer_exclude=exclude))
        elif name == "names":
            out.append(testsets.build_names(vault, min_alias_len=args.min_alias_len,
                                            stoplist=comma(args.stoplist),
                                            answer_exclude=exclude))
        elif name == "descriptions":
            if not args.index_note:
                sys.stderr.write("the descriptions set needs --index-note; skipping it\n")
                continue
            out.append(testsets.build_descriptions(vault, args.index_note,
                                                   answer_exclude=exclude))
        elif name == "linked_sentences":
            out.append(testsets.build_linked_sentences(
                vault, anchored_only=args.anchored_only,
                target_folders=tuple(comma(args.target_folders)),
                answer_exclude=exclude))
        else:
            raise SystemExit("unknown set %r; known sets: %s" % (name, ", ".join(ALL_SETS)))
    return out


def sample(cases, n, seed):
    if not n or n >= len(cases):
        return cases
    picked = random.Random(seed).sample(range(len(cases)), n)
    return [cases[i] for i in sorted(picked)]


def cmd_sets(args):
    vault = open_vault(args)
    sets = build_sets(vault, args)
    print("%d notes loaded from %s" % (len(vault.notes), vault.root))
    for ts in sets:
        counts = ts.counts()
        print("%-18s all %5d   dev %5d   held %5d   corpus %5d"
              % (ts.name, counts["all"], counts["dev"], counts["held"], len(ts.corpus)))
        if args.verbose:
            print("    %s" % json.dumps(ts.stats, sort_keys=True))
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        for ts in sets:
            path = os.path.join(args.out, ts.name + ".json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(ts.to_json(), fh, indent=1, sort_keys=True)
            print("wrote %s" % path)
    return 0


def cmd_run(args):
    vault = open_vault(args)
    sets = build_sets(vault, args)
    specs = comma(args.ranker)
    if args.ranker_cmd:
        specs.append("cmd:" + args.ranker_cmd)
    if not specs:
        specs = ["count", "tiered"]
    reranker = rerankmod.load_reranker(args.rerank) if args.rerank else None
    rows = []
    payload = {"vault": vault.root, "split": args.split, "sets": {},
               "rankers": specs, "rerank": args.rerank or None}
    for ts in sets:
        index = rankers.Index(vault, ts.corpus)
        cases = sample(ts.split(args.split), args.sample, args.seed)
        payload["sets"][ts.name] = {"counts": ts.counts(), "scored": len(cases),
                                    "stats": ts.stats, "rankers": {}}
        for spec in specs:
            ranker = rankers.build_ranker(spec, vault_root=vault.root)
            started = time.time()
            ranked = [ranker.rank(case["query"], index) for case in cases]
            result = metrics.evaluate(cases, ranked)
            result["seconds"] = round(time.time() - started, 2)
            rows.append((ts.name, ranker.name, result))
            payload["sets"][ts.name]["rankers"][spec] = result
            if reranker is not None:
                started = time.time()
                moved = [rerankmod.apply_rerank(case["query"], r, index, reranker,
                                                depth=args.rerank_depth)
                         for case, r in zip(cases, ranked)]
                second = metrics.evaluate(cases, moved)
                second["seconds"] = round(time.time() - started, 2)
                label = ranker.name + "+rerank"
                rows.append((ts.name, label, second))
                payload["sets"][ts.name]["rankers"][spec + "+rerank"] = second
    print(metrics.table(rows))
    if reranker is not None:
        # A rerank row is only evidence if a model really answered. Say which it was, every time.
        totals = getattr(sys.modules.get(getattr(reranker, "__module__", "")), "TOTALS", None)
        payload["rerank_run"] = dict(totals) if totals else None
        print("")
        if totals is None:
            print("RERANK: a custom reranker ran; this tool cannot tell whether it called a model.")
        elif totals["dry_run_calls"]:
            print("RERANK ROWS ARE PLACEHOLDERS. This was a DRY RUN: no model was called, every pair "
                  "scored the same,\nties kept the plain order, so each '+rerank' row equals its plain "
                  "row BY CONSTRUCTION and says nothing.\nSet JEV_DRY_RUN=0 and a key to measure a "
                  "real reranker.")
        elif totals["errors"]:
            print("RERANK WARNING: %d of %d model calls FAILED (spend cap, network or key) and were "
                  "scored as ties.\nThe '+rerank' rows are partly or wholly the plain order. Check "
                  "ledger.jsonl and JEV_SPEND_CAP_USD before trusting them."
                  % (totals["errors"], totals["calls"]))
        else:
            print("RERANK: %d model calls over %d queries, 0 failed." % (totals["calls"], totals["queries"]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
        print("\nwrote %s" % args.json)
    return 0


def parser():
    ap = argparse.ArgumentParser(prog="vaultbench", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")

    def common(p):
        p.add_argument("--vault", required=True, help="folder of markdown notes")
        p.add_argument("--include", default="**/*.md", help="comma separated globs to include")
        p.add_argument("--exclude", default="", help="comma separated globs to skip")
        p.add_argument("--answer-folders", default="",
                       help="folders a right answer may come from (default: the corpus)")
        p.add_argument("--corpus-folders", default="",
                       help="folders a ranker may search (default: the whole vault)")
        p.add_argument("--answer-exclude", default="",
                       help="comma separated regexes; matching notes are never an answer")
        p.add_argument("--sets", default="", help="which sets to build (default: all)")
        p.add_argument("--index-note", default="",
                       help="the note holding one line summaries, for the descriptions set")
        p.add_argument("--stoplist", default="", help="aliases to drop from the names set")
        p.add_argument("--min-alias-len", type=int, default=3)
        p.add_argument("--min-title-terms", type=int, default=2)
        p.add_argument("--anchored-only", action="store_true",
                       help="linked sentences: keep only links that point inside a note")
        p.add_argument("--target-folders", default="",
                       help="linked sentences: folders the answer must live in")

    p_sets = sub.add_parser("sets", help="build the sets and print their sizes")
    common(p_sets)
    p_sets.add_argument("--out", default="", help="folder to write one JSON file per set")
    p_sets.add_argument("--verbose", action="store_true")
    p_sets.set_defaults(func=cmd_sets)

    p_run = sub.add_parser("run", help="score one or more rankers on the sets")
    common(p_run)
    p_run.add_argument("--ranker", default="count,tiered",
                       help="comma separated: count, tiered, bm25, bm25:title_boost=1.5")
    p_run.add_argument("--ranker-cmd", default="",
                       help="your own search command, with {query} in it, printing one path a line")
    p_run.add_argument("--split", default="dev", choices=["dev", "held", "all"])
    p_run.add_argument("--sample", type=int, default=0, help="score at most N cases per set")
    p_run.add_argument("--seed", type=int, default=7)
    p_run.add_argument("--rerank", default="",
                       help="module:callable or path/to/file.py:callable; off by default")
    p_run.add_argument("--rerank-depth", type=int, default=20)
    p_run.add_argument("--json", default="", help="write the full result here")
    p_run.set_defaults(func=cmd_run)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    if not getattr(args, "func", None):
        parser().print_help()
        return 2
    return args.func(args)
