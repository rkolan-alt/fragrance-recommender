# GCP deployment runbook

Preparation is checked into Git. The commands below are **manual release steps**;
none run automatically on push. Provisioning/building can incur GCP charges.
Use project `fragrance-recommender-511822`, initially in `us-central1`.

## Architecture and launch gates

- Cloud Run `fragrance-web`: Next.js standalone server; public website and
  same-origin account/API proxies. No database/provider secrets in this service.
- Cloud Run `fragrance-api`: FastAPI, one worker, max one instance initially,
  2 GiB memory and concurrency 4 as a starting point; measure before raising.
- Neon Free PostgreSQL: persistent users, collections, filters and price cache.
  No paid Cloud SQL instance is part of this launch.
- Secret Manager: database URL, stable session secret, rotated Google secret,
  optional SerpApi key. Resend is not needed for the Google-only launch.
  Grant access only to the backend identity.
- Artifact Registry: private, versioned backend/frontend images. The backend image
  contains only six processed catalog files, no accounts or credentials.
- Cloud Run Job `fragrance-migrate`: same backend image and database configuration,
  runs Alembic once before the new backend revision serves traffic.

This launch uses guest access and Google sign-in on the provided HTTPS
`run.app` address. No domain purchase or Resend setup is required. Set
`EMAIL_PASSWORD_ENABLED=false`; password registration, login, recovery and
verification are disabled in both API and UI. Google credential
rotation and local sign-in were confirmed by the owner on 23 October 2026.
Decide whether to migrate local accounts: Alembic creates the schema, not copies
of local accounts or prices. Existing email-only accounts must connect Google
while email login is still enabled before moving to a Google-only environment;
matching email addresses are never silently merged. Preserve any retained data
via private backup and a
separate reviewed import. Until cached offers are populated, Budget can be empty
and fragrances may have no Amazon link. Do not upload `dev.db` with the catalog.

The owner selected a free-tier database on 23 October 2026. Use Neon Free, not
Cloud SQL. Neon currently includes 1 GB storage and 100 CU-hours per project per
month; check its dashboard for current limits. It can suspend when idle and pause
when free limits are reached. Do not upgrade to a paid plan without approval.
Cloud Run, builds, image storage, secrets and network traffic can still incur GCP
charges. Configure billing alerts; alerts do not cap spending. Keep app minimum
instances at zero. Arrange private database exports and review free-plan recovery
limits before launch; do not assume paid backup/PITR guarantees.

## 1. Local verification and image builds

From the repository root:

```sh
make test
make lint
cd frontend && npm test && npm run build && cd ..
make release-check
make artifacts
gcloud meta list-files-for-upload
```

Inspect the final command's list: only application sources, deployment build
files and the six allowed processed files belong there. `.gcloudignore` includes
the `.dockerignore` allowlist; raw data, `.env`, databases, mail and dependencies
are excluded. Artifacts are ignored by Git, so a fresh GitHub checkout alone
cannot build the backend. For now submit locally after regenerating/verifying
artifacts. Use only trusted catalog files. Future CI will need private artifact
storage and workload identity; no deployment workflow is enabled yet.

Optional local Docker checks:

```sh
docker build -f deployment/backend.Dockerfile -t fragrance-backend:predeploy .
docker build -f deployment/frontend.Dockerfile -t fragrance-frontend:predeploy .
```

Both runtime containers run as unprivileged users and listen on `$PORT` (8080).
Dependencies resolve at build time; before repeatable releases, pin reviewed
Python dependencies and base-image digests. Release using the resulting immutable
image digest rather than a moving tag.

## 2. Provision infrastructure

Use the GCP console or reviewed infrastructure commands to:

1. Confirm the project/billing account and enable Cloud Run, Cloud Build,
   Artifact Registry and Secret Manager APIs (no Cloud SQL API required).
2. Create a **Docker** Artifact Registry repository named `fragrance` in
   `us-central1`. Keep it private.
3. In [Neon](https://console.neon.tech/), create a **Free** project named
   `fragrance-recommender`. Choose a US region near `us-central1` if available;
   use PostgreSQL 17 to match CI. Keep the default `neondb` database or create
   `fragrance`. Keep managed Neon Auth disabled: this app already manages Google
   sign-in. Use the pooled endpoint for app traffic and direct/unpooled endpoint
   for migrations. Keep scale-to-zero enabled.
4. Create separate service accounts `fragrance-web` and `fragrance-api`.
   Give the API account Secret Manager Secret Accessor **on the required individual
   secrets**; use it for the migration job too. Neither account needs Cloud SQL
   Client. The web identity needs no database/provider secret access.
5. Grant the build identity Artifact Registry Writer on the repository; grant
   the release operator permission to deploy and act as the runtime identities.
   Cross-project setups also need explicit image-reader grants.

Create Secret Manager entries via the console; never paste values in Git or shell
arguments. Suggested names: `fragrance-database-url`, `fragrance-auth-secret`,
`fragrance-google-secret`, `fragrance-database-unpooled` for the migration job,
optional `fragrance-serpapi-key`.
Use a newly generated random auth secret of at least 32 characters, stable across
revisions. The existing linked workspace uses `neon.ts` (Postgres only) and the
CLI. Run `neon login` if necessary, review `neon config plan`, then `neon deploy`.
The CLI preserves unrelated `.env` keys and writes `DATABASE_URL` (pooled),
`DATABASE_URL_UNPOOLED` (direct), and `NEON_BRANCH`. These files are ignored.
The original local environment/database were backed up under `deployment/local/`.

The backend accepts the Neon PostgreSQL URLs as supplied, normalizes the driver
to asyncpg, and translates libpq TLS parameters into certificate/hostname-verified
TLS. It keeps a small application connection pool and checks stale connections.
Alembic prefers `DATABASE_URL_UNPOOLED`. Do not print these URLs: they contain
passwords. Map the pooled URL to `fragrance-database-url` and the direct URL to
`fragrance-database-unpooled` in Secret Manager. Map the latter only into the
migration job as `DATABASE_URL_UNPOOLED`.

Local setup has validated the schema on an expiring branch before production,
then privately copied existing local account/collection and cached pricing data
into the initially empty production tables in one transaction. The original
SQLite file was left unchanged. Do not repeat that initial import into a
nonempty destination. No account data belongs in build uploads or Git.

Use numbered secret versions for releases so a rollback also restores its secret
configuration. The examples below use version `1`; replace it when necessary.

## 3. Build in GCP (uploads catalog sources, incurs build charges)

Run only after the infrastructure above exists:

```sh
export FRAGRANCE_PROJECT=fragrance-recommender-511822
export FRAGRANCE_REGION=us-central1
export FRAGRANCE_TAG="$(git rev-parse --short HEAD)"
gcloud builds submit . --project="$FRAGRANCE_PROJECT" \
  --region="$FRAGRANCE_REGION" --config=deployment/cloudbuild.yaml \
  --substitutions="_REGION=$FRAGRANCE_REGION,_TAG=$FRAGRANCE_TAG"
```

Record the two pushed image digests. Replace `WEB_IMAGE_DIGEST` and
`API_IMAGE_DIGEST` below with full `us-central1-docker.pkg.dev/...@sha256:...`
addresses. This build configuration builds/pushes images only.

## 4. Establish the website origin and configure runtime

Create the web service first to obtain its HTTPS URL. It can serve the shell,
but API features will be unavailable until step 6. Keep it unadvertised:

```sh
gcloud run deploy fragrance-web --project="$FRAGRANCE_PROJECT" \
  --region="$FRAGRANCE_REGION" --image=WEB_IMAGE_DIGEST \
  --service-account="fragrance-web@$FRAGRANCE_PROJECT.iam.gserviceaccount.com" \
  --allow-unauthenticated --port=8080 --memory=512Mi --cpu=1 \
  --min-instances=0 --max-instances=1 --concurrency=20
```

Copy its HTTPS service URL (no trailing slash) into backend `FRONTEND_ORIGIN`,
frontend `FRAGRANCE_PUBLIC_ORIGIN`, and both Google production callback settings.
Use the custom domain instead if it has already been configured.

Create ignored `deployment/local/api-env.yaml` with **nonsecret** values:

```yaml
ENVIRONMENT: production
COOKIE_SECURE: 'true'
FRONTEND_ORIGIN: https://YOUR_WEB_HOST
GOOGLE_OAUTH_CLIENT_ID: YOUR_EXISTING_CLIENT_ID
GOOGLE_OAUTH_REDIRECT_URL: https://YOUR_WEB_HOST/api/account/auth/google/callback
EMAIL_PASSWORD_ENABLED: 'false'
DATA_DIR: /data
PRICING_AUTO_REFRESH: 'false'
PRICING_DAILY_REQUEST_LIMIT: '10'
RATE_LIMIT_STORAGE_URI: 'memory://'
```

Register these additional URIs in the existing Google web client; retain the
localhost URIs for development:

```text
https://YOUR_WEB_HOST/api/account/auth/google/callback
https://YOUR_WEB_HOST/api/account/auth/google/associate/callback
```

Review Google Auth Platform's audience/publishing status and test-user access.
Use this exact origin for Google callbacks. Do not change local `.env` to cloud
values; deployment settings are separate.

## 5. Run migrations once

Replace image digest and any secret-version placeholders. Use the direct Neon
URL for migrations; there is no Cloud SQL attachment.
Use `gcloud run jobs update` for later releases after initial creation:

```sh
gcloud run jobs create fragrance-migrate --project="$FRAGRANCE_PROJECT" \
  --region="$FRAGRANCE_REGION" --image=API_IMAGE_DIGEST \
  --service-account="fragrance-api@$FRAGRANCE_PROJECT.iam.gserviceaccount.com" \
  --env-vars-file=deployment/local/api-env.yaml \
  --set-secrets=DATABASE_URL=fragrance-database-url:1,AUTH_SECRET=fragrance-auth-secret:1,GOOGLE_OAUTH_CLIENT_SECRET=fragrance-google-secret:1,DATABASE_URL_UNPOOLED=fragrance-database-unpooled:1 \
  --command=alembic --args=upgrade,head --tasks=1 --parallelism=1 \
  --max-retries=0 --task-timeout=300s --memory=1Gi
gcloud run jobs execute fragrance-migrate --project="$FRAGRANCE_PROJECT" \
  --region="$FRAGRANCE_REGION" --wait
```

Do not deploy the backend if migrations fail. Review existing OAuth duplicate
ownership if its unique-index migration fails. Never automatically delete users.

## 6. Deploy API and connect web

```sh
gcloud run deploy fragrance-api --project="$FRAGRANCE_PROJECT" \
  --region="$FRAGRANCE_REGION" --image=API_IMAGE_DIGEST \
  --service-account="fragrance-api@$FRAGRANCE_PROJECT.iam.gserviceaccount.com" \
  --env-vars-file=deployment/local/api-env.yaml \
  --set-secrets=DATABASE_URL=fragrance-database-url:1,AUTH_SECRET=fragrance-auth-secret:1,GOOGLE_OAUTH_CLIENT_SECRET=fragrance-google-secret:1 \
  --allow-unauthenticated --port=8080 --memory=2Gi --cpu=1 \
  --min-instances=0 --max-instances=1 --concurrency=4 --timeout=60s \
  --startup-probe=httpGet.path=/health/ready,httpGet.port=8080,initialDelaySeconds=5,periodSeconds=10,timeoutSeconds=5,failureThreshold=20
gcloud run services update fragrance-web --project="$FRAGRANCE_PROJECT" \
  --region="$FRAGRANCE_REGION" \
  --update-env-vars=FRAGRANCE_API_URL=https://YOUR_API_HOST,FRAGRANCE_PUBLIC_ORIGIN=https://YOUR_WEB_HOST
```

The initial API is public at the platform layer; account endpoints still enforce
application authentication and CSRF. Do not switch it to IAM-only without first
adding service-to-service ID tokens in the Next.js proxies. Public search and
recommendation endpoints also need abuse/load monitoring. Keep one backend
instance/worker while the limiter is in memory; moving beyond that needs a shared
rate-limit store. Max instances is an operational scaling setting, not a strict
global rate-limit guarantee (revision overlap can occur).

If deliberate live price refresh is needed later, grant only the API identity
access to `fragrance-serpapi-key` and map it as `SERPAPI_KEY`. Populate validated
offers through a separately controlled refresh/import; keep automatic refresh
off until its budget and schedule are approved. Prices from the local SQLite
database are not bundled in either image.

## 7. Verify, observe, release

- `/health/ready` must return 200. Verify guest search, five-item collections,
  personalized rows, filters, empty states, images and mobile navigation.
- Fresh Google sign-in, Google linking, account persistence after a new revision,
  must work on the real HTTPS origin. Confirm email/password controls are absent
  and direct password/email API calls are rejected. Use a disposable account for
  deletion checks. If email/password is enabled later, first configure Resend, a
  verified sender and its secret mapping, then test verification/reset delivery.
- Measure cold starts, peak memory, concurrent latency, and DB connections. Check
  private database export and restore procedure, and Neon free-tier quotas. Configure alerts for readiness failures,
  5xx rates, latency, memory and billing.
- Cloud Run's platform request logs can contain OAuth query strings independently
  of application logging. Restrict log access/retention and configure a Logs Router
  exclusion for callback request-log entries if required; never share callback
  URLs or logs containing authorization codes. Application logs omit query data.
- Roll back traffic to the previous healthy image/revision on application failure.
  Database downgrades are a separate reviewed recovery action; take backups and
  ensure schema compatibility before release. Do not run automatic downgrades.
- Record image/secret versions and test results. Only advertise the site after
  these checks pass. GitHub CI runs checks, not production deployment.

References: [Neon Free limits](https://neon.com/pricing),
[Cloud Run secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets),
[Cloud Run migrations](https://cloud.google.com/blog/topics/developers-practitioners/running-database-migrations-cloud-run-jobs),
[Cloud Build submit](https://docs.cloud.google.com/sdk/gcloud/reference/builds/submit),
[upload exclusions](https://docs.cloud.google.com/sdk/gcloud/reference/topic/gcloudignore).
