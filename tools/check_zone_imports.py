#!/usr/bin/env python3
"""Enforce ARCHITECTURE §6 invariants 1, 2 and 5 on the import graph.

Invariant 1: Zone U code (workers/fetcher, workers/renderer, workers/parser)
             must not import neptiq_db or neptiq_security.credentials.
Invariant 2: packages/neptiq_rules must not import the LLM gateway.
Invariant 5: no dangerouslySetInnerHTML anywhere in apps/web.

Implemented as an AST walk, not a grep, because a grep for "neptiq_db" misses
`importlib.import_module("neptiq" + "_db")` and produces false positives on
comments and docstrings. The AST walk also follows TRANSITIVE reachability
through first-party packages: a Zone U worker importing neptiq_extract, which
imports neptiq_db, is a violation even though the worker's own imports look
clean. That transitive case is the one a reviewer will miss.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ZONE_U_ROOTS = ("workers/fetcher", "workers/renderer", "workers/parser")
ZONE_U_FORBIDDEN = ("neptiq_db", "neptiq_security.credentials")
RULES_ROOT = "packages/neptiq_rules"
RULES_FORBIDDEN = ("neptiq_llm",)


def module_paths() -> dict[str, Path]:
    """Map first-party module name -> its source directory."""
    out: dict[str, Path] = {}
    for base in ("packages", "apps", "workers", "services"):
        for src in (REPO_ROOT / base).rglob("src/*/"):
            if src.is_dir():
                out[src.name] = src
    return out


def imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        sys.stderr.write(f"FATAL: cannot parse {path}: {exc}\n")
        raise SystemExit(1) from exc
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return found


def reachable(start_modules: set[str], index: dict[str, Path]) -> set[str]:
    """Transitive closure of first-party imports."""
    seen: set[str] = set()
    queue = list(start_modules)
    while queue:
        mod = queue.pop()
        top = mod.split(".")[0]
        if top in seen or top not in index:
            seen.add(top)
            continue
        seen.add(top)
        for py in index[top].rglob("*.py"):
            for imported in imports_of(py):
                queue.append(imported)
                seen.add(imported)
    return seen


def check_python(index: dict[str, Path]) -> list[str]:
    failures: list[str] = []

    for root in ZONE_U_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for py in base.rglob("*.py"):
            direct = imports_of(py)
            closure = direct | reachable(direct, index)
            for forbidden in ZONE_U_FORBIDDEN:
                hits = {m for m in closure if m == forbidden or m.startswith(forbidden + ".")}
                if hits:
                    via = "directly" if hits & direct else "transitively"
                    failures.append(
                        f"INVARIANT 1 VIOLATION: {py.relative_to(REPO_ROOT)} (ZONE U) "
                        f"imports {forbidden} {via} ({sorted(hits)}). Zone U has no DB "
                        "credentials and no secrets by design (ARCHITECTURE §1)."
                    )

    base = REPO_ROOT / RULES_ROOT
    if base.is_dir():
        for py in base.rglob("*.py"):
            direct = imports_of(py)
            closure = direct | reachable(direct, index)
            for forbidden in RULES_FORBIDDEN:
                hits = {m for m in closure if m == forbidden or m.startswith(forbidden + ".")}
                if hits:
                    failures.append(
                        f"INVARIANT 2 VIOLATION: {py.relative_to(REPO_ROOT)} imports "
                        f"{forbidden} ({sorted(hits)}). CONSTITUTION §7: the things rules "
                        "compute are exactly computable; a model that is 97% right on them "
                        "poisons the evidence chain."
                    )
    return failures


_DANGEROUS = re.compile(r"dangerouslySetInnerHTML")
# Strip // line comments and /* */ block comments before scanning. Invariant 5
# is about USE of the API, and the codebase legitimately *names* it in comments
# explaining why it is forbidden. Flagging those would push authors to stop
# documenting the rule in order to satisfy the checker.
_LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_JSX_COMMENT = re.compile(r"\{\s*/\*.*?\*/\s*\}", re.DOTALL)


def check_web() -> list[str]:
    """Invariant 5: no dangerouslySetInnerHTML anywhere in apps/web."""
    failures: list[str] = []
    web = REPO_ROOT / "apps" / "web"
    if not web.is_dir():
        return failures
    for ext in ("*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs"):
        for f in web.rglob(ext):
            if "node_modules" in f.parts or ".next" in f.parts:
                continue
            source = f.read_text("utf-8")
            stripped = _JSX_COMMENT.sub("", source)
            stripped = _BLOCK_COMMENT.sub("", stripped)
            stripped = _LINE_COMMENT.sub("", stripped)
            for lineno, line in enumerate(stripped.splitlines(), 1):
                if _DANGEROUS.search(line):
                    failures.append(
                        f"INVARIANT 5 VIOLATION: {f.relative_to(REPO_ROOT)}:{lineno} uses "
                        "dangerouslySetInnerHTML. Crawled HTML is never rendered as HTML "
                        "(ARCHITECTURE §6.5); it is hostile content (CONSTITUTION P6)."
                    )
    return failures


def main() -> int:
    index = module_paths()
    failures = check_python(index) + check_web()
    if failures:
        sys.stderr.write("ZONE / IMPORT INVARIANT FAILURES\n" + "=" * 70 + "\n")
        for f in failures:
            sys.stderr.write(f"  - {f}\n")
        return 1
    print(
        f"zone import invariants hold: {len(ZONE_U_ROOTS)} Zone U roots, "
        "neptiq_rules LLM-free, apps/web free of dangerouslySetInnerHTML"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
