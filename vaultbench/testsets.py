"""Test sets built from the vault's own structure, with no labelling and no model.

Every set here is a list of cases. A case is a query string plus the set of notes that count
as a right answer, and it comes from something the vault already contains for another
reason: a note's name, the words people use when they link to it, a one line summary in an
index note, or a sentence that cites a source.

A case also carries its split. The split is the parity of the sha1 of the query text, so the
same query always lands on the same side however the sets are rebuilt, and no shuffle or
saved seed is needed to keep dev and held-out apart.
"""

import hashlib
import re

from . import vault as vaultmod
from .rankers import terms_of

DASHES = chr(8212) + chr(8211)   # the em dash and the en dash, by code point
DESC_RE = re.compile(
    r"^[ \t]*[-*+][ \t]+\[\[([^\[\]]+)\]\][ \t]*(?:[" + DASHES + r"]|-{1,2}|:)[ \t]*(.+?)[ \t]*$")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")


def split_of(query):
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()
    return "dev" if int(digest, 16) % 2 == 0 else "held"


def make_case(name, query, answers, meta=None):
    query = " ".join(query.split())
    answers = sorted(set(a for a in answers if a))
    return {"set": name, "query": query, "answers": answers,
            "split": split_of(query), "meta": meta or {}}


def dedupe(cases):
    """Drop repeats and put the list in a fixed order, so two runs agree exactly."""
    seen = set()
    out = []
    for case in cases:
        key = (case["set"], case["query"], tuple(case["answers"]))
        if key in seen or not case["query"] or not case["answers"]:
            continue
        seen.add(key)
        out.append(case)
    out.sort(key=lambda c: (c["query"], c["answers"]))
    return out


class TestSet(object):
    """A named list of cases, the corpus they are searched in, and how it was built."""

    def __init__(self, name, cases, corpus, stats=None):
        self.name = name
        self.cases = dedupe(cases)
        self.corpus = list(corpus)
        self.stats = dict(stats or {})

    def split(self, which="all"):
        if which in ("all", None):
            return list(self.cases)
        return [c for c in self.cases if c["split"] == which]

    def counts(self):
        return {"all": len(self.cases),
                "dev": len(self.split("dev")),
                "held": len(self.split("held"))}

    def to_json(self):
        return {"set": self.name, "corpus": self.corpus, "stats": self.stats,
                "counts": self.counts(), "cases": self.cases}


def _answerable(vault, answer_exclude):
    keep = []
    for rel in vault.answer_paths():
        if any(re.search(p, rel) for p in answer_exclude):
            continue
        keep.append(rel)
    return keep


def build_titles(vault, min_terms=2, answer_exclude=(), corpus=None):
    """Search a note's own title and see whether the note comes back.

    A known item lookup, and the easiest set in the file. It is a floor: a ranker that fails
    here is broken, and a ranker that passes here has proved nothing about topic search.
    """
    corpus = list(corpus if corpus is not None else vault.corpus_paths())
    cases = []
    skipped = 0
    for rel in _answerable(vault, answer_exclude):
        title = vault.notes[rel].title
        if len(terms_of(title)) < min_terms:
            skipped += 1
            continue
        cases.append(make_case("titles", title, [rel], {"source": rel}))
    return TestSet("titles", cases, corpus,
                   {"titles_too_short": skipped, "answer_notes": len(_answerable(vault, answer_exclude))})


def build_names(vault, min_alias_len=3, stoplist=(), answer_exclude=(), corpus=None,
                source_folders=(), target_folders=(), include_frontmatter=True):
    """Search the words people actually use for a note, and see whether the note comes back.

    Two sources, both free. Every `[[note|the words someone wrote]]` link is a person naming
    that note in their own words. Every `aliases:` entry in a note's frontmatter is the same
    thing written by the note's author. An alias that is just the note's title or filename
    teaches nothing, so it goes; so does an alias shorter than three characters, and anything
    in the stoplist. The notes that use an alias stay in the corpus as distractors.
    """
    corpus = list(corpus if corpus is not None else vault.corpus_paths())
    allowed = set(_answerable(vault, answer_exclude))
    stop = set(s.strip().lower() for s in stoplist)
    by_alias = {}
    counted = {"links": 0, "frontmatter": 0, "too_short": 0, "same_as_name": 0,
               "stoplisted": 0, "unresolved": 0, "out_of_scope": 0}

    def offer(alias, rel, kind):
        alias = " ".join((alias or "").split())
        if len(alias) < min_alias_len:
            counted["too_short"] += 1
            return
        if alias.lower() in stop:
            counted["stoplisted"] += 1
            return
        note = vault.notes[rel]
        if (alias.lower() == note.title.lower() or alias.lower() == note.stem.lower()
                or vaultmod.slug(alias) == vaultmod.slug(note.stem)
                or vaultmod.slug(alias) == vaultmod.slug(note.title)):
            counted["same_as_name"] += 1
            return
        by_alias.setdefault(alias, set()).add(rel)
        counted[kind] += 1

    for rel in vault.paths(source_folders):
        for link in vault.notes[rel].links:
            if not link.label:
                continue
            targets = vault.resolve(link.target)
            if not targets:
                counted["unresolved"] += 1
                continue
            for target in targets:
                if target not in allowed:
                    counted["out_of_scope"] += 1
                    continue
                if target_folders and not any(vaultmod.in_folder(target, f) for f in target_folders):
                    counted["out_of_scope"] += 1
                    continue
                offer(link.label, target, "links")

    if include_frontmatter:
        for rel in vault.paths(target_folders or source_folders):
            if rel not in allowed:
                continue
            for alias in vault.notes[rel].aliases:
                offer(alias, rel, "frontmatter")

    cases = [make_case("names", alias, sorted(rels), {"answers": len(rels)})
             for alias, rels in by_alias.items()]
    counted["distinct_aliases"] = len(by_alias)
    return TestSet("names", cases, corpus, counted)


def build_descriptions(vault, index_rel, min_terms=3, answer_exclude=(), corpus=None):
    """Search a note's one line summary and see whether the note comes back.

    This needs an index note whose lines read `- [[note]] then a separator then one line of
    what it is`. The index note itself is removed from the corpus, because it contains every
    query in the set and would otherwise win all of them.
    """
    corpus = list(corpus if corpus is not None else vault.corpus_paths())
    corpus = [c for c in corpus if c != index_rel]
    note = vault.notes.get(index_rel)
    allowed = set(_answerable(vault, answer_exclude))
    cases = []
    stats = {"lines": 0, "matched": 0, "unresolved": 0, "too_short": 0, "out_of_scope": 0}
    if note is None:
        stats["missing_index"] = 1
        return TestSet("descriptions", cases, corpus, stats)
    for line in note.body.split("\n"):
        if not line.strip():
            continue
        stats["lines"] += 1
        match = DESC_RE.match(line)
        if not match:
            continue
        target, _, _ = vaultmod.split_link(match.group(1))
        targets = vault.resolve(target)
        if not targets:
            stats["unresolved"] += 1
            continue
        rel = targets[0]
        if rel not in allowed:
            stats["out_of_scope"] += 1
            continue
        query = vaultmod.strip_links(match.group(2))
        query = re.sub(r"[*`_]+", " ", query)
        if len(terms_of(query)) < min_terms:
            stats["too_short"] += 1
            continue
        stats["matched"] += 1
        cases.append(make_case("descriptions", query, [rel], {"source": index_rel}))
    return TestSet("descriptions", cases, corpus, stats)


def iter_sentences(body, skip_tables=True):
    """The body's sentences, with links masked so a dot inside a link cannot split one."""
    masked = []
    holes = []

    def hide(match):
        holes.append(match.group(0))
        return "\x00%d\x00" % (len(holes) - 1)

    in_fence = False
    for line in body.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        if skip_tables and line.lstrip().startswith("|"):
            continue
        masked.append(vaultmod.LINK_RE.sub(hide, line))
    for line in masked:
        for piece in SENTENCE_SPLIT.split(line):
            if not piece.strip():
                continue
            yield re.sub(r"\x00(\d+)\x00", lambda m: holes[int(m.group(1))], piece)


def build_linked_sentences(vault, anchored_only=False, target_folders=(), source_folders=(),
                           min_terms=4, per_link=True, answer_exclude=(), corpus=None,
                           name="linked_sentences", skip_tables=True):
    """Search the sentence that links to a note, with the link taken out, and see whether
    the note comes back.

    This is the one set here whose queries are long. It is close to the question a note
    taking assistant actually asks, which is "where did this claim come from", and it is
    nothing like what a person types into a search box. Read the two results separately.

    `anchored_only` keeps sentences whose link points at a block or heading inside the
    target, which in a vault that cites its sources is the mark of a citation rather than a
    passing mention. `per_link` writes one case per link; turn it off to write one case per
    sentence, with every qualifying link removed and all of their targets accepted.
    """
    corpus = list(corpus if corpus is not None else vault.corpus_paths())
    allowed = set(_answerable(vault, answer_exclude))
    cases = []
    stats = {"sentences": 0, "with_links": 0, "kept": 0, "too_short": 0, "unresolved": 0}

    def qualifies(link):
        if anchored_only and not link.anchored:
            return []
        targets = [t for t in vault.resolve(link.target) if t in allowed]
        if target_folders:
            targets = [t for t in targets
                       if any(vaultmod.in_folder(t, f) for f in target_folders)]
        return targets

    for rel in vault.paths(source_folders):
        for sentence in iter_sentences(vault.notes[rel].body, skip_tables=skip_tables):
            stats["sentences"] += 1
            links = vaultmod.find_links(sentence)
            if not links:
                continue
            good = [(link, qualifies(link)) for link in links]
            good = [(link, targets) for link, targets in good if targets]
            if not good:
                continue
            stats["with_links"] += 1
            groups = [[pair] for pair in good] if per_link else [good]
            for group in groups:
                drop = [link for link, _ in group]
                answers = sorted(set(t for _, targets in group for t in targets))
                query = vaultmod.strip_links(sentence, drop=drop)
                query = re.sub(r"[*`_>]+", " ", query)
                if len(terms_of(query)) < min_terms:
                    stats["too_short"] += 1
                    continue
                stats["kept"] += 1
                cases.append(make_case(name, query, answers, {"source": rel}))
    return TestSet(name, cases, corpus, stats)
