# ADR 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-08-28
- **Supersedes:** none

## Context

CONSTITUTION.md §9 (§8 at the time this ADR was written; renumbered when
§8 AGENT AUTHORITY AND ITS LIMITS was inserted — see ADR 0001 entry 7)
states: *"This document changes only by an ADR in
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
   consequences, and — per CONSTITUTION §9 — **the evidence that prompted it**.
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
  §9 asks for reasoning and evidence, which a diff does not carry.
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
| 7 | **Invariant 11 added: the agent does not modify `.github/workflows/**`.** Raised by the repository owner during Task 2A and adopted as permanent policy. An agent able to edit its own verification gates can weaken them, most likely by relaxing an assertion to turn a red build green — a failure invisible precisely because the reporting mechanism is what changed. Same failure class as a vacuously-passing test job, but self-inflicted. Recorded in CONSTITUTION.md as new §8 (AGENT AUTHORITY AND ITS LIMITS) and ARCHITECTURE.md §6 as invariant 11. **Text amended:** CONSTITUTION.md previously ended at `## 8. AMENDMENT`; that clause is now `## 9. AMENDMENT`, verbatim and unchanged in content. ARCHITECTURE.md §6 previously ended at item 10 (`Dependencies are pinned; lockfiles are committed.`), unchanged, with item 11 appended. Stale `CONSTITUTION §8` cross-references in this ADR were repointed to §9. Procedure: CI changes are proposed as complete files in `docs/ci-proposed/` and committed by a human; `tools/check_ci_drift.py` fails the build when the live workflow and the proposed copy disagree. | **Accepted, permanent** |
| 8 | **Task 2A: initial push landed without `.github/workflows/ci.yml`.** GitHub rejected the push — `refusing to allow a GitHub App to create or update workflow ... without \`workflows\` permission`. Diagnosis: credentials, network and write access were all confirmed working (a commit predating the workflow file pushed successfully to a temp branch); the rejection is specific to the workflow path and applies to every target branch. A PAT was explicitly refused by the owner. Resolution: source pushed without `.github/`, the intended CI definition committed to `docs/ci-proposed/ci.yml`, and the live workflow committed by the owner via the GitHub web UI. This is what made invariant 11 (entry 7) the natural permanent policy rather than a workaround. | Accepted |
| 9 | **Vacuous-pass mechanism corrected.** The Task 1 report stated the empty `integration` job would "collect nothing and report green". Measured: `pytest` on empty directories exits **5**, which already fails the step. The real hole is different — a module whose tests are all **skipped** reports `2 skipped` and exits **0**. So the C1 fix must assert a minimum *executed* count and fail on wholly-skipped modules, not merely guard against zero collection. Recorded because the original claim was wrong in a way that would have produced a fix aimed at the wrong failure. | Corrected, C1 pending |
