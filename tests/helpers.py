import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixture_vault")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def notes_vault(**kwargs):
    """The fixture vault with the article folder as both corpus and answer space."""
    from vaultbench import Vault
    options = {"answer_folders": ("notes",), "corpus_folders": ("notes",)}
    options.update(kwargs)
    return Vault(FIXTURE, **options)


def whole_vault(**kwargs):
    from vaultbench import Vault
    return Vault(FIXTURE, **kwargs)


def write_vault(root, files):
    """Write a dictionary of {relative path: text} and return the folder."""
    for rel, text in files.items():
        path = os.path.join(root, rel)
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return root
