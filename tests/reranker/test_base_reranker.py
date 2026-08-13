"""Tests for BaseReranker: scoring, sorting, and unknown reranker."""

import numpy as np
import pytest

from zotero_arxiv_daily.reranker.base import BaseReranker, get_reranker_cls
from tests.canned_responses import make_sample_paper, make_sample_corpus


class StubReranker(BaseReranker):
    """Reranker with a controlled similarity matrix for deterministic tests."""

    def __init__(self, sim_matrix: np.ndarray):
        self.config = None
        self._sim = sim_matrix

    def get_similarity_score(self, s1, s2):
        return self._sim


def test_rerank_scores_and_sorts():
    corpus = make_sample_corpus(3)
    papers = [make_sample_paper(title=f"Paper {i}") for i in range(2)]

    # Paper 1 has higher similarity to all corpus papers
    sim = np.array([
        [0.1, 0.1, 0.1],  # paper 0 — low
        [0.9, 0.9, 0.9],  # paper 1 — high
    ])
    reranker = StubReranker(sim)
    ranked = reranker.rerank(papers, corpus)
    assert ranked[0].title == "Paper 1"
    assert ranked[1].title == "Paper 0"
    assert ranked[0].score > ranked[1].score


def test_rerank_uses_mean_of_top_five_similarities():
    corpus = make_sample_corpus(7)
    papers = [make_sample_paper(title="P")]
    sim = np.array([[0.9, 0.8, 0.7, 0.6, 0.5, 0.1, 0.0]])

    ranked = StubReranker(sim).rerank(papers, corpus)

    assert ranked[0].score == pytest.approx(7.0)


def test_rerank_clips_scores_to_zero_to_ten():
    corpus = make_sample_corpus(2)
    papers = [
        make_sample_paper(title="Above"),
        make_sample_paper(title="Below"),
    ]
    sim = np.array([[1.2, 1.1], [-0.3, -0.1]])

    ranked = StubReranker(sim).rerank(papers, corpus)

    assert ranked[0].score == pytest.approx(10.0)
    assert ranked[1].score == pytest.approx(0.0)


def test_rerank_single_candidate_single_corpus():
    corpus = make_sample_corpus(1)
    papers = [make_sample_paper()]
    sim = np.array([[0.5]])
    reranker = StubReranker(sim)
    ranked = reranker.rerank(papers, corpus)
    assert len(ranked) == 1
    assert ranked[0].score is not None


def test_rerank_rejects_empty_zotero_corpus():
    papers = [make_sample_paper()]
    reranker = StubReranker(np.empty((1, 0)))

    with pytest.raises(ValueError, match="empty Zotero corpus"):
        reranker.rerank(papers, [])


def test_get_reranker_cls_unknown():
    with pytest.raises(ValueError, match="not found"):
        get_reranker_cls("nonexistent_reranker_xyz")
