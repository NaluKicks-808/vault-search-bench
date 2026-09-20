"""The rankers a vault can be searched with, plus the plug for an outside one.

Every ranker takes a query string and an `Index` and returns a list of note paths, best
first. A ranker may leave a note out entirely: a note with no match is not ranked, the way
a plain search tool shows nothing for a word it cannot find.

Ties keep the order the notes came in, which is alphabetical by path. That is a real
property of the two simple rankers here and the tests check it, because a ranker that
breaks ties randomly cannot be compared with itself from one run to the next.
"""

import math
import os
import re
import shlex
import subprocess

TERM_RE = re.compile(r"[a-z0-9'&-]+")

STOPWORDS = frozenset(
    "the a an and or of in on for to with at by from is was his her its it as that this "
    "what how who why when vs not".split())


def terms_of(query, min_len=3, stopwords=STOPWORDS):
    """The distinct usable words of a query, lowercased, in order of first appearance."""
    words = [w for w in TERM_RE.findall(query.lower())
             if len(w) >= min_len and w not in stopwords]
    return list(dict.fromkeys(words))


class Index(object):
    """The searchable form of a corpus: lowercased text, lines and paths, prepared once."""

    def __init__(self, vault, paths=None):
        self.vault = vault
        self.paths = list(paths if paths is not None else vault.corpus_paths())
        self.text = {}
        self.lines = {}
        self.path_low = {}
        self.title = {}
        for rel in self.paths:
            note = vault.notes[rel]
            self.text[rel] = note.text.lower()
            self.lines[rel] = [l for l in self.text[rel].split("\n") if l.strip()]
            self.path_low[rel] = rel.lower()
            self.title[rel] = note.title.lower()
        self._bm25 = None

    def subset(self, paths):
        keep = set(paths)
        clone = object.__new__(Index)
        clone.vault = self.vault
        clone.paths = [p for p in self.paths if p in keep]
        clone.text = self.text
        clone.lines = self.lines
        clone.path_low = self.path_low
        clone.title = self.title
        clone._bm25 = None
        return clone

    def bm25_stats(self):
        if self._bm25 is None:
            freqs = {}
            lengths = {}
            df = {}
            for rel in self.paths:
                counts = {}
                tokens = TERM_RE.findall(self.text[rel])
                for token in tokens:
                    counts[token] = counts.get(token, 0) + 1
                freqs[rel] = counts
                lengths[rel] = len(tokens) or 1
                for token in counts:
                    df[token] = df.get(token, 0) + 1
            total = sum(lengths.values())
            avg = total / float(len(lengths)) if lengths else 1.0
            self._bm25 = (freqs, lengths, df, avg)
        return self._bm25

    def matching_lines(self, rel, terms, limit=5):
        out = []
        for line in self.lines[rel]:
            if any(t in line for t in terms):
                out.append(line.strip())
                if len(out) >= limit:
                    break
        return out


class Ranker(object):
    name = "ranker"

    def rank(self, query, index):
        raise NotImplementedError


class CountRanker(Ranker):
    """Raw substring counts, OR-ed over the query's words.

    This is what a small hand written search script usually does: count how many times each
    word appears in each file and sort by the total. It is a strong baseline for a query
    that repeats a rare word and a weak one for a long sentence, because a long file wins on
    volume alone.
    """

    name = "count"

    def __init__(self, min_len=3, stopwords=STOPWORDS):
        self.min_len = min_len
        self.stopwords = stopwords

    def rank(self, query, index):
        terms = terms_of(query, self.min_len, self.stopwords)
        if not terms:
            return []
        scored = []
        for rel in index.paths:
            text = index.text[rel]
            score = sum(text.count(t) for t in terms)
            if score:
                scored.append((score, rel))
        scored.sort(key=lambda pair: -pair[0])
        return [rel for _, rel in scored]


class TieredRanker(Ranker):
    """Ten points per distinct query word present, two for a word in the path, up to three
    for lines that match. A word counts once however often it appears, so a long file no
    longer wins by volume, and a file whose name carries a query word edges ahead of one
    that only mentions it.
    """

    name = "tiered"

    def __init__(self, min_len=3, stopwords=STOPWORDS, word_points=10, path_points=2,
                 line_cap=3):
        self.min_len = min_len
        self.stopwords = stopwords
        self.word_points = word_points
        self.path_points = path_points
        self.line_cap = line_cap

    def rank(self, query, index):
        terms = terms_of(query, self.min_len, self.stopwords)
        if not terms:
            return []
        scored = []
        for rel in index.paths:
            text = index.text[rel]
            present = [t for t in terms if t in text]
            if not present:
                continue
            fragments = 0
            for line in index.lines[rel]:
                if any(t in line for t in terms):
                    fragments += 1
                    if fragments >= self.line_cap:
                        break
            name = self.path_points if any(t in index.path_low[rel] for t in terms) else 0
            scored.append((len(present) * self.word_points + name + fragments, rel))
        scored.sort(key=lambda pair: -pair[0])
        return [rel for _, rel in scored]


class BM25Ranker(Ranker):
    """Okapi BM25 with the usual constants, and an optional boost for a word in the title.

    BM25 is the standard classical baseline: a word is worth more when few files contain it,
    a repeat of the same word is worth less each time (k1), and a long file is discounted (b).
    """

    name = "bm25"

    def __init__(self, k1=1.2, b=0.75, title_boost=0.0, min_len=3, stopwords=STOPWORDS):
        self.k1 = k1
        self.b = b
        self.title_boost = title_boost
        self.min_len = min_len
        self.stopwords = stopwords

    def rank(self, query, index):
        terms = terms_of(query, self.min_len, self.stopwords)
        if not terms:
            return []
        freqs, lengths, df, avg = index.bm25_stats()
        n = len(index.paths) or 1
        idf = {}
        for t in terms:
            seen = df.get(t, 0)
            idf[t] = math.log(1.0 + (n - seen + 0.5) / (seen + 0.5))
        scored = []
        for rel in index.paths:
            counts = freqs[rel]
            length = lengths[rel]
            score = 0.0
            hit = False
            for t in terms:
                f = counts.get(t, 0)
                if f:
                    hit = True
                    denom = f + self.k1 * (1.0 - self.b + self.b * length / avg)
                    score += idf[t] * f * (self.k1 + 1.0) / denom
                if self.title_boost and t in index.title[rel]:
                    hit = True
                    score += self.title_boost * idf[t]
            if hit:
                scored.append((score, rel))
        scored.sort(key=lambda pair: -pair[0])
        return [rel for _, rel in scored]


class ExternalRanker(Ranker):
    """Any search tool of your own, as long as it prints one file path per line.

    The command is a template holding `{query}`, for example `mysearch --top 20 {query}`.
    The template is split into arguments first and the query is substituted into whichever
    argument holds the placeholder, so a query with spaces or quotes in it stays one
    argument and no shell is involved. Paths may be absolute or relative to the vault root;
    anything that is not a note in the corpus is ignored.
    """

    name = "external"

    def __init__(self, template, cwd=None, timeout=60, name=None):
        self.template = template
        self.cwd = cwd
        self.timeout = timeout
        if name:
            self.name = name
        self.errors = 0

    def argv(self, query):
        parts = shlex.split(self.template)
        if not any("{query}" in p for p in parts):
            parts.append("{query}")
        return [p.replace("{query}", query) for p in parts]

    def parse(self, stdout, index):
        root = index.vault.root
        known = set(index.paths)
        out = []
        for line in stdout.split("\n"):
            line = line.strip()
            if not line:
                continue
            candidate = line
            if os.path.isabs(candidate):
                try:
                    candidate = os.path.relpath(candidate, root)
                except ValueError:
                    continue
            candidate = candidate.replace(os.sep, "/").lstrip("./")
            if candidate in known and candidate not in out:
                out.append(candidate)
        return out

    def rank(self, query, index):
        try:
            done = subprocess.run(self.argv(query), cwd=self.cwd, timeout=self.timeout,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, subprocess.SubprocessError):
            self.errors += 1
            return []
        return self.parse(done.stdout.decode("utf-8", "ignore"), index)


BUILTIN = {"count": CountRanker, "tiered": TieredRanker, "bm25": BM25Ranker}


def build_ranker(spec, vault_root=None):
    """`count`, `tiered`, `bm25`, `bm25:title_boost=1.5`, or `cmd:<template>`."""
    if spec.startswith("cmd:"):
        return ExternalRanker(spec[4:], cwd=vault_root)
    name, _, tail = spec.partition(":")
    if name not in BUILTIN:
        raise ValueError("unknown ranker %r; try one of %s" % (spec, ", ".join(sorted(BUILTIN))))
    kwargs = {}
    for piece in tail.split(",") if tail else []:
        if not piece.strip():
            continue
        key, _, value = piece.partition("=")
        kwargs[key.strip()] = float(value) if value.strip() else True
    return BUILTIN[name](**kwargs)
