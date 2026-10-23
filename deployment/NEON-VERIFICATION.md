# Neon setup verification — 23 October 2026

Project: `long-morning-85497419`, branch `production`.

## Configuration

- Neon CLI 8.11.1 is installed and authenticated using the owner's browser login.
- `neon init` linked the supplied organization/project and installed the Neon
  plugin for Codex. Its MCP configuration points to `mcp.neon.tech` without an
  embedded API key. MCP tools are not exposed in this current chat; reload the
  plugin and authorize its OAuth connection before first MCP use. Verification
  below used the authenticated CLI, not MCP.
- `neon config plan`: `No changes — branch production already matches the policy.`
- `neon deploy`: Postgres only; pulled `DATABASE_URL`, `DATABASE_URL_UNPOOLED`
  and `NEON_BRANCH` into ignored `.env`. Other existing settings were preserved.
- Existing SQLAlchemy/asyncpg and Google/FastAPI Users authentication remain.
  App traffic uses the pooled URL, migrations use the direct URL. TLS validates
  certificates and hostnames. Regression migration tests explicitly clear the
  direct URL to protect real databases from test downgrades.
- Root `npm run build` builds Next.js. `npm start` serves standalone output with
  copied static assets. Local environment/database backups are private under
  ignored `deployment/local/`.

## Database rollout

Production had no application tables before setup. A temporary expiring branch
passed Alembic upgrade, metadata check, downgrade and re-upgrade before production
was upgraded. Production's metadata check reported:

```text
No new upgrade operations detected.
```

The existing local SQLite database was snapshotted read-only, then copied into
initially empty production tables in one transaction. UUIDs, timestamps, provider
links and account data were preserved; the original SQLite file was unchanged.
Counts verified after test cleanup: 1 original account, 5 collection items,
51 offers, 5 product links. No live retailer searches were made.

## Application verification

```text
npm run build: exit 0; Compiled successfully
pytest: 206 passed, 1 skipped
frontend tests: 5 passed
backend/frontend lint and git diff --check: passed
```

The built website on temporary port 3010 proxied to an API on 8002 backed by real
Neon PostgreSQL. HTTP checks verified:

- website and static JavaScript assets: HTTP 200;
- catalog search and guest recommendations with cached prices;
- Google-only feature options and rejection of email registration/recovery;
- creation of a disposable verified account/session, five collection items and
  a custom filter, followed by saved-collection recommendations;
- logout and returning sign-in preserve data; an unauthenticated visitor receives
  401 when requesting saved collections;
- a real API/website process restart preserves the session, collection and filter;
- self-service deletion removes only the disposable account and revokes its session;
- original imported account, collection and offers remain; `/health/ready`: 200.

Only Google's token/identity responses were synthetic in the first isolated API
process. Database traffic, HTTP proxies, session persistence and collection/filter
operations were real. After restart the API ran without provider mocks. No new
interactive real Google sign-in was performed during this verification.

## Issues and remaining deployment work

- Free plan rejected an explicit suspend interval while creating the validation
  branch. Retrying with the plan's default succeeded; no plan upgrade was made.
- `next start` warned about standalone output. Root `npm start` was corrected to
  launch the standalone server and verified with real static assets.
- Temporary account and validation branch were removed after verification.
- The website is still local; no public Cloud Run website was deployed by this
  Neon setup. Production HTTPS OAuth callbacks and a fresh interactive Google
  login still need checking when Cloud Run is deployed.
- Restart the existing local backend to load the new environment variables.
  Local email-account development remains enabled by default; the cloud reference
  configuration uses `EMAIL_PASSWORD_ENABLED=false` for guest/Google-only launch.
