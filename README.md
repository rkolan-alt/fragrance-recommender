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
search/recommendation API routes and account persistence are implemented; pricing,
frontend account pages, and deployment remain planned.

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

Start with `make backend`, then open `http://localhost:8001/docs` for interactive
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
Account-backed requests and saved collections are now implemented in Milestone 6.


## Accounts and saved collections (Milestone 6)

Run `make setup` to install account dependencies, then `make migrate` before
starting the API with `make backend`. SQLite is the development default.
For PostgreSQL use `DATABASE_URL=postgresql+asyncpg://...` and run the same migration.
Migrations are explicit; the server never silently creates or changes tables.

Email/password registration, login/logout, email verification, password reset,
and password/email updates use FastAPI Users. Passwords must be 12–128 characters.
Sessions are stored in the database and carried in an httpOnly, SameSite=Lax
cookie. Logout revokes that session; password/email changes and password resets
revoke all sessions. Set `COOKIE_SECURE=true` for HTTPS production and set a
stable, random `AUTH_SECRET` with at least 32 characters. With the development
placeholder a temporary secret is generated, so email links expire on restart.

For browser requests, use `credentials: "include"`. First fetch `GET /auth/csrf`
and send its `csrf_token` as `X-CSRF-Token` on all account mutations and on
signed-in `POST /recommend` requests. Keep the cookie returned by that request.
Origins must match `FRONTEND_ORIGIN` when present. Cross-site frontend/API
hosting needs a first-party proxy or shared parent domain before deployment.

Routes (also visible at `/docs`):

- `POST /auth/register` accepts JSON email/password; `POST /auth/login` accepts
  form fields `username` (email) and `password`; `POST /auth/logout` ends a session.
- `POST /auth/request-verify-token`, `/auth/verify`, `/auth/forgot-password`,
  and `/auth/reset-password` handle email verification and password recovery.
- `GET/PATCH /users/me` reads the account and updates email/password.
- `GET/POST /me/collection`, `PATCH/DELETE /me/collection/{perfume_id}` manage
  `owned`, `wishlist`, and `disliked` items and optional 1–5 personal ratings.
- `POST /me/collection/import` accepts `{ "items": [{ "perfume_id": 31861 }] }`.
  It merges guest items without overwriting existing edits; duplicates are skipped
  and invalid perfume IDs reject the entire batch.
- `GET/POST /me/filters`, `DELETE /me/filters/{id}` store named filters;
  use `is_default` or `is_custom_row` to apply them on future visits.
- `POST /me/feedback` accepts a perfume ID and `not_interested`, `clicked`, or `bought`.
- `GET /me/oauth` lists connected providers without exposing provider tokens.
- `DELETE /me` removes the account and cascades its collection, filters, feedback,
  OAuth connections, and sessions.

Signed-in `POST /recommend` takes `{}` or filters/category options; it reads
owned items from the database, requires five distinct owned fragrances, and
rejects supplied `owned_ids`. Explicit filters override saved defaults. Guest
requests continue using `owned_ids`. Personal ratings weight the taste profile
from 0.5× at one star to 1.5× at five stars. Dislikes penalize similar scents;
wishlist/disliked/not-interested items are excluded. Clone and owned-original
exclusions remain active. Account caches include user ID and collection/feedback
state and are cleared on changes; named custom rows use their saved filters.

### Email and Google configuration

`EMAIL_BACKEND=outbox` writes development verification/reset links to the ignored
`backend/mail-outbox/` directory. This makes the API testable before the frontend
email-link pages exist. The frontend will read the token and call the matching
API endpoint in Milestone 8. For real delivery, set `EMAIL_BACKEND=resend`,
`RESEND_API_KEY`, and a verified `EMAIL_FROM`; outbox delivery is refused when
secure production cookies are enabled.

Google sign-in fetches verified email and the stable subject ID from Google's
OpenID Connect UserInfo endpoint; enabling the Google People API is unnecessary.
Provider identity failures return an actionable response rather than an unhandled 500.

Google routes are enabled only when both OAuth client credentials are configured.
Register the exact `GOOGLE_OAUTH_REDIRECT_URL` and the corresponding
`/auth/google/associate/callback` URL with Google. Fetch
`GET /auth/google/authorize` then navigate to its `authorization_url` in the same
browser. Callbacks bind signed state to a browser cookie to prevent login CSRF.
Email/password accounts are never automatically linked just because an email
matches: verified, logged-in users explicitly connect Google using
`/auth/google/associate/authorize`. Provider callbacks currently return the API
response; the account UI and redirect experience arrive in Milestone 8.

Auth POST routes are limited to 10 requests per minute per client IP. The default
in-memory limiter applies per process; configure shared storage before running
multiple production workers, and use a trusted reverse-proxy configuration.
Local integration tests exercise emails via the outbox and Google via mocked
provider responses. Live Google/Resend delivery and a live PostgreSQL deployment
require their credentials/services and have not been tested here.
