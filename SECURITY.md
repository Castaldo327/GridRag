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
time and memory limits. Persistent secrets, extension autoinstall/autoload, and
external access are disabled before configuration is locked. Logging, sleeping,
sequence mutation, and configuration-reading functions are rejected in parsed SQL.
Model instructions are not the security boundary. These engine settings are defense
in depth, not an operating-system sandbox; see [DuckDB's security model](https://duckdb.org/security).

Vercel bundles a generated DuckDB file with the Python function. It is not copied
to the public static directory. The build copies an explicit list of frontend
assets, and excludes local credentials, experiments, artifacts and model caches
from uploads. Security headers restrict scripts and connections to the same origin.
Inline scripts and styles, embedded objects, and frames are blocked. Markdown is
rendered through pinned local Marked/DOMPurify bundles with a tag/attribute allowlist;
model output cannot inject scripts, images, event handlers, or executable links.
The API rejects oversized, incomplete, ambiguous, and excessively nested JSON bodies.

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

### Reviewed historical exposure

The November 6, 2026 review found one Vercel OIDC JWT in a historical `.env.local`
blob (`4c5c1f9c41b1`, introduced in commit `7ad2744`). Its encoded expiration was
**November 5, 2026 at 07:26:57 UTC**. It is absent from the current tracked files
and deployment. No active provider credential was found in the scanned source or
history. Expiration does not establish whether it was accessed during its original
lifetime; account audit logs remain the source for that question.

The focused scanner reports this exact immutable blob as an advisory instead of
silently hiding it. Gitleaks has a single commit/path/rule/line exception in
`.gitleaksignore` for the same reviewed, expired token. These exceptions do not
apply to current-file copies, new commits, changed blobs, or other credential
categories. JWT detection now runs even when no local environment files exist.
Git history has not been rewritten; removing historical copies everywhere would
also require coordination with the repository host and existing clones.

If a real credential was ever public, revoke and replace it; deleting the current
file does not remove it from previous commits or copies.

## Deployment scope

This is a hardened demonstration, not a multi-tenant production service. It has no
user authentication, tenant data entitlements, or strong per-query process isolation.
The process-local concurrency lock is not a global Vercel rate limit. A production
deployment with organizational data needs those controls and broader
adversarial and accuracy evaluation. The public demo uses only synthetic data.

### Public sharing assessment — November 6, 2026

Sharing the Vercel demo is reasonable within that scope. Demo, Architecture, and
Evaluation use static assets, require no key, and make no model calls. Playground
requests cannot spend an owner's provider key. Production has no configured
environment variables. Private paths and the warehouse file are not public assets.

Remaining risks include hosting quota exhaustion or interruption from abusive
traffic, incorrect model-generated SQL/answers, and visitors choosing to trust this
backend with their own API key. A per-IP edge rate limit reduces repeated API
requests but cannot eliminate distributed abuse; Vercel counters are regional.
Account usage alerts and firewall activity should be monitored after sharing.
Do not use the hosted demo with private data or describe this limited synthetic
benchmark as a production accuracy guarantee.

The review used request/SQL regression tests, a full-history redacted scan,
network-isolated Gitleaks, pip-audit for 21 installed runtime packages, and npm's
advisory endpoint for the two vendored browser libraries. No known dependency
advisories were returned on the review date. Dependency scans identify known
advisories, not every possible vulnerability.

Do not put credentials in public bug reports. Report reproducible issues using
synthetic inputs and redacted diagnostics.
