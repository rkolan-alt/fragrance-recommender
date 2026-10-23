# Fragrance Recommender

Enter at least 5 fragrances you own and get carousels of recommendations: For You, Spring/Summer, Fall/Winter, Budget, Something Different, and more. Cards show matched Amazon offers when available.

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
Budget recommendations use fresh verified retail matches when available. Clones are hidden by
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
  matched cached `offers`, comparable bottle pricing, and store search-link fallbacks.

Filters support `genders`, `seasons`, `min_season_share`, `min_rating`, `min_votes`,
`min_longevity`, `max_longevity`, included/excluded notes and accords,
`exclude_brands`, and `include_clones`. Invalid fields/ranges return 422;
missing perfumes return 404. Price/store filters are implemented in Milestone 7.
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


## Retail pricing (Milestone 7)

Run `make migrate` to add `offers`, refresh-state, and daily-quota tables.
Set `SERPAPI_KEY` in the ignored root `.env`. The provider uses SerpApi's
Amazon-specific search engine for Amazon US listings. It accepts only structured
prices and matching variant titles. No retail pages are scraped by this app.
Queries include concentration and 100 ml as search hints; matched sizes always
come from the listing itself.
`make prices` refreshes up to 50 popular perfumes with explicit concentrations,
subject to a default shared cap of **10 provider attempts per UTC day**. To choose
perfumes explicitly, run from `backend/`:

```sh
.venv/bin/python -m app.pricing.refresh --ids 25967 --top 1
```

`PRICING_AUTO_REFRESH=false` is the default: adding a key alone does not cause
website requests to spend credits. Opt into background refresh by setting it to
`true`; at most `PRICING_LAZY_PER_REQUEST=2` due perfumes are queried per response,
still within `PRICING_DAILY_REQUEST_LIMIT=10`. Restart the backend after changing
environment settings. Schedule the CLI externally if periodic refresh is wanted.
There is no scheduler installed by this milestone.

Successful matches and no-match responses cache for `PRICING_CACHE_DAYS=7`.
Database leases prevent duplicate concurrent refreshes. Each fragrance refresh
uses one SerpApi Amazon US search, counted against the shared UTC daily cap.
Provider failures back off for six hours; hitting the cap defers for one hour.
Failures preserve historical offers, but expired prices never qualify for Budget.

Pricing is Amazon-only. Matching requires a direct HTTPS Amazon.com link, an
explicit catalog concentration, the same fragrance including flanker terms,
a 25–300 ml bottle, and a USD price. Testers, samples, decants, sets, refills,
non-fragrance products, unavailable stock and installment prices are rejected.
Unknown concentrations are never guessed. Products without a matched Amazon
offer have no purchase link (`best_offer: null`, `search_links: {}`). Jomashop
coverage is deferred; no search-link fallback is generated.

Matching allows retail adjectives and descriptive wording around the fragrance
name. It indexes every catalog fragrance, including those outside the candidate
pool, and checks whether extra identifying words name a more specific flanker
(e.g. Eros Flame). Note-description clauses are excluded from identity matching.
Brand text may be omitted from titles. Names shared across brands (such as
Legend) require brand context in the title or Amazon product URL; URL wording
helps disambiguate search results but does not independently verify the product.
Conflicting explicit brands and mixed-concentration bundles remain excluded.
"Splash" and "Jumbo" are bottle descriptions, and Muelhens is an alias for 4711.

Cards and details include `offers`, `best_offer`, `best_value_offer`,
`price_status`, `pricing_source`, `price_label`, `price_basis`, and `search_links`.
The best matched Amazon offer prefers a nominal 100 ml bottle (including retail
3.3/3.4 oz rounding), then smaller sizes from largest to smallest, then larger
sizes from smallest to largest if no 100 ml or smaller bottle is available.
It chooses the lowest price within the preferred concentration/size group.
Price and Budget filters apply before size preference, so a smaller affordable
bottle can appear in Budget even if a more expensive 100 ml offer exists.
`best_value_offer` separately minimizes price/ml across accepted sizes. Bottle
size and fetch time accompany offers. Shipping and tax are excluded; cached
search listings do not guarantee checkout prices or marketplace authenticity.

Filters support `price_min`, `price_max`, `store` (`amazon` or `any`), and
`budget_max` (default $60). Unknown prices fail price/store filters. The Budget
row uses qualifying bottle prices, with a small unit-value ranking bonus;
its displayed offer stays within budget. Clone and owned exclusions still apply.
Fresh price snapshots participate in recommendation cache keys. Without matched
prices, Budget is empty and other recommendations have no purchase links.

The existing offer-table schema retains historical retailer compatibility; the
provider, matcher, price reads and API expose only Amazon. A future retailer can
be added behind the provider interface without changing recommendation scoring.

### Broader pricing validation

`make validate-prices` explicitly runs up to ten Amazon searches. It respects the
same database quota and active refresh leases as production. Nothing raises the
daily allowance. To recheck completed cached searches, use:

```sh
cd backend
.venv/bin/python -m app.pricing.validate --live --retry-cached --limit 10
```

Each successful provider response is saved **before matching**, with only public
product fields. Request metadata, keys, credentials and URL query parameters are
excluded. Files live under ignored `data/processed/pricing-validation/`:

- `response-<id>.json`: replayable product listings and their observation time.
- `report.json`: observed coverage, per-listing acceptance/rejection reasons,
  owned/clone exclusions, Budget checks and (live mode) API integration checks.
- `manual-review.json`: accepted offers to check against Amazon, with fields for
  variant, size, availability, observed price and check time. Human entries survive
  reruns. Accuracy is explicitly unmeasured until those checks are completed.

Offline replay uses no network requests and does not update cached offers:

```sh
.venv/bin/python -m app.pricing.validate --replay ../data/processed/pricing-validation/RUN_DIRECTORY
```

Replay measures matching against historical observations; it does not establish
that those prices remain available. `--ids` selects fragrances, `--owned-ids`
sets the test collection, and `--budget-max` sets its budget. `--limit` is 1–15;
quota exhaustion ends the run early. Unknown catalog concentrations are skipped.
Provider errors/backoff and active leases remain respected with `--retry-cached`.

### Live validation results — October 22, 2026

Ten fragrances were observed using ten queries within the unchanged daily cap.
Three had accepted offers: Dior Sauvage EDP, Versace Crystal Noir EDT, and Chloé
EDP (**30% coverage in this small selected sample**, not a catalog-wide estimate).
The sample included popular, premium and potentially affordable fragrances.

The public recommendation endpoint returned Crystal Noir EDT in the $60 Budget
row at **$59.99 for approximately 89 ml**, with its observation time and Amazon
link. Detail endpoints returned HTTP 200 for all three matched fragrances. Saved
responses can now be diagnosed and replayed without additional provider queries.
Many rejected listings omitted brand, size or concentration; others represented
samples, sets or different concentrations. These were results from the original matcher.

Direct Amazon product-page requests could not be fetched in the validation
environment. Independent variant/availability/checkout-price checks therefore
remain unverified. This establishes live provider-to-API and Budget integration,
not broad coverage or independently measured price accuracy. The local aggregate
report is `data/processed/pricing-validation/diagnostic-20261022/summary/report.json`.


Replaying these same saved responses with optional brand text increased coverage
from 3/10 to **5/10**, adding Versace Eros EDP and YSL Y EDP. No new provider
requests were needed. Concentration, size, scent/flanker identity, price and
retail-product checks remain required. The local price cache was rebuilt from
these observations with their original timestamps preserved. This measures
matching coverage, not independent confirmation of the offers' identity or price.
Updated report: `data/processed/pricing-validation/diagnostic-20261022/optional-brand/report.json`.


Catalog-aware descriptive matching now accepts **7/10** saved searches, including
Montblanc Legend EDP and 4711 Original EDC. No additional provider queries were
used. Other brands' Legend listings remain rejected when the brand context does
not support Montblanc. Updated report:
`data/processed/pricing-validation/diagnostic-20261022/catalog-matching-v2/report.json`.
