# docs/ci-proposed/

Proposed CI definitions. **Not executed.** GitHub only runs what is in
`.github/workflows/`.

## Why this directory exists

ARCHITECTURE §6 invariant 11 and CONSTITUTION §8: an automated agent must not
author, edit, rename or delete anything under `.github/workflows/**`.

An agent that can edit the gates judging its work can also weaken them. The
likely form is not sabotage but convenience — relaxing an assertion to turn a
red build green — and the failure is invisible, because the mechanism that
would report it is the thing that changed. The thing being tested does not
control the test.

So the agent proposes here, and a human commits there.

## Procedure

1. The agent writes the **complete** intended file to `docs/ci-proposed/<name>.yml`
   (never a patch or fragment — a reviewer must be able to read exactly what
   will run), explains the diff and the reasoning in its report, and stops.
2. A human reviews and commits it to `.github/workflows/<name>.yml`.
3. `tools/check_ci_drift.py`, run by the `lint` job, fails the build if the two
   copies disagree.

## The drift check

Compares **parsed YAML**, not bytes. A comment reflow or re-indent is not a
behavioural change; failing on one would train people to ignore the check,
which is worse than not having it. Mapping key order is ignored (YAML mappings
are unordered); **list order is compared**, because step order is behaviour.

When `.github/workflows/` is empty the check passes and says so. The invariant
forbids the agent from creating that file, so its absence cannot be the agent's
fault — but a live workflow with **no** proposed counterpart *is* a failure,
since its intent would then be unreviewable.

## Current state

| File | Live counterpart | Notes |
|------|------------------|-------|
| `ci.yml` | *awaiting human commit* | The Task 1 CI gate. Could not be pushed by the agent: GitHub rejects an App token without `workflows` permission. See ADR 0001 register entry 8. |
