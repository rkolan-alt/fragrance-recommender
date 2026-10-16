"""In-memory perfume catalog: metadata, feature matrix, scores and clone flags.

Every array is aligned by row (the row order of perfumes.parquet). Perfume ids
map to rows through `row_of`.
"""

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

from app.config import settings
from app.engine import config

META_COLUMNS = [
    "id",
    "name",
    "brand",
    "year",
    "gender",
    "rating_avg",
    "vote_count",
    "longevity_avg",
    "longevity_votes",
    "season_share_winter",
    "season_share_spring",
    "season_share_summer",
    "season_share_autumn",
    "warm_share",
    "cold_share",
    "in_pool",
]


@dataclass(frozen=True)
class Catalog:
    perfumes: pd.DataFrame  # META_COLUMNS + quality, quality_pct, popularity
    matrix: sp.csr_matrix  # one feature row per perfume
    layout: dict[str, tuple[int, int]]  # block name → column range
    accords: list[str]  # accord block column names
    notes: list[str]  # note block column names
    block_weights: dict[str, float]  # weights the matrix was built with
    is_clone: np.ndarray
    clone_of: list[list[int]]  # original perfume ids, per row
    row_of: dict[int, int]

    @classmethod
    def from_frames(
        cls,
        perfumes: pd.DataFrame,
        matrix: sp.csr_matrix,
        vocab: dict,
        scores: pd.DataFrame,
        clones: pd.DataFrame,
        block_weights: dict[str, float] | None = None,
    ) -> "Catalog":
        ids = perfumes["id"].tolist()
        if vocab["ids"] != ids or scores["id"].tolist() != ids or clones["id"].tolist() != ids:
            raise ValueError("perfumes, features, scores and clones are not row-aligned")
        meta = perfumes[META_COLUMNS].reset_index(drop=True)
        meta = meta.join(scores[["quality", "quality_pct", "popularity"]].reset_index(drop=True))
        return cls(
            perfumes=meta,
            matrix=matrix.tocsr(),
            layout={k: (int(v[0]), int(v[1])) for k, v in vocab["layout"].items()},
            accords=list(vocab["accords"]),
            notes=list(vocab["notes"]),
            block_weights=dict(block_weights or config.BLOCK_WEIGHTS),
            is_clone=clones["is_clone"].to_numpy(dtype=bool),
            clone_of=[list(map(int, c)) for c in clones["clone_of"]],
            row_of={int(pid): row for row, pid in enumerate(ids)},
        )

    def rows(self, ids: list[int]) -> np.ndarray:
        missing = [i for i in ids if i not in self.row_of]
        if missing:
            raise KeyError(f"unknown perfume ids: {missing}")
        return np.array([self.row_of[i] for i in ids], dtype=int)

    def reweighted(self, block_weights: dict[str, float]) -> "Catalog":
        """Return a copy whose similarity uses different block weights."""
        scale = np.ones(self.matrix.shape[1], dtype=np.float32)
        for name, (start, end) in self.layout.items():
            scale[start:end] = math.sqrt(block_weights[name] / self.block_weights[name])
        return replace(
            self,
            matrix=(self.matrix @ sp.diags(scale)).tocsr(),
            block_weights=dict(block_weights),
        )


def load_catalog(processed: Path | None = None) -> Catalog:
    processed = processed or settings.data_dir / "processed"
    return Catalog.from_frames(
        perfumes=pd.read_parquet(processed / "perfumes.parquet", columns=META_COLUMNS),
        matrix=sp.load_npz(processed / "features.npz"),
        vocab=json.loads((processed / "vocab.json").read_text()),
        scores=pd.read_parquet(processed / "scores.parquet"),
        clones=pd.read_parquet(processed / "clones.parquet"),
    )
