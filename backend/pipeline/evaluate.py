"""Offline evaluation against Fragrantica's "smells like this" votes.

The votes (`similar.reminds_me_of` in data/raw/perfumes.jsonl) are used only
as ground truth here; the engine does not use them for similarity scoring. Clone exclusions do use
these votes, so this measures agreement with the community, not independent validation.

  - Single-perfume queries: own one perfume; its well-supported "smells like"
    neighbors are the targets.
  - Collection queries: own 5 random popular perfumes of one gender; the
    targets are the union of their neighbors.

Targets are limited to perfumes the engine may recommend for that query (in
the pool, not owned, not a clone). Metrics, averaged over queries:
hit@K (any target in the top K) and recall@K (share of targets in the top K).

python -m pipeline.evaluate                 # engine vs baselines
python -m pipeline.evaluate --grid          # also grid-search weights
"""

import argparse
import itertools
import json
import sys
from collections import defaultdict
from collections.abc import Callable

import numpy as np
import pandas as pd

from app.config import settings
from app.engine import config
from app.engine.catalog import Catalog, load_catalog
from app.engine.recommend import Filters, build_profile, candidate_mask, rank, similarity
from pipeline.clones import read_similar_votes

# A "smells like" pair is a target when the community clearly agrees.
TRUTH_MIN_UP_VOTES = 10
TRUTH_MIN_AGREEMENT = 0.6
COLLECTION_SIZE = 5
# Collections are drawn from the most-voted perfumes, like real collections.
COLLECTION_POOL_SIZE = 5000
RANDOM_POPULAR_POOL = 1000

# Picks the top-K rows for one query: (catalog, owned rows, candidate mask, k) → rows.
Method = Callable[[Catalog, np.ndarray, np.ndarray, int], list[int]]


def build_truth(votes: pd.DataFrame, catalog: Catalog) -> dict[int, set[int]]:
    """Row → rows of perfumes the community says it smells like (both directions)."""
    agreement = votes["up"] / (votes["up"] + votes["down"]).clip(lower=1)
    strong = votes[(votes["up"] >= TRUTH_MIN_UP_VOTES) & (agreement >= TRUTH_MIN_AGREEMENT)]
    truth: dict[int, set[int]] = defaultdict(set)
    for a, b in strong[["a", "b"]].itertuples(index=False):
        ra, rb = catalog.row_of.get(int(a)), catalog.row_of.get(int(b))
        if ra is not None and rb is not None and ra != rb:
            truth[ra].add(rb)
            truth[rb].add(ra)
    return truth


def make_queries(
    catalog: Catalog, truth: dict[int, set[int]], singles: int, collections: int, seed: int
) -> dict[str, list[np.ndarray]]:
    rng = np.random.default_rng(seed)
    p = catalog.perfumes
    pool = p["in_pool"].to_numpy() & ~catalog.is_clone
    has_truth = np.zeros(len(p), dtype=bool)
    has_truth[list(truth)] = True

    single_rows = np.flatnonzero(pool & has_truth)
    picked = rng.choice(single_rows, size=min(singles, len(single_rows)), replace=False)

    popular = p.index[pool & has_truth].to_series()
    popular = popular.loc[p.loc[popular, "vote_count"].nlargest(COLLECTION_POOL_SIZE).index]
    genders = p.loc[popular, "gender"]
    collection_list = []
    for _ in range(collections):
        gender = rng.choice(["male", "female"])
        options = popular[genders.isin([gender, "unisex"])].to_numpy()
        collection_list.append(rng.choice(options, size=COLLECTION_SIZE, replace=False))
    return {"single": [np.array([r]) for r in picked], "collection": collection_list}


# --- Methods ------------------------------------------------------------------------


def engine(weights: dict[str, float] | None = None) -> Method:
    def run(catalog: Catalog, rows: np.ndarray, mask: np.ndarray, k: int) -> list[int]:
        profile = build_profile(catalog, rows)
        recs = rank(catalog, profile, mask, similarity(catalog, profile), weights, k)
        return [catalog.row_of[r.id] for r in recs]

    return run


def popular(catalog: Catalog, rows: np.ndarray, mask: np.ndarray, k: int) -> list[int]:
    votes = np.where(mask, catalog.perfumes["vote_count"].to_numpy(), -1)
    eligible = np.flatnonzero(mask)
    return list(eligible[np.argsort(-votes[eligible], kind="stable")[:k]])


def random_popular(seed: int) -> Method:
    rng = np.random.default_rng(seed)

    def run(catalog: Catalog, rows: np.ndarray, mask: np.ndarray, k: int) -> list[int]:
        top = popular(catalog, rows, mask, RANDOM_POPULAR_POOL)
        return list(rng.choice(top, size=min(k, len(top)), replace=False))

    return run


# --- Scoring ------------------------------------------------------------------------


def evaluate(
    catalog: Catalog,
    truth: dict[int, set[int]],
    queries: dict[str, list[np.ndarray]],
    method: Method,
    k: int,
) -> dict[str, float]:
    results = {}
    for kind, query_rows in queries.items():
        hits, recalls = [], []
        for rows in query_rows:
            mask = candidate_mask(catalog, rows, Filters())
            targets = {t for r in rows for t in truth.get(int(r), ()) if mask[t]}
            if not targets:
                continue
            found = len(targets & set(method(catalog, rows, mask, k)))
            hits.append(found > 0)
            recalls.append(found / len(targets))
        results[f"{kind} hit@{k}"] = float(np.mean(hits)) if hits else 0.0
        results[f"{kind} recall@{k}"] = float(np.mean(recalls)) if recalls else 0.0
        results[f"{kind} n"] = len(hits)
    return results


def print_table(rows: dict[str, dict[str, float]]) -> None:
    table = pd.DataFrame(rows).T
    counts = [c for c in table.columns if c.endswith(" n")]
    print(table.drop(columns=counts).to_string(float_format=lambda v: f"{v:.3f}"))
    print("queries: " + ", ".join(f"{c[:-2]}={int(table[c].iloc[0])}" for c in counts))


def block_weight_grid() -> list[dict[str, float]]:
    """Vary accords and notes; seasons/longevity/gender share the rest in their
    current proportions."""
    base = config.BLOCK_WEIGHTS
    rest = {k: v for k, v in base.items() if k not in ("accords", "notes")}
    rest_total = sum(rest.values())
    grid = []
    for accords, notes in itertools.product([0.3, 0.4, 0.5], [0.25, 0.35, 0.45]):
        left = 1 - accords - notes
        grid.append(
            {
                "accords": accords,
                "notes": notes,
                **{k: v / rest_total * left for k, v in rest.items()},
            }
        )
    return grid


def score_weight_grid() -> list[dict[str, float]]:
    """Vary the similarity share; quality and popularity split the rest 25:15."""
    base = config.SCORE_WEIGHTS
    other = base["quality"] + base["popularity"]
    return [
        {
            "similarity": s,
            "quality": (1 - s) * base["quality"] / other,
            "popularity": (1 - s) * base["popularity"] / other,
        }
        for s in (0.6, 0.75, 0.9)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--singles", type=int, default=1000)
    parser.add_argument("--collections", type=int, default=300)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--grid", action="store_true", help="grid-search block and score weights")
    args = parser.parse_args()

    raw = settings.data_dir / "raw" / "perfumes.jsonl"
    if not raw.exists():
        print(f"Missing {raw}: download perfumes.jsonl from Kaggle into data/raw/")
        return 1
    try:
        with raw.open() as f:
            votes = read_similar_votes(f)
    except json.JSONDecodeError as e:
        print(f"{raw} is not valid JSON lines ({e}); re-download it from Kaggle")
        return 1

    catalog = load_catalog()
    truth = build_truth(votes, catalog)
    queries = make_queries(catalog, truth, args.singles, args.collections, args.seed)
    print(f"{sum(map(len, truth.values())) // 2:,} target pairs; k={args.k}\n")

    methods: dict[str, Method] = {
        "engine": engine(),
        "similarity only": engine({"similarity": 1.0, "quality": 0.0, "popularity": 0.0}),
        "popular": popular,
        "random popular": random_popular(args.seed),
    }
    print_table({name: evaluate(catalog, truth, queries, m, args.k) for name, m in methods.items()})

    if args.grid:
        results = {}
        for blocks, scores in itertools.product(block_weight_grid(), score_weight_grid()):
            label = (
                f"acc={blocks['accords']:.2f} notes={blocks['notes']:.2f} "
                f"sim={scores['similarity']:.2f}"
            )
            reweighted = catalog.reweighted(blocks)
            results[label] = evaluate(reweighted, truth, queries, engine(scores), args.k)
            print(f"  {label}: {results[label]}", flush=True)
        ranked = dict(
            sorted(
                results.items(),
                key=lambda kv: (
                    -(kv[1][f"single recall@{args.k}"] + kv[1][f"collection recall@{args.k}"])
                ),
            )
        )
        print("\nGrid, best first (by single + collection recall):")
        print_table(ranked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
