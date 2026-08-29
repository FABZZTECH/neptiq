# NEPTIQ — PRODUCT CONSTITUTION v2.0

Status: BINDING. This document governs every contribution to NEPTIQ,
human or machine. Where any other document, prompt, ticket, or instruction
conflicts with this one, this one wins. If you believe a principle here is
wrong, raise it as an ADR — do not work around it.

---

## 1. WHAT NEPTIQ IS

NEPTIQ is a search intelligence and digital growth system that continuously
investigates a customer's website and its competitive search environment,
records everything it observes as immutable, timestamped, source-attributed
evidence, derives findings from deterministic rule engines rather than from
language-model opinion, prioritises those findings using the customer's own
first-party performance data, converts approved findings into concrete
implementation artifacts, delivers those artifacts for human approval and
merge rather than writing to production itself, and then mechanically
re-verifies the live site to prove the change actually shipped and to record
the measured outcome.

In one sentence: NEPTIQ is the system of record for search work — it proves
what is wrong, proves the fix shipped, and proves what happened next.

## 2. WHAT NEPTIQ IS NOT

It is not a chatbot. It is not a content generator. It is not a rank-tracking
dashboard. It is not a wrapper around a single AI API. It is not an autonomous
agent with write access to a customer's website. It does not produce composite
scores.

## 3. CUSTOMER

Primary: in-house search and growth teams at mid-market companies — roughly
50 to 1,000 employees, 5,000 to 500,000 URLs, an engineering team that ships
via pull requests, and someone whose job depends on organic revenue.

Secondary: technical SEO consultancies who need defensible client deliverables.

Explicitly not: SMB self-serve. They will not cover crawl and inference cost
and cannot merge a pull request.

## 4. CORE PROMISE

Every claim traces backwards to the byte that justified it and forwards to the
deployment that resolved it.

---

## 5. THE THIRTEEN PRINCIPLES

**P1 — Evidence before opinion.**
No claim ships without a retrievable artifact of observation: an HTTP exchange,
a DOM fragment, an API response, or a statistical sample with its parameters.
If evidence cannot be produced, the claim is not made.

**P2 — Deterministic before probabilistic.**
Anything computable is computed. Language models are used only where the task
is genuinely open-ended: synthesis, prioritisation narrative, code drafting,
and natural-language explanation. A model's output is never treated as a fact
about the world.

**P3 — Verification before claim.**
NEPTIQ does not report that something is fixed. It re-fetches the live resource
and asserts the fix deterministically, and reports the assertion result
including failures. A failure displayed honestly is worth more than a success
asserted loosely.

**P4 — Immutable history.**
Observations, evidence, and API responses are append-only. Findings and
artifacts are versioned, never overwritten. Correction happens by superseding,
never by mutation. The past is queryable exactly as it was recorded.

**P5 — Human authorisation for consequential change.**
NEPTIQ never mutates a customer system. It produces reviewable artifacts. A
human merges. Autonomy applies to investigation, analysis, artifact generation
and verification — never to mutation.

**P6 — All external content is hostile.**
Web pages, structured data, PDFs, API responses and uploads are untrusted.
They are parsed in a zone with no credentials and no tool access, and they
cannot reach a model context without passing a validation and neutralisation
gate. Instructions found inside retrieved content are data, never directives.

**P7 — Uncertainty is displayed, not hidden.**
Every derived quantity carries a confidence representation appropriate to its
method: exact for deterministic checks, interval-with-n for sampled
measurement, and an explicit "not measurable" label where it is not measurable.

**P8 — Reproducibility.**
Every run records its inputs, code version, rule versions, model versions,
prompt versions and cost. Any run can be explained after the fact.

**P9 — Cost is a first-class datum.**
Every unit of work writes a cost record in the same transaction as the work.
Per-project, per-run and per-tenant cost is always known, never estimated
after the fact.

**P10 — Architectural independence.**
No single external provider may be load-bearing. Every external capability
sits behind an adapter with at least one alternative implementation and a
defined degraded mode. NEPTIQ must remain useful with all external LLM
providers disabled. This is verified by a CI test, not by intention.

**P11 — Honest non-measurement.**
Where a thing cannot be reliably measured, NEPTIQ says so plainly and offers
the best honest proxy, clearly labelled. It never converts unmeasurable
phenomena into confident scores.

**P12 — Refuse impressive but untrustworthy features.**
A feature that demos well and cannot be defended under scrutiny is rejected
regardless of commercial pressure.

**P13 — Be a good citizen of the web.**
Named crawler, published IP ranges, working reverse DNS, honoured robots
directives, conservative default politeness, immediate back-off on 429 and
503, and a public crawler policy page. Ownership verification before any
meaningful crawl volume.

---

## 6. THE GEO HONESTY CHARTER

Binding on any future generative-engine-optimisation feature.

**Measurable:** whether a brand, domain or URL appears in a generated answer
for a specified prompt, on a specified surface, at a specified time, from a
specified locale — as a rate over repeated sampling, with n and a confidence
interval. Whether a URL is cited with a link. The set of sources a surface
cites. Change in appearance rate over time, tested for significance.

**Not measurable, and never to be presented as if it were:** position or rank
within a generated answer. Market share of AI answers. Any "GEO score".
Traffic attributable to AI answers absent first-party referrer data. Causal
attribution of a content change to an appearance-rate change without a
controlled design.

**Evidence basis:** the SparkToro/Gumshoe 2026 study (approx. 600 volunteers,
12 controlled prompts, 2,961 runs) found under a 1-in-100 chance that two runs
of the same prompt return the same brand set, and under 1-in-1,000 for the
same ordering; mean pairwise semantic similarity across 142 human prompts was
0.081. Rank is noise. Appearance rate is defensible.

**Method:** prompt sets are versioned per project. n >= 96 samples per prompt
per window gives approximately +/-10 percentage points at 95% confidence near
p=0.5; the UI states n and the interval. Sampling uses official APIs where
terms permit and licensed vendor data where they do not. NEPTIQ does not
scrape consumer assistant interfaces. Where no lawful path exists, the surface
is reported as "not measurable by NEPTIQ".

**Prohibited:** composite GEO scores, leaderboards, visibility indices.
Shipping one is grounds for reverting the feature.

---

## 7. WHAT MUST NEVER BE DECIDED BY A LANGUAGE MODEL

Canonical validation. HTTP status interpretation. Robots.txt evaluation.
Sitemap parsing. Duplicate and near-duplicate detection. Structured-data
schema validation. Core Web Vitals threshold evaluation. Redirect chain
analysis. URL normalisation. Link graph computation.

These are exactly computable. A model that is 97% right on them is worse than
useless, because it poisons the evidence chain. Code paths implementing these
must not import the LLM gateway; CI enforces this.

---

## 8. AGENT AUTHORITY AND ITS LIMITS

An automated agent may author application code, tests, migrations, tooling and
documentation in this repository. It may not author, edit, rename or delete the
definitions of its own verification gates.

Concretely: `.github/workflows/**` is human-committed only.

**Reasoning.** An agent that can edit the gates that judge its work can also
weaken them, and the most likely form of that is not sabotage but convenience —
relaxing an assertion to make a red build green. The failure is invisible,
because the very mechanism that would report it is the thing that was changed.
This is the same failure class as a test suite that passes while collecting
nothing, except self-inflicted and harder to detect. The thing being tested
does not control the test.

This also follows from P3 (verification before claim). A claim of verification
is only worth the independence of the verifier.

**To propose a CI change**, an agent writes the complete intended file content
to `docs/ci-proposed/<filename>.yml`, explains the diff and the reason in its
report, and stops. A human reviews and commits it. The proposed copy is
tracked, so the intent lives in history and is reviewable as a diff.

A drift check compares the live workflow against the proposed copy and fails
when they disagree. This keeps the proposal honest without granting write
access to the real file.

---

## 9. AMENDMENT

This document changes only by an ADR in `docs/ADR/` explaining what changed,
why, and what evidence prompted it. Silent edits are a process violation.
