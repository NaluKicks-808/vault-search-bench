"""Load a folder of markdown notes, with no third party libraries.

A vault here is just a directory tree of `.md` files. This module reads them, parses the
little bit of YAML that note frontmatter actually uses (scalars and simple lists), finds
every `[[wikilink]]`, and resolves a link target to the note or notes it points at.

Nothing in this file writes to disk.
"""

import os
import re

LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
SLUG_RE = re.compile(r"[^a-z0-9]+")


class Link(object):
    """One `[[target#anchor|label]]` occurrence, with where it sits in the text."""

    __slots__ = ("target", "anchor", "label", "start", "end", "raw")

    def __init__(self, target, anchor, label, start, end, raw):
        self.target = target
        self.anchor = anchor
        self.label = label
        self.start = start
        self.end = end
        self.raw = raw

    @property
    def text(self):
        """What a reader sees: the label if there is one, else the target."""
        return self.label or self.target

    @property
    def anchored(self):
        return bool(self.anchor)

    def __repr__(self):
        return "Link(%r, %r, %r)" % (self.target, self.anchor, self.label)


def split_link(inner):
    """Split the inside of a wikilink into (target, anchor, label).

    Obsidian requires a pipe inside a table cell to be written `\\|`, so a link in a table
    row reads `[[note#^id\\|label]]`. Both spellings mean the same thing here.
    """
    inner = inner.replace("\\|", "|")
    target, sep, label = inner.partition("|")
    label = label.strip() if sep else ""
    base, _, anchor = target.partition("#")
    return base.strip(), anchor.strip(), label


def find_links(text):
    """Every wikilink in `text`, in the order they appear."""
    out = []
    for m in LINK_RE.finditer(text):
        target, anchor, label = split_link(m.group(1))
        if not target and not anchor:
            continue
        out.append(Link(target, anchor, label, m.start(), m.end(), m.group(0)))
    return out


def strip_links(text, drop=()):
    """Reduce links to their display text, and delete the ones in `drop` entirely.

    `drop` is a collection of Link objects taken from this same string. This is how a test
    query stops being a giveaway: the link that holds the answer is removed, and the links
    that merely decorate the sentence become ordinary words.
    """
    drop_spans = set((d.start, d.end) for d in drop)
    out = []
    at = 0
    for link in find_links(text):
        out.append(text[at:link.start])
        if (link.start, link.end) not in drop_spans:
            out.append(link.text)
        at = link.end
    out.append(text[at:])
    return "".join(out)


def _scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value.strip()


def parse_frontmatter(text):
    """Return (mapping, body). Handles `key: value`, `key: [a, b]`, and block lists.

    This is deliberately not a YAML parser. Note frontmatter in practice is a flat mapping
    of strings and lists of strings, and anything fancier is left as the raw string.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    body = text[match.end():]
    data = {}
    key = None
    for line in match.group(1).split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if line[:1] in (" ", "\t") and stripped.startswith("- ") and key is not None:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(_scalar(stripped[2:]))
            continue
        name, sep, value = line.partition(":")
        if not sep or not name.strip() or " " in name.strip():
            continue
        key = name.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [_scalar(p) for p in value[1:-1].split(",")]
            data[key] = [p for p in items if p]
        elif value:
            data[key] = _scalar(value)
        else:
            data[key] = []
    return data, body


def slug(value):
    return SLUG_RE.sub("-", value.lower()).strip("-")


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v]
    value = str(value).strip()
    return [value] if value else []


class Note(object):
    """One markdown file, parsed once."""

    def __init__(self, rel, path, text):
        self.rel = rel
        self.path = path
        self.text = text
        self.frontmatter, self.body = parse_frontmatter(text)
        self.stem = os.path.splitext(os.path.basename(rel))[0]
        self.folder = os.path.dirname(rel)

    @property
    def heading(self):
        match = re.search(r"^#[ \t]+(.+?)[ \t]*$", self.body, re.M)
        return match.group(1).strip() if match else ""

    @property
    def title(self):
        fm = self.frontmatter.get("title")
        if isinstance(fm, str) and fm.strip():
            return fm.strip()
        return self.heading or self.stem

    @property
    def aliases(self):
        out = []
        for key in ("aliases", "alias"):
            out.extend(as_list(self.frontmatter.get(key)))
        return out

    @property
    def summary(self):
        """The first ordinary line of the body: what a search result shows under the name."""
        for line in self.body.split("\n"):
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith(">") and not s.startswith("---"):
                return s
        return ""

    @property
    def links(self):
        return find_links(self.body)

    def __repr__(self):
        return "Note(%r)" % (self.rel,)


_GLOB_CACHE = {}


def glob_re(pattern):
    """Compile a path glob the way people mean it.

    `**/` matches no folders or any number of them, so `wiki/**/*.md` finds `wiki/a.md` as
    well as `wiki/people/a.md`. A single `*` stops at a folder boundary, which is what
    `fnmatch` alone gets wrong.
    """
    if pattern in _GLOB_CACHE:
        return _GLOB_CACHE[pattern]
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    compiled = re.compile("".join(out) + r"\Z")
    _GLOB_CACHE[pattern] = compiled
    return compiled


def _match_any(rel, patterns):
    return any(glob_re(p).match(rel) for p in patterns)


def in_folder(rel, folder):
    """True when `rel` sits inside `folder`. An empty folder means the whole vault."""
    folder = (folder or "").strip("/")
    if not folder or folder == ".":
        return True
    return rel == folder or rel.startswith(folder + "/")


class Vault(object):
    """Every note under `root`, plus the index that resolves a link target to notes.

    `answer_folders` are the folders a test set may draw right answers from. `corpus_folders`
    are the folders a ranker is allowed to search. They are usually the same, and they differ
    for a set like claim to source, where the question comes from one folder and the answer
    lives in another.
    """

    def __init__(self, root, include=("**/*.md",), exclude=(),
                 answer_folders=(), corpus_folders=()):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.include = tuple(include)
        self.exclude = tuple(exclude)
        self.answer_folders = tuple(answer_folders)
        self.corpus_folders = tuple(corpus_folders)
        self.notes = {}
        self._load()
        self._build_index()

    def _load(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if not name.lower().endswith(".md"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, self.root).replace(os.sep, "/")
                if not _match_any(rel, self.include):
                    continue
                if self.exclude and _match_any(rel, self.exclude):
                    continue
                try:
                    with open(path, encoding="utf-8", errors="ignore") as fh:
                        text = fh.read()
                except (IOError, OSError):
                    continue
                self.notes[rel] = Note(rel, path, text)

    def _build_index(self):
        self.index = {}
        self.alias_index = {}
        for rel in sorted(self.notes):
            note = self.notes[rel]
            keys = {rel.lower(), rel[:-3].lower(), note.stem.lower(), slug(note.stem),
                    note.title.lower(), slug(note.title)}
            for alias in note.aliases:
                keys.add(alias.lower())
                keys.add(slug(alias))
                self.alias_index.setdefault(alias.strip().lower(), set()).add(rel)
            for key in keys:
                if key:
                    self.index.setdefault(key, []).append(rel)

    def resolve(self, target):
        """Every note a link target could mean, most specific first, or an empty list."""
        target = (target or "").strip()
        if not target:
            return []
        for key in (target.lower(), target.lower() + ".md", slug(target)):
            hit = self.index.get(key)
            if hit:
                return list(dict.fromkeys(hit))
        return []

    def resolve_one(self, target):
        hit = self.resolve(target)
        return hit[0] if len(hit) == 1 else (hit[0] if hit else None)

    def paths(self, folders=()):
        folders = tuple(folders)
        rels = sorted(self.notes)
        if not folders:
            return rels
        return [r for r in rels if any(in_folder(r, f) for f in folders)]

    def corpus_paths(self):
        return self.paths(self.corpus_folders)

    def answer_paths(self):
        return self.paths(self.answer_folders or self.corpus_folders)
