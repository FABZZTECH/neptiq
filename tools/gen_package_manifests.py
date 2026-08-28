#!/usr/bin/env python3
"""Generate the per-package pyproject.toml files for the uv workspace.

This is an authoring convenience, not a build step. The generated files are
committed. Run it again only if a package's dependency set changes; it will
rewrite the manifests in place.

Dependency direction is deliberate and load-bearing:

  * Zone U packages/workers (fetcher, renderer, parser) must NEVER be able to
    reach neptiq_db or neptiq_security.credentials. That is ARCHITECTURE
    invariant 1. Manifests here are the first line of defence (the package
    simply does not declare the dependency); tools/check_zone_imports.py is
    the enforced one, because a transitive dependency could otherwise
    reintroduce it.
  * neptiq_rules must never reach neptiq_llm (invariant 2, CONSTITUTION §7).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# name -> (description, [workspace deps], [external deps])
PACKAGES: dict[str, tuple[str, list[str], list[str]]] = {
    "neptiq_core": (
        "Settings, typed errors, uuidv7 identifiers, structured logging, taint-free primitives.",
        [],
        ["pydantic==2.11.7", "pydantic-settings==2.8.1", "uuid-utils==0.10.0"],
    ),
    "neptiq_security": (
        "SSRF validator, taint types, sanitisers, envelope encryption. ZONE BOUNDARY package.",
        ["neptiq-core"],
        ["cryptography==44.0.1", "idna==3.10"],
    ),
    "neptiq_url": (
        "Pure URL normalisation. Property-tested, must be injective on the fixture corpus.",
        ["neptiq-core"],
        ["idna==3.10", "w3lib==2.3.1"],
    ),
    "neptiq_robots": (
        "Dual-agent robots.txt evaluation: NeptiqBot (may we fetch) and "
        "Googlebot (is it a finding).",
        ["neptiq-core", "neptiq-url"],
        ["protego==0.4.0"],
    ),
    "neptiq_extract": (
        "DOM, structured data and content extraction. Operates on tainted input only.",
        ["neptiq-core", "neptiq-security", "neptiq-url"],
        ["selectolax==0.3.28", "trafilatura==2.0.0", "extruct==0.18.0"],
    ),
    "neptiq_db": (
        "SQLAlchemy models, async session, RLS session binding helpers, repositories.",
        ["neptiq-core"],
        ["sqlalchemy[asyncio]==2.0.38", "asyncpg==0.30.0", "alembic==1.14.1", "pgvector==0.3.6"],
    ),
    "neptiq_evidence": (
        "Evidence ledger writers, provenance construction, forward/backward traceability.",
        ["neptiq-core", "neptiq-db"],
        [],
    ),
    "neptiq_graph": (
        "rustworkx in-memory link-graph analysis. One graph per run, never a graph database.",
        ["neptiq-core"],
        ["rustworkx==0.16.0"],
    ),
    "neptiq_queue": (
        "Postgres SKIP LOCKED job queue and crawl frontier: leases, reaper, DLQ.",
        ["neptiq-core", "neptiq-db"],
        [],
    ),
    "neptiq_rules": (
        "Versioned rule registry and all detection rules. MUST NOT import neptiq_llm.",
        ["neptiq-core", "neptiq-url", "neptiq-extract", "neptiq-graph"],
        [],
    ),
    "neptiq_llm": (
        "ModelRouter gateway client, versioned prompts, eval harness. Never imported by rules.",
        ["neptiq-core", "neptiq-security"],
        ["httpx==0.28.1"],
    ),
}

# Zone U workers get an intentionally starved dependency set.
WORKERS: dict[str, tuple[str, list[str], list[str]]] = {
    "orchestrator": (
        "ZONE T — workflow runtime, DAGs typed in code.",
        ["neptiq-core", "neptiq-db", "neptiq-queue"],
        [],
    ),
    "fetcher": (
        "ZONE U — HTTP fetch through the egress proxy. No DB credentials, no secrets.",
        ["neptiq-core", "neptiq-url", "neptiq-robots", "neptiq-security"],
        ["httpx==0.28.1"],
    ),
    "renderer": (
        "ZONE U — isolated Playwright/Chromium pool. No DB credentials, no secrets.",
        ["neptiq-core", "neptiq-url", "neptiq-security"],
        ["playwright==1.50.0"],
    ),
    "parser": (
        "ZONE U — extraction. No DB credentials, no secrets.",
        ["neptiq-core", "neptiq-url", "neptiq-extract", "neptiq-security"],
        [],
    ),
    "analyzer": (
        "ZONE T — rules, graph, findings.",
        [
            "neptiq-core",
            "neptiq-db",
            "neptiq-rules",
            "neptiq-graph",
            "neptiq-evidence",
            "neptiq-queue",
        ],
        [],
    ),
    "connector": (
        "ZONE T — GSC, CrUX, SERP adapters.",
        ["neptiq-core", "neptiq-db", "neptiq-evidence", "neptiq-security"],
        ["httpx==0.28.1"],
    ),
    "artifactor": (
        "ZONE T — artifact generation plus deterministic validators.",
        ["neptiq-core", "neptiq-db", "neptiq-llm", "neptiq-evidence"],
        [],
    ),
    "verifier": (
        "ZONE T — deterministic assertions against the live site.",
        ["neptiq-core", "neptiq-db", "neptiq-rules", "neptiq-evidence", "neptiq-url"],
        ["httpx==0.28.1"],
    ),
}

SERVICES: dict[str, tuple[str, list[str], list[str]]] = {
    "egress-proxy": (
        "SSRF gate, DNS pinning, per-host and per-tenant token buckets. No DB.",
        ["neptiq-core", "neptiq-security"],
        ["fastapi==0.115.8", "uvicorn[standard]==0.34.0", "httpx==0.28.1", "redis==5.2.1"],
    ),
    "llm-gateway": (
        "ModelRouter, provider adapters, budgets, response cache, circuit breakers.",
        ["neptiq-core", "neptiq-security", "neptiq-llm"],
        ["fastapi==0.115.8", "uvicorn[standard]==0.34.0", "httpx==0.28.1", "redis==5.2.1"],
    ),
}


def render(
    dist_name: str,
    module_name: str | None,
    description: str,
    ws_deps: list[str],
    ext_deps: list[str],
    src_layout: bool,
) -> str:
    deps = ws_deps + ext_deps
    dep_block = "\n".join(f'    "{d}",' for d in deps)
    sources = "\n".join(f"{d.replace('-', '-')} = {{ workspace = true }}" for d in ws_deps)
    src_line = ""
    if src_layout and module_name:
        src_line = f'\n[tool.hatch.build.targets.wheel]\npackages = ["src/{module_name}"]\n'
    return f"""[project]
name = "{dist_name}"
version = "0.1.0"
description = "{description}"
requires-python = "==3.13.*"
dependencies = [
{dep_block}
]

[build-system]
requires = ["hatchling==1.27.0"]
build-backend = "hatchling.build"
{src_line}
[tool.uv.sources]
{sources}
"""


def main() -> None:
    written: list[Path] = []

    for mod, (desc, ws, ext) in PACKAGES.items():
        dist = mod.replace("_", "-")
        path = REPO_ROOT / "packages" / mod / "pyproject.toml"
        path.write_text(render(dist, mod, desc, ws, ext, src_layout=True))
        written.append(path)

    for name, (desc, ws, ext) in WORKERS.items():
        mod = f"neptiq_worker_{name}"
        dist = f"neptiq-worker-{name}"
        path = REPO_ROOT / "workers" / name / "pyproject.toml"
        path.write_text(render(dist, mod, desc, ws, ext, src_layout=True))
        written.append(path)

    for name, (desc, ws, ext) in SERVICES.items():
        mod = "neptiq_" + name.replace("-", "_")
        dist = f"neptiq-{name}"
        path = REPO_ROOT / "services" / name / "pyproject.toml"
        path.write_text(render(dist, mod, desc, ws, ext, src_layout=True))
        written.append(path)

    for p in written:
        print(f"wrote {p.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
