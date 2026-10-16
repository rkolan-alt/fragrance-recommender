"""Tunable settings for feature vectors and scoring."""

# Share of overall similarity each block contributes. Must sum to 1.
BLOCK_WEIGHTS: dict[str, float] = {
    "accords": 0.40,
    "notes": 0.35,
    "seasons": 0.10,
    "longevity": 0.05,
    "gender": 0.10,
}

# Base notes last longest and define a scent most; top notes fade first.
NOTE_TIER_FACTORS: dict[str, float] = {
    "notes_top": 0.8,
    "notes_middle": 1.0,
    "notes_base": 1.2,
}

# Listed-but-unvoted notes have weight 0; treat them as faintly present.
NOTE_WEIGHT_FLOOR = 10

# A specific note also counts toward its general parent at this strength,
# e.g. "calabrian bergamot" → "bergamot", "sichuan pepper" → "pepper".
NOTE_PARENT_FACTOR = 0.7

# Parents too generic to link notes by ("orange flower water" ≠ "water").
NOTE_GENERIC_PARENTS = {"water", "flowers", "leaf", "leaves", "notes", "accord"}

# Ignore notes that appear in fewer perfumes than this.
NOTE_MIN_PERFUMES = 2

# Angle (0–1 of a right angle) used to place each gender on an arc, so
# male–unisex are partly similar and male–female are not.
GENDER_POSITION: dict[str, float] = {"female": 0.0, "unisex": 0.5, "male": 1.0}

# Bayesian rating prior strength, in votes (median pool perfume has ~114).
QUALITY_PRIOR_VOTES = 100

# --- Clone detection -------------------------------------------------------
# Houses whose catalog is essentially all dupes: every perfume is a clone.
DUPE_HOUSES = {
    "Maison Alhambra",
    "Fragrance World",
    "French Avenue",
    "Alexandria Fragrances",
    "In The Box",
    "PARIS CORNER",
    "Pendora Scents",
    "Nuancielo",
    "The Dua Brand",
    "La Rive",
    "Zimaya",
    "Oakcha",
    "Zara",
    "Dossier",
    "Max Philip",
    "Kelsey Berwin",
    "Pocket Parfum",
    "Jo Milano Paris",
    "Adopt Parfums",
    "LPDO",
    "Patrice Martin",
    "Sapil",
    "Reyane Tradition",
    "Dumont",
    "Emper",
    "Le Chameau",
    "Paris Elysees",
    "Aromatix X French Avenue",
    "Milton Lloyd",
    "Just Jack",
    "Yodeyma",
    "Fine'ry.",
    "Thera Cosméticos",
}

# Houses that make both originals and dupes: a perfume is a clone only when
# the community says it smells like an earlier, more popular perfume.
MIXED_HOUSES = {
    "Armaf",
    "Lattafa Perfumes",
    "Afnan",
    "Rasasi",
    "Al Haramain Perfumes",
    "Orientica",
    "Orientica Premium",
    "Ard Al Zaafaran",
    "Khadlaj Perfumes",
    "ALREHAB PERFUMES",
    "Al Wataniah",
    "Junaid Perfumes",
    "Ahmed Al Maghribi",
    "Swiss Arabian",
    "Arabian Oud",
    "Ajmal",
    "Rayhaan",
    "Riiffs Perfumes",
    "Arabiyat Prestige",
    "Parfums Vintage",
    "Verset Parfums",
    "Samam",
    "Linn Young",
    "Lou De Pre",
    "Athena Fragrances",
    "Killer Oud",
    "Le Falconé Perfumes",
    "New Brand Parfums",
    "Atralia",
    "Bidaya Parfums",
}

# A "smells like" vote counts when it has enough agreement.
CLONE_MIN_UP_VOTES = 20
CLONE_MIN_AGREEMENT = 0.6
# Without known release years, the original must have this many times the votes.
CLONE_ORIGINAL_VOTE_RATIO = 2

# --- Recommendation ranking ------------------------------------------------
# score = Σ weight × term; similarity is in [0, 1], quality and popularity are
# percentiles within the candidate pool.
SCORE_WEIGHTS: dict[str, float] = {"similarity": 0.60, "quality": 0.25, "popularity": 0.15}

# Taste clusters: k = min(MAX_CLUSTERS, owned // PERFUMES_PER_CLUSTER); k < 2 → centroid only.
MAX_CLUSTERS = 3
PERFUMES_PER_CLUSTER = 3

# Only the top-scoring candidates go through flanker collapsing and MMR.
SHORTLIST_SIZE = 200
# At most this many perfumes from one line (e.g. Sauvage, Sauvage Elixir) per row.
MAX_PER_LINE = 2
# MMR trade-off: 1 = pure score, lower = more variety within a row.
MMR_LAMBDA = 0.8
# How many shared accords / notes to show in a recommendation's "why".
EXPLAIN_TOP = 3

# Trailing words that mark a flanker or concentration rather than a new line,
# e.g. "Sauvage Eau de Parfum" → "sauvage". Accent-free, lowercase.
LINE_SUFFIXES = {
    "parfum", "eau de parfum", "eau de toilette", "eau de cologne", "edp", "edt",
    "extrait", "extrait de parfum", "le parfum", "parfum intense", "elixir", "intense",
    "l'intense", "absolu", "absolute", "profumo", "cologne", "sport", "edition",
    "limited edition", "collector", "collector edition", "pour homme", "pour femme",
    "homme", "femme", "for men", "for women", "for him", "for her", "eau fraiche",
    "concentree", "eau extreme", "extreme", "essence de parfum", "oil", "all-over spray",
}  # fmt: skip
