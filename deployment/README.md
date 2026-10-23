# Before deployment

The product remains local. These changes do not create GCP resources, spend cloud
credits, send real email, rotate credentials, or publish data.

## Checks available now

- `make test`: backend regression tests, including account deletion confirmations,
  password/session revocation, Google identity conflicts, OAuth browser-state
  binding, email-provider failures, production configuration and artifact integrity.
- `cd frontend && npm test && npm run lint && npm run build`: URL/filter and proxy
  origin/redirect policy tests, lint and production build.
- `make release-check`: six real collections (fresh, sweet, Middle Eastern, niche,
  feminine and clone-heavy) with six filter configurations each. The ignored
  `data/processed/release-check.json` records row sizes and timings. It checks
  exclusions, uniqueness, constraints, intentional empty results and taste variation.
  It does not judge subjective scent quality or make live retailer searches.
- `make artifacts`: creates `data/processed/deployment/fragrance-artifacts.tar.gz`.
  The archive contains `perfumes.parquet`, `features.npz`, `vocab.json`,
  `scores.parquet`, `clones.parquet`, `images.json` and a SHA-256 manifest.
  Verify with `cd backend && .venv/bin/python -m pipeline.artifacts --verify
  ../data/processed/deployment/fragrance-artifacts.tar.gz`. Never add account
  databases, `.env`, mail outboxes or raw downloads to this bundle.
- `.github/workflows/checks.yml` runs portable backend/SQLite/PostgreSQL checks
  and frontend checks on pushes to main and pull requests. It requires no live
  Google, Kaggle, Resend or SerpApi credentials. The workflow starts running after
  it is pushed; local test success does not imply a GitHub run has already passed.

## PostgreSQL verification

Tests use a disposable database named **fragrance_test**. Never point this command
at an account database: tests recreate the schema and delete test rows.

```sh
cd backend
TEST_POSTGRES_URL='postgresql+asyncpg://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/fragrance_test' \
  .venv/bin/pytest -q tests/test_accounts.py tests/test_migrations.py
```

The same schema migration sequence is checked on both SQLite and PostgreSQL:
upgrade, metadata consistency check, downgrade, and upgrade. The OAuth identity
index fails safely if historical duplicate provider identities exist; resolve
ownership explicitly rather than deleting accounts automatically.

This verifies the schema, not a transfer of existing local account data. Before
launch, decide whether to retain the local accounts/collections. If retaining
them, take a private backup and perform a separate controlled data migration;
never place the SQLite account database in a public catalog bucket or repository.

## Production configuration

Use `production.env.example` as a reference, with real secrets stored outside Git.
Setting `ENVIRONMENT=production` validates HTTPS, secure cookies, a stable auth
secret, PostgreSQL/asyncpg, a configured email provider/sender, and the Google
callback address. Invalid startup settings report requirements without printing
input secret values.

Keep the website and OAuth callback on the same public origin. The backend can
run separately; the Next.js server proxies the callback and forwards the session
cookie to the browser. Register these exact production redirect URIs with Google:

```text
https://YOUR_WEBSITE_HOST/api/account/auth/google/callback
https://YOUR_WEBSITE_HOST/api/account/auth/google/associate/callback
```

Set backend `GOOGLE_OAUTH_REDIRECT_URL` to the first URI, backend `FRONTEND_ORIGIN`
and frontend `FRAGRANCE_PUBLIC_ORIGIN` to `https://YOUR_WEBSITE_HOST`, and frontend
`FRAGRANCE_API_URL` to the backend address. The explicit public origin validates
browser mutations and callback return addresses behind an HTTPS reverse proxy.
Local development can continue using the existing localhost:8001 callback URIs.

Use `uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --no-access-log` for the
backend. JSON diagnostics contain request IDs, method, path, status and duration;
they deliberately omit query parameters, bodies, cookies, recipient details and
exception values. `/health` is liveness and `/health/ready` checks the catalog and
account database. Configure deployment health probes and error/latency alerts when
the service exists. Run migrations once as a release step before serving traffic.

The default rate-limit storage is per process. Start with one backend instance
and one worker, or configure a shared supported store before scaling. Keep
`PRICING_AUTO_REFRESH=false` and the 10-search daily limit until scheduled refresh
is deliberately enabled. Catalog load time, instance memory, and concurrent-load
behavior still need measuring on the chosen Cloud Run instance configuration.

## Human steps before public launch

1. Rotate the Google OAuth client secret shared earlier and replace it privately.
2. Set up a Resend account and verify a sending domain; configure its key and
   `EMAIL_FROM`. Email remains in the development outbox until then.
3. Configure the production hostname, OAuth audience/test users as appropriate,
   and both redirect URIs above. Check real Google login and linking in a fresh
   browser session. Local provider tests use mocks and grant no real Google access.
4. Send a verification email and reset email to a real inbox, follow their links,
   and check password change, logout and account deletion using a disposable
   production test account.
5. Provision the selected GCP services, private artifact storage, persistent
   database/backups, Secret Manager values, billing alerts and runtime health alerts.
   Connect GitHub deployment only after the release checks pass.
6. Preserve dataset attribution. Confirm commercial-use permission before adding
   affiliate revenue; the dataset is licensed CC BY-NC-SA 4.0.

Jomashop and broader Amazon coverage can follow launch; unpriced scents remain
useful recommendations and do not receive invented purchase prices.
