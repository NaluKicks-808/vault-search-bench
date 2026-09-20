import unittest

from helpers import notes_vault, whole_vault

from vaultbench import find_links, split_link, strip_links
from vaultbench.vault import glob_re, parse_frontmatter, slug


class TestLinkParsing(unittest.TestCase):

    def test_plain_link(self):
        self.assertEqual(split_link("lamp-room-rota"), ("lamp-room-rota", "", ""))

    def test_labelled_link(self):
        self.assertEqual(split_link("foghorn-repair|horn work"),
                         ("foghorn-repair", "", "horn work"))

    def test_anchor_and_label(self):
        target, anchor, label = split_link("2026-01-04_workshop-notes#^compressor|the notes")
        self.assertEqual(target, "2026-01-04_workshop-notes")
        self.assertEqual(anchor, "^compressor")
        self.assertEqual(label, "the notes")

    def test_escaped_pipe_inside_a_table_row(self):
        row = r"| Cloth | [[2026-01-04_workshop-notes#^cloth\|the cloth line]] |"
        links = find_links(row)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].target, "2026-01-04_workshop-notes")
        self.assertEqual(links[0].anchor, "^cloth")
        self.assertEqual(links[0].label, "the cloth line")
        self.assertTrue(links[0].anchored)

    def test_heading_anchor_is_an_anchor_too(self):
        self.assertEqual(split_link("a-note#A heading")[1], "A heading")

    def test_two_links_keep_their_order_and_spans(self):
        text = "see [[one|first]] and then [[two]] at the end"
        links = find_links(text)
        self.assertEqual([l.text for l in links], ["first", "two"])
        self.assertEqual(text[links[0].start:links[0].end], "[[one|first]]")

    def test_strip_links_reduces_to_display_text(self):
        text = "after the [[foghorn-repair|horn work]] and [[lens-polish]]"
        self.assertEqual(strip_links(text), "after the horn work and lens-polish")

    def test_strip_links_can_delete_the_answer(self):
        text = "the reason is in [[2026-01-04_workshop-notes#^compressor|the notes]] today"
        dropped = find_links(text)
        self.assertEqual(strip_links(text, drop=dropped), "the reason is in  today")


class TestFrontmatter(unittest.TestCase):

    def test_block_list(self):
        data, body = parse_frontmatter("---\ntitle: A\naliases:\n  - one\n  - two\n---\n# A\n")
        self.assertEqual(data["title"], "A")
        self.assertEqual(data["aliases"], ["one", "two"])
        self.assertEqual(body, "# A\n")

    def test_inline_list_and_quotes(self):
        data, _ = parse_frontmatter("---\naliases: [one, \"two words\"]\n---\nbody\n")
        self.assertEqual(data["aliases"], ["one", "two words"])

    def test_no_frontmatter_is_all_body(self):
        data, body = parse_frontmatter("# just a note\n")
        self.assertEqual(data, {})
        self.assertEqual(body, "# just a note\n")

    def test_slug(self):
        self.assertEqual(slug("Lamp Room Rota"), "lamp-room-rota")


class TestGlobs(unittest.TestCase):

    def matches(self, pattern, rel):
        return bool(glob_re(pattern).match(rel))

    def test_double_star_means_here_or_below(self):
        self.assertTrue(self.matches("**/*.md", "a.md"))
        self.assertTrue(self.matches("**/*.md", "one/two/a.md"))
        self.assertTrue(self.matches("notes/**/*.md", "notes/a.md"))
        self.assertTrue(self.matches("notes/**/*.md", "notes/deep/a.md"))

    def test_a_folder_prefix_is_respected(self):
        self.assertFalse(self.matches("notes/**/*.md", "sources/a.md"))

    def test_a_single_star_stops_at_a_folder(self):
        self.assertTrue(self.matches("log/*", "log/changelog.md"))
        self.assertFalse(self.matches("log/*", "log/deep/changelog.md"))

    def test_include_reaches_a_note_at_the_top_of_a_folder(self):
        vault = whole_vault(include=("notes/**/*.md",))
        self.assertIn("notes/_catalogue.md", vault.notes)
        self.assertNotIn("sources/2026-01-04_workshop-notes.md", vault.notes)


class TestVaultLoading(unittest.TestCase):

    def test_loads_every_note(self):
        vault = whole_vault()
        self.assertEqual(len(vault.notes), 8)
        self.assertIn("notes/lamp-room-rota.md", vault.notes)
        self.assertIn("sources/2026-01-04_workshop-notes.md", vault.notes)

    def test_folders_split_corpus_from_answers(self):
        vault = notes_vault()
        self.assertEqual(len(vault.corpus_paths()), 5)
        self.assertTrue(all(p.startswith("notes/") for p in vault.answer_paths()))

    def test_exclude_glob(self):
        vault = whole_vault(exclude=("log/*",))
        self.assertNotIn("log/changelog.md", vault.notes)

    def test_title_and_summary(self):
        note = whole_vault().notes["notes/lamp-room-rota.md"]
        self.assertEqual(note.title, "Lamp room rota")
        self.assertTrue(note.summary.startswith("The rota decides who climbs"))

    def test_resolve_by_filename_title_and_alias(self):
        vault = whole_vault()
        self.assertEqual(vault.resolve("lamp-room-rota"), ["notes/lamp-room-rota.md"])
        self.assertEqual(vault.resolve("Lamp room rota"), ["notes/lamp-room-rota.md"])
        self.assertEqual(vault.resolve("the rota"), ["notes/lamp-room-rota.md"])
        self.assertEqual(vault.resolve("night watch order"), ["notes/lamp-room-rota.md"])
        self.assertEqual(vault.resolve("the horn job"), ["notes/foghorn-repair.md"])

    def test_resolve_a_missing_target(self):
        self.assertEqual(whole_vault().resolve("no-such-note"), [])


if __name__ == "__main__":
    unittest.main()
