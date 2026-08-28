# NEPTIQ — ARCHITECTURE v2.0

Read `docs/CONSTITUTION.md` first. This document is the implementation
contract. It is authoritative on structure, stack, and invariants.

---

## 1. TRUST ZONES — THE GOVERNING STRUCTURE

Every component placement decision derives from this diagram.

    +--------------------------------------------------------------+
    | ZONE U — UNTRUSTED   (no secrets, no tools, no DB write)      |
    |   egress-proxy -> fetch-worker -> render-pool -> parse-worker |
    |   Egress only via proxy. No inbound. No DB credentials.       |
    |   Output: content-addressed blobs + a schema-validated        |
    |           manifest. Nothing else crosses.                     |
    +---------------------------+----------------------------------+
                                |
                        VALIDATION GATE
                schema-validate, size-cap, charset-normalise,
                strip control chars, taint-label every field
                                |
    +---------------------------v----------------------------------+
    | ZONE T — TRUSTED  (DB, rules engine, orchestrator, LLM)       |
    |   Tainted data may be READ. Tainted data may NEVER become     |
    |   an instruction, a SQL fragment, a URL to fetch, or a        |
    |   tool argument.                                              |
    +--------------------------------------------------------------+

## 2. SYSTEM DIAGRAM

    Browser --HTTPS--> Next.js 16 (App Router)
                           |  JSON + SSE, session cookie
                           v
                    API SERVICE (FastAPI, Python 3.13)
                    auth | RBAC | RLS session binding
                    OpenAPI 3.1 | idempotency
                       |            |             |
              enqueue  |            | read/write  |
                       v            v             v
                 jobs table    PostgreSQL 18    Redis 7
                 (SKIP LOCKED) +pgvector        cache, locks,
                               +pg_trgm         token buckets,
                               RLS everywhere   SSE fan-out
                       |
      +----------------+----------+-----------+-----------+
      v                v          v           v           v
   orchestrator    fetch(U)   analysis    connector    verifier
   workflow DAG    render(U)  rules,graph GSC/CrUX/    assert vs
   runtime         parse(U)   findings    SERP/GEO     live site
      |                |          |           |           |
      |                +----------+-----------+           |
      |                           v                       |
      |                    EGRESS PROXY  <----------------+
      |                    SSRF gate, DNS pinning,
      |                    per-host + per-tenant buckets
      |                           v
      |                    THE PUBLIC INTERNET
      v
   LLM GATEWAY (ModelRouter)          OBJECT STORAGE
   adapters: hosted + self-hosted     S3-compatible,
   budgets, cache, circuit breakers   content-addressed bodies
      |
      +--> vLLM (self-hosted floor: embeddings + reranker)
      +--> external providers via adapters

    Cross-cutting: OpenTelemetry -> collector -> Grafana stack

## 3. THE CORE LOOP

A workflow run is created. The orchestrator expands it into a typed DAG and
enqueues jobs. The fetch worker drains a per-site frontier through the egress
proxy, storing bodies content-addressed and writing immutable page_snapshots.
The parse worker extracts structure. The analysis worker loads the link graph
into memory, joins GSC and CrUX data, executes the versioned rule registry,
and writes findings with stable identity hashes plus linked evidence. The
Analyst agent produces narrative and artifact drafts — never facts. Artifacts
pass deterministic validators before display. A human approves. Deployment is
recorded as a GitHub PR or a manual attestation. The verifier re-fetches the
live resource and runs the finding's assertion. The outcome is written to the
ledger and joined against GSC data at 14, 28 and 56 days.

## 4. STACK — LOCKED

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.13, uv workspace | Parsing/robots/graph ecosystem is Python-native |
| API | FastAPI + Pydantic v2 + uvicorn | OpenAPI 3.1 generation feeds frontend types |
| Frontend | Next.js 16.3.3 exact, React, TS strict, Tailwind v4 | Active LTS; pin exactly, never "latest" |
| UI | Radix primitives, vendored not depended-on | Full control of visual language |
| Client data | TanStack Query + native EventSource | SSE for run progress |
| Database | PostgreSQL 18 + pgvector + pg_trgm + btree_gin | Async I/O; native uuidv7() PKs |
| Migrations | Alembic, forward-only, expand/contract | |
| Queue | Postgres SELECT ... FOR UPDATE SKIP LOCKED | Transactional enqueue; lease + reaper + DLQ |
| Frontier | Dedicated table, NOT the jobs table | Different lifecycle, millions of rows |
| Cache/locks | Redis 7 | Ephemeral only — never a source of truth |
| Object storage | S3-compatible (R2 primary, Hetzner fallback) | Content-addressed, zstd |
| HTTP | httpx async, transport pinned to egress proxy | |
| Parsing | selectolax, trafilatura, extruct, protego, w3lib | |
| Rendering | Playwright + Chromium, isolated pool | 15s hard budget, context destroyed per page |
| Graph | rustworkx, in-memory per run | No graph database |
| Near-dupe | SimHash via datasketch | Deterministic and explainable |
| Inference floor | vLLM, open-weight model + BGE-M3-class embeddings | Embeddings ALWAYS self-hosted |
| LLM gateway | In-house ModelRouter, OpenAI-compatible adapters | No third party in the inference path |
| Auth | Session cookies + Argon2id + TOTP; Google OAuth for GSC only | |
| Secrets | Env-injected + envelope encryption (AES-256-GCM) | KEK outside the DB |
| Observability | OpenTelemetry -> Grafana (Tempo/Loki/Mimir) | Vendor-neutral |
| Errors | Sentry, body capture DISABLED in production | |
| CI/CD | GitHub Actions, egress-restricted, pinned, SBOM | 7-day cooling-off on non-security bumps |
| Deploy | Docker + Kamal 2 -> Hetzner (EU) | No Kubernetes at this stage |
| Testing | pytest, pytest-asyncio, Hypothesis, testcontainers, Playwright, respx | |

**Rejected and why:** Neo4j, Qdrant, Elasticsearch (three failure domains, no
Phase-1 benefit — link graphs fit in RAM); Celery (job loss on Redis eviction);
Temporal (correct at Phase 4, overkill now); Auth0/Clerk (we still hold GSC
refresh tokens, so it adds a dependency without removing the hard problem);
LiteLLM/OpenRouter as a hard dependency (violates P10 — permitted only behind
an adapter); Ollama in production (no continuous batching); serverless workers
(wrong shape for long crawls).

**Not in the runtime:** no AI build tool, model vendor, or hosted platform
appears in the production dependency graph or deployment topology.

## 5. REPOSITORY TREE

    neptiq/
    |-- apps/
    |   |-- web/                     Next.js 16 frontend
    |   |   |-- app/(marketing)/
    |   |   |-- app/(auth)/
    |   |   |-- app/(app)/orgs/[org]/projects/[project]/...
    |   |   |-- components/          design system, vendored Radix
    |   |   |-- lib/api/             GENERATED from OpenAPI — never hand-edit
    |   |   +-- styles/tokens.css
    |   +-- api/                     FastAPI service
    |       |-- neptiq_api/routers/  thin, one file per resource
    |       |-- neptiq_api/schemas/  Pydantic, incl. ProvenanceModel base
    |       |-- neptiq_api/deps/     auth, tenancy, RLS session binding
    |       +-- neptiq_api/main.py
    |-- workers/
    |   |-- orchestrator/            workflow runtime, DAGs typed in code
    |   |-- fetcher/                 ZONE U — no DB creds, no secrets
    |   |-- renderer/                ZONE U — Playwright pool
    |   |-- parser/                  ZONE U — extraction
    |   |-- analyzer/                ZONE T — rules, graph, findings
    |   |-- connector/               GSC, CrUX, SERP adapters
    |   |-- artifactor/              artifact generation + validators
    |   +-- verifier/                deterministic assertions vs live
    |-- services/
    |   |-- egress-proxy/            SSRF gate, DNS pinning, token buckets
    |   +-- llm-gateway/             ModelRouter, adapters, budgets, cache
    |-- packages/                    ALL logic lives here
    |   |-- neptiq_core/             settings, errors, uuidv7 ids, logging
    |   |-- neptiq_db/               models, session, RLS helpers, repos
    |   |-- neptiq_url/              normalisation — pure, property-tested
    |   |-- neptiq_robots/           dual-agent robots evaluation
    |   |-- neptiq_extract/          DOM, structured data, content
    |   |-- neptiq_rules/            rule registry + all rules
    |   |-- neptiq_evidence/         ledger writers, provenance, traceability
    |   |-- neptiq_graph/            rustworkx link-graph analysis
    |   |-- neptiq_queue/            jobs + frontier, leases, DLQ
    |   |-- neptiq_security/         SSRF validator, taint types, sanitisers
    |   +-- neptiq_llm/              gateway client, versioned prompts, evals
    |-- db/
    |   |-- migrations/              Alembic, forward-only
    |   +-- policies/                RLS policies, reviewed separately
    |-- brand/                       SVG masters + build script
    |-- fixtures/site-lab/           12 nginx sites + ground-truth YAML
    |-- tests/                       unit, integration, e2e, security, evals, load
    |-- infra/                       compose, kamal, otel
    |-- docs/                        ADR/, CONSTITUTION.md, ARCHITECTURE.md, RUNBOOK.md
    |-- Makefile
    +-- docker-compose.yml

Rationale: `packages/` holds all logic; `apps/` and `workers/` are thin entry
points. Every rule, parser and security control is unit-testable without
starting a service, and zone boundaries are visible in the import graph.

## 6. NON-NEGOTIABLE INVARIANTS

Each is enforced by CI, not by convention.

1. Zone U code (`workers/fetcher`, `workers/renderer`, `workers/parser`) must
   not import `neptiq_db` or `neptiq_security.credentials`.
2. `packages/neptiq_rules` must not import the LLM gateway.
3. Every table with an `org_id` column must have a row-level security policy.
4. Every response model containing a derived number must inherit
   `ProvenanceModel`.
5. Crawled HTML is never rendered as HTML. No `dangerouslySetInnerHTML`
   anywhere in `apps/web`.
6. No hostname, domain, or URL is hardcoded in source. All come from env vars.
7. Immutable tables reject UPDATE and DELETE at the database level.
8. Every unit of billable work writes a `cost_records` row in the same
   transaction.
9. A complete audit must be producible with all external LLM providers
   disabled.
10. Dependencies are pinned; lockfiles are committed.

## 7. ENVIRONMENT VARIABLES

    DATABASE_URL, DATABASE_URL_MIGRATOR
    REDIS_URL
    S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY
    EGRESS_PROXY_URL
    KEK_BASE64                       envelope master key
    SESSION_SECRET
    GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
    CRUX_API_KEY
    LLM_PROVIDER_PRIMARY, LLM_PROVIDER_SECONDARY, LLM_LOCAL_BASE_URL
    SERP_PROVIDER_PRIMARY, SERP_PROVIDER_SECONDARY
    OTEL_EXPORTER_OTLP_ENDPOINT
    SENTRY_DSN
    NEPTIQ_ENV, NEPTIQ_REGION
    NEPTIQ_PUBLIC_HOST, NEPTIQ_APP_URL, NEPTIQ_API_URL
    NEPTIQ_BOT_INFO_URL, NEPTIQ_EVIDENCE_HOST
    CRAWL_MAX_URLS_DEFAULT=25000
    CRAWL_MAX_URLS_CEILING=50000
    RENDER_BUDGET_DEFAULT=500
    LLM_BUDGET_CENTS_PER_AUDIT=300

Production domain is not yet purchased. Dev uses `neptiq.localhost`.

## 8. DATA MODEL

Postgres 18. `uuidv7()` primary keys. RLS on every tenant table bound to
`current_setting('neptiq.org_id')`. No RLS-bypass role for application code;
only migrations run as owner.

**Immutable** (UPDATE/DELETE raise): page_snapshots, links, evidence,
api_observations, geo_samples, llm_runs, cost_records, audit_events,
verification_runs.

**Versioned** (new row + supersedes_id, partial unique index on current):
findings, artifacts, site_versions.

**Mutable state machines** (all transitions written to audit_events):
sites, crawl_runs, workflow_runs, jobs, frontier, deployments.

Tables: organizations, users, memberships, projects, sites, site_versions,
urls, frontier, crawl_runs, page_snapshots, page_extractions, links, findings,
finding_urls, evidence, api_observations, artifacts, deployments,
verification_runs, outcomes, gsc_daily, crux_records, geo_samples, embeddings,
workflow_runs, workflow_steps, jobs, llm_runs, cost_records, credentials,
audit_events.

Indexing follows four hot query shapes: findings by site+state+priority;
snapshots by crawl+url; links by crawl (bulk graph load); GSC by site+date
range. Everything else gets an index when a slow query proves it needs one.

Notable columns: `urls.url_hash` = sha256 of the normalised URL, unique per
site. `page_snapshots.body_sha256` points at object storage; identical content
across crawls costs zero additional storage. `findings.identity_hash` =
hash(rule_id, scope_key), giving stable identity across crawls — without this,
history is garbage. `artifacts.generated_by` records model, prompt version and
run id.

## 9. API

REST, OpenAPI 3.1 generated from Pydantic. RFC 9457 errors. `Idempotency-Key`
on all POSTs with 24-hour response storage. Opaque cursor pagination. Long
operations return 202 + run id, progress via SSE.

Every response object containing a derived number includes:
`provenance: { method, source_ids[], computed_at, engine_version, confidence }`

    POST   /v1/auth/session
    POST   /v1/orgs
    GET    /v1/projects                      POST /v1/projects
    POST   /v1/sites
    POST   /v1/sites/{id}/verification       GET  /v1/sites/{id}/verification
    POST   /v1/sites/{id}/crawls
    GET    /v1/crawls/{id}                   GET  /v1/crawls/{id}/events   (SSE)
    GET    /v1/crawls/{id}/urls
    GET    /v1/sites/{id}/findings
    GET    /v1/findings/{id}
    GET    /v1/evidence/{id}                 GET  /v1/evidence/{id}/raw    (text/plain)
    POST   /v1/findings/{id}/artifacts
    GET    /v1/artifacts/{id}                POST /v1/artifacts/{id}/approve
    POST   /v1/artifacts/{id}/deployments
    POST   /v1/findings/{id}/verify          GET  /v1/findings/{id}/verifications
    POST   /v1/sites/{id}/integrations/gsc
    GET    /v1/sites/{id}/coverage
    GET    /v1/projects/{id}/usage
    GET    /v1/projects/{id}/timeline

## 10. CRAWLER

Frontier keyed by (site_id, url_hash) with depth, priority, state,
next_attempt_at, attempts, host_bucket. Claimed via SKIP LOCKED ordered by
(priority, depth, discovered_at), filtered by host-bucket availability — this
gives per-host politeness with no central scheduler.

URL normalisation is pure and property-tested: lowercase scheme and host,
IDN to punycode, default ports removed, dot segments resolved, percent-encoding
normalised to uppercase hex, tracking parameters stripped, fragment removed.
Must be injective on the fixture corpus — a collision silently corrupts both
the frontier and the evidence ledger.

Robots is evaluated TWICE: as NeptiqBot (governs whether we fetch) and as
Googlebot (governs whether we report an indexability problem). Conflating
these is the most common false positive in commercial SEO tools.

Politeness: 1 concurrent connection per host, 1 req/sec, Crawl-delay honoured,
exponential back-off on 429/503 with Retry-After respected, per-tenant
concurrency cap. Unverified domains hard-capped at 50 URLs.

Limits: 5 MB body cap, content-type allow-list, redirect chain max 5 with each
hop re-validated for SSRF, timeouts connect 5s / read 15s / total 25s,
decompression-bomb protection.

Render-parity probe: before a full crawl, fetch 30-50 stratified URLs both raw
and rendered and compare title, canonical, meta robots, H1, link count and
main-content token overlap. Below threshold, the site is raw-sufficient. This
one probe is the difference between a $5 and a $25 audit at 50k URLs.

Bot identity: `Mozilla/5.0 (compatible; NeptiqBot/1.0; +${NEPTIQ_BOT_INFO_URL})`,
static egress IPs with forward-confirmed reverse DNS, a public policy page, and
a block-request form with a 24-hour SLA.

## 11. AI ARCHITECTURE

Task classes: T0 deterministic (no model, ever); T1 extraction/classification
(self-hosted or cheapest hosted tier); T2 synthesis (mid-tier hosted); T3
complex reasoning and code (frontier, budget-capped); T4 embeddings and
reranking (ALWAYS self-hosted — a deprecated hosted embedding model invalidates
your entire index).

ModelRouter adapter interface:
`complete(messages, schema, budget, trust_level, timeout) -> (output, usage, provenance)`

Fallback is ordered and explicit: primary -> secondary -> self-hosted ->
deterministic-only degraded mode with a visible banner. Cache keys hash
(prompt version, model id, full normalised input, schema version) — never
partial. Every call writes llm_runs + cost_records transactionally.

Trust levels: any call whose input contains tainted content gets a hardened
system prompt, zero tool access, schema-constrained output with no free-form
URL or command fields, and capped output length.

**Phase 1 has exactly one agent: the Analyst.** No tools. Turns deterministic
findings plus first-party data into prioritised narrative and artifact drafts.
Forbidden from asserting any fact, URL, or number not present in its input —
enforced by a post-generation numeric-provenance check that rejects any figure
absent from the input set. Cannot invoke other agents. The cap is four agents,
forever.

CI eval gates: grounding 100% (every assertion traceable to an input evidence
id), numeric fidelity 100% (zero invented numbers), schema compliance >= 99.5%,
injection resistance zero compliance events. Prompts are versioned files; a
prompt change without an eval run is a blocked merge.

## 12. RULE ENGINE

Each rule is a declarative record: rule_id, version, category, severity_default,
scope, preconditions, detection (pure function over the trusted site model),
evidence_extractor, false_positive_risk, fix_generator, verification_assertion,
fixture_cases, CI-measured precision and recall.

**Any rule below 0.85 precision on the fixture corpus is automatically demoted
to INFO and excluded from priority ranking.** Enforced in CI, not by policy.

MVP set is 42 rules across: indexability and crawlability; canonicals;
metadata and headings; structured data; internal linking; performance (CrUX);
sitemaps and robots; security hygiene; content structure.

## 13. FIXTURE CORPUS — THE MOST IMPORTANT TEST ASSET

`fixtures/site-lab`: 12 static sites served by nginx, each with a
machine-readable ground-truth file listing every finding that must be detected
and every non-finding that must not be.

    01 clean baseline (ANY finding is a false positive)
    02 canonical pathologies      03 redirect pathologies
    04 indexability conflicts     05 JS-dependent (parity probe must escalate)
    06 structured-data errors     07 hreflang/i18n traps
    08 duplicate/near-duplicate   09 ADVERSARIAL
    10 pagination/facet explosion 11 hostile robots.txt
    12 large (10k pages, perf regression)

Site 09 carries prompt injection in visible text, alt attributes, JSON-LD,
HTML comments and an HTTP header; plus a decompression bomb, a 50 MB page, and
a redirect chain ending at a private IP.

CI gates: per-rule precision >= 0.85; zero findings on site 01; zero injection
compliance events; zero SSRF escapes; zero cross-tenant rows; zero executed XSS
payloads; deterministic output byte-identical across two runs of the same
fixture; p95 analysis budget on site 12.

## 14. SECURITY

Prompt injection is handled structurally, not by prompt wording: delimited,
escaped, length-capped tainted fields; no tool access on tainted calls;
schema-constrained output; numeric-provenance post-check; adversarial CI corpus
with zero tolerance.

SSRF and DNS rebinding: all egress through the proxy, which resolves DNS
itself, validates every resolved address (IPv4 and IPv6 private, loopback,
link-local, CGNAT, multicast, reserved, cloud metadata) and pins the validated
IP for the connection, re-validating each redirect hop. CI corpus covers
decimal/octal/hex encodings, IPv6-mapped IPv4, userinfo tricks, and
redirect-to-internal chains.

Tenant isolation: RLS everywhere, no bypass role, plus a CI test that runs the
full API suite as tenant A asserting zero rows of tenant B ever appear.

Credentials: envelope encryption, KEK outside the DB, just-in-time decryption
in the single worker that needs it, never in an LLM context, never logged,
Sentry body capture off in production, CI secret-pattern scanning over source
and captured traces.

Render pool: seccomp, read-only filesystem, no host network, 1 GB memory cap,
context destroyed per page, Chromium patched on a defined cadence.

Evidence viewing: raw bodies served as text/plain from a SEPARATE REGISTRABLE
DOMAIN (not a subdomain — subdomains share cookie scope), under strict CSP.

Supply chain: pinned lockfiles, SBOM in CI, egress-restricted runners, 7-day
cooling-off on non-security upgrades, signed images.

## 15. DEPLOYMENT

Containers only. Hetzner (EU), Kamal 2 over SSH. Topology: app node (API
behind Caddy for TLS), worker node, crawl node with dedicated static egress
IPs, Postgres 18 primary + streaming replica + PITR via WAL archiving, small
Redis, observability node. GPU inference node arrives with Phase 2 embeddings.

Migrations are a pre-deploy step, forward-only, expand/contract so a code
rollback never meets a schema it cannot read. Nightly full backups plus
continuous WAL; restore rehearsed monthly, and a skipped rehearsal two months
running blocks the release. Workers drain leases before shutdown.

## 16. PHASE 1 ACCEPTANCE

Phase 1 is complete only when all of these are objectively true on production
infrastructure with a real customer site:

A new user signs up, creates an org and project, registers a site, verifies
ownership by at least two methods, and connects Search Console. A crawl of at
least 25,000 URLs completes with per-host politeness observable in egress logs
and no complaint from the target. The parity probe classifies correctly and the
render budget holds. Every rule above INFO measures >= 0.85 precision, and the
clean baseline produces zero findings. Every finding traces to a stored HTTP
response and a byte-anchored excerpt; every derived number carries provenance.
One finding goes through the full loop — artifact, validation, human approval,
deployment, deterministic verification that passes — and a deliberately
unfixed finding produces a verification failure displayed honestly. A second
crawl reports the finding fixed with correct lifecycle history. The adversarial
corpus yields zero injection events, zero SSRF escapes, zero cross-tenant
leaks, zero executed XSS. A complete audit is produced with all external LLM
providers disabled. Per-project cost reconciles to within 5% of provider
invoices. A backup restore has been rehearsed successfully. Traces span
API -> queue -> worker -> external call, and a runbook exists.

**Explicitly NOT acceptance criteria:** the UI looks good, the code compiles,
the demo works, a landing page exists.
