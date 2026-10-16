# Fragrance Recommender

Enter at least 5 fragrances you own and get carousels of recommendations: For You, Spring/Summer, Fall/Winter, Budget, Something Different, and more. Each card links to whichever of Amazon or Jomashop is cheaper.

- `backend/` — FastAPI app, recommendation engine, data pipeline
- `frontend/` — Next.js app
- `data/` — downloaded and processed data (gitignored)

## Setup
1. `cp .env.example .env`
2. Get a Kaggle API token (Kaggle → Settings → API → Create New Token) and save it to `~/.kaggle/kaggle.json`
3. `make setup`
4. `make data`
5. In two separate terminals: `make backend` and `make frontend`

## Data
[Fragrantica Perfumes](https://www.kaggle.com/datasets/ledecanteur/fragrantica-perfumes) by Le Decanteur, CC BY-NC-SA 4.0.

## Current development status

The offline data pipeline, feature vectors, clone exclusions, core recommendation
engine, and category builders are implemented. The frontend is a placeholder;
search/recommendation API routes, accounts, pricing, and deployment remain planned.

After placing `perfumes.csv` and `perfumes.jsonl` in `data/raw/`, run
`make process`, `make features`, and `make clones`. Run `make test` for backend
checks and `make evaluate` for the community-similarity benchmark.

`app.engine.categories.recommend_rows(catalog, owned_ids, filters)` requires five
distinct owned fragrances. It returns For You, Spring/Summer, Fall/Winter,
Long-Lasting, Hidden Gems, Something Different, two accord rows, and a
Because You Own row. Empty rows are valid when filters leave no matches.
Budget recommendations await verified retail prices. Clones are hidden by
default; enabling them never re-enables recorded originals of owned dupes.

A seed-0 sample (200 singles requested, 166 with eligible targets; 60 collections)
measured top-20 hit rates of 25.9% / 28.3% for the blended engine, versus
3.0% / 8.3% for popularity and 0% / 5.0% for random popular. Similarity-only
scoring reached 35.5% / 36.7%. These are development diagnostics rather than
held-out proof: community votes also inform the clone exclusions, and collections
are synthetic. Ranking weights remain provisional.

## API (Milestone 5)

Start with `make backend`, then open `http://localhost:8000/docs` for interactive
OpenAPI documentation. Routes:

- `GET /search?q=Dior%20Sauvage`: fuzzy search across the full catalog.
- `POST /recommend`: send `owned_ids` (at least five distinct IDs), optional
  `filters`, `categories`, and `limit` (1–50). Returns category rows with cards,
  scores, and shared-note/accord explanations.
- `GET /perfume/{id}`: notes, accords, season shares, longevity histogram, and
  an empty `offers` list pending pricing integration.

Filters support `genders`, `seasons`, `min_season_share`, `min_rating`, `min_votes`,
`min_longevity`, `max_longevity`, included/excluded notes and accords,
`exclude_brands`, and `include_clones`. Invalid fields/ranges return 422;
missing perfumes return 404. Price/store filters await Milestone 7.
Recommendation results use a bounded in-process cache; restart the backend after
rebuilding data artifacts to reload the catalog and clear cached results.
Account-backed requests and saved collections arrive in Milestone 6.
