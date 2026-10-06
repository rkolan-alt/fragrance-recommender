"""Build perfume feature vectors and quality/popularity scores.

Every perfume gets a row in a sparse matrix made of blocks (accords, notes,
seasons, longevity, gender). Each block is L2-normalized and multiplied by
sqrt(block weight), so for two perfumes with every block present:

    dot(a, b) = sum(weight_b * cosine_b)

i.e. similarity is the weighted average of per-block similarities, in [0, 1].
Rows are stored for the full catalog (owned perfumes may be outside the pool).

Outputs in data/processed/: features.npz, vocab.json, scores.parquet.
"""

import json
import math
import sys

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.preprocessing import normalize

from app.config import settings
from app.engine import config
from pipeline.parsing import NOTE_ALIASES

SEASONS = ["winter", "spring", "summer", "autumn"]


def arc(position: np.ndarray) -> np.ndarray:
    """Map positions in [0, 1] onto a quarter circle; dot = cos(difference)."""
    theta = position * math.pi / 2
    return np.column_stack([np.cos(theta), np.sin(theta)])


def weighted_bag(rows: list[list[tuple[str, float]]], vocab: dict[str, int]) -> sp.csr_matrix:
    data, indices, indptr = [], [], [0]
    for items in rows:
        for name, value in items:
            col = vocab.get(name)
            if col is not None:
                indices.append(col)
                data.append(value)
        indptr.append(len(indices))
    return sp.csr_matrix((data, indices, indptr), shape=(len(rows), len(vocab)))


def accord_block(df: pd.DataFrame) -> tuple[sp.csr_matrix, list[str]]:
    names = sorted({a["name"] for accords in df["accords"] for a in accords})
    vocab = {n: i for i, n in enumerate(names)}
    rows = [[(a["name"], a["weight"] / 100) for a in accords] for accords in df["accords"]]
    return weighted_bag(rows, vocab), names


def note_parents(names: set[str]) -> dict[str, str]:
    """Map a note to its longest word-suffix that is also a note."""
    parents = {}
    for name in names:
        words = name.split()
        for k in range(1, len(words)):
            suffix = NOTE_ALIASES.get(" ".join(words[k:]), " ".join(words[k:]))
            if suffix in names and suffix != name:
                if suffix not in config.NOTE_GENERIC_PARENTS:
                    parents[name] = suffix
                break
    return parents


def note_block(df: pd.DataFrame) -> tuple[sp.csr_matrix, list[str]]:
    tiers = list(config.NOTE_TIER_FACTORS)
    all_names = {n["name"] for col in tiers for notes in df[col] for n in notes}
    parents = note_parents(all_names)

    rows: list[list[tuple[str, float]]] = []
    for perfume in df[tiers].itertuples(index=False):
        terms: dict[str, float] = {}
        for notes, factor in zip(perfume, config.NOTE_TIER_FACTORS.values(), strict=True):
            for note in notes:
                value = max(note["weight"], config.NOTE_WEIGHT_FLOOR) / 100 * factor
                name = note["name"]
                terms[name] = max(terms.get(name, 0.0), value)
                if name in parents:
                    parent, scaled = parents[name], value * config.NOTE_PARENT_FACTOR
                    terms[parent] = max(terms.get(parent, 0.0), scaled)
        rows.append(list(terms.items()))

    doc_freq: dict[str, int] = {}
    for terms in rows:
        for name, _ in terms:
            doc_freq[name] = doc_freq.get(name, 0) + 1
    names = sorted(n for n, c in doc_freq.items() if c >= config.NOTE_MIN_PERFUMES)
    vocab = {n: i for i, n in enumerate(names)}

    n_docs = sum(1 for terms in rows if terms)
    idf = np.array([math.log((1 + n_docs) / (1 + doc_freq[n])) + 1 for n in names])
    return weighted_bag(rows, vocab) @ sp.diags(idf), names


def season_block(df: pd.DataFrame) -> sp.csr_matrix:
    shares = df[[f"season_share_{s}" for s in SEASONS]].fillna(0).to_numpy()
    return sp.csr_matrix(shares)


def longevity_block(df: pd.DataFrame) -> sp.csr_matrix:
    position = ((df["longevity_avg"] - 1) / 4).clip(0, 1)
    vectors = arc(position.fillna(0).to_numpy())
    vectors[position.isna().to_numpy()] = 0
    return sp.csr_matrix(vectors)


def gender_block(df: pd.DataFrame) -> sp.csr_matrix:
    position = df["gender"].map(config.GENDER_POSITION)
    vectors = arc(position.fillna(0).to_numpy())
    vectors[position.isna().to_numpy()] = 0
    return sp.csr_matrix(vectors)


def build_features(df: pd.DataFrame) -> tuple[sp.csr_matrix, dict]:
    accords, accord_names = accord_block(df)
    notes, note_names = note_block(df)
    blocks = {
        "accords": accords,
        "notes": notes,
        "seasons": season_block(df),
        "longevity": longevity_block(df),
        "gender": gender_block(df),
    }
    weighted, layout, offset = [], {}, 0
    for name, block in blocks.items():
        weight = math.sqrt(config.BLOCK_WEIGHTS[name])
        weighted.append(normalize(block, norm="l2") * weight)
        layout[name] = [offset, offset + block.shape[1]]
        offset += block.shape[1]
    matrix = sp.hstack(weighted, format="csr", dtype=np.float32)
    vocab = {
        "ids": df["id"].tolist(),
        "layout": layout,
        "accords": accord_names,
        "notes": note_names,
    }
    return matrix, vocab


def build_scores(df: pd.DataFrame) -> pd.DataFrame:
    pool = df["in_pool"]
    global_mean = df.loc[pool, "rating_avg"].mean()
    votes = df["vote_count"]
    m = config.QUALITY_PRIOR_VOTES
    quality = (votes / (votes + m)) * df["rating_avg"].fillna(global_mean) + (
        m / (votes + m)
    ) * global_mean
    popularity = votes.where(pool).rank(pct=True)
    return pd.DataFrame(
        {
            "id": df["id"],
            "quality": quality,
            "quality_pct": quality.where(pool).rank(pct=True),
            "popularity": popularity,
        }
    )


def main() -> int:
    processed = settings.data_dir / "processed"
    df = pd.read_parquet(processed / "perfumes.parquet")
    matrix, vocab = build_features(df)
    sp.save_npz(processed / "features.npz", matrix)
    (processed / "vocab.json").write_text(json.dumps(vocab))
    build_scores(df).to_parquet(processed / "scores.parquet", index=False)
    print(
        f"features: {matrix.shape[0]:,} × {matrix.shape[1]:,} "
        f"({len(vocab['accords'])} accords, {len(vocab['notes']):,} notes), nnz={matrix.nnz:,}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
