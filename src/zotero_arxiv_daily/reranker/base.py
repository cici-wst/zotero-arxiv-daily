from abc import ABC, abstractmethod
from omegaconf import DictConfig
from ..protocol import Paper, CorpusPaper
import numpy as np
from typing import Type

TOP_SIMILAR_PAPERS = 5
SCORE_SCALE = 10.0
MIN_SCORE = 0.0
MAX_SCORE = 10.0


class BaseReranker(ABC):
    def __init__(self, config:DictConfig):
        self.config = config

    def rerank(self, candidates:list[Paper], corpus:list[CorpusPaper]) -> list[Paper]:
        if not corpus:
            raise ValueError("Cannot rerank against an empty Zotero corpus")
        sim = self.get_similarity_score([c.abstract for c in candidates], [c.abstract for c in corpus])
        assert sim.shape == (len(candidates), len(corpus))
        top_count = min(TOP_SIMILAR_PAPERS, len(corpus))
        top_similarities = np.partition(sim, -top_count, axis=1)[:, -top_count:]
        scores = np.clip(top_similarities.mean(axis=1) * SCORE_SCALE, MIN_SCORE, MAX_SCORE)
        for s,c in zip(scores,candidates):
            c.score = s
        candidates = sorted(candidates,key=lambda x: x.score,reverse=True)
        return candidates
    
    @abstractmethod
    def get_similarity_score(self, s1:list[str], s2:list[str]) -> np.ndarray:
        raise NotImplementedError

registered_rerankers = {}

def register_reranker(name:str):
    def decorator(cls):
        registered_rerankers[name] = cls
        return cls
    return decorator

def get_reranker_cls(name:str) -> Type[BaseReranker]:
    if name not in registered_rerankers:
        raise ValueError(f"Reranker {name} not found")
    return registered_rerankers[name]
