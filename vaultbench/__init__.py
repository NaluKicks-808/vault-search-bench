"""vault-search-bench: measure search over a folder of linked markdown notes.

The links in a vault are an answer key nobody had to write. Import what you need:

    from vaultbench import Vault, build_titles, build_names, Index, TieredRanker, evaluate
"""

from .vault import Vault, Note, Link, find_links, split_link, strip_links
from .rankers import (Index, Ranker, CountRanker, TieredRanker, BM25Ranker,
                      ExternalRanker, build_ranker, terms_of)
from .testsets import (TestSet, build_titles, build_names, build_descriptions,
                       build_linked_sentences, split_of, make_case)
from .metrics import evaluate, score, rank_of, table
from .rerank import apply_rerank, candidates_for, load_reranker

__version__ = "0.1.0"

__all__ = [
    "Vault", "Note", "Link", "find_links", "split_link", "strip_links",
    "Index", "Ranker", "CountRanker", "TieredRanker", "BM25Ranker", "ExternalRanker",
    "build_ranker", "terms_of", "TestSet", "build_titles", "build_names",
    "build_descriptions", "build_linked_sentences", "split_of", "make_case",
    "evaluate", "score", "rank_of", "table", "apply_rerank", "candidates_for",
    "load_reranker", "__version__",
]
