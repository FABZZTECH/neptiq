#!/usr/bin/env python3
"""Fail when a live CI workflow disagrees with its proposed copy.

ARCHITECTURE §6 invariant 11 / CONSTITUTION §8: ``.github/workflows/**`` is
human-committed only. An automated agent proposes a CI change by writing the
complete intended file to ``docs/ci-proposed/<name>.yml`` and stopping.

That split creates a new risk: the proposed copy silently rots. Once it no
longer matches the live workflow, reviewing the proposal tells you nothing
about what actually runs, and the audit trail the invariant exists to protect
is gone. This check closes that gap from the safe side — it can only *report*
disagreement, never write the live file.

Comparison is on PARSED YAML, not bytes. A comment reflow or a re-indent is not
a behavioural change and failing on it would train people to ignore this check,
which is worse than not having it. Two spellings of the same workflow semantics
are therefore equal here; any difference in keys, values, ordering of steps, or
shell bodies is not.

Exit status:
    0  every live workflow has a matching proposed copy
    1  drift, a missing proposed copy, or unparseable YAML
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Final

import yaml

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
LIVE_DIR: Final = REPO_ROOT / ".github" / "workflows"
PROPOSED_DIR: Final = REPO_ROOT / "docs" / "ci-proposed"

_WORKFLOW_GLOBS: Final = ("*.yml", "*.yaml")


def _load(path: Path) -> Any:
    """Parse a workflow, or raise with the path attached."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - exercised via CI
        msg = f"{path.relative_to(REPO_ROOT)} is not valid YAML: {exc}"
        raise ValueError(msg) from exc


def _workflows(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        return {}
    found: dict[str, Path] = {}
    for pattern in _WORKFLOW_GLOBS:
        for path in sorted(directory.glob(pattern)):
            found[path.name] = path
    return found


def _describe_difference(  # noqa: PLR0911
    live: Any,
    proposed: Any,
    path: str = "",
) -> str | None:
    """Return a human-readable location of the first difference, or None.

    A whole-document dump diff is unreadable for a file this size, and a
    reviewer who cannot see *which key* moved will not act on the failure. So
    this walks to the specific divergence and names it.

    PLR0911 (too many returns) is suppressed deliberately: each return is one
    distinct, separately-worded kind of drift (type changed, key added, key
    removed, list length, scalar value). Collapsing them into a single exit
    would cost the specificity that makes the failure actionable.
    """
    where = path or "<root>"

    if type(live) is not type(proposed):
        return f"{where}: live is {type(live).__name__}, proposed is {type(proposed).__name__}"

    if isinstance(live, dict):
        assert isinstance(proposed, dict)
        live_keys, proposed_keys = set(live), set(proposed)
        if only_live := sorted(live_keys - proposed_keys):
            return f"{where}: keys present in live but not proposed: {only_live}"
        if only_proposed := sorted(proposed_keys - live_keys):
            return f"{where}: keys present in proposed but not live: {only_proposed}"
        # Key ORDER is not compared: YAML mappings are unordered and GitHub
        # does not derive behaviour from it.
        for key in live:
            child = f"{path}.{key}" if path else str(key)
            if (diff := _describe_difference(live[key], proposed[key], child)) is not None:
                return diff
        return None

    if isinstance(live, list):
        assert isinstance(proposed, list)
        if len(live) != len(proposed):
            return f"{where}: live has {len(live)} items, proposed has {len(proposed)}"
        # List order IS compared: step order is behaviour.
        for index, (a, b) in enumerate(zip(live, proposed, strict=True)):
            if (diff := _describe_difference(a, b, f"{path}[{index}]")) is not None:
                return diff
        return None

    if live != proposed:
        return f"{where}: live={live!r} proposed={proposed!r}"
    return None


def main() -> int:
    live = _workflows(LIVE_DIR)
    proposed = _workflows(PROPOSED_DIR)

    if not live:
        # Legitimate and expected on a fresh clone whose owner has not yet
        # committed the workflow, and in the sandbox, where the agent is
        # forbidden from creating it. Not a failure: the invariant says the
        # agent must not write that file, so its absence cannot be the
        # agent's fault. Report and pass.
        print(
            "ci drift: no live workflow in .github/workflows/ — nothing to compare. "
            f"{len(proposed)} proposed file(s) awaiting human commit: {sorted(proposed)}"
        )
        return 0

    failures: list[str] = []

    for name, live_path in live.items():
        proposed_path = proposed.get(name)
        if proposed_path is None:
            failures.append(
                f"{live_path.relative_to(REPO_ROOT)} has no counterpart at "
                f"docs/ci-proposed/{name}. Every live workflow must have a "
                f"proposed copy so its intent is reviewable."
            )
            continue

        try:
            live_doc = _load(live_path)
            proposed_doc = _load(proposed_path)
        except ValueError as exc:
            failures.append(str(exc))
            continue

        if (diff := _describe_difference(live_doc, proposed_doc)) is not None:
            failures.append(
                f"{name}: live workflow and proposed copy disagree.\n"
                f"    first difference at {diff}\n"
                f"    Update docs/ci-proposed/{name} to match what actually runs, "
                f"or revert the live change."
            )

    # A proposed file with no live counterpart is a pending proposal, not
    # drift. Surfaced for visibility only.
    if pending := sorted(set(proposed) - set(live)):
        print(f"ci drift: pending proposals not yet committed as live workflows: {pending}")

    if failures:
        print("CI DRIFT CHECK FAILED", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"ci definitions consistent: {len(live)} live workflow(s) match docs/ci-proposed/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
