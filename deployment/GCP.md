# GCP deployment runbook

Preparation is checked into Git. The commands below are **manual release steps**;
none run automatically on push. Provisioning/building can incur GCP charges.
Use project `fragrance-recommender-511822`, initially in `us-central1`.

## Architecture and launch gates

- Cloud Run `fragrance-web`: Next.js standalone server; public website and
  same-origin account/API proxies. No database/provider secrets in this service.
- Cloud Run `fragrance-api`: FastAPI, one worker, max one instance initially,
  2 GiB memory and concurrency 4 as a starting point; measure before raising.
- Cloud SQL PostgreSQL: persistent users, collections, filters and price cache.
- Secret Manager: database URL, stable session secret, rotated Google secret,
  Resend key and optional SerpApi key. Grant access only to the backend identity.
- Artifact Registry: private, versioned backend/frontend images. The backend image
  contains only six processed catalog files, no accounts or credentials.
- Cloud Run Job `fragrance-migrate`: same backend image and database configuration,
  runs Alembic once before the new backend revision serves traffic.

Before proceeding: verify a Resend sending domain and real delivery; production
configuration deliberately rejects the local email outbox. Google credential
rotation and local sign-in were confirmed by the owner on 23 October 2026.
Decide whether to migrate local accounts: Alembic creates the schema, not copies
of local accounts or prices. Preserve any retained data via private backup and a
separate reviewed import. Until cached offers are populated, Budget can be empty
and fragrances may have no Amazon link. Do not upload `dev.db` with the catalog.

Set a billing budget/alerts, backups and point-in-time recovery before launch.
Budget alerts notify; they do not cap spending. Cloud SQL has ongoing costs even
when Cloud Run scales to zero. Review the console estimate before creating it.

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
   Artifact Registry, Cloud SQL Admin and Secret Manager APIs.
2. Create a **Docker** Artifact Registry repository named `fragrance` in
   `us-central1`. Keep it private.
3. Create a PostgreSQL Cloud SQL instance in the same region, database `fragrance`,
   and a dedicated application database user. Enable automated backups/PITR.
   Use Cloud Run's Cloud SQL integration, not an unrestricted authorized-network
   rule. Record the connection name `PROJECT:REGION:INSTANCE`.
4. Create separate service accounts `fragrance-web` and `fragrance-api`.
   Give the API account Cloud SQL Client and Secret Manager Secret Accessor
   **on the required individual secrets**. Use it for the migration job too.
   The web account needs neither database nor secret access.
5. Grant the build identity Artifact Registry Writer on the repository; grant
   the release operator permission to deploy and act as the runtime identities.
   Cross-project setups also need explicit image-reader grants.

Create Secret Manager entries via the console; never paste values in Git or shell
arguments. Suggested names: `fragrance-database-url`, `fragrance-auth-secret`,
`fragrance-google-secret`, `fragrance-resend-key`, optional `fragrance-serpapi-key`.
Use a newly generated random auth secret of at least 32 characters, stable across
revisions. Percent-encode database username/password in the URL. For asyncpg with
the Cloud SQL Unix socket, the URL format is:

```text
postgresql+asyncpg://USER:ENCODED_PASSWORD@/fragrance?host=/cloudsql/PROJECT:REGION:INSTANCE
```

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
EMAIL_BACKEND: resend
EMAIL_FROM: 'Fragrance Recommender <hello@YOUR_VERIFIED_DOMAIN>'
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
Use the verified origin in emailed links. Do not change local `.env` to cloud
values; deployment settings are separate.

## 5. Run migrations once

Replace `SQL_CONNECTION_NAME`, image digest and any secret-version placeholders.
Use `gcloud run jobs update` for later releases after initial creation:

```sh
gcloud run jobs create fragrance-migrate --project="$FRAGRANCE_PROJECT" \
  --region="$FRAGRANCE_REGION" --image=API_IMAGE_DIGEST \
  --service-account="fragrance-api@$FRAGRANCE_PROJECT.iam.gserviceaccount.com" \
  --set-cloudsql-instances=SQL_CONNECTION_NAME \
  --env-vars-file=deployment/local/api-env.yaml \
  --set-secrets=DATABASE_URL=fragrance-database-url:1,AUTH_SECRET=fragrance-auth-secret:1,GOOGLE_OAUTH_CLIENT_SECRET=fragrance-google-secret:1,RESEND_API_KEY=fragrance-resend-key:1 \
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
  --add-cloudsql-instances=SQL_CONNECTION_NAME \
  --env-vars-file=deployment/local/api-env.yaml \
  --set-secrets=DATABASE_URL=fragrance-database-url:1,AUTH_SECRET=fragrance-auth-secret:1,GOOGLE_OAUTH_CLIENT_SECRET=fragrance-google-secret:1,RESEND_API_KEY=fragrance-resend-key:1 \
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
  and email verification/reset must work on the real HTTPS origin. Use a disposable
  account to test password changes/session revocation and deletion.
- Measure cold starts, peak memory, concurrent latency, and DB connections. Check
  database backups and restore procedure. Configure alerts for readiness failures,
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

References: [Cloud Run secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets),
[Cloud Run migrations](https://cloud.google.com/blog/topics/developers-practitioners/running-database-migrations-cloud-run-jobs),
[Cloud Build submit](https://docs.cloud.google.com/sdk/gcloud/reference/builds/submit),
[upload exclusions](https://docs.cloud.google.com/sdk/gcloud/reference/topic/gcloudignore).
