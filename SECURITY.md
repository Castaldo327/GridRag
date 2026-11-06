# Security and privacy

GridRag uses generated, fictional grid data. It contains no employer dataset or
customer records. Public pages include schema documentation and selected synthetic
results so visitors can inspect the experiment.

## Visitor credentials

The hosted playground requires each visitor's own OpenAI key. The key is held in
JavaScript memory, sent in an Authorization header over HTTPS to this application's
backend, and used by a request-scoped provider client. The app does not write it to
browser storage, files, analytics, or application logs. Reloading or removing the
key clears it from the tab. Do not configure an owner's API key on Vercel; public
endpoints ignore one even if it is present. The CLI can use a local ignored `.env`.

Provider requests contain the question, selected schema and returned synthetic
rows. OpenAI and the hosting provider have their own retention policies. The app
makes no claim of zero retention by infrastructure providers. Do not enter private
information in questions. API usage is billed to the visitor's project.

## Database boundary

Only explicitly registered catalog tables are queryable. The database opens
read-only; the SQL guard accepts one SELECT statement, validates table and function
references, disables external access, locks configuration, and applies row, byte,
time and memory limits. Model instructions are not the security boundary.

Vercel bundles a generated DuckDB file with the Python function. It is not copied
to the public static directory. The build copies an explicit list of frontend
assets, and excludes local credentials, experiments, artifacts and model caches
from uploads. Security headers restrict scripts and connections to the same origin.

## Before making source public

Run `uv run python -m scripts.security_audit --history`. It prints categories and
locations, never secret values. It checks known credential patterns, private keys,
personal paths, email addresses and exact copies of secrets in local env files.
It is a focused guard, not exhaustive secret detection. CI also runs Gitleaks against
all reachable Git history, with redacted output and networking disabled during the scan.

Run `uv run python -m scripts.public_release` to prepare `artifacts/public-source`.
This explicit source snapshot excludes `.git`, environment files, hosting project
metadata, local output, screenshots and experiments. Publish from that clean copy
if the working repository has private historical content. Review the included
`RELEASE_MANIFEST.json`. Choose a public-safe Git author identity before creating
new commits; Git records author names and email addresses separately from files.
Existing history is not rewritten by these scripts.

If a real credential was ever public, revoke and replace it; deleting the current
file does not remove it from previous commits or copies.

## Deployment scope

This is a hardened demonstration, not a multi-tenant production service. It has no
user authentication, tenant data entitlements, distributed rate limiter or strong
per-query process isolation. The process-local concurrency lock is not a global
Vercel rate limit. A production deployment needs those controls and broader
adversarial and accuracy evaluation. The public demo uses only synthetic data.

Do not put credentials in public bug reports. Report reproducible issues using
synthetic inputs and redacted diagnostics.
