"""Scoring, with the count behind every percentage.

A case is a hit at k when any of its right answers is in the first k results. The reciprocal
rank is one divided by the position of the best placed right answer, and zero when none of
them was returned at all. Everything here is a plain average over the cases scored; there is
no weighting and no smoothing.

Percentages are printed with the count beside them on purpose. Eighty percent of five cases
and eighty percent of five hundred are the same number and not the same evidence.
"""


def rank_of(answers, ranked):
    """The one based position of the best placed right answer, or None."""
    wanted = set(answers)
    for i, rel in enumerate(ranked, 1):
        if rel in wanted:
            return i
    return None


def score(ranks, ks=(1, 3, 10)):
    """Turn a list of ranks (None for a miss) into the summary numbers."""
    n = len(ranks)
    found = [r for r in ranks if r]
    out = {"n": n, "found": len(found), "ks": list(ks)}
    for k in ks:
        hits = sum(1 for r in found if r <= k)
        out["top%d" % k] = hits
        out["top%d_rate" % k] = (hits / float(n)) if n else 0.0
    out["mrr"] = (sum(1.0 / r for r in found) / n) if n else 0.0
    ordered = sorted(found)
    out["median_rank"] = ordered[len(ordered) // 2] if ordered else None
    return out


def evaluate(cases, ranked_lists, ks=(1, 3, 10)):
    ranks = [rank_of(case["answers"], ranked)
             for case, ranked in zip(cases, ranked_lists)]
    result = score(ranks, ks)
    result["ranks"] = ranks
    return result


def pct(part, whole):
    return "%5.1f%%" % (100.0 * part / whole) if whole else "    n/a"


def table(rows, ks=(1, 3, 10)):
    """`rows` is a list of (set name, ranker name, score dict). Returns printable text."""
    head = ["set", "ranker", "n"]
    for k in ks:
        head.append("top-%d" % k)
    head.append("MRR")
    widths = [max(12, max([len(str(r[0])) for r in rows] + [3])),
              max(10, max([len(str(r[1])) for r in rows] + [6])), 6]
    widths.extend([16] * len(ks))
    widths.append(6)
    lines = ["  ".join(h.ljust(w) for h, w in zip(head, widths)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for name, ranker, s in rows:
        cells = [str(name).ljust(widths[0]), str(ranker).ljust(widths[1]),
                 str(s["n"]).ljust(widths[2])]
        for i, k in enumerate(ks):
            cell = "%s (%s)" % (str(s["top%d" % k]).rjust(4), pct(s["top%d" % k], s["n"]))
            cells.append(cell.ljust(widths[3 + i]))
        cells.append(("%.3f" % s["mrr"]).ljust(widths[-1]))
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)
