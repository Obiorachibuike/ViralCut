"""Duplicate moment detection (spec 17).

Candidates generated from adjacent anchors frequently describe the same point.
We embed each candidate, cluster near-duplicates, and keep the strongest member
of every cluster so the results list never shows ten versions of one moment.

Two candidates are considered duplicates when their semantic similarity clears
the threshold **or** when one substantially contains the other in time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from moments.embeddings import Embedder, get_embedder
from moments.candidates import Candidate

logger = logging.getLogger("viralcut.moments.dedupe")


@dataclass(slots=True)
class Cluster:
    leader: int
    members: list[int]

    @property
    def size(self) -> int:
        return len(self.members)


def overlap_ratio(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    """Fraction of the *shorter* interval covered by the intersection."""
    intersection = max(0, min(a_end, b_end) - max(a_start, b_start))
    shorter = max(1, min(a_end - a_start, b_end - b_start))
    return intersection / shorter


def find_clusters(
    candidates: list[Candidate],
    *,
    embedder: Embedder | None = None,
    threshold: float = 0.72,
    overlap_threshold: float = 0.8,
) -> tuple[list[Cluster], np.ndarray]:
    """Greedy leader clustering: deterministic, O(n·k), stable ordering."""
    if not candidates:
        return [], np.zeros((0, 0), dtype=np.float32)

    embedder = embedder or get_embedder()
    vectors = embedder.embed_many([c.text for c in candidates])
    normalised = np.linalg.norm(vectors, axis=1, keepdims=True)
    normalised[normalised == 0] = 1.0
    vectors = vectors / normalised

    clusters: list[Cluster] = []
    for index, candidate in enumerate(candidates):
        placed = False
        for cluster in clusters:
            leader = candidates[cluster.leader]
            similarity = float(np.dot(vectors[index], vectors[cluster.leader]))
            temporal = overlap_ratio(
                candidate.start_ms, candidate.end_ms, leader.start_ms, leader.end_ms
            )
            if similarity >= threshold or temporal >= overlap_threshold:
                cluster.members.append(index)
                # Promote the strongest member to leader so the kept moment is
                # the best version of the topic, not merely the first seen.
                if candidate.final > candidates[cluster.leader].final:
                    cluster.leader = index
                placed = True
                break
        if not placed:
            clusters.append(Cluster(leader=index, members=[index]))

    logger.debug("clustered %d candidates into %d groups", len(candidates), len(clusters))
    return clusters, vectors


def dedupe(
    candidates: list[Candidate],
    *,
    embedder: Embedder | None = None,
    threshold: float = 0.72,
    overlap_threshold: float = 0.8,
    keep_losers: bool = False,
) -> tuple[list[Candidate], list[Cluster]]:
    """Return the best candidate per cluster.

    Every candidate gets a stable `cluster_id` on the way out, so the UI can
    offer "show duplicates" without re-running the pipeline.
    """
    if not candidates:
        return [], []

    clusters, _ = find_clusters(
        candidates, embedder=embedder, threshold=threshold, overlap_threshold=overlap_threshold
    )

    survivors: list[Candidate] = []
    for cluster in clusters:
        best = candidates[cluster.leader]
        best.cluster_id = f"c{cluster.leader}"
        best.is_cluster_best = True
        best.cluster_size = cluster.size
        survivors.append(best)
        if keep_losers:
            for member_index in cluster.members:
                if member_index == cluster.leader:
                    continue
                loser = candidates[member_index]
                loser.cluster_id = f"c{cluster.leader}"
                loser.is_cluster_best = False
                loser.cluster_size = cluster.size
                survivors.append(loser)

    return survivors, clusters
