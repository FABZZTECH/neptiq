# NEPTIQ — RUNBOOK

ARCHITECTURE §16 requires that "a runbook exists" as a Phase 1 acceptance
condition. This is the stub; each section is filled by the task that first
makes the procedure real, because a runbook describing a procedure nobody has
executed is worse than an empty one — it reads as authoritative and is wrong.

## Verification environments

| Environment | What it verifies | Why |
|---|---|---|
| Authoring sandbox | Lint, mypy strict, pure unit tests, Hypothesis property tests, brand build, Next build | No Docker runtime available |
| **GitHub Actions** | **Authoritative gate.** Everything above, plus `docker compose up` health checks, testcontainers integration, RLS/tenant isolation, adversarial security corpus | Runners have Docker |
| Local machine | Interactive dev loop via `make dev` | Developer has Docker |

A claim of "passing" is only meaningful against the environment that ran it.
See `docs/ADR/0001` deviation register entries 1 and 2.

## Procedures

- **Bring up local infrastructure:** `make dev` — see `docker-compose.yml`.
- **Apply migrations:** `make migrate` (forward-only; see §15).
- **Rebuild brand assets:** `make brand`.
- **Run everything runnable here:** `make check`.

## Not yet written

Backup restore rehearsal (§15 requires monthly, and a skipped rehearsal two
months running blocks the release). Worker lease draining. Crawl abort. Egress
IP rotation. Incident response for a block-request (§10 mandates a 24-hour
SLA). KEK rotation. Each arrives with the system it operates.
