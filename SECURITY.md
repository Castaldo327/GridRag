# Security and release boundaries

GridRag is a demonstration over a fixed, fictional warehouse. The model gate and
retrieval scores help classify questions; they are not authorization controls.

Model-written SQL is parsed independently and restricted to one read-only query
over the approved tables. Table functions are allowlisted, process-state functions
are blocked, and DuckDB disables external access, extension loading and mutable
configuration. Query execution and result formatting have time, memory, row and
UTF-8 byte budgets. These safeguards do not establish that generated SQL answers
every question correctly.

Hosted live questions always require a visitor's provider key. The browser keeps
the active key in tab memory, and the backend closes its separate provider client
after the request. Request URLs, provider error bodies and credentials are excluded
from application logs. Provider requests contain the question, selected schema and
returned fictional rows. Local CLI use may read a key from the ignored `.env` file
or process environment. Use HTTPS for hosted requests.

The local HTTP server binds to loopback. Requests have bounded body sizes and
socket waits, reject ambiguous framing and cross-origin browser requests, and use
a process-local admission lock. Vercel serves the security headers declared in
`vercel.json`. Hosted evaluation endpoints are read-only and cannot start live
evaluation runs. A local admission lock is not a distributed rate limiter.

Before connecting real organizational data, supply authentication, tenant
entitlements, isolated SQL workers, distributed request limits, operational
monitoring and broader adversarial evaluation. No production accuracy or isolation
claim follows from this synthetic benchmark.

## Source and history checks

Run `python -m scripts.security_audit --history` to scan current source and reachable
Git blobs. Findings report locations and categories without printing secret values.
CI also runs Gitleaks independently. Neither scanner detects every credential or
every type of personal information.

One historical `.env.local` blob contains a reviewed Vercel OIDC token that expired
on **November 5, 2026 at 07:26:57 UTC**. The immutable blob is
`4c5c1f9c41b15dc6dc7afe38ddb361e93b7a223d`, introduced in commit
`7ad27448cb97b4206cefb56582d664b82d2f1b64`. The focused scanner reports this exact
blob as an advisory; `.gitleaksignore` records its exact historical fingerprint.
Current copies, changed blobs and other credentials remain blocking findings.
The repository's existing history also contains normal Git author metadata.

`python -m scripts.public_release` creates `artifacts/public-source/` from approved
source paths, scans the bytes and writes a SHA-256 manifest. It excludes Git
history, local environment files, deployment metadata, databases and caches.
Use that snapshot when creating a new public repository that must omit private
history, and configure a public-safe Git author identity before committing it.
The snapshot does not rewrite or remove history from the original repository.

## Reporting

Report suspected vulnerabilities through a private channel to the repository
owner. Do not put keys, tokens, provider error bodies or exploit details in public
issues. If no private channel is available, request one without disclosing the
sensitive details. Revoke exposed credentials at their provider before sharing
redacted diagnostic information.
