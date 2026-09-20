"""The optional second pass: reorder the top few results with something smarter.

A reranker is any Python callable of two arguments:

    order = rerank(query, candidates)

`candidates` is a list of dictionaries, best first, each holding

    {"path": "notes/a-note.md",
     "title": "A note",
     "summary": "the note's first ordinary line",
     "lines": ["the lines in the note that match the query", ...]}

and the callable returns the same candidates in the order it prefers. It may return the
dictionaries, or just their `path` strings; both are accepted. Anything it leaves out keeps
its original relative position at the end, so a reranker cannot silently lose a result.

Reranking is off unless you ask for it. It is a second pass over the first N results only,
so it can reorder what the ranker found and can never find what the ranker missed.
"""

import importlib
import importlib.util
import os


def candidates_for(query, ranked, index, depth=20, lines=5):
    from .rankers import terms_of
    terms = terms_of(query)
    out = []
    for rel in ranked[:depth]:
        note = index.vault.notes[rel]
        out.append({"path": rel, "title": note.title, "summary": note.summary,
                    "lines": index.matching_lines(rel, terms, lines)})
    return out


def apply_rerank(query, ranked, index, reranker, depth=20, lines=5):
    """Run the reranker over the head of `ranked` and stitch the tail back on."""
    head = ranked[:depth]
    tail = ranked[depth:]
    if len(head) < 2:
        return list(ranked)
    ordered = reranker(query, candidates_for(query, ranked, index, depth, lines))
    out = []
    for item in ordered or []:
        path = item.get("path") if isinstance(item, dict) else item
        if path in head and path not in out:
            out.append(path)
    for path in head:
        if path not in out:
            out.append(path)
    return out + tail


def load_reranker(spec):
    """`package.module:callable`, or `path/to/file.py:callable`."""
    target, _, attr = spec.partition(":")
    attr = attr or "rerank"
    if target.endswith(".py") or os.sep in target:
        path = os.path.abspath(os.path.expanduser(target))
        name = "vaultbench_reranker_" + os.path.splitext(os.path.basename(path))[0]
        spec_obj = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    return getattr(module, attr)
