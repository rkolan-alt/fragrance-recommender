"""Core recommender: profile → similarity → candidates → ranked, diverse row.

    profile = build_profile(catalog, owned_rows)
    sims = similarity(catalog, profile)
    mask = candidate_mask(catalog, owned_rows, filters)
    recs = rank(catalog, profile, mask, sims)

`recommend()` runs all four with defaults; category rows (Milestone 4) call
the steps directly with their own mask, profile or score weights.
"""

import math
import re
import unicodedata
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans

from app.engine import config
from app.engine.catalog import Catalog

SEASONS = ["winter", "spring", "summer", "autumn"]


@dataclass(frozen=True)
class Filters:
    """Narrow the candidates. Empty / None fields don't filter."""

    genders: tuple[str, ...] = ()
    seasons: tuple[str, ...] = ()
    min_season_share: float = 0.5  # combined vote share of the chosen seasons
    min_rating: float | None = None
    min_votes: int | None = None
    min_longevity: float | None = None
    max_longevity: float | None = None
    include_accords: tuple[str, ...] = ()  # must have all of these
    exclude_accords: tuple[str, ...] = ()  # must have none of these
    include_notes: tuple[str, ...] = ()
    exclude_notes: tuple[str, ...] = ()
    exclude_brands: tuple[str, ...] = ()
    include_clones: bool = False


@dataclass(frozen=True)
class Profile:
    rows: np.ndarray  # owned perfume rows
    centers: np.ndarray  # (centers × features); row 0 is the centroid, then clusters


@dataclass(frozen=True)
class Rec:
    id: int
    name: str
    brand: str
    score: float
    similarity: float
    quality: float
    popularity: float
    because_of: int  # id of the owned perfume it is most similar to
    shared_accords: tuple[str, ...]
    shared_notes: tuple[str, ...]


def recommend(
    catalog: Catalog,
    owned_ids: list[int],
    filters: Filters | None = None,
    limit: int = 20,
    weights: dict[str, float] | None = None,
) -> list[Rec]:
    rows = catalog.rows(list(dict.fromkeys(owned_ids)))
    if not len(rows):
        raise ValueError("need at least one owned perfume")
    profile = build_profile(catalog, rows)
    mask = candidate_mask(catalog, rows, filters or Filters())
    return rank(catalog, profile, mask, similarity(catalog, profile), weights, limit)


# --- Profile and similarity ---------------------------------------------------


def _unit_blocks(vector: np.ndarray, catalog: Catalog) -> np.ndarray:
    """Rescale each block to the norm a perfume's block has, sqrt(weight).

    Then dot(perfume, center) = Σ weight × block cosine, like perfume-to-perfume.
    """
    out = vector.astype(np.float64)
    for name, (start, end) in catalog.layout.items():
        norm = np.linalg.norm(out[start:end])
        if norm > 0:
            out[start:end] *= math.sqrt(catalog.block_weights[name]) / norm
    return out


def build_profile(catalog: Catalog, rows: np.ndarray) -> Profile:
    """Centroid of the owned perfumes plus up to MAX_CLUSTERS taste clusters,
    so a half-aquatic, half-gourmand collection isn't averaged into nothing."""
    owned = catalog.matrix[rows].toarray()
    centers = [owned.mean(axis=0)]
    k = min(config.MAX_CLUSTERS, len(rows) // config.PERFUMES_PER_CLUSTER)
    if k >= 2:
        kmeans = KMeans(n_clusters=k, n_init=10, random_state=0).fit(owned)
        centers.extend(kmeans.cluster_centers_)
    return Profile(rows=rows, centers=np.vstack([_unit_blocks(c, catalog) for c in centers]))


def similarity(catalog: Catalog, profile: Profile) -> np.ndarray:
    """Per perfume: similarity to the closest profile center, in [0, 1]."""
    return np.asarray(catalog.matrix @ profile.centers.T).max(axis=1)


# --- Candidates ----------------------------------------------------------------


def _has_terms(catalog: Catalog, block: str, names: tuple[str, ...]) -> np.ndarray:
    """(perfumes × names) bool: does each perfume have each accord / note?"""
    vocab = catalog.accords if block == "accords" else catalog.notes
    index = {n: i for i, n in enumerate(vocab)}
    wanted = [n.strip().lower() for n in names]
    unknown = [n for n in wanted if n not in index]
    if unknown:
        raise ValueError(f"unknown {block}: {unknown}")
    start = catalog.layout[block][0]
    columns = [start + index[n] for n in wanted]
    return catalog.matrix[:, columns].toarray() > 0


def candidate_mask(catalog: Catalog, owned_rows: np.ndarray, filters: Filters) -> np.ndarray:
    p = catalog.perfumes
    mask = p["in_pool"].to_numpy(dtype=bool, copy=True)
    mask[owned_rows] = False

    # Never suggest the original of a clone the user owns.
    originals = {o for r in owned_rows for o in catalog.clone_of[r] if o in catalog.row_of}
    mask[[catalog.row_of[o] for o in originals]] = False
    if not filters.include_clones:
        mask &= ~catalog.is_clone

    if filters.genders:
        mask &= p["gender"].isin(filters.genders).to_numpy()
    if filters.seasons:
        unknown = set(filters.seasons) - set(SEASONS)
        if unknown:
            raise ValueError(f"unknown seasons: {sorted(unknown)}")
        share = p[[f"season_share_{s}" for s in filters.seasons]].sum(axis=1)
        mask &= (share >= filters.min_season_share).to_numpy()
    if filters.min_rating is not None:
        mask &= (p["rating_avg"] >= filters.min_rating).to_numpy()
    if filters.min_votes is not None:
        mask &= (p["vote_count"] >= filters.min_votes).to_numpy()
    if filters.min_longevity is not None:
        mask &= (p["longevity_avg"] >= filters.min_longevity).to_numpy()
    if filters.max_longevity is not None:
        mask &= (p["longevity_avg"] <= filters.max_longevity).to_numpy()
    if filters.include_accords:
        mask &= _has_terms(catalog, "accords", filters.include_accords).all(axis=1)
    if filters.exclude_accords:
        mask &= ~_has_terms(catalog, "accords", filters.exclude_accords).any(axis=1)
    if filters.include_notes:
        mask &= _has_terms(catalog, "notes", filters.include_notes).all(axis=1)
    if filters.exclude_notes:
        mask &= ~_has_terms(catalog, "notes", filters.exclude_notes).any(axis=1)
    if filters.exclude_brands:
        mask &= ~p["brand"].isin(filters.exclude_brands).to_numpy()
    return mask


# --- Ranking -------------------------------------------------------------------


def line_stem(name: str) -> tuple[str, ...]:
    """A perfume's product line: "Acqua di Giò Profumo" → ("acqua", "di", "gio")."""
    text = unicodedata.normalize("NFKD", name.replace("’", "'"))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"\(.*?\)|\b(19|20)\d\d\b", " ", text)
    words = text.split()
    stripped = True
    while stripped:
        stripped = False
        for n in (3, 2, 1):
            if len(words) > n and " ".join(words[-n:]) in config.LINE_SUFFIXES:
                del words[-n:]
                stripped = True
                break
    return tuple(words)


def same_line(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Lines match when one is a word-prefix of the other (Sauvage ⊂ Sauvage Noir)."""
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def rank(
    catalog: Catalog,
    profile: Profile,
    mask: np.ndarray,
    sims: np.ndarray,
    weights: dict[str, float] | None = None,
    limit: int = 20,
) -> list[Rec]:
    """Score candidates, then pick a diverse row with flanker caps and MMR."""
    w = weights or config.SCORE_WEIGHTS
    p = catalog.perfumes
    candidates = np.flatnonzero(mask)
    score = (
        w["similarity"] * sims[candidates]
        + w["quality"] * np.nan_to_num(p["quality_pct"].to_numpy()[candidates])
        + w["popularity"] * np.nan_to_num(p["popularity"].to_numpy()[candidates])
    )
    top = np.argsort(-score, kind="stable")[: config.SHORTLIST_SIZE]
    shortlist, score = candidates[top], score[top]
    picks = _diversify(catalog, shortlist, score, limit)
    return [_explain(catalog, profile, shortlist[i], score[i], sims) for i in picks]


def _diversify(catalog: Catalog, rows: np.ndarray, score: np.ndarray, limit: int) -> list[int]:
    """Maximal marginal relevance, skipping a line once it has MAX_PER_LINE picks."""
    vectors = catalog.matrix[rows]
    pairwise = (vectors @ vectors.T).toarray()
    names = catalog.perfumes["name"].to_numpy()[rows]
    brands = catalog.perfumes["brand"].to_numpy()[rows]
    lines = [line_stem(n) for n in names]

    picks: list[int] = []
    available = np.ones(len(rows), dtype=bool)
    lam = config.MMR_LAMBDA
    while len(picks) < limit and available.any():
        redundancy = pairwise[:, picks].max(axis=1) if picks else np.zeros(len(rows))
        mmr = np.where(available, lam * score - (1 - lam) * redundancy, -np.inf)
        i = int(np.argmax(mmr))
        available[i] = False
        same = sum(brands[j] == brands[i] and same_line(lines[j], lines[i]) for j in picks)
        if same < config.MAX_PER_LINE:
            picks.append(i)
    return picks


def _top_shared(shared: np.ndarray, names: list[str]) -> tuple[str, ...]:
    """Highest shared terms, skipping a note already covered by its parent/child
    (e.g. "bergamot" after "calabrian bergamot")."""
    chosen: list[str] = []
    for i in np.argsort(-shared, kind="stable"):
        if shared[i] <= 0 or len(chosen) == config.EXPLAIN_TOP:
            break
        name = names[i]
        if not any(c.endswith(" " + name) or name.endswith(" " + c) for c in chosen):
            chosen.append(name)
    return tuple(chosen)


def _explain(catalog: Catalog, profile: Profile, row: int, score: float, sims: np.ndarray) -> Rec:
    """Find the owned perfume it's closest to and the accords / notes they share."""
    contributions = catalog.matrix[profile.rows].multiply(catalog.matrix[row]).toarray()
    best = int(np.argmax(contributions.sum(axis=1)))
    shared = contributions[best]
    a0, a1 = catalog.layout["accords"]
    n0, n1 = catalog.layout["notes"]
    p = catalog.perfumes
    return Rec(
        id=int(p.at[row, "id"]),
        name=str(p.at[row, "name"]),
        brand=str(p.at[row, "brand"]),
        score=float(score),
        similarity=float(sims[row]),
        quality=float(p.at[row, "quality"]),
        popularity=float(p.at[row, "popularity"]),
        because_of=int(p.at[profile.rows[best], "id"]),
        shared_accords=_top_shared(shared[a0:a1], catalog.accords),
        shared_notes=_top_shared(shared[n0:n1], catalog.notes),
    )
