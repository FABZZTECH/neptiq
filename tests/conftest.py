"""Shared pytest configuration.

The `ci_only` marker is auto-skipped when no Docker daemon is reachable. This
is the mechanism that lets integration tests be WRITTEN AND COMMITTED here
while being VERIFIED in GitHub Actions.

Read this before "fixing" a skipped test: the correct response to a skip is
never to substitute SQLite for PostgreSQL, an in-memory dict for Redis, or the
local filesystem for S3. SQLite has no row-level security, so a SQLite
substitution would leave the entire tenant-isolation model (ARCHITECTURE §8,
invariant 3) untested while reporting green — strictly worse than an honest
skip. See CONSTITUTION P3 and docs/ADR/0001 register entry 2.
"""

from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path

import pytest


def _docker_available() -> bool:
    if os.environ.get("NEPTIQ_FORCE_CI_TESTS") == "1":
        return True
    if shutil.which("docker") is None:
        return False
    sock = Path("/var/run/docker.sock")
    if sock.exists():
        return True
    host = os.environ.get("DOCKER_HOST", "")
    if host.startswith("tcp://"):
        hostport = host.removeprefix("tcp://")
        h, _, p = hostport.partition(":")
        try:
            with socket.create_connection((h, int(p or 2375)), timeout=2):
                return True
        except OSError:
            return False
    return False


DOCKER_AVAILABLE = _docker_available()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if DOCKER_AVAILABLE:
        return
    skip = pytest.mark.skip(
        reason=(
            "requires a Docker runtime (docker compose / testcontainers). "
            "Verified by the GitHub Actions integration job. NOT to be satisfied "
            "by substituting SQLite/in-memory fakes — see tests/conftest.py."
        )
    )
    for item in items:
        if "ci_only" in item.keywords or "integration" in item.keywords:
            item.add_marker(skip)
