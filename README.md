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
