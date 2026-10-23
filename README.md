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

The offline data pipeline, feature vectors, clone exclusions, recommendation API,
accounts backend, and Amazon pricing are implemented. The frontend now supports
guest and account collections, email/password and Google sign-in, guest collection
import, personal ratings, wishlist/disliked statuses, real recommendation carousels,
clone inclusion, and fragrance details. Advanced filters, account settings and
public deployment are still to come.

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
`backend/mail-outbox/` directory. Open the message’s link to use the website’s
`/verify-email` or `/reset-password` page. No email is actually delivered in outbox
mode. For real delivery, set `EMAIL_BACKEND=resend`,
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
`/auth/google/associate/authorize` (account linking is currently API-only).
The website requests `/auth/google/authorize?web=true`; successful callbacks
retain the session cookie and redirect to the fixed `FRONTEND_ORIGIN`. Failures
return to the sign-in screen. Direct API sign-in still returns its normal 204.
For local Google login, frontend and callback must use the same hostname
(`localhost`, on ports 3000 and 8001). The website carries the guest collection
from `127.0.0.1` to the configured frontend origin before starting Google; the
transfer contains only fragrance metadata and is removed from the URL immediately.
Production must similarly keep the callback and website on one hostname through
a reverse proxy, with HTTPS, secure cookies and matching Google redirect settings.

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
`make prices` refreshes up to 50 popular perfumes,
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

Pricing is Amazon-only. Priced offers require a direct HTTPS Amazon.com link, a
listing-declared concentration, the same fragrance including flanker terms,
a 25–300 ml bottle, and a USD price. Testers, samples, decants, sets, refills,
non-fragrance products, unavailable stock and installment prices are rejected.
Missing catalog concentrations no longer block pricing. A listing must declare
its concentration; if that concentration belongs to a separately named catalog
version (e.g. Sauvage EDP), it is not assigned to the base fragrance. Nothing
invents bottle size or concentration.

A positively identified Amazon product may have an `amazon_link` without a
priced offer when its search title omits size/concentration. This shows **View
on Amazon**, with no quoted price (`best_offer: null`, `price_status: link_only`).
These product links never qualify for Budget. Products with neither a matched
offer nor an identified product remain unlinked; search links stay empty.
Jomashop coverage remains deferred.

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
`price_status`, `pricing_source`, `price_label`, `price_basis`, `amazon_link`, and `search_links`.
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
quota exhaustion ends the run early. Catalog concentration may be absent; retailer concentration is required for priced offers.
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


## Local website — collection builder and recommendations

With the data artifacts and migrations already prepared, start the backend and
frontend in separate terminals from the project root:

```sh
make backend
```

```sh
make frontend
```

Open [the local website](http://127.0.0.1:3000). Keep using the same origin:
`localhost` and `127.0.0.1` have separate browser storage. Search by fragrance or
brand, select at least five distinct bottles, then choose **Discover my matches**.
**Try an example collection** fetches five real catalog entries to get started.
Guest collections persist in this browser. Choose **Sign in / Save collection**
to create an account, use email/password, or continue with Google. Guest bottles
are merged into the account without replacing existing statuses or ratings; browser
data is cleared only after a successful import. Signed-in collection edits save
to the database, and returning users with five owned bottles load matches automatically.
Use personal ratings beside owned bottles, or open details to add to your collection,
wishlist, or disliked list. Wishlist and disliked bottles do not count toward the
five-owned-bottle minimum. Sign out hides account collection data.

Recommendation rows support swipe, arrow buttons and keyboard navigation. Cards
show ratings, accord profiles, an explanation, and Amazon offers only when
available. Bottle photos appear alongside fragrance names in search, your collection,
recommendation cards and details. Select a card to open the notes, accord strengths, season votes and
longevity. Removing a fragrance or changing clone inclusion hides results that
no longer match the current inputs. Search prevents duplicate entries.

Browser requests use same-origin `/api/search`, `/api/recommend` and
`/api/perfumes/<id>`. These narrow guest proxies connect to the FastAPI backend
without forwarding login cookies, so an existing backend login does not change
guest recommendation behavior. Signed-in requests use the allowlisted
`/api/account/*` proxy, which forwards only account cookies and CSRF headers,
checks the browser origin for mutations, preserves upstream Set-Cookie headers,
and disables caching. Credentials remain in httpOnly cookies. The default upstream is `http://127.0.0.1:8001`.
To change it, set `FRAGRANCE_API_URL` in **frontend/.env.local**, then restart Next.
The frontend does not load the backend's root `.env` or expose its credentials.

Frontend verification: `npm run lint` and `npm run build` from `frontend/`.
The production build uses Next.js's supported webpack builder to avoid a local
Turbopack worker-permission failure. No external font downloads are required.
Manual browser checks cover real autocomplete, keyboard selection, duplicate
prevention, the minimum of five, reload persistence, recommendation generation,
card details, carousel controls, input-change invalidation, and desktop/mobile
layouts without horizontal page overflow. Account browser checks use a separate
temporary database: guest import, sign out/in, restored ratings and personalized
recommendations. Google redirects and state binding use mocked provider tests.
Advanced filtering and account settings are separate upcoming work.


### Bottle photos

The JSONL dataset contains `picture` and `thumbnail` URLs that are absent from the
CSV. Run `make images` after downloading `data/raw/perfumes.jsonl` to extract
`data/processed/images.json`. The app reads this optional, display-only sidecar;
images are never used in similarity, ranking or clone detection. The API adds
`image_url` to search, recommendations and fragrance details. Rebuilding the
sidecar is detected without restarting the backend.

Photos load lazily from the dataset's Fragrantica image host, with no referrer.
Only HTTPS URLs on the expected image host/path are accepted. Missing or failed
images display an accessible bottle placeholder. Existing saved browser
collections resolve their image metadata using their catalog IDs. Bottle photos
are externally hosted and may differ from current packaging or go unavailable.
The URLs are not guessed from perfume IDs, and no external image-search service
or additional SerpApi credits are used.


### Budget coverage and collection-specific price discovery

Budget uses only cached matching bottle offers within the selected cap. It now
keeps the closer scent matches within that affordable pool (top 60% by similarity,
with a floor of 75% of the best affordable similarity). This avoids repeating all
cheap bottles for every collection. Verified Middle Eastern value-house matches
lead the row, retaining taste/quality ranking within that group; other affordable
houses follow. Clone, owned-item, original-of-owned-dupe, and user filter rules
still apply. A house name alone never establishes an affordable price.

Price discovery prioritizes collection-matched candidates from Lattafa, Afnan,
Rasasi, Armaf, Swiss Arabian, Ajmal and other configured value houses, covering
different brands before more fragrances from one house. It can price candidates
that do not yet appear in Budget; the old discovery loop only visited displayed
cards, so it could never grow an empty or tiny price-gated Budget pool.

To explicitly expand coverage for a collection:

```sh
cd backend
.venv/bin/python -m app.pricing.refresh --owned-ids 31861 9099 9828 5521 33519 --top 10
```

Add `--include-clones` to include them in discovery. Existing leases, price
freshness, failures and the shared daily quota remain respected. Opt-in background
pricing also alternates value candidates with ordinary recommendation candidates.
`PRICING_AUTO_REFRESH` remains false by default, and the normal daily cap stays 10.

Eight additional live searches were explicitly authorized for this development
check. Six produced usable Middle Eastern single-bottle offers: Khamrah Qahwa,
Honor & Glory, Shaghaf Oud, Rare Reef, Odyssey Limoni Fresh and Casablanca. Daarej
results were rejected as multipacks, combined products or a different version.
Aventus yielded an identified Amazon product link without a comparable price;
the API now serves that link separately. Saved responses are under ignored
`data/processed/pricing-validation/value-expansion/` and can be replayed without
more credits. These observations remain subject to normal price expiration.

Collection names now open detail dialogs, so a user can access an identified
Amazon product link for an owned fragrance such as Aventus as well as a
recommendation. This UI still does not invent a price when only a link is known.
Run `make migrate` before starting this version to create the product-links table.
