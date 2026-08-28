# ADR 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-08-28
- **Supersedes:** none

## Context

CONSTITUTION.md §8 states: *"This document changes only by an ADR in
`docs/ADR/` explaining what changed, why, and what evidence prompted it.
Silent edits are a process violation."* ARCHITECTURE.md is likewise
*"authoritative on structure, stack, and invariants"*, and CONSTITUTION §5 P12
and the preamble both require that a disagreement with a governing principle be
*raised as an ADR rather than worked around*.

Until this record exists there is nowhere for such a decision to live, which
means the only available options are silent deviation (a process violation) or
inaction. This ADR establishes the register.

## Decision

1. Every deviation from CONSTITUTION.md or ARCHITECTURE.md is recorded as a
   numbered file in `docs/ADR/`, before or with the change that deviates.
2. An ADR states: context, the decision, the alternatives rejected, the
   consequences, and — per CONSTITUTION §8 — **the evidence that prompted it**.
   "It was easier" is not evidence.
3. ADRs are immutable once accepted. A later decision *supersedes* an earlier
   one by referencing it; the earlier file is not edited. This mirrors
   CONSTITUTION P4 (correction by superseding, never by mutation) applied to
   our own process.
4. Numbering is sequential and gapless. `0001` is this file.
5. Amending CONSTITUTION.md or ARCHITECTURE.md itself requires an ADR that
   quotes the previous text verbatim, so the diff is auditable from the ADR
   alone.

## Alternatives rejected

- **Git history as the record.** A commit message explains *what* changed, and
  reviewers reliably fail to reconstruct *why* six months later. CONSTITUTION
  §8 asks for reasoning and evidence, which a diff does not carry.
- **A single running DECISIONS.md.** Mutable, so it violates the same
  append-only discipline the product enforces on its own data. It also produces
  merge conflicts on every parallel decision.

## Consequences

- A pull request that deviates from the governing documents without an ADR is
  rejected on process grounds, independent of code quality.
- The ADR directory is the first place to look when a reader asks why the code
  disagrees with ARCHITECTURE.md.

## Register of current deviations and deferrals

Recorded here in Task 1 for traceability. Each becomes its own ADR if it
hardens into a permanent decision.

| # | Item | Status |
|---|------|--------|
| 1 | **`make dev` unverified in the authoring sandbox.** The sandbox has no Docker runtime, so `docker compose up` cannot execute there. `docker-compose.yml` and the `dev` target are written and reviewed; verification is the `compose-up` job in CI, which health-checks PostgreSQL 18 (asserting pgvector + pg_trgm present), Redis 7, MinIO and the OTEL collector. **This is an environment limitation, not an architectural deviation.** No substitution (SQLite, in-memory Redis, local-filesystem storage) was made. | Accepted, verified in CI |
| 2 | **Integration and RLS tests marked `ci_only`.** Tests that require real PostgreSQL are written and committed but skipped where no Docker daemon exists. Substituting SQLite would leave RLS — the whole tenant-isolation model — untested while showing green, which is a worse outcome than an honestly skipped test (CONSTITUTION P3). | Accepted |
| 3 | **`is_same_registrable_site` compares exact hosts, not eTLD+1.** Correct eTLD+1 needs the Public Suffix List, a versioned data dependency. Until it is vendored and pinned, exact-host comparison is the conservative honest behaviour rather than a wrong answer for `foo.co.uk` (CONSTITUTION P11). | Deferred |
| 4 | **Local type stubs in `stubs/` for `protego` and `pgvector`.** Neither ships `py.typed`. Under mypy `strict` + `disallow_any_unimported` the alternative was `ignore_missing_imports`, which makes every value from those libraries `Any` and silently disables strict checking inside `neptiq_robots` — the package deciding whether we may fetch a URL at all. | Accepted |
| 5 | **`packages/` skeletons without implementation.** `neptiq_extract`, `neptiq_rules`, `neptiq_evidence`, `neptiq_graph`, `neptiq_queue`, `neptiq_llm` exist as declared packages with dependency manifests but no logic yet. This is deliberate: it makes the ARCHITECTURE §5 dependency direction and the zone-import invariants enforceable from Task 1, rather than trivially passing until the moment they matter. | Accepted |
| 6 | **Data model is partial.** ARCHITECTURE §8 lists 30 tables. Task 1 implements the tenancy spine plus one exemplar of each lifecycle class (immutable, versioned, mutable), so migrations, RLS policies and the invariant checks run against real DDL. Remaining tables land with the features that use them, carrying the same lifecycle declarations. | Accepted |
